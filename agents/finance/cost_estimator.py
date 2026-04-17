"""
agents/finance/cost_estimator.py — CostEstimator

Applies a fixed overhead multiplier (default 15%) to any raw cost estimate.
100% deterministic — no LLM calls.
"""

import config


class CostEstimator:
    """
    Applies FINANCE["overhead_multiplier"] to a request's estimated_cost_usd.
    """

    OVERHEAD_MULTIPLIER: float = config.FINANCE.get("overhead_multiplier", 1.15)

    def estimate(self, request: dict) -> float:
        """
        Parameters
        ----------
        request : dict with key "estimated_cost_usd" (float)

        Returns
        -------
        float — total_cost = estimated_cost_usd * OVERHEAD_MULTIPLIER
        """
        raw_cost   = float(request.get("estimated_cost_usd", 0.0))
        total_cost = raw_cost * self.OVERHEAD_MULTIPLIER
        return round(total_cost, 2)
