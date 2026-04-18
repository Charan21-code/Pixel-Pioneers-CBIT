"""
backend/erp/erp_adapter.py — Abstract ERP Adapter Base Class

Defines the 4-capability contract that every ERP adapter must implement:
  READ   — pull live data from ERP
  WRITE  — push decisions back to ERP
  LISTEN — poll for new ERP events
  EXPLAIN — generate rationale deep-links
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime


class ERPAdapter(ABC):
    """Abstract base class for all ERP adapters.

    Subclasses implement each method for a specific ERP (SAP, Odoo, Oracle, etc.).
    OPS//CORE calls only these methods — it never knows which ERP is behind them.
    """

    # Overridden by each subclass — used in audit logs and the UI banner
    erp_type: str = "base"

    # ── READ ──────────────────────────────────────────────────────────────────

    @abstractmethod
    def pull_inventory(self, plant_id: str) -> list[dict]:
        """Live stock levels for the given plant.

        Returns list of dicts with keys:
            plant, material, qty, threshold, uom, source
        """

    @abstractmethod
    def pull_open_orders(self, plant_id: str) -> list[dict]:
        """Open production / sales orders for the plant.

        Returns list of dicts with keys:
            order_id, product, qty, status, due_date
        """

    @abstractmethod
    def pull_bom(self, product_id: str) -> dict:
        """Bill of Materials for a product.

        Returns dict with keys:
            product, bom_items: list[{component, qty, uom}]
        """

    @abstractmethod
    def pull_machine_status(self, plant_id: str) -> list[dict]:
        """Machine telemetry for the plant.

        Returns list of dicts with keys:
            machine_id, oee_pct, temp_c, vibration_mm_s, ttf_hrs, source
        """

    # ── WRITE ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def push_production_order(self, order: dict) -> dict:
        """Create or update a production order in the ERP.

        order keys: plant, qty, product, run_id, shift_id (optional)

        Returns dict with keys:
            doc_id, status, erp_ref, source
        """

    @abstractmethod
    def push_purchase_order(self, po: dict) -> dict:
        """Create a purchase order in the ERP.

        po keys: plant, material, qty, unit_price, vendor (optional)

        Returns dict with keys:
            doc_id, vendor, status, source
        """

    # ── LISTEN ────────────────────────────────────────────────────────────────

    @abstractmethod
    def poll_events(self, since: datetime) -> list[dict]:
        """Poll the ERP for new events since the given datetime.

        Returns list of event dicts with keys:
            event_id, type, timestamp, plant, payload
        """

    # ── EXPLAIN ───────────────────────────────────────────────────────────────

    def generate_audit_link(self, action_id: str, run_id: str = None) -> str:
        """Generate a deep-link to the Agent Reasoning page for this action."""
        base = f"/agent-reasoning?audit_id={action_id}"
        if run_id:
            base += f"&run_id={run_id}"
        return base

    # ── Health ────────────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """Returns a basic health dict. Subclasses can override for real checks."""
        return {
            "erp_type":   self.erp_type,
            "status":     "connected",
            "latency_ms": 0,
        }
