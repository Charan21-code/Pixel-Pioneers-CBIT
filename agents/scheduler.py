"""
agents/scheduler.py — SchedulerAgent

Responsibility
--------------
Builds an optimised 7-day shift plan using:
  1. MechanicAgent's facility_risks — blacklists facilities with risk_score >= critical threshold
  2. ForecasterAgent's forecast_qty — total demand to cover
  3. OEE-ranked facility list from the cursor-sliced DataFrame

Calls Ollama ONCE to generate a structured JSON shift plan. Falls back to a
greedy capacity-assignment if Ollama is offline.

Live-data contract
------------------
Only reads from context["df"]. Never queries production_events from the DB.
Receives mechanic and forecast outputs as context keys passed by Orchestrator.
"""

import json
import logging

import pandas as pd

import config
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Approximate daily capacity per facility (units) used in heuristic fallback
_DEFAULT_DAILY_CAPACITY = 5_000


class SchedulerAgent(BaseAgent):
    def __init__(self, db_path: str = config.DB_PATH):
        super().__init__("Scheduler", db_path)

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self, context: dict) -> dict:
        """
        Parameters
        ----------
        context["df"]          : cursor-sliced DataFrame
        context["as_of_time"]  : pd.Timestamp
        context["mechanic"]    : MechanicAgent output dict  (required)
        context["forecast"]    : ForecasterAgent output dict (required)

        Returns
        -------
        dict with keys:
            shift_plan            list  — [{facility, shift, assigned_qty, oee_pct}]
            utilisation_pct       float — filled capacity / total capacity * 100
            expected_throughput   int   — total assigned units across all shifts
            excluded_facilities   list  — blacklisted by MechanicAgent
            available_facilities  list  — used in planning
            summary               str
        """
        df: pd.DataFrame = context.get("df", pd.DataFrame())
        mechanic_out: dict = context.get("mechanic", {})
        forecast_out: dict = context.get("forecast", {})

        if df.empty:
            return self._empty_result("No data available in context.")

        forecast_qty = int(forecast_out.get("forecast_qty", 0))

        # ── Step 1: Identify critical (blacklisted) facilities ────────────────
        critical_threshold = config.AGENT["risk_score_critical"]
        facility_risks     = mechanic_out.get("facility_risks", {})
        excluded           = [
            f for f, v in facility_risks.items()
            if v.get("risk_score", 0) >= critical_threshold
        ]

        # ── Step 2: Build OEE ranking of available facilities ─────────────────
        ranked_facilities = self._rank_facilities(df, excluded)

        if not ranked_facilities:
            self.publish_signal(
                severity="CRITICAL",
                message="No available facilities for scheduling — all are blacklisted or data missing.",
                confidence_pct=0.0,
                action_taken="HITL escalation required",
            )
            return self._empty_result("No available facilities.", excluded=excluded)

        # ── Step 3: Call Ollama for a structured shift plan ───────────────────
        llm_out = self._ask_ollama(ranked_facilities, forecast_qty, excluded)
        shift_plan = llm_out.get("shift_plan", [])

        # Fallback: greedy assignment if Ollama returned nothing
        if not shift_plan:
            shift_plan = self._greedy_assign(ranked_facilities, forecast_qty)

        # ── Step 4: Compute utilisation metrics ───────────────────────────────
        total_capacity   = len(ranked_facilities) * _DEFAULT_DAILY_CAPACITY * config.SIMULATION["sim_days"] * 3  # 3 shifts
        expected_thru    = int(sum(s.get("assigned_qty", 0) for s in shift_plan))
        utilisation_pct  = min(100.0, (expected_thru / (total_capacity + 1e-9)) * 100)

        # Override with Ollama values if provided
        utilisation_pct  = float(llm_out.get("utilisation_pct", utilisation_pct))
        if llm_out.get("expected_throughput"):
            expected_thru = int(llm_out["expected_throughput"])

        # ── Step 5: Publish signal ────────────────────────────────────────────
        summary = self._build_summary(shift_plan, excluded, utilisation_pct)
        self.publish_signal(
            severity="INFO",
            message=summary,
            confidence_pct=round(utilisation_pct, 1),
            action_taken="Shift plan committed",
        )

        return {
            "shift_plan":           shift_plan,
            "utilisation_pct":      round(utilisation_pct, 2),
            "expected_throughput":  expected_thru,
            "excluded_facilities":  excluded,
            "available_facilities": [f["facility"] for f in ranked_facilities],
            "summary":              summary,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _rank_facilities(self, df: pd.DataFrame, excluded: list) -> list:
        """
        Groups df by Assigned_Facility, computes mean OEE, filters out blacklisted
        facilities and those below min_oee_for_assignment.
        Returns sorted list of {facility, oee_pct} dicts (best OEE first).
        """
        min_oee = config.AGENT.get("min_oee_for_assignment", 80)
        try:
            grouped = (
                df.groupby("Assigned_Facility")
                .agg(oee_pct=("Machine_OEE_Pct", "mean"))
                .reset_index()
            )
            ranked = []
            for _, row in grouped.iterrows():
                fac = row["Assigned_Facility"]
                oee = float(row["oee_pct"])
                if fac in excluded:
                    continue
                if oee < min_oee:
                    continue
                ranked.append({"facility": fac, "oee_pct": round(oee, 1)})

            # Sort by OEE descending (best first)
            ranked.sort(key=lambda x: x["oee_pct"], reverse=True)
            return ranked
        except Exception as exc:
            logger.warning("[Scheduler] Facility ranking failed: %s", exc)
            return []

    def _ask_ollama(self, facilities: list, forecast_qty: int, excluded: list) -> dict:
        """
        One LLM call to generate a structured shift plan.
        Expected JSON:
        {
          "shift_plan": [
            {"facility": "...", "shift": "AM|PM|Night", "assigned_qty": N, "oee_pct": N}
          ],
          "utilisation_pct": float,
          "expected_throughput": int
        }
        """
        prompt = f"""You are a production scheduler for a global electronics factory.

Available facilities (sorted by OEE, best first):
{json.dumps(facilities, indent=2)}

Excluded facilities (critical maintenance risk):
{excluded}

Total demand to fulfil over {config.SIMULATION['sim_days']} days: {forecast_qty:,} units

Assign production across AM, PM, and Night shifts. Prioritise high-OEE facilities.
Do not assign to excluded facilities.

Respond ONLY with a JSON object using exactly this structure:
{{
  "shift_plan": [
    {{
      "facility": "exact facility name",
      "shift": "AM or PM or Night",
      "assigned_qty": integer,
      "oee_pct": number
    }}
  ],
  "utilisation_pct": number,
  "expected_throughput": integer
}}"""
        return self.call_ollama(prompt)

    def _greedy_assign(self, facilities: list, forecast_qty: int) -> list:
        """
        Simple greedy assignment: distribute forecast_qty proportionally by OEE
        across all shifts (AM, PM, Night) for each available facility.
        """
        if not facilities or forecast_qty <= 0:
            return []

        total_oee  = sum(f["oee_pct"] for f in facilities) or 1
        shifts     = ["AM", "PM", "Night"]
        plan       = []
        remaining  = forecast_qty

        for i, fac in enumerate(facilities):
            fac_share = int(forecast_qty * (fac["oee_pct"] / total_oee))
            per_shift  = fac_share // len(shifts)

            for shift in shifts:
                qty = per_shift
                # Give leftover to last facility's last shift
                if i == len(facilities) - 1 and shift == shifts[-1]:
                    assigned_so_far = sum(s["assigned_qty"] for s in plan)
                    qty = max(0, forecast_qty - assigned_so_far)

                plan.append({
                    "facility":    fac["facility"],
                    "shift":       shift,
                    "assigned_qty": qty,
                    "oee_pct":     fac["oee_pct"],
                })

        return plan

    def _build_summary(self, shift_plan: list, excluded: list, util_pct: float) -> str:
        n_shifts    = len(shift_plan)
        n_excluded  = len(excluded)
        throughput  = sum(s.get("assigned_qty", 0) for s in shift_plan)
        return (
            f"Shift plan: {n_shifts} shifts planned | "
            f"Est. throughput: {throughput:,} units | "
            f"Utilisation: {util_pct:.1f}% | "
            f"{n_excluded} facilit{'ies' if n_excluded != 1 else 'y'} excluded (maintenance)."
        )

    def _empty_result(self, reason: str, excluded: list = None) -> dict:
        self.publish_signal(severity="WARNING", message=reason, confidence_pct=0.0)
        return {
            "shift_plan":           [],
            "utilisation_pct":      0.0,
            "expected_throughput":  0,
            "excluded_facilities":  excluded or [],
            "available_facilities": [],
            "summary":              reason,
        }
