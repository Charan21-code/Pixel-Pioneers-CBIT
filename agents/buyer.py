"""
agents/buyer.py — BuyerAgent

Responsibility
--------------
Checks raw-material inventory levels for each facility in the cursor-sliced
DataFrame. When stock falls below the safety threshold, it computes a reorder
quantity and submits a purchase-order (PO) clearance request to FinanceAgent
BEFORE creating the order — no money moves without Finance approval.

Decision flow per reorder opportunity
--------------------------------------
  inventory < threshold * safety_pct?
        │
  YES   └─→ estimate cost → FinanceAgent.request_clearance()
                │
                ├── auto_approve  → publish INFO signal + log monthly_spend
                ├── auto_reject   → publish WARNING signal (no PO)
                └── hitl_escalate → enqueue_hitl() + publish WARNING signal

Live-data contract
------------------
Only reads from context["df"]. Never queries production_events from the DB.
FinanceAgent is instantiated lazily to avoid circular imports.
"""

import logging
from typing import TYPE_CHECKING

import pandas as pd

import config
from agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from agents.finance.finance_agent import FinanceAgent  # type-check only

logger = logging.getLogger(__name__)

# Estimated per-unit cost (USD) used when no quote data is available in df
_DEFAULT_UNIT_COST_USD = 5.00


class BuyerAgent(BaseAgent):
    def __init__(self, db_path: str = config.DB_PATH):
        super().__init__("Buyer", db_path)
        self._finance = None   # lazy-loaded

    # ── Lazy-load Finance to avoid circular imports ───────────────────────────

    @property
    def finance(self):
        if self._finance is None:
            from agents.finance.finance_agent import FinanceAgent
            self._finance = FinanceAgent(db_path=self.db_path)
        return self._finance

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self, context: dict) -> dict:
        """
        Parameters
        ----------
        context["df"]          : cursor-sliced DataFrame
        context["as_of_time"]  : pd.Timestamp
        context["forecast"]    : ForecasterAgent output dict (optional)
            Used to size reorder_qty = forecast_qty * 1.5 - current_stock

        Returns
        -------
        dict with keys:
            reorders                  list  — one entry per triggered reorder
            total_spend_requested_usd float — sum across all reorder costs
            total_approved_spend_usd  float — approved portion logged by Finance
            facilities_checked        int
            reorders_triggered        int
            summary                   str   — Buyer narrative for the dashboard
        """
        df: pd.DataFrame = context.get("df", pd.DataFrame())
        forecast: dict   = context.get("forecast", {})
        forecast_qty     = int(forecast.get("forecast_qty", 0))

        if df.empty:
            return self._empty_result("No data available in context.")

        # ── Step 1: Compute per-facility inventory snapshot ───────────────────
        inventory_snap = self._inventory_snapshot(df)

        reorders: list[dict] = []
        total_requested_spend = 0.0
        total_approved_spend  = 0.0
        summary               = ""

        # ── Step 2: Evaluate each facility ───────────────────────────────────
        for fac, snap in inventory_snap.items():
            current_stock = snap["inventory_units"]
            threshold     = snap["inventory_threshold"]
            safety_level  = threshold * config.AGENT["inventory_safety_pct"]

            if current_stock >= safety_level:
                continue  # No reorder needed

            # Compute reorder quantity
            if forecast_qty > 0:
                reorder_qty = max(0, int(forecast_qty * 1.5) - current_stock)
            else:
                # Fallback: top-up to 2× threshold
                reorder_qty = max(0, int(threshold * 2) - current_stock)

            if reorder_qty <= 0:
                continue

            # Estimate cost
            estimated_cost = reorder_qty * snap.get("unit_price", _DEFAULT_UNIT_COST_USD)

            # ── Step 3: Finance clearance (mandatory gate) ────────────────────
            clearance_request = {
                "agent":               "Buyer",
                "description":         f"Reorder {snap['product']} components @ {fac}",
                "estimated_cost_usd":  estimated_cost,
                "facility":            fac,
                "qty":                 reorder_qty,
            }
            clearance = self.finance.request_clearance(clearance_request)
            decision  = clearance["decision"]

            # ── Step 4: Publish signal based on decision ──────────────────────
            severity = "INFO" if decision == "auto_approve" else "WARNING"
            self.publish_signal(
                severity=severity,
                message=(
                    f"PO {decision}: {reorder_qty:,} units @ {fac} "
                    f"(${clearance['total_cost_usd']:,.0f}) — {clearance.get('reason', '')}"
                ),
                facility=fac,
                confidence_pct=100.0,
                action_taken=decision,
            )

            # ── Step 5: HITL escalation if needed ────────────────────────────
            if decision == "hitl_escalate":
                self.enqueue_hitl(
                    "finance",
                    {
                        **clearance_request,
                        "clearance_result": clearance,
                    },
                )

            reorder_entry = {
                "facility":             fac,
                "item":                 snap["product"],
                "current_stock":        current_stock,
                "reorder_qty":          reorder_qty,
                "base_cost_usd":        round(estimated_cost, 2),
                "estimated_cost_usd":   float(clearance["total_cost_usd"]),
                "total_cost_usd":       float(clearance["total_cost_usd"]),
                "clearance_decision":   decision,
                "clearance_token":      clearance.get("clearance_token"),
                "risk_score":           clearance.get("risk_score", 0.0),
                "budget_remaining_usd": clearance.get("budget_status", {}).get("remaining_usd", 0.0),
            }
            reorders.append(reorder_entry)
            total_requested_spend += float(clearance["total_cost_usd"])

            if decision == "auto_approve":
                total_approved_spend += clearance["total_cost_usd"]

        # ── Step 6: Ollama call for supplier rationale ────────────────────────
        if reorders:
            llm_out = self._ask_ollama(reorders)
            summary = llm_out.get("summary", self._heuristic_summary(reorders))
            for i, rec in enumerate(reorders):
                supplier_info = llm_out.get("suppliers", [{}])[i] if i < len(llm_out.get("suppliers", [])) else {}
                rec["supplier"] = supplier_info.get("supplier", "Preferred supplier")
                rec["supplier_rationale"] = supplier_info.get("rationale", "")

        if not reorders:
            summary = "All facility inventory levels are above safety thresholds."
            self.publish_signal(
                severity="INFO",
                message=summary,
                confidence_pct=95.0,
                action_taken="No reorder required",
            )

        return {
            "reorders":                  reorders,
            "total_spend_requested_usd": round(total_requested_spend, 2),
            "total_approved_spend_usd":  round(total_approved_spend, 2),
            "facilities_checked":        len(inventory_snap),
            "reorders_triggered":        len(reorders),
            "summary":                   summary,
            "narrative":                 summary,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _inventory_snapshot(self, df: pd.DataFrame) -> dict:
        """
        Computes the latest inventory reading per facility.
        Returns {facility_name: {inventory_units, inventory_threshold, product}}.
        """
        result = {}
        try:
            # Use last (most recent) row per facility for current stock.
            latest = df.sort_values("Timestamp").groupby("Assigned_Facility").last().reset_index()
            for _, row in latest.iterrows():
                fac = row["Assigned_Facility"]
                fac_df = df[df["Assigned_Facility"] == fac]
                quote_series = pd.Series(dtype=float)
                if "Live_Supplier_Quote_USD" in fac_df.columns:
                    quote_series = fac_df["Live_Supplier_Quote_USD"].replace(0, pd.NA).dropna()
                unit_price = float(quote_series.mean()) if not quote_series.empty else _DEFAULT_UNIT_COST_USD
                result[fac] = {
                    "inventory_units":      float(row.get("Raw_Material_Inventory_Units", 0)),
                    "inventory_threshold":  float(row.get("Inventory_Threshold", 0)),
                    "product":              str(row.get("Product_Category", row.get("Product_ID", "Unknown"))),
                    "unit_price":           round(unit_price, 3),
                }
        except Exception as exc:
            logger.warning("[Buyer] Inventory snapshot failed: %s", exc)
        return result

    def _ask_ollama(self, reorders: list) -> dict:
        """
        One LLM call to get supplier selection rationale.
        Expected JSON:
        {
          "summary": "2-3 sentence inventory summary",
          "suppliers": [
            {"facility": "...", "supplier": "...", "rationale": "..."}
          ]
        }
        """
        summary = [
            {"facility": r["facility"], "item": r["item"], "qty": r["reorder_qty"]}
            for r in reorders
        ]
        prompt = f"""You are a procurement specialist for a global electronics factory.

The following purchase orders have been approved and need supplier assignment:
{summary}

Respond ONLY with a JSON object using exactly this structure:
{{
  "summary": "2-3 sentence inventory summary with the highest-priority action",
  "suppliers": [
    {{
      "facility": "exact facility name",
      "supplier": "recommended supplier name",
      "rationale": "one sentence reason"
    }}
  ]
}}"""
        return self.call_ollama(prompt)

    def _heuristic_summary(self, reorders: list[dict]) -> str:
        urgent = [
            f"{r['facility']} ({r['reorder_qty']:,} units, ${r['total_cost_usd']:,.0f})"
            for r in reorders[:3]
        ]
        total_cost = sum(float(r.get("total_cost_usd", 0.0)) for r in reorders)
        return (
            f"{len(reorders)} facility reorder(s) need attention. "
            f"Highest-priority actions: {', '.join(urgent)}. "
            f"Estimated total procurement exposure is ${total_cost:,.0f}."
        )

    def _empty_result(self, reason: str) -> dict:
        self.publish_signal(severity="WARNING", message=reason, confidence_pct=0.0)
        return {
            "reorders":                  [],
            "total_spend_requested_usd": 0.0,
            "total_approved_spend_usd":  0.0,
            "facilities_checked":        0,
            "reorders_triggered":        0,
            "summary":                   reason,
            "narrative":                 reason,
        }
