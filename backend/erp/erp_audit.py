"""
backend/erp/erp_audit.py — ERP Audit Trail

Every ERP read and write is logged here with full traceability back to the
agent run that triggered it, enabling the EXPLAIN capability in the frontend.

Tables created (in production.db alongside existing agent_events):
  erp_audit_log  — one row per ERP action (read or write)
  erp_events     — one row per ERP event received from poll_events()
"""

from __future__ import annotations
import json
import logging
import sqlite3
from datetime import datetime

import config

logger = logging.getLogger(__name__)

_AUDIT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS erp_audit_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        DATETIME DEFAULT CURRENT_TIMESTAMP,
    erp_type         TEXT NOT NULL,
    action_type      TEXT NOT NULL,
    document_id      TEXT,
    idempotency_key  TEXT,
    agent_name       TEXT,
    run_id           TEXT,
    rationale        TEXT,
    payload_before   TEXT,
    payload_after    TEXT,
    status           TEXT DEFAULT 'success',
    explain_url      TEXT
)
"""

_EVENTS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS erp_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    erp_type         TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    event_id         TEXT,
    plant            TEXT,
    payload          TEXT,
    triggered_agent  TEXT,
    replan_triggered INTEGER DEFAULT 0
)
"""

_IDEMPOTENCY_IDX_DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_erp_audit_ikey
ON erp_audit_log (idempotency_key)
WHERE idempotency_key IS NOT NULL
"""


class ERPAudit:
    """Manages the ERP audit trail tables in the shared production.db SQLite database."""

    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        """Create tables if they don't already exist — idempotent."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(_AUDIT_TABLE_DDL)
            conn.execute(_EVENTS_TABLE_DDL)
            try:
                conn.execute(_IDEMPOTENCY_IDX_DDL)
            except Exception:
                pass  # index already exists
            conn.commit()

    # ── Idempotency ───────────────────────────────────────────────────────────

    def is_duplicate(self, idempotency_key: str) -> bool:
        """Check if this idempotency key was already processed."""
        if not idempotency_key:
            return False
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id FROM erp_audit_log WHERE idempotency_key = ?",
                (idempotency_key,)
            ).fetchone()
        return row is not None

    # ── Write-side logging ────────────────────────────────────────────────────

    def log(
        self,
        erp_type: str,
        action_type: str,
        document_id: str = None,
        idempotency_key: str = None,
        agent_name: str = None,
        run_id: str = None,
        rationale: str = None,
        payload_before: dict = None,
        payload_after: dict = None,
        status: str = "success",
    ) -> int:
        """
        Insert one row into erp_audit_log.

        Returns the new row id, or -1 if a duplicate was detected.
        If `idempotency_key` already exists, the status is changed to 'duplicate'
        and the row is skipped (INSERT OR IGNORE).
        """
        if idempotency_key and self.is_duplicate(idempotency_key):
            logger.debug("[ERPAudit] Duplicate suppressed: %s", idempotency_key)
            return -1

        explain_url = None
        if run_id:
            explain_url = f"/agent-reasoning?run_id={run_id}"
            if agent_name:
                explain_url += f"&highlight={agent_name}"

        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO erp_audit_log
                        (erp_type, action_type, document_id, idempotency_key,
                         agent_name, run_id, rationale,
                         payload_before, payload_after, status, explain_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        erp_type, action_type, document_id, idempotency_key,
                        agent_name, run_id, rationale,
                        json.dumps(payload_before, default=str),
                        json.dumps(payload_after,  default=str),
                        status, explain_url,
                    ),
                )
                conn.commit()
                return cur.lastrowid or -1
        except Exception as exc:
            logger.error("[ERPAudit] log() failed: %s", exc)
            return -1

    # ── Event-side logging ────────────────────────────────────────────────────

    def log_event(
        self,
        erp_type: str,
        event_type: str,
        event_id: str,
        plant: str,
        payload: dict,
        triggered_agent: str = None,
        replan: bool = False,
    ):
        """Insert one row into erp_events."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO erp_events
                        (erp_type, event_type, event_id, plant,
                         payload, triggered_agent, replan_triggered)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        erp_type, event_type, event_id, plant,
                        json.dumps(payload, default=str),
                        triggered_agent, 1 if replan else 0,
                    ),
                )
                conn.commit()
        except Exception as exc:
            logger.error("[ERPAudit] log_event() failed: %s", exc)

    # ── Read helpers (for API endpoints) ─────────────────────────────────────

    def get_audit_log(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return recent audit log rows, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM erp_audit_log ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            # Parse JSON strings back to dicts for API response
            for key in ("payload_before", "payload_after"):
                if isinstance(d.get(key), str):
                    try:
                        d[key] = json.loads(d[key])
                    except Exception:
                        pass
            result.append(d)
        return result

    def get_audit_entry(self, audit_id: int) -> dict | None:
        """Return a single audit row by id, or None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM erp_audit_log WHERE id = ?", (audit_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        for key in ("payload_before", "payload_after"):
            if isinstance(d.get(key), str):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    pass
        return d

    def get_events(self, limit: int = 50) -> list[dict]:
        """Return recent ERP events, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM erp_events ORDER BY received_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get("payload"), str):
                try:
                    d["payload"] = json.loads(d["payload"])
                except Exception:
                    pass
            result.append(d)
        return result
