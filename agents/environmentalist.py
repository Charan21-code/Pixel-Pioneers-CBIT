"""
agents/environmentalist.py — EnvironmentalistAgent

Responsibility
--------------
Monitors energy consumption and carbon emissions from the cursor-sliced
production DataFrame. Separates peak-period waste from off-peak consumption,
flags compliance violations, and calls Ollama once for shift-rescheduling
suggestions to reduce peak-hour carbon penalties.

Live-data contract
------------------
Only reads from context["df"]. Never queries production_events from the DB.
"""

import logging

import pandas as pd

import config
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class EnvironmentalistAgent(BaseAgent):
    def __init__(self, db_path: str = config.DB_PATH):
        super().__init__("Environmentalist", db_path)

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self, context: dict) -> dict:
        """
        Parameters
        ----------
        context["df"]          : cursor-sliced DataFrame
        context["as_of_time"]  : pd.Timestamp

        Returns
        -------
        dict with keys:
            total_carbon_kg       float
            total_energy_kwh      float
            total_penalty_usd     float
            peak_penalty_usd      float
            off_peak_penalty_usd  float
            peak_energy_kwh       float
            off_peak_energy_kwh   float
            peak_penalty_pct      float  — peak share in percent
            peak_ratio            float  — peak share as 0–1 fraction
            compliance_flag       bool
            compliance_status     str
            key_finding           str
            recommendation        str
            hotspot               dict
            shift_suggestions     list[str]
            estimated_savings_usd float
            summary               str
        """
        df: pd.DataFrame = context.get("df", pd.DataFrame())
        run_id: str = context.get("run_id")

        if df.empty:
            return self._empty_result("No data available in context.")

        self.publish_signal(
            severity="INFO",
            message="Auditing peak vs off-peak energy consumption and carbon penalty exposure...",
            confidence_pct=50.0,
            action_taken="Environmental scan started",
            run_id=run_id,
        )

        totals = self._aggregate_totals(df)
        peak_stats = self._split_by_period(df)
        hotspot = self._identify_peak_hotspot(df)

        peak_pct = (
            peak_stats["peak_penalty_usd"] / (totals["total_penalty_usd"] + 1e-9)
        ) * 100
        heuristic_compliant = peak_pct < (config.AGENT["peak_penalty_ratio"] * 100)

        llm_out = self._ask_ollama(
            peak_kwh=peak_stats["peak_energy_kwh"],
            off_peak_kwh=peak_stats["off_peak_energy_kwh"],
            carbon_penalty_usd=totals["total_penalty_usd"],
            peak_pct=peak_pct,
            hotspot=hotspot,
        )

        compliance_flag = llm_out.get("compliance_flag", heuristic_compliant)
        compliance_status = "COMPLIANT" if compliance_flag else "PARTIALLY NON-COMPLIANT"
        shift_suggestions = llm_out.get("shift_suggestions", self._heuristic_suggestions(peak_pct))
        estimated_savings = float(llm_out.get("estimated_savings_usd", 0.0))
        key_finding = llm_out.get("key_finding", self._default_key_finding(hotspot))
        recommendation = llm_out.get(
            "recommendation",
            shift_suggestions[0] if shift_suggestions else "Keep shifting heavy loads to off-peak windows.",
        )

        severity = "WARNING" if not compliance_flag else "INFO"
        summary = self._build_summary(totals, peak_pct, compliance_status, key_finding)
        self.publish_signal(
            severity=severity,
            message=summary,
            confidence_pct=round(100 - peak_pct, 1),
            action_taken="Compliance flag raised" if not compliance_flag else "Monitoring",
        )

        return {
            "total_carbon_kg": round(totals["total_carbon_kg"], 2),
            "total_energy_kwh": round(totals["total_energy_kwh"], 2),
            "total_penalty_usd": round(totals["total_penalty_usd"], 2),
            "peak_penalty_usd": round(peak_stats["peak_penalty_usd"], 2),
            "off_peak_penalty_usd": round(peak_stats["off_peak_penalty_usd"], 2),
            "peak_energy_kwh": round(peak_stats["peak_energy_kwh"], 2),
            "off_peak_energy_kwh": round(peak_stats["off_peak_energy_kwh"], 2),
            "peak_penalty_pct": round(peak_pct, 2),
            "peak_ratio": round(peak_pct / 100.0, 4),
            "compliance_flag": compliance_flag,
            "compliance_status": compliance_status,
            "key_finding": key_finding,
            "recommendation": recommendation,
            "hotspot": hotspot,
            "shift_suggestions": shift_suggestions,
            "estimated_savings_usd": round(estimated_savings, 2),
            "summary": summary,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _aggregate_totals(self, df: pd.DataFrame) -> dict:
        """Sum energy, carbon, and penalty across all rows."""
        try:
            return {
                "total_carbon_kg": float(df["Carbon_Emissions_kg"].sum()),
                "total_energy_kwh": float(df["Energy_Consumed_kWh"].sum()),
                "total_penalty_usd": float(df["Carbon_Cost_Penalty_USD"].sum()),
            }
        except Exception as exc:
            logger.warning("[Environmentalist] Aggregation failed: %s", exc)
            return {"total_carbon_kg": 0.0, "total_energy_kwh": 0.0, "total_penalty_usd": 0.0}

    def _split_by_period(self, df: pd.DataFrame) -> dict:
        """Split energy and penalties into peak vs off-peak totals."""
        try:
            if "Grid_Pricing_Period" not in df.columns:
                total_penalty = float(df["Carbon_Cost_Penalty_USD"].sum())
                total_energy = float(df["Energy_Consumed_kWh"].sum())
                return {
                    "peak_penalty_usd": 0.0,
                    "off_peak_penalty_usd": total_penalty,
                    "peak_energy_kwh": 0.0,
                    "off_peak_energy_kwh": total_energy,
                }

            peak_mask = df["Grid_Pricing_Period"].str.lower() == "peak"
            peak_df = df[peak_mask]
            off_peak_df = df[~peak_mask]

            return {
                "peak_penalty_usd": float(peak_df["Carbon_Cost_Penalty_USD"].sum()),
                "off_peak_penalty_usd": float(off_peak_df["Carbon_Cost_Penalty_USD"].sum()),
                "peak_energy_kwh": float(peak_df["Energy_Consumed_kWh"].sum()),
                "off_peak_energy_kwh": float(off_peak_df["Energy_Consumed_kWh"].sum()),
            }
        except Exception as exc:
            logger.warning("[Environmentalist] Period split failed: %s", exc)
            return {
                "peak_penalty_usd": 0.0,
                "off_peak_penalty_usd": 0.0,
                "peak_energy_kwh": 0.0,
                "off_peak_energy_kwh": 0.0,
            }

    def _identify_peak_hotspot(self, df: pd.DataFrame) -> dict:
        """Identify the facility/product pair driving the biggest peak penalty."""
        try:
            peak_df = df[df["Grid_Pricing_Period"].str.lower() == "peak"].copy()
        except Exception:
            peak_df = pd.DataFrame()

        if peak_df.empty:
            return {
                "facility": "N/A",
                "product": "N/A",
                "carbon_kg": 0.0,
                "penalty_usd": 0.0,
                "peak_hours": [],
            }

        grouped = (
            peak_df.groupby(["Assigned_Facility", "Product_Category"])
            .agg(
                carbon_kg=("Carbon_Emissions_kg", "sum"),
                penalty_usd=("Carbon_Cost_Penalty_USD", "sum"),
            )
            .reset_index()
            .sort_values(["penalty_usd", "carbon_kg"], ascending=False)
        )
        top = grouped.iloc[0]
        peak_hours = sorted(peak_df["Timestamp"].dt.hour.dropna().unique().tolist())[:4]
        return {
            "facility": str(top["Assigned_Facility"]),
            "product": str(top["Product_Category"]),
            "carbon_kg": round(float(top["carbon_kg"]), 2),
            "penalty_usd": round(float(top["penalty_usd"]), 2),
            "peak_hours": peak_hours,
        }

    def _ask_ollama(
        self,
        peak_kwh: float,
        off_peak_kwh: float,
        carbon_penalty_usd: float,
        peak_pct: float,
        hotspot: dict,
    ) -> dict:
        """
        One LLM call for shift-rescheduling suggestions.
        Expected JSON:
        {
          "compliance_flag": true/false,
          "key_finding": "...",
          "recommendation": "...",
          "shift_suggestions": ["...", "..."],
          "estimated_savings_usd": N
        }
        """
        prompt = f"""You are a sustainability analyst for a global electronics factory.

Current energy and carbon summary:
- Peak-period energy:     {peak_kwh:,.0f} kWh
- Off-peak energy:        {off_peak_kwh:,.0f} kWh
- Total carbon penalty:   ${carbon_penalty_usd:,.0f} USD
- Peak penalty share:     {peak_pct:.1f}% of total (target: <40%)
- Peak hotspot facility:  {hotspot.get("facility", "N/A")}
- Peak hotspot product:   {hotspot.get("product", "N/A")}
- Hotspot penalty:        ${hotspot.get("penalty_usd", 0):,.0f} USD

Respond ONLY with a JSON object using exactly this structure:
{{
  "compliance_flag": true or false,
  "key_finding": "single sentence identifying the main peak-hour issue",
  "recommendation": "single sentence with the highest-priority timing adjustment",
  "shift_suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"],
  "estimated_savings_usd": number
}}"""
        return self.call_ollama(prompt)

    def _heuristic_suggestions(self, peak_pct: float) -> list:
        if peak_pct >= 60:
            return [
                "Move at least 30% of production to off-peak night shifts immediately.",
                "Disable non-critical equipment during 9AM–5PM peak windows.",
                "Evaluate renewable energy procurement to offset peak penalties.",
            ]
        if peak_pct >= 40:
            return [
                "Shift 15% of production volume to off-peak windows.",
                "Review HVAC scheduling to reduce peak draw.",
            ]
        return [
            "Energy usage is within compliance. Continue monitoring peak exposure.",
        ]

    def _default_key_finding(self, hotspot: dict) -> str:
        if hotspot.get("facility") == "N/A":
            return "Peak-hour production is distributed evenly with no single hotspot."
        return (
            f"{hotspot.get('facility')} is the main peak-hour hotspot, driven by "
            f"{hotspot.get('product')} loads worth ${hotspot.get('penalty_usd', 0):,.0f} in penalties."
        )

    def _build_summary(self, totals: dict, peak_pct: float, status: str, key_finding: str) -> str:
        return (
            f"[{status}] Total energy: {totals['total_energy_kwh']:,.0f} kWh | "
            f"Carbon: {totals['total_carbon_kg']:,.0f} kg | "
            f"Penalty: ${totals['total_penalty_usd']:,.0f} | "
            f"Peak share: {peak_pct:.1f}% | {key_finding}"
        )

    def _empty_result(self, reason: str) -> dict:
        self.publish_signal(severity="WARNING", message=reason, confidence_pct=0.0)
        return {
            "total_carbon_kg": 0.0,
            "total_energy_kwh": 0.0,
            "total_penalty_usd": 0.0,
            "peak_penalty_usd": 0.0,
            "off_peak_penalty_usd": 0.0,
            "peak_energy_kwh": 0.0,
            "off_peak_energy_kwh": 0.0,
            "peak_penalty_pct": 0.0,
            "peak_ratio": 0.0,
            "compliance_flag": True,
            "compliance_status": "COMPLIANT",
            "key_finding": reason,
            "recommendation": "Review the incoming production feed and retry the analysis.",
            "hotspot": {
                "facility": "N/A",
                "product": "N/A",
                "carbon_kg": 0.0,
                "penalty_usd": 0.0,
                "peak_hours": [],
            },
            "shift_suggestions": [],
            "estimated_savings_usd": 0.0,
            "summary": reason,
        }
