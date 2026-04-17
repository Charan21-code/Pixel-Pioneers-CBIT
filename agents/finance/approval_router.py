"""
agents/finance/approval_router.py — ApprovalRouter

Routes a purchase request to one of three outcomes:
  - auto_approve   — instant, issues a UUID clearance token
  - auto_reject    — blocked (over budget or mid-range cost + bad budget)
  - hitl_escalate  — routes to human review queue

Rules are applied in strict priority order. 100% deterministic — no LLM calls.
"""

import uuid

import config

_FINANCE = config.FINANCE


class ApprovalRouter:
    """
    Applies the Finance decision ruleset (in priority order):

    1. If over budget → auto_reject (regardless of cost)
    2. If cost < auto_approve_max → auto_approve
    3. If cost > hitl_escalate_min → hitl_escalate
    4. Otherwise → auto_approve if budget healthy, else auto_reject
    """

    def route(
        self,
        total_cost: float,
        risk_score: float,
        budget_status: dict,
    ) -> dict:
        """
        Parameters
        ----------
        total_cost    : overhead-adjusted cost from CostEstimator
        risk_score    : 0–100 score from RiskScorer
        budget_status : dict from BudgetTracker.get_status()

        Returns
        -------
        dict with keys:
            decision         : "auto_approve" | "auto_reject" | "hitl_escalate"
            clearance_token  : str (UUID4) on auto_approve, else None
            reason           : human-readable explanation
            risk_score       : float (echoed back)
        """
        # ── Rule 1: Hard reject if over budget ────────────────────────────────
        if budget_status.get("over_budget", False):
            return self._result(
                "auto_reject",
                f"Monthly budget exhausted "
                f"(${budget_status['spent_usd']:,.0f} of "
                f"${_FINANCE['monthly_budget']:,.0f} used).",
                risk_score,
            )

        # ── Rule 2: Micro-purchase fast-track ─────────────────────────────────
        if total_cost < _FINANCE["auto_approve_max"]:
            return self._result(
                "auto_approve",
                f"Cost ${total_cost:,.0f} is below auto-approval threshold "
                f"${_FINANCE['auto_approve_max']:,.0f}.",
                risk_score,
                issue_token=True,
            )

        # ── Rule 3: Large purchase → human review ─────────────────────────────
        if total_cost > _FINANCE["hitl_escalate_min"]:
            return self._result(
                "hitl_escalate",
                f"Cost ${total_cost:,.0f} exceeds HITL threshold "
                f"${_FINANCE['hitl_escalate_min']:,.0f}. Routed to human review.",
                risk_score,
            )

        # ── Rule 4: Mid-range — approve only if budget is comfortable ─────────
        if budget_status.get("remaining_usd", 0.0) >= total_cost:
            return self._result(
                "auto_approve",
                f"Cost ${total_cost:,.0f} approved within available budget "
                f"(${budget_status['remaining_usd']:,.0f} remaining).",
                risk_score,
                issue_token=True,
            )

        return self._result(
            "auto_reject",
            f"Cost ${total_cost:,.0f} exceeds remaining budget "
            f"${budget_status['remaining_usd']:,.0f}.",
            risk_score,
        )

    # ── Helper ────────────────────────────────────────────────────────────────

    @staticmethod
    def _result(
        decision: str,
        reason: str,
        risk_score: float,
        issue_token: bool = False,
    ) -> dict:
        return {
            "decision":        decision,
            "clearance_token": str(uuid.uuid4()) if issue_token else None,
            "reason":          reason,
            "risk_score":      risk_score,
        }
