"""
hitl/manager.py — HitlManager

Human-In-The-Loop approval queue manager.

Tables used
-----------
    hitl_queue (id, created_at, resolved_at, item_type, source, payload, status, comment, resolved_by)

item_type values
----------------
    "ops"         — Orchestrator / Scheduler production plan approvals
    "procurement" — Buyer agent purchase orders
    "finance"     — Finance agent budget escalations
    "maintenance" — Mechanic agent emergency maintenance requests
    "carbon"      — Environmentalist agent compliance alerts

status values
-------------
    "pending"  — awaiting human decision
    "approved" — human approved
    "rejected" — human rejected

Usage
-----
    from hitl.manager import HitlManager
    hm = HitlManager()

    pending = hm.get_pending(item_type="procurement")
    hm.approve(item_id=3, comment="Approved — within budget", approved_by="Supply Chain Head")
    hm.reject(item_id=4,  comment="Quantity too high",       rejected_by="CFO")
"""

import json
import logging
import sqlite3
from datetime import datetime
from typing import Optional

import config

logger = logging.getLogger(__name__)


class HitlManager:
    """Reads and writes to the hitl_queue table in production.db."""

    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path
        self._ensure_schema()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        """
        Adds any missing columns to hitl_queue introduced in this phase.
        Safe to call multiple times (idempotent).
        """
        with self._conn() as conn:
            # Base table (already created by BaseAgent._init_db)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hitl_queue (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME,
                    item_type   TEXT NOT NULL,
                    source      TEXT NOT NULL,
                    payload     TEXT NOT NULL,
                    status      TEXT DEFAULT 'pending',
                    comment     TEXT,
                    resolved_by TEXT
                )
            """)
            # Add columns that might be missing from older schema
            for col, coltype in [("comment", "TEXT"), ("resolved_by", "TEXT")]:
                try:
                    conn.execute(f"ALTER TABLE hitl_queue ADD COLUMN {col} {coltype}")
                except Exception:
                    pass  # column already exists
            conn.commit()

    # ── Public API ────────────────────────────────────────────────────────────

    def get_pending(self, item_type: Optional[str] = None) -> list[dict]:
        """
        Return all pending HITL items, optionally filtered by item_type.

        Parameters
        ----------
        item_type : str or None
            Filter by "ops" | "procurement" | "finance" | "maintenance" | "carbon".
            None returns all pending items.

        Returns
        -------
        list of dicts with keys:
            id, created_at, item_type, source, payload (parsed dict), status
        """
        query  = "SELECT * FROM hitl_queue WHERE status = 'pending'"
        params = []
        if item_type:
            query += " AND item_type = ?"
            params.append(item_type)
        query += " ORDER BY created_at DESC"

        try:
            with self._conn() as conn:
                rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            logger.error("[HitlManager] get_pending failed: %s", exc)
            return []

    def get_history(self, limit: int = 50, item_type: Optional[str] = None) -> list[dict]:
        """
        Return resolved (approved / rejected) HITL items.

        Parameters
        ----------
        limit     : max rows to return
        item_type : optional filter

        Returns
        -------
        list of dicts (newest resolved first)
        """
        query  = "SELECT * FROM hitl_queue WHERE status != 'pending'"
        params = []
        if item_type:
            query += " AND item_type = ?"
            params.append(item_type)
        query += f" ORDER BY resolved_at DESC LIMIT {int(limit)}"

        try:
            with self._conn() as conn:
                rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            logger.error("[HitlManager] get_history failed: %s", exc)
            return []

    def get_counts(self) -> dict:
        """
        Return pending item counts per item_type.
        Useful for sidebar badge counts.

        Returns
        -------
        dict: {"ops": N, "procurement": N, "finance": N, "maintenance": N, "carbon": N, "total": N}
        """
        types   = ["ops", "procurement", "finance", "maintenance", "carbon"]
        counts  = {t: 0 for t in types}
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT item_type, COUNT(*) as cnt FROM hitl_queue "
                    "WHERE status = 'pending' GROUP BY item_type"
                ).fetchall()
            for row in rows:
                t = row["item_type"]
                if t in counts:
                    counts[t] = row["cnt"]
        except Exception as exc:
            logger.error("[HitlManager] get_counts failed: %s", exc)
        counts["total"] = sum(counts.values())
        return counts

    def approve(
        self,
        item_id:     int,
        comment:     str = "",
        approved_by: str = "Human Head",
    ) -> bool:
        """
        Mark an item as approved.

        Parameters
        ----------
        item_id     : the hitl_queue primary key
        comment     : optional approval note
        approved_by : name / role of the approver

        Returns
        -------
        True if the row was updated, False otherwise.
        """
        return self._resolve(item_id, "approved", comment, approved_by)

    def reject(
        self,
        item_id:      int,
        comment:      str = "",
        rejected_by:  str = "Human Head",
    ) -> bool:
        """
        Mark an item as rejected.

        Parameters
        ----------
        item_id     : the hitl_queue primary key
        comment     : reason for rejection
        rejected_by : name / role of the rejector

        Returns
        -------
        True if the row was updated, False otherwise.
        """
        return self._resolve(item_id, "rejected", comment, rejected_by)

    def enqueue(
        self,
        item_type: str,
        source:    str,
        payload:   dict,
    ) -> int:
        """
        Manually push a new item to the queue (used by pages, not just agents).

        Parameters
        ----------
        item_type : "ops" | "procurement" | "finance" | "maintenance" | "carbon"
        source    : agent name or page name
        payload   : any JSON-serialisable dict

        Returns
        -------
        The new row's primary key (id).
        """
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "INSERT INTO hitl_queue (item_type, source, payload) VALUES (?, ?, ?)",
                    (item_type, source, json.dumps(payload, default=str)),
                )
                conn.commit()
                new_id = cur.lastrowid
            logger.info("[HitlManager] Enqueued %s item id=%d from %s", item_type, new_id, source)
            return new_id
        except Exception as exc:
            logger.error("[HitlManager] enqueue failed: %s", exc)
            return -1

    def pending_count(self) -> int:
        """Quick total count of all pending items."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM hitl_queue WHERE status = 'pending'"
                ).fetchone()
            return row["cnt"] if row else 0
        except Exception:
            return 0

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolve(self, item_id: int, new_status: str, comment: str, resolved_by: str) -> bool:
        """Common logic for approve() and reject()."""
        try:
            now = datetime.utcnow().isoformat()
            with self._conn() as conn:
                cur = conn.execute(
                    """UPDATE hitl_queue
                       SET status = ?, resolved_at = ?, comment = ?, resolved_by = ?
                       WHERE id = ? AND status = 'pending'""",
                    (new_status, now, comment, resolved_by, item_id),
                )
                conn.commit()
                updated = cur.rowcount > 0
            if updated:
                logger.info(
                    "[HitlManager] Item %d → %s by %s (%s)",
                    item_id, new_status, resolved_by, comment[:60]
                )
            else:
                logger.warning("[HitlManager] Item %d not found or already resolved.", item_id)
            return updated
        except Exception as exc:
            logger.error("[HitlManager] _resolve failed for id=%d: %s", item_id, exc)
            return False

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert sqlite3.Row to plain dict, parsing JSON payload."""
        d = dict(row)
        try:
            d["payload"] = json.loads(d.get("payload", "{}"))
        except Exception:
            d["payload"] = {}
        return d
