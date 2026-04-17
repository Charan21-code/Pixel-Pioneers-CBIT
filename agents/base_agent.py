"""
agents/base_agent.py — Abstract base class for all Factory Agents.

LIVE-DATA CONTRACT (READ THIS BEFORE WRITING AN AGENT)
=======================================================
The simulation treats data.csv as if it were a live event stream.
Only rows up to the current cursor (st.session_state.time_cursor) have
been "seen" by the system. To enforce this, the Orchestrator passes a
pre-sliced DataFrame in context["df"].

  ┌─────────────────────────────────────────────────────────────┐
  │  AGENTS MUST:                                               │
  │  • READ production data exclusively from context["df"]      │
  │  • NEVER call pd.read_sql("SELECT * FROM production_events")│
  │    directly — that would expose future (unprocessed) rows.  │
  │                                                             │
  │  AGENTS MAY freely:                                         │
  │  • Read from agent_events  (their own past signals)         │
  │  • Read from hitl_queue    (pending approvals)              │
  │  • Read from monthly_spend (Finance tracking)               │
  │  • Write to any of the above via publish_signal() etc.      │
  └─────────────────────────────────────────────────────────────┘

Usage
-----
Every specialist agent inherits BaseAgent and implements run():

    class ForecasterAgent(BaseAgent):
        def __init__(self):
            super().__init__("Forecaster")

        def run(self, context: dict) -> dict:
            df          = context["df"]           # cursor-limited DataFrame
            as_of_time  = context["as_of_time"]   # pd.Timestamp
            ...
            self.publish_signal(severity="INFO", message="...")
            return {...}
"""

import sqlite3
import json
import uuid
import logging
from abc import ABC, abstractmethod
from datetime import datetime

import httpx

import config

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base for all factory agents.

    Parameters
    ----------
    agent_name : str
        Human-readable name written into agent_events rows.
    db_path : str
        Path to the SQLite database (default: config.DB_PATH).
    """

    def __init__(self, agent_name: str, db_path: str = config.DB_PATH):
        self.agent_name = agent_name
        self.db_path    = db_path
        self._init_db()

    # ── Internal DB helpers ───────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Returns a connection with Row factory enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """
        Ensures all agent-managed tables exist.
        Called automatically on __init__ — idempotent (safe to call multiple times).
        """
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_events (
                    log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    agent_name     TEXT     NOT NULL,
                    severity       TEXT     CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
                    order_id       TEXT,
                    facility_id    TEXT,
                    message        TEXT     NOT NULL,
                    confidence_pct REAL,
                    action_taken   TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hitl_queue (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME,
                    item_type   TEXT NOT NULL,
                    source      TEXT NOT NULL,
                    payload     TEXT NOT NULL,
                    status      TEXT DEFAULT 'pending'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monthly_spend (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                    amount_usd  REAL     NOT NULL,
                    description TEXT,
                    cleared_by  TEXT
                )
            """)
            conn.commit()

    # ── Public DB write helpers ───────────────────────────────────────────────

    def publish_signal(
        self,
        severity:       str,
        message:        str,
        order_id:       str  = None,
        facility:       str  = None,
        confidence_pct: float = 0.0,
        action_taken:   str  = None,
    ):
        """
        Write one row to agent_events.

        Parameters
        ----------
        severity       : 'INFO' | 'WARNING' | 'CRITICAL'
        message        : Human-readable description of the signal.
        order_id       : (optional) related production order ID.
        facility       : (optional) related facility name.
        confidence_pct : 0–100 confidence in the signal.
        action_taken   : Short description of the action being taken.
        """
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_events
                    (agent_name, severity, order_id, facility_id,
                     message, confidence_pct, action_taken)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (self.agent_name, severity, order_id, facility,
                 message, confidence_pct, action_taken),
            )
            conn.commit()
        logger.debug("[%s] Signal published: %s — %s", self.agent_name, severity, message)

    def enqueue_hitl(self, item_type: str, payload: dict):
        """
        Push a decision to the HITL approval queue.

        Parameters
        ----------
        item_type : 'ops' (Orchestrator escalations) or 'finance' (Finance escalations)
        payload   : dict that will be JSON-serialised and stored.
        """
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO hitl_queue (item_type, source, payload) VALUES (?, ?, ?)",
                (item_type, self.agent_name, json.dumps(payload, default=str)),
            )
            conn.commit()
        logger.info("[%s] Enqueued HITL item (type=%s)", self.agent_name, item_type)

    # ── Public DB read helpers ────────────────────────────────────────────────

    def read_signals(
        self,
        agent_name: str  = None,
        severity:   str  = None,
        limit:      int  = 50,
    ) -> list[dict]:
        """
        Read past agent_events rows — safe to call (not production_events).

        Parameters
        ----------
        agent_name : filter by a specific agent (None = all agents)
        severity   : filter by 'INFO', 'WARNING', or 'CRITICAL' (None = all)
        limit      : max rows returned (newest first)

        Returns
        -------
        list of dicts with keys matching the agent_events table columns.
        """
        query  = "SELECT * FROM agent_events WHERE 1=1"
        params = []
        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        query += " ORDER BY logged_at DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ── Ollama LLM helper ─────────────────────────────────────────────────────

    def call_ollama(self, prompt: str) -> dict:
        """
        Send a prompt to the local Ollama instance and return a parsed JSON dict.

        Always requests structured JSON output via Ollama's `format: json` option.
        Falls back gracefully to {} if:
          - Ollama is not running
          - The response JSON cannot be parsed
          - The call times out

        This means every agent that calls call_ollama() MUST handle the case
        where the returned dict is empty ({}) and fill in sensible defaults.

        Parameters
        ----------
        prompt : str
            Full prompt string. Include a JSON schema description in the prompt
            so the model knows exactly what fields to produce.

        Returns
        -------
        dict — parsed JSON response, or {} on any failure.
        """
        try:
            resp = httpx.post(
                config.OLLAMA_URL,
                json={
                    "model":  config.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
                timeout=config.OLLAMA_TIMEOUT,
            )
            raw = resp.json().get("response", "{}")
            return json.loads(raw)
        except httpx.TimeoutException:
            logger.warning("[%s] Ollama call timed out (%.0fs)", self.agent_name, config.OLLAMA_TIMEOUT)
            return {}
        except Exception as exc:
            logger.warning("[%s] Ollama call failed: %s", self.agent_name, exc)
            return {}

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    def run(self, context: dict) -> dict:
        """
        Execute the agent's analysis on the current simulation state.

        Parameters
        ----------
        context : dict with at minimum:
            "df"          : pd.DataFrame — cursor-sliced production_events.
                            This is the ONLY safe source of production data.
            "as_of_time"  : pd.Timestamp — the latest timestamp in df.

            Additional keys may be added by the Orchestrator:
            "forecast"    : ForecasterAgent output dict
            "mechanic"    : MechanicAgent output dict
            (etc.)

        Returns
        -------
        dict — standardised signal dict. Required keys vary by agent
               (see the implementation plan for each agent's output schema).

        Side effects
        ------------
        - SHOULD call self.publish_signal() at least once per run.
        - MAY call self.enqueue_hitl() for escalations.
        - MUST NOT query production_events from the DB.
        """
        ...
