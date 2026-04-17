"""
agents/finance/finance_agent.py — FinanceAgent

The top-level Finance agent that wires the 4 deterministic sub-modules:

    BudgetTracker  →  CostEstimator  →  RiskScorer  →  ApprovalRouter

Public API used by other agents:
    finance.request_clearance(request)  -> dict
    finance.financial_health_score(plan) -> float

Zero LLM calls. All decisions are instant and deterministic.
"""

import logging

import config
from agents.base_agent import BaseAgent
from agents.finance.budget_tracker  import BudgetTracker
from agents.finance.cost_estimator  import CostEstimator
from agents.finance.risk_scorer     import RiskScorer
from agents.finance.approval_router import ApprovalRouter

logger = logging.getLogger(__name__)


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
        Called by OrchestratorAgent. Returns a finance health snapshot.
        Does NOT process a spending request — use request_clearance() for that.

        Parameters
        ----------
        context : dict (df, as_of_time) — not used by Finance, included for API conformity

        Returns
        -------
        dict with budget_status + health_score
        """
        budget_status = self.budget_tracker.get_status()
        health_score  = self.financial_health_score()

        self.publish_signal(
            severity="INFO",
            message=(
                f"Finance health: {health_score:.1f}/100 | "
                f"Spent: ${budget_status['spent_usd']:,.0f} / "
                f"${config.FINANCE['monthly_budget']:,.0f} "
                f"({budget_status['pct_used']:.1f}%)"
            ),
            confidence_pct=health_score,
            action_taken="Budget snapshot logged",
        )

        return {
            "budget_status": budget_status,
            "health_score":  health_score,
        }
