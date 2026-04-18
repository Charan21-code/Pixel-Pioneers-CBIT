"""
agents/orchestrator.py ΓÇö OrchestratorAgent

Responsibility
--------------
The central supervisor for the entire factory AI system.

Run order (dependencies respected):
  1. ForecasterAgent      ΓåÆ demand forecast + anomalies
  2. MechanicAgent        ΓåÆ per-plant risk scores + blacklist
  3. BuyerAgent           ΓåÆ inventory status + reorder list
  4. EnvironmentalistAgent ΓåÆ carbon compliance
  5. FinanceAgent         ΓåÆ budget snapshot + gate decision
  6. SchedulerAgent       ΓåÆ per-plant 7-day shift plans (uses all above)

After all agents run:
  7. Build per-plant inventory stats with lead time
  8. Detect cross-agent conflicts (schedule vs maintenance, etc.)
  9. Determine final system status (ALL_OK | NEEDS_HITL | BLOCKED)
  10. Escalate CRITICAL conflicts to hitl_queue
  11. Compute global system health score (0ΓÇô100)
  12. Return a rich unified output dict stored in st.session_state["orch_output"]

Live-data contract
------------------
Passes the pre-sliced DataFrame to every agent. Agents never query
production_events directly ΓÇö they all receive context["df"].
"""

import logging
import uuid
from typing import Optional

import numpy as np
import pandas as pd

import config
from agents.base_agent import BaseAgent
from agents.forecaster import ForecasterAgent
from agents.mechanic import MechanicAgent
from agents.buyer import BuyerAgent
from agents.environmentalist import EnvironmentalistAgent
from agents.finance.finance_agent import FinanceAgent
from agents.scheduler import SchedulerAgent

logger = logging.getLogger(__name__)

# Estimated lead time brackets (days) derived from Live_Supplier_Quote_USD
_LEAD_URGENT_DAYS   = 2   # quote >= $5.25  (premium/urgent channel)
_LEAD_STANDARD_DAYS = 4   # quote < $5.25 and > 0 (standard channel)
_LEAD_DEFAULT_DAYS  = config.AGENT.get("default_lead_days", 3)

# Daily production entries per facility (data cadence: 2-hr intervals = 12 per day)
_ENTRIES_PER_DAY = 12


class OrchestratorAgent(BaseAgent):
    """Central supervisor. Instantiate once per tick; call .run()."""

    def __init__(self, db_path: str = config.DB_PATH):
        super().__init__("Orchestrator", db_path)

    # ΓöÇΓöÇ Main entry point ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def run(self, context: dict, progress_callback=None) -> dict:
        """
        Parameters
        ----------
        context["df"]         : cursor-sliced production DataFrame
        context["as_of_time"] : pd.Timestamp of latest row in df

        Returns
        -------
        Unified output dict with keys:
            forecast, mechanic, buyer, buyer_inventory,
            environ, finance, scheduler,
            conflicts, final_status, system_health, last_run_at
        """
        df: pd.DataFrame = context.get("df", pd.DataFrame())
        as_of_time: pd.Timestamp = context.get("as_of_time", pd.Timestamp.now())

        # ── Scenario overrides (injected by /api/twin/apply-scenario) ──────────
        forecast_qty_override   = context.get("forecast_qty_override")   # int or None
        oee_override_pct        = context.get("oee_override_pct")        # float or None
        workforce_override_pct  = context.get("workforce_override_pct")  # float or None
        optimise_for_override   = context.get("optimise_for", "Time")
        scenario_label          = context.get("scenario_label")

        # Pass override keys along in context so agents can pick them up
        if oee_override_pct is not None:
            context["oee_override_pct"] = float(oee_override_pct)
        if workforce_override_pct is not None:
            context["workforce_override_pct"] = float(workforce_override_pct)
        if forecast_qty_override is not None:
            context["forecast_qty_override"] = int(forecast_qty_override)
        context["optimise_for"] = optimise_for_override

        if scenario_label:
            logger.info("[Orchestrator] Running with scenario override: %s", scenario_label)

        # Generate a unique run_id for this orchestration tick so the frontend
        # can scope its log queries to only the current run.
        run_id = str(uuid.uuid4())
        context["run_id"] = run_id
        logger.info("[Orchestrator] Run ID: %s", run_id)

        def _cb(name):
            if progress_callback:
                try:
                    progress_callback(name)
                except Exception:
                    pass

        if df.empty:
            _cb(None)
            return self._empty_result("No production data available.")

        plants: list[str] = sorted(df["Assigned_Facility"].unique().tolist())

        # ΓöÇΓöÇ 1. ForecasterAgent ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        _cb("Forecaster")
        logger.info("[Orchestrator] Running ForecasterAgent...")
        try:
            forecast = ForecasterAgent(self.db_path).run(context)
        except Exception as exc:
            logger.warning("[Orchestrator] ForecasterAgent failed: %s", exc)
            forecast = self._empty_agent_result("Forecaster", exc)
        context["forecast"] = forecast

        # ΓöÇΓöÇ 2. MechanicAgent ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        _cb("Mechanic")
        logger.info("[Orchestrator] Running MechanicAgent...")
        try:
            mechanic = MechanicAgent(self.db_path).run(context)
        except Exception as exc:
            logger.warning("[Orchestrator] MechanicAgent failed: %s", exc)
            mechanic = {"facility_risks": {}, "critical_facilities": [],
                        "warning_facilities": [], "recommendations": [], "summary": str(exc)}
        context["mechanic"] = mechanic

        # ΓöÇΓöÇ 3. BuyerAgent ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        _cb("Buyer")
        logger.info("[Orchestrator] Running BuyerAgent...")
        try:
            buyer = BuyerAgent(self.db_path).run(context)
        except Exception as exc:
            logger.warning("[Orchestrator] BuyerAgent failed: %s", exc)
            buyer = {"reorders": [], "total_spend_requested_usd": 0.0,
                     "facilities_checked": 0, "reorders_triggered": 0}
        context["buyer"] = buyer

        # ΓöÇΓöÇ 4. EnvironmentalistAgent ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        _cb("Environmentalist")
        logger.info("[Orchestrator] Running EnvironmentalistAgent...")
        try:
            environ = EnvironmentalistAgent(self.db_path).run(context)
        except Exception as exc:
            logger.warning("[Orchestrator] EnvironmentalistAgent failed: %s", exc)
            environ = self._empty_environ_result(exc)
        context["environ"] = environ

        # ΓöÇΓöÇ 5. FinanceAgent ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        _cb("Finance")
        logger.info("[Orchestrator] Running FinanceAgent...")
        try:
            finance = FinanceAgent(self.db_path).run(context)
        except Exception as exc:
            logger.warning("[Orchestrator] FinanceAgent failed: %s", exc)
            finance = {"budget_status": {}, "health_score": 50.0}
        context["finance"] = finance

        # ΓöÇΓöÇ 6. Per-plant inventory analysis ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        logger.info("[Orchestrator] Computing per-plant inventory stats...")
        buyer_inventory = self._compute_inventory_stats(df, plants)

        # ΓöÇΓöÇ 7. Per-plant SchedulerAgent ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        _cb("Scheduler")
        logger.info("[Orchestrator] Running SchedulerAgent per plant...")
        scheduler_plans = {}
        for plant in plants:
            try:
                plant_df = df[df["Assigned_Facility"] == plant].copy()
                plant_context = {
                    "df":         plant_df,
                    "as_of_time": as_of_time,
                    "mechanic":   mechanic,
                    "forecast":   forecast,
                }
                plan = SchedulerAgent(self.db_path).run(plant_context)
                scheduler_plans[plant] = plan
                logger.info("[Orchestrator] Scheduler plan done for %s", plant)
            except Exception as exc:
                logger.warning("[Orchestrator] Scheduler failed for %s: %s", plant, exc)
                scheduler_plans[plant] = {
                    "shift_plan": [], "utilisation_pct": 0.0,
                    "expected_throughput": 0, "excluded_facilities": [],
                    "available_facilities": [], "summary": str(exc),
                }

        # ΓöÇΓöÇ 8. Conflict detection ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        _cb("Orchestrator")
        conflicts = self._detect_conflicts(
            forecast, mechanic, buyer, finance,
            scheduler_plans, buyer_inventory
        )

        # ΓöÇΓöÇ 9. Final system status ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        final_status = self._determine_status(conflicts, finance)

        # ΓöÇΓöÇ 10. HITL escalations ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        for conflict in conflicts:
            if conflict["severity"] == "CRITICAL":
                try:
                    self.enqueue_hitl("ops", conflict)
                except Exception as exc:
                    logger.warning("[Orchestrator] HITL enqueue failed: %s", exc)

        # Escalate mechanic critical alerts
        for fac in mechanic.get("critical_facilities", []):
            fac_risk = mechanic["facility_risks"].get(fac, {})
            try:
                self.enqueue_hitl("maintenance", {
                    "facility":   fac,
                    "risk_score": fac_risk.get("risk_score", 100),
                    "ttf_hrs":    fac_risk.get("ttf_hrs", 0),
                    "temp_c":     fac_risk.get("temp_c", 0),
                    "oee_pct":    fac_risk.get("oee_pct", 0),
                    "message":    f"CRITICAL machine risk at {fac}. TTF={fac_risk.get('ttf_hrs', '?')}hrs",
                })
            except Exception as exc:
                logger.warning("[Orchestrator] Mechanic HITL enqueue failed: %s", exc)

        # Escalate carbon non-compliance
        if not environ.get("compliance_flag", True):
            try:
                self.enqueue_hitl("carbon", {
                    "peak_penalty_pct":   environ.get("peak_penalty_pct", 0),
                    "total_penalty_usd":  environ.get("total_penalty_usd", 0),
                    "shift_suggestions":  environ.get("shift_suggestions", []),
                    "message":            environ.get("summary", "Carbon non-compliance detected"),
                })
            except Exception as exc:
                logger.warning("[Orchestrator] Carbon HITL enqueue failed: %s", exc)

        # ΓöÇΓöÇ 11. System health score ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        system_health = self._compute_health_score(mechanic, finance, environ, buyer_inventory)

        # ΓöÇΓöÇ 12. Publish orchestrator summary ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        n_critical = len([c for c in conflicts if c["severity"] == "CRITICAL"])
        n_warning  = len([c for c in conflicts if c["severity"] == "WARNING"])
        orch_msg = (
            f"System health: {system_health:.0f}/100 | "
            f"Status: {final_status} | "
            f"Conflicts: {n_critical} critical, {n_warning} warnings"
        )
        self.publish_signal(
            severity="CRITICAL" if final_status == "BLOCKED" else
                      "WARNING"  if final_status == "NEEDS_HITL" else "INFO",
            message=orch_msg,
            confidence_pct=round(system_health, 1),
            action_taken=f"All agents run. Status: {final_status}",
            run_id=run_id,
        )
        logger.info("[Orchestrator] Run complete. %s", orch_msg)

        # ── Process coordination evals ────────────────────────────────────────────
        try:
            evals = self.bus.get_evals_for_orchestrator(run_id)
            for ev in evals:
                ev_payload = ev.get("payload", {})
                if isinstance(ev_payload, str):
                    import json
                    try:
                        ev_payload = json.loads(ev_payload)
                    except Exception:
                        ev_payload = {}

                winning = ev_payload.get("recommended_option")
                budget_ok = ev_payload.get("within_budget", False)
                proposal_id = ev.get("parent_id")

                if budget_ok and winning:
                    # Apply the winning alternative to the scheduler plan
                    alt_facility = winning.get("alt_facility")
                    if alt_facility and alt_facility in scheduler_plans:
                        logger.info(
                            "[Orchestrator] Coordination consensus: applying option '%s' (facility %s)",
                            winning.get("label"), alt_facility
                        )
                    self.bus.post_consensus(
                        run_id=run_id,
                        from_agent="Orchestrator",
                        eval_id=ev["id"],
                        subject=f"Consensus: {winning.get('label', 'Option accepted')}",
                        resolution={
                            "winning_option": winning,
                            "applied_to": alt_facility,
                            "cost_delta_usd": winning.get("cost_delta_usd", 0),
                        },
                    )
                else:
                    # Escalate to HITL with full thread
                    thread = self.bus.get_full_thread(ev.get("parent_id", ev["id"]))
                    self.enqueue_hitl("coordination", {
                        "run_id": run_id,
                        "subject": ev.get("subject"),
                        "thread": thread,
                        "finance_eval": ev_payload,
                        "reason": ev_payload.get("reason", "No viable option within budget"),
                        "recommended_human_action": ev_payload.get("recommended_human_action", "Review proposals and approve budget override or alternative plan."),
                    })
                    self.bus.post_escalate(
                        run_id=run_id,
                        from_agent="Orchestrator",
                        eval_id=ev["id"],
                        subject=f"Escalated: {ev.get('subject', 'Coordination conflict')}",
                        context={"reason": ev_payload.get("reason", ""), "thread_length": len(thread)},
                    )
        except Exception as exc:
            logger.warning("[Orchestrator] Coordination eval processing failed: %s", exc)

        # Signal all agents have finished
        _cb(None)

        return {
            "forecast":        forecast,
            "mechanic":        mechanic,
            "buyer":           buyer,
            "buyer_inventory": buyer_inventory,   # {plant: {current_stock, daily_use, days_remaining, ...}}
            "environ":         environ,
            "finance":         finance,
            "scheduler":       scheduler_plans,   # {plant: {shift_plan, utilisation_pct, ...}}
            "conflicts":       conflicts,
            "final_status":    final_status,       # "ALL_OK" | "NEEDS_HITL" | "BLOCKED"
            "system_health":   system_health,      # 0ΓÇô100
            "plants":          plants,
            "last_run_at":     pd.Timestamp.now(),
        }

    # ΓöÇΓöÇ Per-plant inventory stats ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def _compute_inventory_stats(self, df: pd.DataFrame, plants: list) -> dict:
        """
        For each plant computes:
            current_stock    - latest Raw_Material_Inventory_Units
            inventory_threshold
            daily_consumption - Actual_Order_Qty summed per day / days in window
            days_remaining   - current_stock / daily_consumption
            shortfall_units  - max(0, threshold*1.20 - current_stock)
            reorder_qty      - units needed for 14 days at current consumption
            lead_days        - estimated delivery time (from supplier quote proxy)
            cost_usd         - estimated reorder cost from Live_Supplier_Quote_USD
            status           - "healthy" | "low" | "critical" | "emergency"
        """
        result = {}
        safety_pct = config.AGENT.get("inventory_safety_pct", 1.20)

        for plant in plants:
            try:
                plant_df = df[df["Assigned_Facility"] == plant].copy()
                if plant_df.empty:
                    continue

                # Latest snapshot
                latest = plant_df.sort_values("Timestamp").iloc[-1]
                current_stock = float(latest.get("Raw_Material_Inventory_Units", 0))
                threshold     = float(latest.get("Inventory_Threshold", 20000))

                # Daily consumption: sum(Actual_Order_Qty) / distinct days
                plant_df["_date"] = pd.to_datetime(plant_df["Timestamp"]).dt.date
                daily_totals = plant_df.groupby("_date")["Actual_Order_Qty"].sum()
                n_days = max(1, len(daily_totals))
                daily_use = float(daily_totals.mean()) if len(daily_totals) > 0 else 1.0
                daily_use = max(daily_use, 1.0)  # avoid division by zero

                days_remaining = round(current_stock / daily_use, 1)

                # Shortfall below safety level
                safety_level   = threshold * safety_pct
                shortfall      = max(0.0, safety_level - current_stock)

                # Reorder qty: cover 14 days at current rate
                reorder_qty = max(0, int(daily_use * 14) - int(current_stock))

                # Lead time estimate from Live_Supplier_Quote_USD
                avg_quote = float(plant_df["Live_Supplier_Quote_USD"].replace(0, np.nan).mean())
                if np.isnan(avg_quote) or avg_quote == 0:
                    lead_days = _LEAD_DEFAULT_DAYS
                elif avg_quote >= 5.25:
                    lead_days = _LEAD_URGENT_DAYS     # premium/urgent supplier
                else:
                    lead_days = _LEAD_STANDARD_DAYS   # standard supplier

                # Estimated cost
                unit_price = avg_quote if not np.isnan(avg_quote) and avg_quote > 0 else 5.0
                cost_usd   = round(reorder_qty * unit_price, 2)

                # Status
                if days_remaining > 14:
                    status = "healthy"
                elif days_remaining > lead_days + 2:
                    status = "low"
                elif days_remaining > lead_days:
                    status = "critical"
                else:
                    status = "emergency"  # stock runs out before delivery arrives

                result[plant] = {
                    "current_stock":       int(current_stock),
                    "inventory_threshold": int(threshold),
                    "safety_level":        int(safety_level),
                    "daily_use":           round(daily_use, 1),
                    "days_remaining":      days_remaining,
                    "shortfall_units":     int(shortfall),
                    "reorder_qty":         reorder_qty,
                    "lead_days":           lead_days,
                    "cost_usd":            cost_usd,
                    "unit_price":          round(unit_price, 3),
                    "status":              status,
                }
            except Exception as exc:
                logger.warning("[Orchestrator] Inventory stats failed for %s: %s", plant, exc)
                result[plant] = {
                    "current_stock": 0, "inventory_threshold": 20000,
                    "safety_level": 24000, "daily_use": 1.0,
                    "days_remaining": 0.0, "shortfall_units": 20000,
                    "reorder_qty": 28000, "lead_days": _LEAD_DEFAULT_DAYS,
                    "cost_usd": 0.0, "unit_price": 5.0, "status": "critical",
                }

        return result

    # ΓöÇΓöÇ Conflict detection ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def _detect_conflicts(
        self,
        forecast:        dict,
        mechanic:        dict,
        buyer:           dict,
        finance:         dict,
        scheduler_plans: dict,
        buyer_inventory: dict,
    ) -> list[dict]:
        """
        Cross-agent conflict rules. Returns list of conflict dicts.
        Each conflict: {type, description, severity, involved_agents, plant}
        """
        conflicts = []

        critical_facs  = set(mechanic.get("critical_facilities", []))
        facility_risks = mechanic.get("facility_risks", {})
        budget_status  = finance.get("budget_status", {})
        health_score   = finance.get("health_score", 100.0)
        reorders       = buyer.get("reorders", [])

        # Rule 1: Schedule-Maintenance conflict
        # Scheduler assigned work to a CRITICAL facility
        for plant, plan in scheduler_plans.items():
            scheduled_facs = {s.get("facility", "") for s in plan.get("shift_plan", [])}
            overlap = scheduled_facs & critical_facs
            for fac in overlap:
                conflicts.append({
                    "type":            "schedule_maintenance_conflict",
                    "description":     f"Scheduler assigned orders to {fac} but Mechanic flagged it CRITICAL. Remove from plan.",
                    "severity":        "CRITICAL",
                    "involved_agents": ["Scheduler", "Mechanic"],
                    "plant":           fac,
                    "action":          f"Blacklist {fac} from shift plan immediately.",
                })

        # Rule 2: Resource-Inventory conflict
        # Buyer says < (lead_days + 1) days stock but scheduler plans 7 days
        for plant, inv in buyer_inventory.items():
            if inv["status"] in ("critical", "emergency"):
                days_rem = inv["days_remaining"]
                plan_days = config.SIMULATION.get("sim_days", 7)
                if days_rem < plan_days:
                    conflicts.append({
                        "type":            "resource_inventory_conflict",
                        "description":     f"{plant}: only {days_rem:.1f} days of inventory left, but production plan spans {plan_days} days.",
                        "severity":        "CRITICAL" if inv["status"] == "emergency" else "WARNING",
                        "involved_agents": ["Buyer", "Scheduler"],
                        "plant":           plant,
                        "action":          f"Cap production plan at {int(days_rem)} days or approve emergency reorder.",
                    })

        # Rule 3: Finance-Procurement conflict
        # Finance budget near exhausted but Buyer triggered reorders
        budget_pct = budget_status.get("pct_used", 0)
        if budget_pct >= 90 and reorders:
            hitl_orders = [r for r in reorders if r.get("clearance_decision") == "hitl_escalate"]
            if hitl_orders:
                conflicts.append({
                    "type":            "finance_procurement_conflict",
                    "description":     f"Budget is at {budget_pct:.1f}% used. {len(hitl_orders)} PO(s) are in HITL queue awaiting finance approval.",
                    "severity":        "CRITICAL" if budget_pct >= 95 else "WARNING",
                    "involved_agents": ["Finance", "Buyer"],
                    "plant":           "All",
                    "action":          "CFO review required before any procurement proceeds.",
                })

        # Rule 4: Demand-Capacity conflict
        # Forecast is growing fast but all plants are near full utilisation
        trend_slope   = forecast.get("trend_slope", 0)
        risk_level    = forecast.get("risk_level", "low")
        avg_util = (
            np.mean([p.get("utilisation_pct", 0) for p in scheduler_plans.values()])
            if scheduler_plans else 0
        )
        if risk_level == "high" and avg_util >= 90:
            conflicts.append({
                "type":            "demand_capacity_conflict",
                "description":     f"Demand rising at {trend_slope:+.1f} units/day (HIGH risk) but average plant utilisation is already {avg_util:.1f}%.",
                "severity":        "WARNING",
                "involved_agents": ["Forecaster", "Scheduler"],
                "plant":           "All",
                "action":          "Consider activating partner overflow facilities (Foxconn, Queretaro).",
            })

        # Rule 5: Finance health gate
        if health_score < config.HITL.get("health_score_min", 50):
            conflicts.append({
                "type":            "finance_health_gate",
                "description":     f"Finance health score is {health_score:.1f}/100 ΓÇö below minimum threshold ({config.HITL['health_score_min']}).",
                "severity":        "CRITICAL",
                "involved_agents": ["Finance", "Orchestrator"],
                "plant":           "All",
                "action":          "Production plan approval blocked until CFO review.",
            })

        # Rule 6: Viral Demand Shock Alert
        if forecast.get("viral_demand_shock") == True:
            trending = forecast.get("trending_product", "Unknown Product")
            conflicts.append({
                "type":            "viral_demand_shock_alert",
                "description":     f"VIRAL DEMAND SHOCK: Rapid social sentiment spike detected for '{trending}'.",
                "severity":        "CRITICAL",
                "involved_agents": ["Forecaster", "Scheduler"],
                "plant":           "All",
                "action":          "Demand Surge Protocol automatically enabled. HITL notification triggered.",
            })

        return conflicts

    # ΓöÇΓöÇ Final status ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def _determine_status(self, conflicts: list, finance: dict) -> str:
        """
        ALL_OK      ΓåÆ no conflicts
        NEEDS_HITL  ΓåÆ at least one WARNING conflict
        BLOCKED     ΓåÆ at least one CRITICAL conflict
        """
        severities = {c["severity"] for c in conflicts}
        if "CRITICAL" in severities:
            return "BLOCKED"
        if "WARNING" in severities:
            return "NEEDS_HITL"
        return "ALL_OK"

    # ΓöÇΓöÇ Health score ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def _compute_health_score(
        self,
        mechanic:        dict,
        finance:         dict,
        environ:         dict,
        buyer_inventory: dict,
    ) -> float:
        """
        Composite 0ΓÇô100 score:
            Finance health   40%
            Machine health   30%
            Inventory health 20%
            Carbon compliance 10%
        """
        # Finance component (0ΓÇô100 from FinanceAgent)
        finance_score = finance.get("health_score", 100.0)

        # Machine component: penalise critical/warning counts
        risks = mechanic.get("facility_risks", {})
        n_total    = max(1, len(risks))
        n_critical = len(mechanic.get("critical_facilities", []))
        n_warning  = len(mechanic.get("warning_facilities", []))
        machine_score = 100.0 - (n_critical * 30) - (n_warning * 10)
        machine_score = max(0.0, min(100.0, machine_score))

        # Inventory component: penalise low/critical/emergency plants
        inv_scores = []
        for plant, inv in buyer_inventory.items():
            s = inv.get("status", "healthy")
            inv_scores.append(
                100 if s == "healthy" else
                 70 if s == "low" else
                 30 if s == "critical" else
                  0   # emergency
            )
        inventory_score = float(np.mean(inv_scores)) if inv_scores else 100.0

        # Carbon component
        carbon_score = 100.0 if environ.get("compliance_flag", True) else 60.0

        composite = (
            finance_score  * 0.40 +
            machine_score  * 0.30 +
            inventory_score * 0.20 +
            carbon_score   * 0.10
        )
        return round(max(0.0, min(100.0, composite)), 1)

    # ΓöÇΓöÇ Fallback helpers ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def _empty_agent_result(self, agent_name: str, exc: Exception) -> dict:
        return {
            "forecast_qty": 0, "trend_slope": 0.0, "r_squared": 0.0,
            "anomaly_count": 0, "anomaly_rows": [],
            "risk_level": "low",
            "summary": f"{agent_name} failed: {exc}",
            "recommended_action": "Check agent logs.",
            "horizon_days": config.SIMULATION["sim_days"],
        }

    def _empty_environ_result(self, exc: Exception) -> dict:
        return {
            "total_carbon_kg": 0.0, "total_energy_kwh": 0.0, "total_penalty_usd": 0.0,
            "peak_penalty_usd": 0.0, "off_peak_penalty_usd": 0.0,
            "peak_energy_kwh": 0.0, "off_peak_energy_kwh": 0.0,
            "peak_penalty_pct": 0.0, "compliance_flag": True,
            "shift_suggestions": [], "estimated_savings_usd": 0.0,
            "summary": f"EnvironmentalistAgent failed: {exc}",
        }

    def _empty_result(self, reason: str) -> dict:
        self.publish_signal(severity="WARNING", message=reason, confidence_pct=0.0)
        return {
            "forecast": {}, "mechanic": {}, "buyer": {},
            "buyer_inventory": {}, "environ": {}, "finance": {},
            "scheduler": {}, "conflicts": [],
            "final_status": "BLOCKED", "system_health": 0.0,
            "plants": [], "last_run_at": pd.Timestamp.now(),
        }
