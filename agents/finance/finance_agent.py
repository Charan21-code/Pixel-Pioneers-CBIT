"""
agents/finance/finance_agent.py — FinanceAgent

The top-level Finance agent that wires the 4 deterministic sub-modules:

    BudgetTracker  →  CostEstimator  →  RiskScorer  →  ApprovalRouter

Public API used by other agents:
    finance.request_clearance(request)   -> dict
    finance.financial_health_score(plan) -> float
    finance.run(context)                 -> dict  (called by Orchestrator)

Phase 3 additions to run():
    - live budget snapshot derived from current df costs
    - proposed_plan_cost derived from pending Buyer reorders
    - Ollama call for actionable cost-reduction suggestions[]
    - Ollama call for full narrative summary
    - financial risk_score (composite of OEE, inventory, demand, carbon)
"""

import logging

import numpy as np
import pandas as pd

import config
from agents.base_agent import BaseAgent
from agents.finance.budget_tracker  import BudgetTracker
from agents.finance.cost_estimator  import CostEstimator
from agents.finance.risk_scorer     import RiskScorer
from agents.finance.approval_router import ApprovalRouter

logger = logging.getLogger(__name__)

_LABOUR_RATE_USD_PER_HOUR = 15.0
_EVENT_DURATION_HOURS = 2.0


class FinanceAgent(BaseAgent):
    """
    Wires the Finance cluster.

    Usage (by BuyerAgent):
        from agents.finance.finance_agent import FinanceAgent
        fa = FinanceAgent()
        result = fa.request_clearance({
            "description":        "Reorder components",
            "estimated_cost_usd": 8500.0,
            "facility":           "Gumi (Korea) - Primary",
            "qty":                15000,
        })
        # result["decision"] -> "auto_approve" | "auto_reject" | "hitl_escalate"
        # result["clearance_token"] -> UUID4 string or None
    """

    def __init__(self, db_path: str = config.DB_PATH):
        super().__init__("FinanceAgent", db_path)
        self.budget_tracker  = BudgetTracker(db_path, config.FINANCE["monthly_budget"])
        self.cost_estimator  = CostEstimator()
        self.risk_scorer     = RiskScorer()
        self.approval_router = ApprovalRouter()

    # ── Public API ────────────────────────────────────────────────────────────

    def request_clearance(self, request: dict) -> dict:
        """
        Main gate called by BuyerAgent (and any other agent that wants to spend).

        Parameters
        ----------
        request : dict with at minimum:
            "description"        : str   — human-readable PO description
            "estimated_cost_usd" : float — raw cost before overhead

        Returns
        -------
        dict with all keys from ApprovalRouter.route() plus:
            total_cost_usd : float — overhead-adjusted cost
            budget_status  : dict  — snapshot from BudgetTracker
        """
        budget_status = self.budget_tracker.get_status()
        total_cost    = self.cost_estimator.estimate(request)
        risk_score    = self.risk_scorer.score(total_cost, budget_status)
        result        = self.approval_router.route(total_cost, risk_score, budget_status)

        # ── Log to agent_events regardless of decision ─────────────────────
        self.publish_signal(
            severity="INFO" if result["decision"] == "auto_approve" else "WARNING",
            message=(
                f"Clearance {result['decision']}: "
                f"{request.get('description', 'PO')} — "
                f"${total_cost:,.0f} | {result['reason']}"
            ),
            facility=request.get("facility"),
            confidence_pct=100.0,
            action_taken=result["decision"],
        )

        # ── Log approved spend to monthly_spend ───────────────────────────
        if result["decision"] == "auto_approve":
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO monthly_spend (amount_usd, description, cleared_by) VALUES (?,?,?)",
                    (total_cost, request.get("description"), result["clearance_token"]),
                )
                conn.commit()
            logger.info(
                "[FinanceAgent] Spend logged: $%.2f for '%s' (token=%s)",
                total_cost, request.get("description"), result["clearance_token"],
            )

        return {
            **result,
            "total_cost_usd": total_cost,
            "budget_status":  budget_status,
        }

    def financial_health_score(self, plan: dict = None) -> float:
        """
        Returns a 0–100 score representing fiscal health.
        100 = budget fully intact; 0 = budget fully exhausted.
        Used by OrchestratorAgent to decide if HITL escalation is needed.

        Parameters
        ----------
        plan : dict (unused; kept for API symmetry with Orchestrator calls)
        """
        budget = self.budget_tracker.get_status()
        score  = (budget["remaining_usd"] / config.FINANCE["monthly_budget"]) * 100
        return round(max(0.0, min(100.0, score)), 1)

    def run(self, context: dict) -> dict:
        """
        Called by OrchestratorAgent. Returns a full finance health snapshot
        including Ollama-generated cost-reduction suggestions and narrative.

        Parameters
        ----------
        context : dict
            df          - cursor-sliced production DataFrame (for cost derivation)
            as_of_time  - pd.Timestamp
            buyer       - BuyerAgent output (for inventory risk input)
            forecast    - ForecasterAgent output (for demand overshoot check)
            mechanic    - MechanicAgent output (for OEE penalty)
            environ     - EnvironmentalistAgent output (for carbon exposure)

        Returns
        -------
        dict with:
            budget_status        dict  — live operating spend/remaining/pct_used
            approved_spend_status dict — approved spend logged in monthly_spend
            health_score         float — 0–100 fiscal health
            proposed_plan_cost   float — base cost of pending reorders / planned spend
            risk_score           float — composite 0–100 financial risk
            gate_decision        str   — "APPROVED" | "BLOCKED"
            suggestions          list  — Ollama cost-reduction tips
            summary              str   — Ollama financial narrative
        """
        df: pd.DataFrame = context.get("df", pd.DataFrame())
        as_of_time = context.get("as_of_time")
        buyer_out   = context.get("buyer",   {})
        forecast    = context.get("forecast", {})
        mechanic    = context.get("mechanic", {})
        environ     = context.get("environ",  {})

        approved_spend_status = self.budget_tracker.get_status()
        budget_status         = self._derive_live_budget_status(df, as_of_time=as_of_time)
        monthly_budget        = config.FINANCE["monthly_budget"]
        spent_usd             = budget_status.get("spent_usd", 0.0)
        remaining_usd         = budget_status.get("remaining_usd", monthly_budget)
        health_score          = round(
            max(0.0, min(100.0, (remaining_usd / monthly_budget) * 100)),
            1,
        )

        # Pending Buyer requests are the best proxy for incremental plan cost.
        proposed_plan_cost = round(
            sum(float(r.get("base_cost_usd", 0.0)) for r in buyer_out.get("reorders", [])),
            2,
        )
        if proposed_plan_cost <= 0 and buyer_out.get("reorders"):
            proposed_plan_cost = round(
                sum(float(r.get("estimated_cost_usd", 0.0)) for r in buyer_out.get("reorders", []))
                / max(config.FINANCE["overhead_multiplier"], 1e-9),
                2,
            )

        projected_total = proposed_plan_cost * config.FINANCE["overhead_multiplier"]
        overhead_only   = projected_total - proposed_plan_cost
        monthly_budget = config.FINANCE["monthly_budget"]
        gate_ok        = (spent_usd + projected_total) <= monthly_budget
        gate_decision  = "APPROVED" if gate_ok else "BLOCKED"

        # ── Composite financial risk score (0–100, higher = riskier) ─────────
        risk_score = self._compute_financial_risk(
            budget_status, mechanic, buyer_out, forecast, environ
        )

        # ── Ollama: cost-reduction suggestions ────────────────────────────────
        suggestions = self._ask_ollama_suggestions(
            budget_status, risk_score, environ, buyer_out, mechanic
        )

        # ── Ollama: financial narrative summary ───────────────────────────────
        summary = self._ask_ollama_summary(
            budget_status, health_score, risk_score, gate_decision,
            proposed_plan_cost, suggestions
        )

        self.publish_signal(
            severity="INFO",
            message=(
                f"Finance health: {health_score:.1f}/100 | "
                f"Spent: ${spent_usd:,.0f} / "
                f"${monthly_budget:,.0f} "
                f"({budget_status.get('pct_used', 0):.1f}%) | "
                f"Gate: {gate_decision} | Risk: {risk_score:.0f}/100"
            ),
            confidence_pct=health_score,
            action_taken=f"Budget snapshot logged. Gate: {gate_decision}",
        )

        return {
            "budget_status":         budget_status,
            "approved_spend_status": approved_spend_status,
            "health_score":          health_score,
            "proposed_plan_cost":    round(proposed_plan_cost, 2),
            "proposed_overhead_usd": round(overhead_only, 2),
            "projected_total_usd":   round(spent_usd + projected_total, 2),
            "risk_score":            risk_score,
            "gate_decision":         gate_decision,
            "suggestions":           suggestions,
            "summary":               summary,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _derive_live_budget_status(
        self,
        df: pd.DataFrame,
        as_of_time: pd.Timestamp | None = None,
    ) -> dict:
        """
        Estimate live operating spend for the active month only.

        The dataset is recorded at a 2-hour cadence, so labour is valued per
        event at 2 hours rather than a full 8-hour shift to avoid inflating
        spend by 4× on the dashboard.
        """
        procurement_usd = 0.0
        carbon_usd      = 0.0
        labour_usd      = 0.0

        if not df.empty:
            try:
                work_df = df.copy()
                if "Timestamp" in work_df.columns:
                    ts = pd.to_datetime(work_df["Timestamp"], errors="coerce")
                    ref_ts = pd.Timestamp(as_of_time) if as_of_time is not None else ts.max()
                    if pd.notna(ref_ts):
                        month_start = ref_ts.to_period("M").to_timestamp()
                        month_end = month_start + pd.offsets.MonthBegin(1)
                        work_df = work_df[(ts >= month_start) & (ts < month_end)].copy()
                procurement_usd = float(work_df.get("Live_Supplier_Quote_USD", pd.Series(dtype=float)).sum())
                carbon_usd      = float(work_df.get("Carbon_Cost_Penalty_USD", pd.Series(dtype=float)).sum())
                workforce_total = float(work_df.get("Workforce_Deployed", pd.Series(dtype=float)).sum())
                labour_usd      = workforce_total * _EVENT_DURATION_HOURS * _LABOUR_RATE_USD_PER_HOUR
            except Exception as exc:
                logger.warning("[FinanceAgent] Live spend derivation failed: %s", exc)

        spent_usd    = procurement_usd + carbon_usd + labour_usd
        remaining_usd = config.FINANCE["monthly_budget"] - spent_usd
        pct_used     = (
            spent_usd / config.FINANCE["monthly_budget"] * 100
            if config.FINANCE["monthly_budget"] > 0 else 0.0
        )
        return {
            "spent_usd":       round(spent_usd, 2),
            "remaining_usd":   round(remaining_usd, 2),
            "pct_used":        round(pct_used, 2),
            "over_budget":     remaining_usd < 0,
            "monthly_budget":  config.FINANCE["monthly_budget"],
            "procurement_usd": round(procurement_usd, 2),
            "carbon_usd":      round(carbon_usd, 2),
            "labour_usd":      round(labour_usd, 2),
            "cost_basis":      "live_df",
        }

    def _compute_financial_risk(
        self,
        budget_status: dict,
        mechanic:      dict,
        buyer_out:     dict,
        forecast:      dict,
        environ:       dict,
    ) -> float:
        """
        Composite financial risk score 0–100 (higher = riskier).

        Components:
          OEE deviation penalty      — poor OEE → higher rework / scrap cost
          Supply shortage penalty    — days_remaining < 7 for any plant
          Demand overshoot penalty   — actual > forecast * 1.3
          Carbon penalty exposure    — peak-hour ratio
          Budget burn penalty        — pct_used > 80%
        """
        score = 0.0

        # 1. OEE deviation (from mechanic facility_risks)
        facility_risks = mechanic.get("facility_risks", {})
        if facility_risks:
            avg_oee = np.mean([
                r.get("oee_pct", 85) for r in facility_risks.values()
            ])
            oee_gap = max(0, 90 - avg_oee)   # ideal OEE = 90%
            score  += min(30, oee_gap * 1.5)

        # 2. Supply shortage
        reorders = buyer_out.get("reorders", [])
        n_critical = sum(
            1 for r in reorders
            if r.get("clearance_decision") in ("hitl_escalate", "auto_reject")
        )
        score += min(25, n_critical * 10)

        # 3. Demand overshoot
        anomaly_count = forecast.get("anomaly_count", 0)
        score += min(20, anomaly_count * 2)

        # 4. Carbon penalty exposure
        peak_ratio = environ.get("peak_penalty_pct", 0.0)
        score += min(15, peak_ratio * 30)

        # 5. Budget burn
        pct_used = budget_status.get("pct_used", 0.0)
        score += min(10, max(0, pct_used - 80) * 0.5)

        return round(min(100.0, max(0.0, score)), 1)

    def _ask_ollama_suggestions(
        self,
        budget_status: dict,
        risk_score:    float,
        environ:       dict,
        buyer_out:     dict,
        mechanic:      dict,
    ) -> list:
        """
        Ask Ollama for 3–4 specific, actionable cost-reduction suggestions.
        Returns list of strings. Falls back to heuristic list if Ollama is offline.
        """
        pct_used      = budget_status.get("pct_used", 0.0)
        peak_ratio    = environ.get("peak_penalty_pct", 0.0) * 100
        total_penalty = environ.get("total_penalty_usd", 0.0)
        n_reorders    = buyer_out.get("reorders_triggered", 0)
        critical_facs = mechanic.get("critical_facilities", [])

        prompt = f"""You are a cost-reduction analyst for a global electronics manufacturing company.

Current financial metrics:
- Budget used: {pct_used:.1f}% of ${config.FINANCE['monthly_budget']:,} monthly budget
- Financial risk score: {risk_score:.0f}/100
- Carbon penalty this period: ${total_penalty:,.0f} ({peak_ratio:.0f}% from peak hours)
- Emergency reorder requests triggered: {n_reorders}
- Facilities with critical machine risk: {len(critical_facs)}

Generate exactly 4 specific, actionable cost-reduction suggestions.
Respond ONLY with a JSON object:
{{
  "suggestions": [
    "suggestion 1 text including specific action, estimated saving, and effort level",
    "suggestion 2 text ...",
    "suggestion 3 text ...",
    "suggestion 4 text ..."
  ]
}}"""
        result = self.call_ollama(prompt)
        suggestions = result.get("suggestions", [])
        if isinstance(suggestions, list) and len(suggestions) >= 1:
            return [str(s) for s in suggestions[:6]]

        # Heuristic fallback
        fallback = []
        if peak_ratio > 30:
            fallback.append(
                f"🌙 Shift Peak-hour production batches to Off-Peak windows — "
                f"estimated saving ~${total_penalty * 0.4:,.0f} in carbon penalties. "
                f"Effort: Low (reschedule 2 shifts per plant)."
            )
        if n_reorders >= 2:
            fallback.append(
                "📦 Consolidate procurement orders across plants — combine separate POs into "
                "bulk orders to unlock supplier volume discounts (~8-12% reduction). Effort: Medium."
            )
        if critical_facs:
            fallback.append(
                f"🔧 Schedule preventive maintenance at {', '.join(critical_facs[:2])} during "
                f"Off-Peak windows — avoids emergency repair costs (~$15,000–$25,000 per incident). Effort: Low."
            )
        if pct_used > 75:
            fallback.append(
                "🔄 Review partner overflow dependency — reduce reliance on premium-rate "
                "partner facilities by improving primary plant OEE to ≥95%. Effort: Medium."
            )
        if not fallback:
            fallback.append(
                "📊 All cost indicators are within normal range. "
                "Continue monitoring carbon penalty ratios and supplier quote trends."
            )
        return fallback

    def _ask_ollama_summary(
        self,
        budget_status:     dict,
        health_score:      float,
        risk_score:        float,
        gate_decision:     str,
        proposed_cost:     float,
        suggestions:       list,
    ) -> str:
        """
        Ask Ollama for a full paragraph financial narrative.
        Falls back to a heuristic sentence if Ollama is offline.
        """
        pct_used      = budget_status.get("pct_used", 0.0)
        spent_usd     = budget_status.get("spent_usd", 0.0)
        remaining_usd = budget_status.get("remaining_usd", 0.0)
        n_suggestions = len(suggestions)

        prompt = f"""You are a CFO assistant summarising the current financial health of a global electronics factory.

Key numbers:
- Monthly budget: ${config.FINANCE['monthly_budget']:,}
- Spent to date:  ${spent_usd:,.0f} ({pct_used:.1f}%)
- Remaining:      ${remaining_usd:,.0f}
- Proposed plan cost: ${proposed_cost:,.0f}
- Finance gate decision: {gate_decision}
- Financial health score: {health_score:.1f}/100
- Financial risk score: {risk_score:.0f}/100 (higher = riskier)
- Number of cost-optimisation opportunities identified: {n_suggestions}

Write a concise 2–3 sentence financial health narrative for a factory operations dashboard.
Be specific with the numbers. Do NOT include JSON.
Respond ONLY with a JSON object:
{{
  "summary": "your 2-3 sentence narrative here"
}}"""
        result = self.call_ollama(prompt)
        summary = result.get("summary", "")
        if summary and len(summary) > 20:
            return str(summary)

        # Heuristic fallback
        risk_label = "HIGH" if risk_score > 65 else "MEDIUM" if risk_score > 35 else "LOW"
        return (
            f"Monthly spend is at {pct_used:.1f}% (${spent_usd:,.0f} of $500,000). "
            f"Finance gate is {gate_decision} — proposed plan cost of ${proposed_cost:,.0f} "
            f"{'fits within' if gate_decision == 'APPROVED' else 'exceeds'} the remaining budget. "
            f"Financial risk is {risk_label} ({risk_score:.0f}/100); "
            f"{n_suggestions} cost-reduction opportunities have been identified."
        )
