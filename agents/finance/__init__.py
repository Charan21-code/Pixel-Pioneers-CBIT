# agents/finance/__init__.py
# Re-export the public API of the Finance cluster.
from agents.finance.finance_agent import FinanceAgent

__all__ = ["FinanceAgent"]
# Finance Agent cluster.
# Sub-modules: budget_tracker, cost_estimator, risk_scorer, approval_router
# Main entrypoint: finance_agent.FinanceAgent
