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
        context["forecast_qty_override"] : optional plant-specific demand target
        context["oee_override"]          : optional slider override (0-1 or 0-100)
        context["workforce_override"]    : optional slider override (0-1 or 0-100)
        context["demand_buffer_pct"]     : optional safety buffer added to demand
        context["optimise_for"]          : optional "Time" | "Cost" | "Carbon"

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
        run_id: str = context.get("run_id")

        if df.empty:
            return self._empty_result("No data available in context.")

        self.publish_signal(
            severity="INFO",
            message="Building 7-day shift plan. Analysing OEE rankings and checking coordination blockers...",
            confidence_pct=50.0,
            action_taken="Scheduling started",
            run_id=run_id,
        )

        viral_demand_shock = forecast_out.get("viral_demand_shock", False)
        optimise_for = str(context.get("optimise_for", "Time") or "Time").title()
        if viral_demand_shock:
            optimise_for = "Surge"
            
        demand_buffer_pct = float(context.get("demand_buffer_pct", 0.0) or 0.0)
        forecast_qty = int(
            context.get("forecast_qty_override", forecast_out.get("forecast_qty", 0)) or 0
        )
        planning_target_qty = max(0, int(round(forecast_qty * (1 + demand_buffer_pct))))
        oee_override_pct = self._normalise_pct_override(context.get("oee_override"))
        workforce_override_pct = self._normalise_pct_override(context.get("workforce_override"))
        overrides_active = any(
            val is not None
            for val in (
                context.get("forecast_qty_override"),
                context.get("oee_override"),
                context.get("workforce_override"),
            )
        ) or demand_buffer_pct > 0 or optimise_for != "Time"

        # ── Step 1: Identify critical (blacklisted) facilities ────────────────
        critical_threshold = config.AGENT["risk_score_critical"]
        facility_risks     = mechanic_out.get("facility_risks", {})
        excluded           = [
            f for f, v in facility_risks.items()
            if v.get("risk_score", 0) >= critical_threshold
        ]

        # ── Step 2: Build OEE ranking of available facilities ─────────────────
        ranked_facilities = self._rank_facilities(df, excluded, oee_override_pct)

        if not ranked_facilities:
            self.publish_signal(
                severity="CRITICAL",
                message="No available facilities for scheduling — all are blacklisted or data missing.",
                confidence_pct=0.0,
                action_taken="HITL escalation required",
            )
            return self._empty_result("No available facilities.", excluded=excluded)

        # ── Step 3: Call Ollama for a structured shift plan ───────────────────
        llm_out = {}
        if not overrides_active:
            llm_out = self._ask_ollama(ranked_facilities, planning_target_qty, excluded)
        shift_plan = llm_out.get("shift_plan", [])

        # Fallback: deterministic planner when overrides are present or Ollama returned nothing
        if overrides_active or not shift_plan:
            shift_plan = self._capacity_assign(
                ranked_facilities,
                planning_target_qty,
                workforce_override_pct=workforce_override_pct,
                optimise_for=optimise_for,
            )

        # ── Step 4: Compute utilisation metrics ───────────────────────────────
        total_capacity = self._estimate_total_capacity(
            ranked_facilities,
            workforce_override_pct=workforce_override_pct,
            optimise_for=optimise_for,
        )
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
            run_id=run_id,
        )

        # ── Step 6: Coordination — read blockers, post proposals ──────────────
        if run_id:
            self._handle_coordination_blockers(run_id, ranked_facilities, context)

        return {
            "shift_plan":           shift_plan,
            "utilisation_pct":      round(utilisation_pct, 2),
            "expected_throughput":  expected_thru,
            "excluded_facilities":  excluded,
            "available_facilities": [f["facility"] for f in ranked_facilities],
            "planning_target_qty":  planning_target_qty,
            "parameters_applied": {
                "optimise_for": optimise_for,
                "oee_pct": oee_override_pct,
                "workforce_pct": workforce_override_pct,
                "demand_buffer_pct": demand_buffer_pct,
                "forecast_qty": forecast_qty,
            },
            "summary":              summary,
        }

    # ── Coordination: read blockers, post proposals ─────────────────────────

    def _handle_coordination_blockers(
        self, run_id: str, ranked_facilities: list, context: dict
    ):
        """For each open blocker assigned to Scheduler, use Ollama to generate
        3 alternative options and post them as a proposal for Finance to evaluate."""
        blockers = self.bus.get_open_blockers(run_id, to_agent="Scheduler")
        for blocker in blockers:
            try:
                payload = blocker.get("payload", {})
                if isinstance(payload, str):
                    import json as _json
                    payload = _json.loads(payload)

                options = self._generate_alternatives_ollama(
                    blocker=blocker,
                    payload=payload,
                    ranked_facilities=ranked_facilities,
                    context=context,
                )
                if not options:
                    logger.warning("[Scheduler] No alternatives generated for blocker %s", blocker["id"])
                    continue

                proposal_subject = f"Alternatives for: {blocker['subject']}"
                self.bus.post_proposal(
                    run_id=run_id,
                    from_agent=self.agent_name,
                    blocker_id=blocker["id"],
                    subject=proposal_subject,
                    options=options,
                )
                self.publish_signal(
                    severity="INFO",
                    message=f"PROPOSAL posted: {len(options)} alternatives for blocker ‘{blocker['subject'][:60]}’",
                    confidence_pct=80.0,
                    action_taken="Coordination proposal posted to Finance",
                    run_id=run_id,
                )
            except Exception as exc:
                logger.warning("[Scheduler] Blocker handling failed for %s: %s", blocker.get("id"), exc)

    def _generate_alternatives_ollama(self, blocker: dict, payload: dict, ranked_facilities: list, context: dict) -> list:
        """Use Ollama to generate 3 concrete alternative options for a supply blocker."""
        facility = payload.get("facility", "unknown")
        sku = payload.get("sku", "Unknown SKU")
        days_remaining = payload.get("days_remaining", 0)
        delay_days = payload.get("delay_days", 5)
        unit_price = payload.get("unit_price", 5.0)
        reorder_qty = payload.get("daily_demand_est", 500) * delay_days

        alt_facilities = [
            f["facility"] for f in ranked_facilities
            if f["facility"] != facility
        ][:2]

        prompt = f"""You are a production scheduler resolving a supply chain blocker at a global electronics factory.

BLOCKER DETAILS:
- Affected facility: {facility}
- Material at risk: {sku}
- Current stock coverage: {days_remaining:.0f} days
- Required lead time: {delay_days} days
- Estimated daily demand: {payload.get('daily_demand_est', 500)} units
- Estimated reorder cost: ${reorder_qty * unit_price:,.0f}
- Urgency: {payload.get('reorder_urgency', 'MEDIUM')}

Alternative facilities available:
{alt_facilities}

Generate exactly 3 alternative options to resolve this blocker. Each option must have a realistic cost delta and lead time impact.

Respond ONLY with this JSON structure:
{{
  "options": [
    {{
      "label": "Short option name (max 6 words)",
      "description": "One sentence explaining the option",
      "alt_facility": "facility name if shifting, else null",
      "cost_delta_usd": number,
      "lead_time_delta_days": number,
      "risk_level": "LOW|MEDIUM|HIGH"
    }}
  ]
}}"""
        result = self.call_ollama(prompt)
        return result.get("options", [
            {
                "label": "Expedite from current supplier",
                "description": f"Pay premium freight to get {sku} to {facility} in {max(1,delay_days-2)} days.",
                "alt_facility": None,
                "cost_delta_usd": round(reorder_qty * unit_price * 0.35, 0),
                "lead_time_delta_days": -2,
                "risk_level": "MEDIUM",
            },
            {
                "label": f"Shift production to {alt_facilities[0] if alt_facilities else 'backup facility'}",
                "description": f"Re-route orders to {alt_facilities[0] if alt_facilities else 'backup'} until stock at {facility} recovers.",
                "alt_facility": alt_facilities[0] if alt_facilities else None,
                "cost_delta_usd": round(reorder_qty * unit_price * 0.12, 0),
                "lead_time_delta_days": 1,
                "risk_level": "LOW",
            },
            {
                "label": "Substitute compatible material",
                "description": f"Use similar-spec material already in stock at {facility} for the next {delay_days} days.",
                "alt_facility": None,
                "cost_delta_usd": round(reorder_qty * unit_price * 0.05, 0),
                "lead_time_delta_days": 0,
                "risk_level": "HIGH",
            },
        ])

    # ── Private helpers ───────────────────────────────────────────────────────

    def _rank_facilities(self, df: pd.DataFrame, excluded: list, oee_override_pct: float = None) -> list:
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
                if oee_override_pct is not None and len(grouped) == 1:
                    oee = oee_override_pct
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

    def _capacity_assign(
        self,
        facilities: list,
        forecast_qty: int,
        workforce_override_pct: float = None,
        optimise_for: str = "Time",
    ) -> list:
        """
        Deterministic planner used for local slider overrides and fallback mode.
        It caps production by estimated 7-day facility capacity, then splits the
        assigned quantity across AM/PM/Night according to the optimisation goal.
        """
        if not facilities or forecast_qty <= 0:
            return []

        shift_mix = {
            "Time":   [0.38, 0.34, 0.28],
            "Cost":   [0.42, 0.33, 0.25],
            "Carbon": [0.28, 0.27, 0.45],
            "Surge":  [0.34, 0.33, 0.33],
        }
        shifts = ["AM", "PM", "Night"]
        mix = shift_mix.get(optimise_for, shift_mix["Time"])

        capacities = []
        total_capacity = self._estimate_total_capacity(
            facilities,
            workforce_override_pct=workforce_override_pct,
            optimise_for=optimise_for,
            by_facility=True,
        )
        total_cap_units = sum(item["capacity_units"] for item in total_capacity)
        planned_total = min(forecast_qty, total_cap_units)
        assigned_so_far = 0
        plan = []

        for idx, fac in enumerate(total_capacity):
            if idx == len(total_capacity) - 1:
                facility_target = max(0, planned_total - assigned_so_far)
            else:
                capacity_share = fac["capacity_units"] / max(total_cap_units, 1)
                facility_target = int(round(planned_total * capacity_share))
                assigned_so_far += facility_target

            shift_assigned = 0
            for shift_idx, shift_name in enumerate(shifts):
                if shift_idx == len(shifts) - 1:
                    assigned_qty = max(0, facility_target - shift_assigned)
                else:
                    assigned_qty = int(round(facility_target * mix[shift_idx]))
                    shift_assigned += assigned_qty

                plan.append({
                    "facility": fac["facility"],
                    "shift": shift_name,
                    "assigned_qty": assigned_qty,
                    "oee_pct": round(fac["oee_pct"], 1),
                })

        return plan

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

    def _estimate_total_capacity(
        self,
        facilities: list,
        workforce_override_pct: float = None,
        optimise_for: str = "Time",
        by_facility: bool = False,
    ):
        """
        Estimate 7-day capacity based on facility OEE, workforce coverage, and
        optimisation goal. Returns either a summed integer or per-facility rows.
        """
        if not facilities:
            return [] if by_facility else 0

        workforce_factor = (
            (workforce_override_pct / 100.0)
            if workforce_override_pct is not None else 1.0
        )
        optimise_factor = {
            "Time": 1.00,
            "Cost": 0.96,
            "Carbon": 0.92,
            "Surge": 1.00,
        }.get(optimise_for, 1.00)

        capacity_rows = []
        for fac in facilities:
            oee_factor = max(0.5, min(1.0, float(fac.get("oee_pct", 100.0)) / 100.0))
            capacity_units = int(
                round(
                    _DEFAULT_DAILY_CAPACITY
                    * config.SIMULATION["sim_days"]
                    * oee_factor
                    * workforce_factor
                    * optimise_factor
                )
            )
            capacity_rows.append({
                "facility": fac["facility"],
                "oee_pct": fac.get("oee_pct", 100.0),
                "capacity_units": max(0, capacity_units),
            })

        if by_facility:
            return capacity_rows
        return sum(item["capacity_units"] for item in capacity_rows)

    def _normalise_pct_override(self, value):
        """Accept either fractional (0.9) or percentage (90) slider inputs."""
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        if value <= 1.5:
            value *= 100.0
        return max(50.0, min(100.0, value))

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
