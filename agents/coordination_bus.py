"""
agents/coordination_bus.py — Inter-Agent Coordination Message Bus

Implements the structured negotiation protocol between agents.
Agents post blockers, proposals, evaluations, consensus or escalation
messages to a shared 'coordination_messages' SQLite table.

Message types
-------------
  blocker   : An agent signals a constraint that blocks another agent.
  proposal  : Scheduler posts alternative options when it encounters a blocker.
  eval      : Finance evaluates each proposal's cost-benefit tradeoff.
  consensus : Orchestrator records the winning resolution.
  escalate  : No viable option — thread goes to HITL with full context.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class CoordinationBus:
    """Lightweight wrapper around the coordination_messages SQLite table."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    # ── DB bootstrap ──────────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS coordination_messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id      TEXT     NOT NULL,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    from_agent  TEXT     NOT NULL,
                    to_agent    TEXT,
                    msg_type    TEXT     NOT NULL CHECK (
                                    msg_type IN ('blocker','proposal','eval','consensus','escalate')
                                ),
                    subject     TEXT     NOT NULL,
                    payload     TEXT     NOT NULL,
                    parent_id   INTEGER  REFERENCES coordination_messages(id),
                    status      TEXT     DEFAULT 'open' CHECK (
                                    status IN ('open','resolved','escalated')
                                ),
                    resolved_by TEXT,
                    resolved_at DATETIME
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_coord_run ON coordination_messages(run_id)"
            )
            conn.commit()

    # ── Write helpers ─────────────────────────────────────────────────────────

    def post_blocker(
        self,
        run_id: str,
        from_agent: str,
        subject: str,
        to_agents: list[str],
        payload: dict,
    ) -> int:
        """Post a constraint that blocks one or more downstream agents."""
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO coordination_messages
                    (run_id, from_agent, to_agent, msg_type, subject, payload)
                VALUES (?, ?, ?, 'blocker', ?, ?)
                """,
                (run_id, from_agent, json.dumps(to_agents),
                 subject, json.dumps(payload, default=str)),
            )
            conn.commit()
            row_id = cur.lastrowid
        logger.info("[CoordBus] BLOCKER posted by %s: %s (id=%s)", from_agent, subject, row_id)
        return row_id

    def post_proposal(
        self,
        run_id: str,
        from_agent: str,
        blocker_id: int,
        subject: str,
        options: list[dict],
    ) -> int:
        """Post a set of alternative options in response to a specific blocker."""
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO coordination_messages
                    (run_id, from_agent, to_agent, msg_type, subject, payload, parent_id)
                VALUES (?, ?, 'Finance', 'proposal', ?, ?, ?)
                """,
                (run_id, from_agent, subject,
                 json.dumps(options, default=str), blocker_id),
            )
            conn.commit()
            row_id = cur.lastrowid
        logger.info("[CoordBus] PROPOSAL posted by %s for blocker %s (id=%s)", from_agent, blocker_id, row_id)
        return row_id

    def post_eval(
        self,
        run_id: str,
        from_agent: str,
        proposal_id: int,
        subject: str,
        recommendation: dict,
    ) -> int:
        """Post Finance's evaluation and recommendation for a proposal."""
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO coordination_messages
                    (run_id, from_agent, to_agent, msg_type, subject, payload, parent_id)
                VALUES (?, ?, 'Orchestrator', 'eval', ?, ?, ?)
                """,
                (run_id, from_agent, subject,
                 json.dumps(recommendation, default=str), proposal_id),
            )
            conn.commit()
            row_id = cur.lastrowid
        logger.info("[CoordBus] EVAL posted by %s for proposal %s (id=%s)", from_agent, proposal_id, row_id)
        return row_id

    def post_consensus(
        self,
        run_id: str,
        from_agent: str,
        eval_id: int,
        subject: str,
        resolution: dict,
    ) -> int:
        """Record the agreed resolution. Marks the eval as resolved."""
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO coordination_messages
                    (run_id, from_agent, to_agent, msg_type, subject, payload, parent_id, status)
                VALUES (?, ?, 'All', 'consensus', ?, ?, ?, 'resolved')
                """,
                (run_id, from_agent, subject,
                 json.dumps(resolution, default=str), eval_id),
            )
            # Mark eval as resolved
            conn.execute(
                "UPDATE coordination_messages SET status='resolved', resolved_by=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                (from_agent, eval_id),
            )
            conn.commit()
            row_id = cur.lastrowid
        logger.info("[CoordBus] CONSENSUS by %s for eval %s (id=%s)", from_agent, eval_id, row_id)
        return row_id

    def post_escalate(
        self,
        run_id: str,
        from_agent: str,
        eval_id: int,
        subject: str,
        context: dict,
    ) -> int:
        """Mark a thread as escalated to HITL with full context."""
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO coordination_messages
                    (run_id, from_agent, to_agent, msg_type, subject, payload, parent_id, status)
                VALUES (?, ?, 'HITL', 'escalate', ?, ?, ?, 'escalated')
                """,
                (run_id, from_agent, subject,
                 json.dumps(context, default=str), eval_id),
            )
            conn.execute(
                "UPDATE coordination_messages SET status='escalated', resolved_by='HITL', resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                (eval_id,),
            )
            conn.commit()
            row_id = cur.lastrowid
        logger.info("[CoordBus] ESCALATE by %s for eval %s (id=%s)", from_agent, eval_id, row_id)
        return row_id

    def mark_resolved(self, msg_id: int, resolved_by: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE coordination_messages SET status='resolved', resolved_by=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                (resolved_by, msg_id),
            )
            conn.commit()

    # ── Read helpers ──────────────────────────────────────────────────────────

    def get_open_blockers(self, run_id: str, to_agent: Optional[str] = None) -> list[dict]:
        """Return open blockers for a run, optionally filtered to a specific target agent."""
        with self._get_conn() as conn:
            if to_agent:
                rows = conn.execute(
                    """
                    SELECT * FROM coordination_messages
                    WHERE run_id = ? AND msg_type = 'blocker' AND status = 'open'
                      AND (to_agent LIKE ? OR to_agent IS NULL)
                    ORDER BY created_at ASC
                    """,
                    (run_id, f'%"{to_agent}"%'),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM coordination_messages
                    WHERE run_id = ? AND msg_type = 'blocker' AND status = 'open'
                    ORDER BY created_at ASC
                    """,
                    (run_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_proposals_for_finance(self, run_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM coordination_messages
                WHERE run_id = ? AND msg_type = 'proposal' AND to_agent = 'Finance' AND status = 'open'
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_evals_for_orchestrator(self, run_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM coordination_messages
                WHERE run_id = ? AND msg_type = 'eval' AND status = 'open'
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_for_run(self, run_id: str) -> list[dict]:
        """Return every coordination message for a run, ordered chronologically."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM coordination_messages
                WHERE run_id = ?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_full_thread(self, blocker_id: int) -> list[dict]:
        """
        Returns the complete negotiation chain starting from a blocker:
        blocker → proposals → evals/consensus/escalate
        """
        result = []
        with self._get_conn() as conn:
            blocker = conn.execute(
                "SELECT * FROM coordination_messages WHERE id = ?", (blocker_id,)
            ).fetchone()
            if not blocker:
                return []
            b = dict(blocker)
            try:
                b["payload"] = json.loads(b.get("payload", "{}"))
            except Exception:
                pass
            result.append(b)

            proposals = conn.execute(
                "SELECT * FROM coordination_messages WHERE parent_id = ? AND msg_type = 'proposal'",
                (blocker_id,),
            ).fetchall()
            for proposal in proposals:
                p = dict(proposal)
                try:
                    p["payload"] = json.loads(p.get("payload", "[]"))
                except Exception:
                    pass

                evals = conn.execute(
                    "SELECT * FROM coordination_messages WHERE parent_id = ?",
                    (proposal["id"],),
                ).fetchall()
                p["_children"] = []
                for ev in evals:
                    e = dict(ev)
                    try:
                        e["payload"] = json.loads(e.get("payload", "{}"))
                    except Exception:
                        pass
                    p["_children"].append(e)

                result.append(p)

        return result

    def get_latest_run_messages(self, limit: int = 20) -> list[dict]:
        """Return the most recent coordination messages across all runs."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM coordination_messages
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
