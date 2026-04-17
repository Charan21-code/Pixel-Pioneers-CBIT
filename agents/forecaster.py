"""
agents/forecaster.py — ForecasterAgent

Responsibility
--------------
Analyses demand trends from the cursor-sliced production_events DataFrame,
fits a linear regression on the last 14 days of daily totals, projects the
next 7 days, detects demand-spike anomalies, and calls Ollama once for a
natural-language summary.

Live-data contract
------------------
Only reads from context["df"]. Never queries production_events from the DB.
"""

import logging
from datetime import timedelta

import requests
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

import config
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class ForecasterAgent(BaseAgent):
    def __init__(self, db_path: str = config.DB_PATH):
        super().__init__("Forecaster", db_path)

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self, context: dict) -> dict:
        """
        Parameters
        ----------
        context["df"]          : cursor-sliced DataFrame (only historical rows)
        context["as_of_time"]  : pd.Timestamp of the latest row in df

        Returns
        -------
        dict with keys:
            forecast_qty        int     — projected demand for next period
            trend_slope         float   — units gained per day
            r_squared           float   — model R²  (0–1)
            anomaly_count       int     — rows where actual > forecast * (1 + spike_pct)
            anomaly_rows        list    — list of Order_IDs flagged
            risk_level          str     — 'low' | 'medium' | 'high'  (from LLM or heuristic)
            summary             str     — natural-language summary
            recommended_action  str     — next step
            horizon_days        int     — 7 (fixed)
        """
        df: pd.DataFrame = context.get("df", pd.DataFrame())
        as_of_time: pd.Timestamp = context.get("as_of_time", pd.Timestamp.now())

        if df.empty:
            return self._empty_result("No data available in context.")

        # ── Step 1: Aggregate daily demand ───────────────────────────────────
        daily = self._daily_demand(df)

        # ── Step 2: Fit linear regression on last 14 days ────────────────────
        reg_result = self._fit_regression(daily)

        # ── Step 3: Project next 7 days ──────────────────────────────────────
        forecast_qty = self._project(reg_result, horizon_days=config.SIMULATION["sim_days"])

        # ── Step 3.5: Social Sentiment Monitor ───────────────────────────────
        sentiment = self._fetch_social_sentiment()
        viral_demand_shock = sentiment["viral_demand_shock"]
        trending_product   = sentiment["trending_product"]

        if viral_demand_shock:
            forecast_qty = int(forecast_qty * config.VIRAL_SHOCK["surge_multiplier"])

        # ── Step 4: Anomaly detection ─────────────────────────────────────────
        anomaly_count, anomaly_rows = self._detect_anomalies(df)

        # ── Step 5: Heuristic risk label (used as fallback) ───────────────────
        slope = reg_result["slope"]
        heuristic_risk = (
            "high"   if anomaly_count > 10 or slope > 500 or viral_demand_shock else
            "medium" if anomaly_count > 3  or slope > 100 else
            "low"
        )

        # ── Step 6: Single Ollama call ────────────────────────────────────────
        llm_out = self._ask_ollama(
            avg_demand=daily["Actual_Order_Qty"].mean() if not daily.empty else 0,
            trend_slope=slope,
            anomaly_count=anomaly_count,
            r_squared=reg_result["r_squared"],
        )

        risk_level         = llm_out.get("risk_level",         heuristic_risk)
        summary            = llm_out.get("summary",            self._heuristic_summary(slope, anomaly_count))
        recommended_action = llm_out.get("recommended_action", "Monitor daily demand trends.")

        if viral_demand_shock:
            risk_level = "high"
            summary = f"🚨 VIRAL DEMAND SHOCK DETECTED. Trending mentions for '{trending_product}' ({sentiment['mentions']}+). Auto-surging forecast by {config.VIRAL_SHOCK['surge_multiplier']}x."
            recommended_action = "Enable Demand Surge Protocol immediately."

        # ── Step 7: Publish one signal ────────────────────────────────────────
        severity = (
            "CRITICAL" if risk_level == "high" else
            "WARNING"  if risk_level == "medium" else
            "INFO"
        )
        self.publish_signal(
            severity=severity,
            message=summary,
            confidence_pct=round(reg_result["r_squared"] * 100, 1),
            action_taken=recommended_action,
        )

        return {
            "forecast_qty":        forecast_qty,
            "trend_slope":         round(slope, 2),
            "r_squared":           round(reg_result["r_squared"], 4),
            "anomaly_count":       anomaly_count,
            "anomaly_rows":        anomaly_rows[:10],  # cap list size
            "risk_level":          risk_level,
            "summary":             summary,
            "recommended_action":  recommended_action,
            "horizon_days":        config.SIMULATION["sim_days"],
            "viral_demand_shock":  viral_demand_shock,
            "trending_product":    trending_product,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch_social_sentiment(self) -> dict:
        """
        Optional REST API call for social sentiment scraping.
        If the endpoint is unavailable, do not fabricate a crisis.
        """
        try:
            resp = requests.get(config.VIRAL_SHOCK["api_url"], timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                mentions = data.get("mentions", 0)
                product = data.get("trending_product", "")
            else:
                raise ValueError("Not 200")
        except Exception:
            logger.info("[Forecaster] Social sentiment feed unavailable; skipping viral-shock override.")
            mentions = 0
            product = ""

        is_viral = mentions >= config.VIRAL_SHOCK["mention_threshold"]
        return {"viral_demand_shock": is_viral, "trending_product": product, "mentions": mentions}

    def _daily_demand(self, df: pd.DataFrame) -> pd.DataFrame:
        """Resample to daily totals of Actual_Order_Qty."""
        try:
            daily = (
                df.set_index("Timestamp")
                .resample("D")["Actual_Order_Qty"]
                .sum()
                .reset_index()
            )
            return daily.dropna()
        except Exception as exc:
            logger.warning("[Forecaster] Daily aggregation failed: %s", exc)
            return pd.DataFrame(columns=["Timestamp", "Actual_Order_Qty"])

    def _fit_regression(self, daily: pd.DataFrame) -> dict:
        """
        Fit LinearRegression on the last 14 daily rows.
        Returns slope, intercept, r_squared. Falls back to zeros on failure.
        """
        tail = daily.tail(14)
        if len(tail) < 2:
            return {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}

        X = np.arange(len(tail)).reshape(-1, 1)
        y = tail["Actual_Order_Qty"].values

        try:
            model = LinearRegression().fit(X, y)
            r2    = max(0.0, model.score(X, y))
            return {
                "slope":     float(model.coef_[0]),
                "intercept": float(model.intercept_),
                "r_squared": r2,
            }
        except Exception as exc:
            logger.warning("[Forecaster] Regression failed: %s", exc)
            return {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}

    def _project(self, reg_result: dict, horizon_days: int) -> int:
        """Project average daily demand for the next `horizon_days` days."""
        n = 14  # offset from the end of training window
        projected_days = [
            reg_result["intercept"] + reg_result["slope"] * (n + i)
            for i in range(1, horizon_days + 1)
        ]
        total = max(0, int(sum(projected_days)))
        return total

    def _detect_anomalies(self, df: pd.DataFrame) -> tuple[int, list]:
        """
        Rows where Actual_Order_Qty > Forecasted_Demand * (1 + demand_spike_pct).
        Returns (count, list_of_order_ids).
        """
        spike_threshold = 1 + config.AGENT["demand_spike_pct"]
        try:
            mask      = df["Actual_Order_Qty"] > df["Forecasted_Demand"] * spike_threshold
            anomalies = df[mask]
            order_ids = anomalies["Order_ID"].tolist() if "Order_ID" in anomalies.columns else []
            return len(anomalies), order_ids
        except Exception as exc:
            logger.warning("[Forecaster] Anomaly detection failed: %s", exc)
            return 0, []

    def _ask_ollama(self, avg_demand: float, trend_slope: float,
                    anomaly_count: int, r_squared: float) -> dict:
        """
        One LLM call. If Ollama is offline, returns {}.
        Expected JSON from model:
        {
          "summary": "...",
          "risk_level": "low|medium|high",
          "recommended_action": "..."
        }
        """
        prompt = f"""You are a production demand analyst for a global electronics factory.

Current demand statistics:
- Average daily demand: {avg_demand:.0f} units
- Trend slope: {trend_slope:+.1f} units/day (positive = growing)
- Demand spike anomalies detected: {anomaly_count}
- Regression confidence (R²): {r_squared:.2f}

Respond ONLY with a JSON object using exactly these keys:
{{
  "summary": "2-3 sentence plain English summary of demand health",
  "risk_level": "low or medium or high",
  "recommended_action": "single most important next step"
}}"""
        return self.call_ollama(prompt)

    def _heuristic_summary(self, slope: float, anomaly_count: int) -> str:
        direction = "rising" if slope > 0 else "falling"
        return (
            f"Demand is {direction} at {abs(slope):.1f} units/day. "
            f"{anomaly_count} spike anomalies detected in current window."
        )

    def _empty_result(self, reason: str) -> dict:
        self.publish_signal(severity="WARNING", message=reason, confidence_pct=0.0)
        return {
            "forecast_qty": 0, "trend_slope": 0.0, "r_squared": 0.0,
            "anomaly_count": 0, "anomaly_rows": [],
            "risk_level": "low", "summary": reason,
            "recommended_action": "Ensure data is available.", "horizon_days": 7,
        }
