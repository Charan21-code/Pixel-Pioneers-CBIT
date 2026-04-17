"""
agents/mechanic.py — MechanicAgent

Responsibility
--------------
Monitors machine health across all facilities in the cursor-sliced DataFrame.
Computes a risk score per facility from TTF, OEE, and temperature readings.
Calls Ollama ONCE (not per facility) with the worst-3 facilities for structured
maintenance recommendations. Publishes signals for critical/warning facilities.

Live-data contract
------------------
Only reads from context["df"]. Never queries production_events from the DB.
"""

import json
import logging

import pandas as pd

import config
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Risk score weights
_TTF_CRITICAL_SCORE = 100
_TTF_WARNING_SCORE  = 60
_TTF_HEALTHY_SCORE  = 20
_OEE_PENALTY        = 15   # added when OEE < config.AGENT["oee_warning_pct"]


class MechanicAgent(BaseAgent):
    def __init__(self, db_path: str = config.DB_PATH):
        super().__init__("Mechanic", db_path)

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
            facility_risks      dict  — {facility_name: {risk_score, status, ttf_hrs, oee_pct, temp_c}}
            critical_facilities list  — names with status == 'critical'
            warning_facilities  list  — names with status == 'warning'
            recommendations     list  — [{facility, action, estimated_downtime_hrs}] from LLM
            summary             str   — plain English summary
        """
        df: pd.DataFrame = context.get("df", pd.DataFrame())

        if df.empty:
            return self._empty_result("No data available in context.")

        # ── Step 1: Compute per-facility risk scores ──────────────────────────
        facility_risks = self._score_facilities(df)

        # ── Step 2: Classify buckets ──────────────────────────────────────────
        critical  = [f for f, v in facility_risks.items() if v["status"] == "critical"]
        warning   = [f for f, v in facility_risks.items() if v["status"] == "warning"]

        # ── Step 3: Publish signals for critical/warning facilities ───────────
        for fac in critical:
            r = facility_risks[fac]
            self.publish_signal(
                severity="CRITICAL",
                message=(
                    f"Imminent failure risk. TTF={r['ttf_hrs']:.1f}h, "
                    f"OEE={r['oee_pct']:.1f}%, Temp={r['temp_c']:.1f}C"
                ),
                facility=fac,
                confidence_pct=round(r["risk_score"], 1),
                action_taken="Triggered emergency maintenance check",
            )

        for fac in warning:
            r = facility_risks[fac]
            self.publish_signal(
                severity="WARNING",
                message=(
                    f"Elevated failure risk. TTF={r['ttf_hrs']:.1f}h, "
                    f"OEE={r['oee_pct']:.1f}%"
                ),
                facility=fac,
                confidence_pct=round(r["risk_score"], 1),
                action_taken="Schedule inspection",
            )

        if not critical and not warning:
            self.publish_signal(
                severity="INFO",
                message="All facilities within healthy operating parameters.",
                confidence_pct=95.0,
                action_taken="No action required",
            )

        # ── Step 4: Single Ollama call for top-3 worst facilities ─────────────
        worst_3 = sorted(
            facility_risks.items(), key=lambda kv: kv[1]["risk_score"], reverse=True
        )[:3]

        recommendations = self._ask_ollama(worst_3)

        # ── Step 5: Build summary ─────────────────────────────────────────────
        summary = self._build_summary(critical, warning, facility_risks)

        return {
            "facility_risks":      facility_risks,
            "critical_facilities": critical,
            "warning_facilities":  warning,
            "recommendations":     recommendations,
            "summary":             summary,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _score_facilities(self, df: pd.DataFrame) -> dict:
        """
        Groups df by Assigned_Facility. For each facility, computes mean
        TTF, OEE, and Temperature, then assigns a risk score 0–100.
        """
        ttf_critical = config.AGENT["ttf_critical_hrs"]
        ttf_warning  = config.AGENT["ttf_warning_hrs"]
        oee_warn     = config.AGENT["oee_warning_pct"]

        results = {}

        try:
            grouped = df.groupby("Assigned_Facility").agg(
                ttf_hrs=("Predicted_Time_To_Failure_Hrs", "mean"),
                oee_pct=("Machine_OEE_Pct",              "mean"),
                temp_c =("Machine_Temperature_C",         "mean"),
            ).reset_index()
        except Exception as exc:
            logger.warning("[Mechanic] Groupby failed: %s", exc)
            return {}

        for _, row in grouped.iterrows():
            fac     = row["Assigned_Facility"]
            ttf     = row["ttf_hrs"]
            oee     = row["oee_pct"]
            temp    = row["temp_c"]

            # Base score from TTF
            if ttf < ttf_critical:
                score = _TTF_CRITICAL_SCORE
            elif ttf < ttf_warning:
                score = _TTF_WARNING_SCORE
            else:
                score = _TTF_HEALTHY_SCORE

            # OEE penalty
            if oee < oee_warn:
                score = min(100, score + _OEE_PENALTY)

            risk_threshold = config.AGENT["risk_score_critical"]
            status = (
                "critical" if score >= risk_threshold else
                "warning"  if score >= 50 else
                "healthy"
            )

            results[fac] = {
                "risk_score": round(score, 1),
                "status":     status,
                "ttf_hrs":    round(ttf,  1),
                "oee_pct":    round(oee,  1),
                "temp_c":     round(temp, 1),
            }

        return results

    def _ask_ollama(self, worst_3: list) -> list:
        """
        Sends the top-3 riskiest facilities to Ollama.
        Expected JSON:
        {
          "recommendations": [
            {"facility": "...", "action": "...", "estimated_downtime_hrs": N}
          ]
        }
        Falls back to a heuristic list on empty response.
        """
        machines_payload = [
            {
                "facility":   fac,
                "risk_score": data["risk_score"],
                "ttf_hrs":    data["ttf_hrs"],
                "oee_pct":    data["oee_pct"],
                "temp_c":     data["temp_c"],
            }
            for fac, data in worst_3
        ]

        prompt = f"""You are a factory maintenance engineer at a global electronics manufacturer.

The following facilities have the highest machine failure risk right now:
{json.dumps(machines_payload, indent=2)}

Respond ONLY with a JSON object using exactly this structure:
{{
  "recommendations": [
    {{
      "facility": "exact facility name",
      "action": "specific maintenance action to take",
      "estimated_downtime_hrs": number
    }}
  ]
}}"""

        llm_out = self.call_ollama(prompt)
        recs    = llm_out.get("recommendations", [])

        if not recs:
            # Heuristic fallback
            recs = [
                {
                    "facility":              fac,
                    "action":                (
                        "Emergency shutdown and inspection" if data["status"] == "critical"
                        else "Schedule preventive maintenance within 48 hours"
                    ),
                    "estimated_downtime_hrs": 4 if data["status"] == "critical" else 2,
                }
                for fac, data in worst_3
            ]

        return recs

    def _build_summary(self, critical: list, warning: list, risks: dict) -> str:
        total = len(risks)
        if not critical and not warning:
            return f"All {total} facilities are healthy."
        parts = []
        if critical:
            parts.append(f"{len(critical)} CRITICAL: {', '.join(critical)}")
        if warning:
            parts.append(f"{len(warning)} WARNING: {', '.join(warning)}")
        return f"{total} facilities monitored. " + "; ".join(parts) + "."

    def _empty_result(self, reason: str) -> dict:
        self.publish_signal(severity="WARNING", message=reason, confidence_pct=0.0)
        return {
            "facility_risks":      {},
            "critical_facilities": [],
            "warning_facilities":  [],
            "recommendations":     [],
            "summary":             reason,
        }
