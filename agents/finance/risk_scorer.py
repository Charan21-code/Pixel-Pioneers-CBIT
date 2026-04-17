"""
agents/finance/risk_scorer.py — RiskScorer

Computes a 0–100 risk score for a purchase request relative to the remaining
monthly budget. 100% deterministic — no LLM calls.
"""


class RiskScorer:
    """
    Risk score = (total_cost / remaining_budget) * 100, clamped to [0, 100].
    A score of 100 means the request alone would exhaust the remaining budget.
    """

    def score(self, total_cost: float, budget_status: dict) -> float:
        """
        Parameters
        ----------
        total_cost     : float — overhead-adjusted cost from CostEstimator
        budget_status  : dict  — from BudgetTracker.get_status()

        Returns
        -------
        float — risk score in [0, 100]
        """
        remaining = budget_status.get("remaining_usd", 0.0)
        # Use remaining + 1 as denominator to avoid division by zero
        raw_score = (total_cost / (remaining + 1.0)) * 100
        return round(min(100.0, max(0.0, raw_score)), 2)
