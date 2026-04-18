"""
backend/erp/erp_odoo_mock.py — Odoo XML-RPC Mock Adapter

Simulates Odoo 16/17 XML-RPC responses using Odoo model names and field
structures (mrp.production, purchase.order, stock.quant, mail.message).

A live Odoo connection can replace the mock return values with actual
xmlrpc.client calls to an Odoo instance — no other code changes needed.
"""

from __future__ import annotations
import random
import uuid
from datetime import datetime, timedelta

from .erp_adapter import ERPAdapter


class OdooMockAdapter(ERPAdapter):
    """Odoo XML-RPC mock adapter — realistic model names and field structures."""

    erp_type = "odoo_mock"

    # ── READ ──────────────────────────────────────────────────────────────────

    def pull_inventory(self, plant_id: str) -> list[dict]:
        """Simulates stock.quant.search_read() for the plant location."""
        qty = random.randint(18000, 38000)
        return [{
            "model":              "stock.quant",
            "id":                 random.randint(100, 999),
            "product_id":         [1, "Raw Material (RAWMAT-001)"],
            "location_id":        [8, f"Physical Locations / {plant_id} / Stock"],
            "quantity":           qty,
            "reserved_quantity":  random.randint(0, 2000),
            "in_date":            datetime.utcnow().isoformat(),
            # normalised keys for the integration layer
            "plant":              plant_id,
            "material":           "RAWMAT-001",
            "qty":                qty,
            "threshold":          20000,
            "uom":                "Units",
            "source":             "ODOO_MOCK",
        }]

    def pull_open_orders(self, plant_id: str) -> list[dict]:
        """Simulates mrp.production.search_read() for orders at the plant."""
        orders = []
        states = ["confirmed", "progress", "done", "draft"]
        for i in range(5):
            mo_name = f"WH/MO/{datetime.utcnow().year}/{random.randint(1000,9999):05d}"
            orders.append({
                "model":          "mrp.production",
                "id":             random.randint(1000, 9999),
                "name":           mo_name,
                "product_id":     [i + 1, f"Product {i+1}"],
                "product_qty":    random.randint(200, 2000),
                "qty_produced":   random.randint(0, 1500),
                "state":          random.choice(states),
                "date_planned_start": (datetime.utcnow() - timedelta(days=random.randint(0, 3))).isoformat(),
                "date_deadline":  (datetime.utcnow() + timedelta(days=random.randint(1, 10))).isoformat(),
                # normalised keys
                "order_id":       mo_name,
                "product":        f"Product {i+1}",
                "qty":            random.randint(200, 2000),
                "status":         "On-Time" if random.random() > 0.3 else "Delayed",
                "source":         "ODOO_MOCK",
            })
        return orders

    def pull_bom(self, product_id: str) -> dict:
        """Simulates mrp.bom + mrp.bom.line.read()."""
        return {
            "model":      "mrp.bom",
            "product":    product_id,
            "type":       "normal",
            "bom_items": [
                {"model": "mrp.bom.line", "product_id": [1, "RAWMAT-001"], "product_qty": 2.5, "product_uom_id": [1, "kg"],
                 "component": "RAWMAT-001", "qty": 2.5, "uom": "kg"},
                {"model": "mrp.bom.line", "product_id": [2, "RAWMAT-002"], "product_qty": 0.8, "product_uom_id": [3, "L"],
                 "component": "RAWMAT-002", "qty": 0.8, "uom": "L"},
            ],
            "source": "ODOO_MOCK",
        }

    def pull_machine_status(self, plant_id: str) -> list[dict]:
        """Simulates maintenance.equipment.read() for the plant."""
        return [{
            "model":          "maintenance.equipment",
            "id":             random.randint(10, 99),
            "name":           f"{plant_id[:10]} Line 1",
            "category_id":    [1, "Production Line"],
            "location":       plant_id,
            "machine_id":     f"{plant_id[:6]}-M01",
            "oee_pct":        round(random.uniform(79, 97), 1),
            "temp_c":         round(random.uniform(68, 89), 1),
            "vibration_mm_s": round(random.uniform(1.2, 4.8), 2),
            "ttf_hrs":        round(random.uniform(40, 500), 1),
            "source":         "ODOO_MOCK",
        }]

    # ── WRITE ─────────────────────────────────────────────────────────────────

    def push_production_order(self, order: dict) -> dict:
        """Simulates mrp.production.create() then action_confirm()."""
        mo_id   = random.randint(1000, 9999)
        mo_name = f"WH/MO/{datetime.utcnow().year}/{mo_id:05d}"
        return {
            "model":      "mrp.production",
            "id":         mo_id,
            "name":       mo_name,
            "state":      "confirmed",
            "product_qty": order.get("qty", 0),
            "doc_id":     mo_name,
            "status":     "confirmed",
            "erp_ref":    f"ODOO-MO-{mo_id}",
            "source":     "ODOO_MOCK",
        }

    def push_purchase_order(self, po: dict) -> dict:
        """Simulates purchase.order.create() + button_confirm()."""
        po_id   = random.randint(1000, 9999)
        po_name = f"P/{datetime.utcnow().year}/{po_id:05d}"
        return {
            "model":   "purchase.order",
            "id":      po_id,
            "name":    po_name,
            "state":   "purchase",
            "doc_id":  po_name,
            "vendor":  "Simulated Odoo Vendor",
            "status":  "confirmed",
            "source":  "ODOO_MOCK",
        }

    # ── LISTEN ────────────────────────────────────────────────────────────────

    def poll_events(self, since: datetime) -> list[dict]:
        """Simulates mail.message webhook notifications from Odoo."""
        event_templates = [
            ("NEW_SALES_ORDER",   "sale.order",          "Sale Order Confirmed"),
            ("GOODS_RECEIPT",     "stock.picking",       "Receipt: Done"),
            ("PO_CONFIRMATION",   "purchase.order",      "Purchase Order: Purchase Order"),
            ("MACHINE_ALERT",     "maintenance.request", "Maintenance Request Created"),
        ]
        events = []
        for i, (etype, model, subtype) in enumerate(event_templates):
            events.append({
                "event_id":    str(uuid.uuid4()),
                "type":        etype,
                "model":       model,
                "subtype":     subtype,
                "res_id":      random.randint(1000, 9999),
                "timestamp":   (datetime.utcnow() - timedelta(minutes=i * 10)).isoformat(),
                "plant":       "Global",
                "payload":     {"model": model, "subtype": subtype, "source": "ODOO_MOCK"},
            })
        return events

    # ── Health ────────────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        return {
            "erp_type":   self.erp_type,
            "status":     "connected",
            "latency_ms": random.randint(20, 120),
            "odoo_version": "17.0",
            "database":   "odoo_prod_mock",
        }
