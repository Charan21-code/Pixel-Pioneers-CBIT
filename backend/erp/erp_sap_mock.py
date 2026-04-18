"""
backend/erp/erp_sap_mock.py — SAP S/4HANA Mock Adapter

Simulates SAP S/4HANA REST/RFC responses with realistic SAP-style field names
(AUFNR, MATNR, WERKS, LGORT, MEINS) and document number formats.

No SAP credentials or pyrfc are required — this is a convincing simulation
for demo / hackathon purposes. A live SAP RFC connection can be dropped in by
replacing the return values with actual RFC_READ_TABLE / BAPI_PRODORD_CREATE calls.
"""

from __future__ import annotations
import random
import uuid
from datetime import datetime, timedelta

from .erp_adapter import ERPAdapter

# SAP document number prefixes (standard S/4HANA format)
_SAP_PROD_ORDER_PREFIX  = "000060"   # AUFNR format
_SAP_PURCH_ORDER_PREFIX = "4500"     # EBELN format
_SAP_GR_PREFIX          = "5000"     # MBLNR format (goods receipt)

# Realistic SAP plant codes (mapped from our facility names)
_PLANT_CODE_MAP = {
    "Noida":   "INDI",
    "Seoul":   "KORE",
    "Munich":  "DEUR",
    "Texas":   "USAX",
    "Brazil":  "BRAZ",
    "Vietnam": "VIET",
}


def _plant_code(plant_id: str) -> str:
    for key, code in _PLANT_CODE_MAP.items():
        if key.lower() in plant_id.lower():
            return code
    return plant_id[:4].upper()


class SapMockAdapter(ERPAdapter):
    """SAP S/4HANA mock adapter — realistic document numbers and field names."""

    erp_type = "sap_mock"

    # ── READ ──────────────────────────────────────────────────────────────────

    def pull_inventory(self, plant_id: str) -> list[dict]:
        """Simulates MM60 / MARD table query for unrestricted stock."""
        werks = _plant_code(plant_id)
        return [{
            "WERKS":    werks,          # Plant (SAP field)
            "MATNR":    "RAWMAT-001",   # Material number
            "LGORT":    "0001",         # Storage location
            "LABST":    random.randint(18000, 38000),   # Unrestricted stock
            "EINME":    random.randint(500, 3000),      # Blocked stock
            "MINBE":    20000,          # Reorder point
            "MEINS":    "EA",           # Base unit of measure
            "plant":    plant_id,
            "material": "RAWMAT-001",
            "qty":      random.randint(18000, 38000),
            "threshold": 20000,
            "uom":      "EA",
            "source":   "SAP_MOCK",
        }]

    def pull_open_orders(self, plant_id: str) -> list[dict]:
        """Simulates PP order list (AUFK + AFKO) for the plant."""
        werks = _plant_code(plant_id)
        orders = []
        for i in range(5):
            aufnr = f"{_SAP_PROD_ORDER_PREFIX}{random.randint(100000, 999999)}"
            orders.append({
                "AUFNR":  aufnr,          # Production order number
                "MATNR":  f"PROD-{i+1:03d}",
                "WERKS":  werks,
                "GAMNG":  random.randint(200, 2000),    # Total order qty
                "WEMNG":  random.randint(0, 1500),      # Delivered qty
                "GSTRS":  (datetime.utcnow() - timedelta(days=random.randint(0, 7))).date().isoformat(),
                "GLTRP":  (datetime.utcnow() + timedelta(days=random.randint(1, 14))).date().isoformat(),
                "STTXT":  random.choice(["REL", "PCNF", "CNF", "DLV"]),   # SAP status
                "order_id": aufnr,
                "product": f"PROD-{i+1:03d}",
                "qty":     random.randint(200, 2000),
                "status":  random.choice(["On-Time", "Delayed", "In Progress"]),
                "source":  "SAP_MOCK",
            })
        return orders

    def pull_bom(self, product_id: str) -> dict:
        """Simulates CS15 BOM explosion."""
        return {
            "product":   product_id,
            "STLAN":     "1",           # BOM usage (production)
            "bom_items": [
                {"IDNRK": "RAWMAT-001", "MENGE": 2.5, "MEINS": "KG", "component": "RAWMAT-001", "qty": 2.5, "uom": "KG"},
                {"IDNRK": "RAWMAT-002", "MENGE": 0.8, "MEINS": "L",  "component": "RAWMAT-002", "qty": 0.8, "uom": "L"},
            ],
            "source": "SAP_MOCK",
        }

    def pull_machine_status(self, plant_id: str) -> list[dict]:
        """Simulates PM equipment data (EQUI / MESS) for the plant."""
        werks = _plant_code(plant_id)
        return [{
            "EQUNR":       f"EQ-{werks}-001",  # Equipment number
            "WERKS":       werks,
            "INGRP":       "PM01",             # Maintenance planner group
            "machine_id":  f"{plant_id[:6]}-M01",
            "oee_pct":     round(random.uniform(79, 97), 1),
            "temp_c":      round(random.uniform(68, 89), 1),
            "vibration_mm_s": round(random.uniform(1.2, 4.8), 2),
            "ttf_hrs":     round(random.uniform(40, 500), 1),
            "source":      "SAP_MOCK",
        }]

    # ── WRITE ─────────────────────────────────────────────────────────────────

    def push_production_order(self, order: dict) -> dict:
        """Simulates BAPI_PRODORD_CREATE — generates an AFKO-style record."""
        werks   = _plant_code(order.get("plant", "INDI"))
        aufnr   = f"{_SAP_PROD_ORDER_PREFIX}{random.randint(100000, 999999)}"
        return {
            "AUFNR":  aufnr,
            "MATNR":  order.get("product", "PROD-001"),
            "WERKS":  werks,
            "GAMNG":  order.get("qty", 0),
            "GSTRS":  datetime.utcnow().isoformat(),
            "GLTRP":  (datetime.utcnow() + timedelta(days=7)).isoformat(),
            "STTXT":  "REL",                   # Released
            "doc_id": aufnr,
            "status": "CREATED",
            "erp_ref": f"SAP-{werks}-{aufnr}",
            "source": "SAP_MOCK",
        }

    def push_purchase_order(self, po: dict) -> dict:
        """Simulates BAPI_PO_CREATE1 — generates an EKKO-style purchase order."""
        werks  = _plant_code(po.get("facility", po.get("plant", "INDI")))
        ebeln  = f"{_SAP_PURCH_ORDER_PREFIX}{random.randint(10000000, 99999999)}"
        return {
            "EBELN":   ebeln,          # PO number
            "BUKRS":   "1000",         # Company code
            "EKGRP":   "G01",          # Purchasing group
            "WERKS":   werks,
            "NETPR":   po.get("unit_price", 5.0),
            "doc_id":  ebeln,
            "vendor":  "Simulated SAP Vendor",
            "status":  "CREATED",
            "source":  "SAP_MOCK",
        }

    # ── LISTEN ────────────────────────────────────────────────────────────────

    def poll_events(self, since: datetime) -> list[dict]:
        """Simulates SAP IDoc / Business Event inbox polling."""
        event_templates = [
            ("NEW_SALES_ORDER",   "VA01", {"VBELN": f"0000080{random.randint(100000,999999)}"}),
            ("GOODS_RECEIPT",     "MIGO", {"MBLNR": f"{_SAP_GR_PREFIX}{random.randint(100000,999999)}", "BWART": "101"}),
            ("PO_CONFIRMATION",   "ME29N",{"EBELN": f"{_SAP_PURCH_ORDER_PREFIX}{random.randint(10000000,99999999)}"}),
            ("MACHINE_ALERT",     "IW31", {"QMNUM": f"000{random.randint(10000000,99999999)}", "QMGRD": "M1"}),
        ]
        events = []
        for i, (etype, tcode, payload) in enumerate(event_templates):
            events.append({
                "event_id":  str(uuid.uuid4()),
                "type":      etype,
                "tcode":     tcode,           # SAP transaction code
                "idoc_num":  f"00000{random.randint(100000,999999)}",
                "timestamp": (datetime.utcnow() - timedelta(minutes=i * 8)).isoformat(),
                "plant":     "INDI",
                "payload":   {**payload, "source": "SAP_MOCK"},
            })
        return events

    # ── Health ────────────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        return {
            "erp_type":   self.erp_type,
            "status":     "connected",
            "latency_ms": random.randint(12, 85),
            "sap_system": "S4H_PROD_MOCK",
            "client":     "800",
        }
