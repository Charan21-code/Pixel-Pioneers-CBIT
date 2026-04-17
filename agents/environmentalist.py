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

# Carbon cost penalty threshold (USD) — above this → flag
_CARBON_PEAK_THRESHOLD_USD = config.AGENT["carbon_peak_threshold"]


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
            total_carbon_kg       float  — total CO₂ equivalent
            total_energy_kwh      float  — total kWh consumed
            total_penalty_usd     float  — total carbon cost penalty
            peak_penalty_usd      float  — penalty attributed to peak-period production
            off_peak_penalty_usd  float
            peak_energy_kwh       float
            off_peak_energy_kwh   float
            peak_penalty_pct      float  — peak_penalty / total_penalty * 100
            compliance_flag       bool   — True = compliant (peak_pct < 40%)
            shift_suggestions     list   — natural-language suggestions from LLM
            estimated_savings_usd float  — LLM's projected savings
            summary               str    — plain English summary
        """
        df: pd.DataFrame = context.get("df", pd.DataFrame())

        if df.empty:
            return self._empty_result("No data available in context.")

        # ── Step 1: Aggregate energy & carbon totals ──────────────────────────
        totals = self._aggregate_totals(df)

        # ── Step 2: Split by grid pricing period ──────────────────────────────
        peak_stats = self._split_by_period(df)

        # ── Step 3: Compliance check ───────────────────────────────────────────
        peak_pct = (
            peak_stats["peak_penalty_usd"] / (totals["total_penalty_usd"] + 1e-9)
        ) * 100
        heuristic_compliant = peak_pct < (config.AGENT["peak_penalty_ratio"] * 100)

        # ── Step 4: Single Ollama call for suggestions ─────────────────────────
        llm_out = self._ask_ollama(
            peak_kwh=peak_stats["peak_energy_kwh"],
            off_peak_kwh=peak_stats["off_peak_energy_kwh"],
            carbon_penalty_usd=totals["total_penalty_usd"],
            peak_pct=peak_pct,
        )

        compliance_flag      = llm_out.get("compliance_flag",      heuristic_compliant)
        shift_suggestions    = llm_out.get("shift_suggestions",    self._heuristic_suggestions(peak_pct))
        estimated_savings    = float(llm_out.get("estimated_savings_usd", 0.0))

        # ── Step 5: Publish signal ────────────────────────────────────────────
        severity = "WARNING" if not compliance_flag else "INFO"
        summary  = self._build_summary(totals, peak_stats, peak_pct, compliance_flag)
        self.publish_signal(
            severity=severity,
            message=summary,
            confidence_pct=round(100 - peak_pct, 1),
            action_taken="Compliance flag raised" if not compliance_flag else "Monitoring",
        )

        return {
            "total_carbon_kg":       round(totals["total_carbon_kg"],   2),
            "total_energy_kwh":      round(totals["total_energy_kwh"],  2),
            "total_penalty_usd":     round(totals["total_penalty_usd"], 2),
            "peak_penalty_usd":      round(peak_stats["peak_penalty_usd"],     2),
            "off_peak_penalty_usd":  round(peak_stats["off_peak_penalty_usd"], 2),
            "peak_energy_kwh":       round(peak_stats["peak_energy_kwh"],      2),
            "off_peak_energy_kwh":   round(peak_stats["off_peak_energy_kwh"],  2),
            "peak_penalty_pct":      round(peak_pct, 2),
            "compliance_flag":       compliance_flag,
            "shift_suggestions":     shift_suggestions,
            "estimated_savings_usd": round(estimated_savings, 2),
            "summary":               summary,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _aggregate_totals(self, df: pd.DataFrame) -> dict:
        """Sum energy, carbon, and penalty across all rows."""
        try:
            return {
                "total_carbon_kg":   float(df["Carbon_Emissions_kg"].sum()),
                "total_energy_kwh":  float(df["Energy_Consumed_kWh"].sum()),
                "total_penalty_usd": float(df["Carbon_Cost_Penalty_USD"].sum()),
            }
        except Exception as exc:
            logger.warning("[Environmentalist] Aggregation failed: %s", exc)
            return {"total_carbon_kg": 0.0, "total_energy_kwh": 0.0, "total_penalty_usd": 0.0}

    def _split_by_period(self, df: pd.DataFrame) -> dict:
        """
        Splits df by Grid_Pricing_Period column ('Peak' vs other values).
        Returns peak and off-peak energy + penalty totals.
        """
        try:
            if "Grid_Pricing_Period" not in df.columns:
                # No period column — treat everything as off-peak
                total_penalty = float(df["Carbon_Cost_Penalty_USD"].sum())
                total_energy  = float(df["Energy_Consumed_kWh"].sum())
                return {
                    "peak_penalty_usd":     0.0,
                    "off_peak_penalty_usd": total_penalty,
                    "peak_energy_kwh":      0.0,
                    "off_peak_energy_kwh":  total_energy,
                }

            peak_mask    = df["Grid_Pricing_Period"].str.lower() == "peak"
            peak_df      = df[peak_mask]
            off_peak_df  = df[~peak_mask]

            return {
                "peak_penalty_usd":     float(peak_df["Carbon_Cost_Penalty_USD"].sum()),
                "off_peak_penalty_usd": float(off_peak_df["Carbon_Cost_Penalty_USD"].sum()),
                "peak_energy_kwh":      float(peak_df["Energy_Consumed_kWh"].sum()),
                "off_peak_energy_kwh":  float(off_peak_df["Energy_Consumed_kWh"].sum()),
            }
        except Exception as exc:
            logger.warning("[Environmentalist] Period split failed: %s", exc)
            return {
                "peak_penalty_usd": 0.0, "off_peak_penalty_usd": 0.0,
                "peak_energy_kwh":  0.0, "off_peak_energy_kwh":  0.0,
            }

    def _ask_ollama(self, peak_kwh: float, off_peak_kwh: float,
                    carbon_penalty_usd: float, peak_pct: float) -> dict:
        """
        One LLM call for shift-rescheduling suggestions.
        Expected JSON:
        {
          "compliance_flag": true/false,
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

Respond ONLY with a JSON object using exactly this structure:
{{
  "compliance_flag": true or false,
  "shift_suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"],
  "estimated_savings_usd": number
}}"""
        return self.call_ollama(prompt)

    def _heuristic_suggestions(self, peak_pct: float) -> list:
        if peak_pct >= 60:
            return [
                "Move at least 30% of production to off-peak night shifts immediately.",
                "Disable non-critical equipment during 9AM–5PM peak window.",
                "Evaluate renewable energy procurement to offset peak penalties.",
            ]
        elif peak_pct >= 40:
            return [
                "Shift 15% of production volume to off-peak windows.",
                "Review HVAC scheduling to reduce peak draw.",
            ]
        return [
            "Energy usage is within compliance. Continue monitoring peak exposure.",
        ]

    def _build_summary(self, totals: dict, peak_stats: dict,
                       peak_pct: float, compliant: bool) -> str:
        status = "COMPLIANT" if compliant else "NON-COMPLIANT"
        return (
            f"[{status}] Total energy: {totals['total_energy_kwh']:,.0f} kWh | "
            f"Carbon: {totals['total_carbon_kg']:,.0f} kg | "
            f"Penalty: ${totals['total_penalty_usd']:,.0f} | "
            f"Peak share: {peak_pct:.1f}%"
        )

    def _empty_result(self, reason: str) -> dict:
        self.publish_signal(severity="WARNING", message=reason, confidence_pct=0.0)
        return {
            "total_carbon_kg": 0.0, "total_energy_kwh": 0.0, "total_penalty_usd": 0.0,
            "peak_penalty_usd": 0.0, "off_peak_penalty_usd": 0.0,
            "peak_energy_kwh": 0.0, "off_peak_energy_kwh": 0.0,
            "peak_penalty_pct": 0.0, "compliance_flag": True,
            "shift_suggestions": [], "estimated_savings_usd": 0.0,
            "summary": reason,
        }
