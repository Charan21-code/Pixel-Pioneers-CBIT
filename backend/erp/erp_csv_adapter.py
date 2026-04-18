"""
backend/erp/erp_csv_adapter.py — CSV / Default ERP Adapter

Wraps the existing data.csv pipeline behind the ERPAdapter interface.
This is the zero-risk default — it behaves exactly as the system does today,
just formalised behind the adapter contract.

The df_getter is a lambda injected from main.py:
    lambda: _CACHE["df"]
"""

from __future__ import annotations
from datetime import datetime
from typing import Callable

import numpy as np
import pandas as pd

from .erp_adapter import ERPAdapter


class CsvAdapter(ERPAdapter):
    """Default adapter — reads from the in-memory data.csv DataFrame."""

    erp_type = "csv"

    def __init__(self, df_getter: Callable[[], pd.DataFrame]):
        """
        Parameters
        ----------
        df_getter : callable that returns the current cached DataFrame.
                    Injected from main.py as ``lambda: _CACHE["df"]``.
        """
        self._df_getter = df_getter

    # ── READ ──────────────────────────────────────────────────────────────────

    def pull_inventory(self, plant_id: str) -> list[dict]:
        df = self._df_getter()
        if df is None or df.empty:
            return []
        fac_df = df[df["Assigned_Facility"] == plant_id]
        if fac_df.empty:
            return []
        latest = fac_df.sort_values("Timestamp").iloc[-1]
        return [{
            "plant":     plant_id,
            "material":  "RAW_MATERIAL",
            "qty":       int(float(latest.get("Raw_Material_Inventory_Units", 0))),
            "threshold": int(float(latest.get("Inventory_Threshold", 20000))),
            "uom":       "units",
            "source":    "csv",
        }]

    def pull_open_orders(self, plant_id: str) -> list[dict]:
        df = self._df_getter()
        if df is None or df.empty:
            return []
        fac_df = df[df["Assigned_Facility"] == plant_id].tail(20)
        orders = []
        for _, row in fac_df.iterrows():
            orders.append({
                "order_id": str(row.get("Order_ID", "")),
                "product":  str(row.get("Product_Category", "Unknown")),
                "qty":      int(float(row.get("Actual_Order_Qty", 0))),
                "status":   str(row.get("Schedule_Status", "Unknown")),
                "due_date": str(row.get("Timestamp", ""))[:10],
                "source":   "csv",
            })
        return orders

    def pull_bom(self, product_id: str) -> dict:
        # CSV has no BOM data
        return {"product": product_id, "bom_items": [], "source": "csv"}

    def pull_machine_status(self, plant_id: str) -> list[dict]:
        df = self._df_getter()
        if df is None or df.empty:
            return []
        fac_df = df[df["Assigned_Facility"] == plant_id]
        if fac_df.empty:
            return []
        latest = fac_df.sort_values("Timestamp").iloc[-1]
        return [{
            "machine_id":      f"{plant_id[:6]}-M01",
            "oee_pct":         float(latest.get("Machine_OEE_Pct", 0)),
            "temp_c":          float(latest.get("Machine_Temperature_C", 0)),
            "vibration_mm_s":  float(latest.get("Machine_Vibration_mm_s", 0)),
            "ttf_hrs":         float(latest.get("Predicted_Time_To_Failure_Hrs", 9999)),
            "source":          "csv",
        }]

    # ── WRITE ─────────────────────────────────────────────────────────────────

    def push_production_order(self, order: dict) -> dict:
        """CSV is read-only — simulate a successful push and log it."""
        plant   = order.get("plant", "UNKNOWN")
        run_id  = order.get("run_id", "manual")
        doc_id  = f"CSV-PROD-{plant[:4].upper()}-{run_id[:8].upper()}"
        return {
            "doc_id":  doc_id,
            "status":  "simulated",
            "erp_ref": "N/A (CSV mode)",
            "source":  "csv",
        }

    def push_purchase_order(self, po: dict) -> dict:
        plant  = po.get("facility", po.get("plant", "UNKNOWN"))
        doc_id = f"CSV-PO-{plant[:4].upper()}"
        return {
            "doc_id":  doc_id,
            "vendor":  "Simulated Vendor",
            "status":  "simulated",
            "source":  "csv",
        }

    # ── LISTEN ────────────────────────────────────────────────────────────────

    def poll_events(self, since: datetime) -> list[dict]:
        """CSV is static — never generates new events."""
        return []

    # ── Health ────────────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        df = self._df_getter()
        row_count = len(df) if df is not None and not df.empty else 0
        return {
            "erp_type":   self.erp_type,
            "status":     "connected" if row_count > 0 else "empty",
            "latency_ms": 0,
            "data_rows":  row_count,
        }
