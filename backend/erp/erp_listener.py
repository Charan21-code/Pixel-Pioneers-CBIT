"""
backend/erp/erp_listener.py — ERP Event Listener

Background async loop that polls the active ERP adapter for new events
and signals the agent loop to replan when relevant events arrive.

This mirrors the existing _agent_loop() pattern in backend/main.py.
"""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .erp_adapter import ERPAdapter
    from .erp_audit import ERPAudit

logger = logging.getLogger(__name__)

# ── Shared replan flag ────────────────────────────────────────────────────────
# Set by the listener when an ERP event warrants a full agent replan.
# Cleared by the agent loop after it has replanned.
_ERP_REPLAN_FLAG: bool = False
_LAST_POLL: datetime = datetime.utcnow() - timedelta(days=1)

# ── Event → Agent mapping ─────────────────────────────────────────────────────
_EVENT_AGENT_MAP: dict[str, str] = {
    "NEW_SALES_ORDER":   "Forecaster",   # new order → re-forecast demand
    "GOODS_RECEIPT":     "Buyer",        # inventory refilled → cancel pending reorders
    "PO_CONFIRMATION":   "Buyer",        # PO confirmed → mark reorder fulfilled
    "MACHINE_ALERT":     "Mechanic",     # machine issue → re-assess maintenance risk
    "mail.message":      "Forecaster",   # Odoo-style generic notification
}


def should_replan() -> bool:
    """Returns True if an ERP event has requested a full agent replan."""
    return _ERP_REPLAN_FLAG


def clear_replan_flag():
    """Called by _agent_loop() after it has responded to the ERP trigger."""
    global _ERP_REPLAN_FLAG
    _ERP_REPLAN_FLAG = False


async def erp_listener_loop(
    get_adapter: Callable[[], "ERPAdapter | None"],
    audit: "ERPAudit",
    poll_interval_secs: int = 30,
):
    """
    Background coroutine — started in FastAPI lifespan alongside _agent_loop.

    Parameters
    ----------
    get_adapter         : callable returning the currently active ERPAdapter
                          (e.g. ``lambda: _CACHE["erp_adapter"]``)
    audit               : ERPAudit instance for logging received events
    poll_interval_secs  : from config.ERP["poll_interval_secs"]
    """
    global _LAST_POLL, _ERP_REPLAN_FLAG

    logger.info("[ERPListener] Started. Polling every %ds.", poll_interval_secs)

    while True:
        try:
            adapter = get_adapter()
            if adapter is not None:
                events = adapter.poll_events(since=_LAST_POLL)
                _LAST_POLL = datetime.utcnow()

                for ev in events:
                    etype          = ev.get("type", "UNKNOWN")
                    triggered_agent = _EVENT_AGENT_MAP.get(etype)
                    needs_replan   = triggered_agent is not None

                    audit.log_event(
                        erp_type        = adapter.erp_type,
                        event_type      = etype,
                        event_id        = ev.get("event_id", ""),
                        plant           = ev.get("plant", ""),
                        payload         = ev,
                        triggered_agent = triggered_agent,
                        replan          = needs_replan,
                    )

                    if needs_replan and not _ERP_REPLAN_FLAG:
                        _ERP_REPLAN_FLAG = True
                        logger.info(
                            "[ERPListener] Event '%s' → requesting replan (agent: %s)",
                            etype, triggered_agent,
                        )

        except asyncio.CancelledError:
            logger.info("[ERPListener] Cancelled, shutting down.")
            raise
        except Exception as exc:
            logger.error("[ERPListener] Poll error: %s", exc, exc_info=True)

        await asyncio.sleep(poll_interval_secs)
