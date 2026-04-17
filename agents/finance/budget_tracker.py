"""
agents/finance/budget_tracker.py — BudgetTracker

Tracks monthly spend against the configured budget by querying the
monthly_spend table. 100% deterministic — no LLM calls.
"""

import sqlite3
from datetime import datetime

import config


class BudgetTracker:
    """
    Reads the monthly_spend table and computes budget utilisation for the
    current calendar month.
    """

    def __init__(self, db_path: str = config.DB_PATH,
                 monthly_budget: float = config.FINANCE["monthly_budget"]):
        self.db_path        = db_path
        self.monthly_budget = monthly_budget

    def get_status(self) -> dict:
        """
        Returns
        -------
        dict with keys:
            spent_usd      float — total spend logged this calendar month
            remaining_usd  float — monthly_budget - spent_usd (may be negative)
            pct_used       float — spent / budget * 100
            over_budget    bool
        """
        now       = datetime.utcnow()
        month_str = now.strftime("%Y-%m")   # e.g. "2026-04"

        try:
            conn = sqlite3.connect(self.db_path)
            row  = conn.execute(
                """
                SELECT COALESCE(SUM(amount_usd), 0.0)
                FROM monthly_spend
                WHERE strftime('%Y-%m', logged_at) = ?
                """,
                (month_str,),
            ).fetchone()
            conn.close()
            spent = float(row[0]) if row else 0.0
        except Exception:
            spent = 0.0

        remaining = self.monthly_budget - spent
        pct_used  = (spent / self.monthly_budget * 100) if self.monthly_budget > 0 else 0.0

        return {
            "spent_usd":     round(spent,     2),
            "remaining_usd": round(remaining, 2),
            "pct_used":      round(pct_used,  2),
            "over_budget":   remaining < 0,
        }
