"""
Shared Streamlit runtime for the multipage dashboard.

This module centralises the Phase 6 integration work:
  - data loading
  - session/bootstrap state
  - orchestrator execution
  - shared sidebar controls
  - Ollama status caching + offline fallback messaging
  - idle-safe auto-refresh
"""

from __future__ import annotations

import logging
import sqlite3
import time

import httpx
import pandas as pd
import streamlit as st

import config

logger = logging.getLogger(__name__)

COLORS = {
    "healthy": "#00C896",
    "warning": "#FFA500",
    "critical": "#FF4C4C",
    "info": "#4A9EFF",
    "background": "#0E1117",
    "card_bg": "#1E1E2E",
    "border": "#2E2E4E",
    "accent": "#7C3AED",
}

STATUS_COLORS = {
    "ALL_OK": COLORS["healthy"],
    "NEEDS_HITL": COLORS["warning"],
    "BLOCKED": COLORS["critical"],
}

STATUS_ICONS = {
    "ALL_OK": "🟢",
    "NEEDS_HITL": "🟡",
    "BLOCKED": "🔴",
}

_DEFAULT_COLUMNS = [
    "Timestamp",
    "Order_ID",
    "Product_Category",
    "Region",
    "Assigned_Facility",
    "Production_Line",
    "Forecasted_Demand",
    "Actual_Order_Qty",
    "Workforce_Required",
    "Workforce_Deployed",
    "Schedule_Status",
    "Operator_Override_Flag",
    "Machine_Temperature_C",
    "Machine_Vibration_Hz",
    "Predicted_Time_To_Failure_Hrs",
    "Machine_OEE_Pct",
    "Raw_Material_Inventory_Units",
    "Inventory_Threshold",
    "Procurement_Action",
    "Live_Supplier_Quote_USD",
    "Grid_Pricing_Period",
    "Energy_Consumed_kWh",
    "Carbon_Emissions_kg",
    "Carbon_Cost_Penalty_USD",
]


def _safe_set_page_config(page_title: str, page_icon: str) -> None:
    try:
        st.set_page_config(
            page_title=page_title,
            page_icon=page_icon,
            layout="wide",
            initial_sidebar_state="expanded",
        )
    except Exception:
        pass


def _ensure_theme() -> None:
    st.session_state["_COLORS"] = COLORS
    st.session_state["_STATUS_COLORS"] = STATUS_COLORS
    st.session_state["_STATUS_ICONS"] = STATUS_ICONS


@st.cache_data(ttl=5, show_spinner=False)
def load_data() -> pd.DataFrame:
    """Load the production event stream from SQLite."""
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            df = pd.read_sql_query("SELECT * FROM production_events", conn)
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
        df = df.dropna(subset=["Timestamp"])
        return df.sort_values(by="Timestamp").reset_index(drop=True)
    except Exception as exc:
        logger.error("[dashboard_runtime] Failed to load production data: %s", exc)
        return pd.DataFrame(columns=_DEFAULT_COLUMNS)


def _initialise_session_state(df_full: pd.DataFrame) -> None:
    ss = st.session_state
    default_cursor = min(100, len(df_full))

    if "time_cursor" not in ss:
        ss.time_cursor = default_cursor
    ss.time_cursor = max(0, min(int(ss.time_cursor), len(df_full)))

    ss.setdefault("orch_output", None)
    ss.setdefault("orch_cursor", -1)
    ss.setdefault("nlp_history", [])
    ss.setdefault("dt_chat_history", [])
    ss.setdefault("dt_scenarios", {})
    ss.setdefault("dt_results", {})
    ss.setdefault("selected_plant", None)
    ss.setdefault("dt_result", None)
    ss.setdefault("dt_result_plant", None)
    ss.setdefault("dt_controls_context", None)
    ss.setdefault("dt_plan_override", None)
    ss.setdefault("_auto_refresh_pending", False)
    ss.setdefault("_auto_refresh_supported", False)
    ss.setdefault("_last_user_interaction_at", time.time())
    ss.setdefault("pause_auto_refresh", False)


def _consume_auto_refresh_flag() -> bool:
    return bool(st.session_state.pop("_auto_refresh_pending", False))


def _mark_user_interaction() -> None:
    if not _consume_auto_refresh_flag():
        st.session_state["_last_user_interaction_at"] = time.time()


def _clear_digital_twin_state() -> None:
    st.session_state["dt_result"] = None
    st.session_state["dt_result_plant"] = None
    st.session_state["dt_results"] = {}
    st.session_state["dt_chat_history"] = []
    st.session_state["dt_scenarios"] = {}
    st.session_state["dt_controls_context"] = None
    st.session_state["dt_plan_override"] = None


def _store_live_slice(df_full: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp]:
    df = df_full.iloc[: st.session_state.time_cursor].copy()
    current_time = df["Timestamp"].max() if not df.empty else pd.Timestamp.now()
    st.session_state["_df"] = df
    st.session_state["_df_full"] = df_full
    st.session_state["_current_time"] = current_time
    return df, current_time


def run_orchestrator(force: bool = False) -> None:
    """Run the orchestrator when the time cursor changes or when forced."""
    cursor = st.session_state.time_cursor
    current_df = st.session_state.get("_df", pd.DataFrame())
    current_time = st.session_state.get("_current_time", pd.Timestamp.now())

    if not force and st.session_state.get("orch_cursor") == cursor:
        return

    if current_df.empty:
        st.session_state["orch_output"] = None
        st.session_state["orch_cursor"] = cursor
        return

    try:
        from agents.orchestrator import OrchestratorAgent

        with st.spinner("🤖 Orchestrator running all agents…"):
            result = OrchestratorAgent().run({"df": current_df, "as_of_time": current_time})
        st.session_state["orch_output"] = result
        st.session_state["orch_cursor"] = cursor
        _clear_digital_twin_state()
        logger.info(
            "[dashboard_runtime] Orchestrator complete. Status=%s Health=%.1f",
            result.get("final_status", "?"),
            result.get("system_health", 0),
        )
    except Exception as exc:
        logger.error("[dashboard_runtime] OrchestratorAgent failed: %s", exc)
        st.session_state["orch_output"] = None
        st.session_state["orch_cursor"] = cursor


def get_agent_log(limit: int = 500) -> pd.DataFrame:
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            log_df = pd.read_sql_query(
                f"SELECT * FROM agent_events ORDER BY logged_at DESC LIMIT {int(limit)}",
                conn,
            )
        log_df["logged_at"] = pd.to_datetime(log_df["logged_at"])
        if "facility_id" in log_df.columns:
            log_df.rename(columns={"facility_id": "facility"}, inplace=True)
        return log_df
    except Exception:
        return pd.DataFrame(
            columns=[
                "logged_at",
                "agent_name",
                "severity",
                "order_id",
                "facility",
                "message",
                "confidence_pct",
                "action_taken",
            ]
        )


def severity_color(val: str) -> str:
    if val == "WARNING":
        return f"color: {COLORS['warning']}; font-weight: bold;"
    if val == "CRITICAL":
        return f"color: {COLORS['critical']}; font-weight: bold;"
    return f"color: {COLORS['healthy']}; font-weight: bold;"


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


@st.cache_data(ttl=config.DASHBOARD["ollama_check_ttl_secs"], show_spinner=False)
def _cached_ollama_check(tags_url: str) -> bool:
    try:
        response = httpx.get(tags_url, timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


def check_ollama() -> bool:
    ok = _cached_ollama_check(config.OLLAMA_TAGS_URL)
    st.session_state["_ollama_ok"] = ok
    return ok


def advance_time(steps: int = 10) -> None:
    df_full = st.session_state.get("_df_full", pd.DataFrame())
    st.session_state.time_cursor = min(
        len(df_full),
        st.session_state.time_cursor + max(0, int(steps)),
    )


def reset_dashboard_state() -> None:
    df_full = st.session_state.get("_df_full", pd.DataFrame())
    st.session_state.time_cursor = min(100, len(df_full))
    st.session_state["orch_output"] = None
    st.session_state["orch_cursor"] = -1
    st.session_state["nlp_history"] = []
    st.session_state["selected_plant"] = None
    _clear_digital_twin_state()
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute("DELETE FROM agent_events;")
            conn.commit()
    except Exception:
        pass


def _render_system_health() -> None:
    out = orch()
    if not out:
        return

    final_status = out.get("final_status", "ALL_OK")
    health = out.get("system_health", 0)
    color = STATUS_COLORS.get(final_status, COLORS["info"])
    icon = STATUS_ICONS.get(final_status, "⚪")
    st.markdown("---")
    st.markdown(
        f"<div style='background:{color}22;border:1px solid {color};border-radius:6px;"
        f"padding:8px 12px;text-align:center;'>"
        f"<span style='color:{color};font-weight:bold;font-size:13px;'>"
        f"{icon} {final_status.replace('_', ' ')}</span><br/>"
        f"<span style='font-size:11px;color:#aaa;'>Health: {health:.0f}/100</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    df_full = st.session_state.get("_df_full", pd.DataFrame())
    current_time = st.session_state.get("_current_time", pd.Timestamp.now())
    idle_secs = int(max(0, time.time() - st.session_state.get("_last_user_interaction_at", time.time())))

    with st.sidebar:
        st.title("🏭 Production System")
        st.markdown("---")

        ollama_ok = check_ollama()
        dot_color = COLORS["healthy"] if ollama_ok else COLORS["critical"]
        status_txt = "Online" if ollama_ok else "Offline"
        st.markdown(
            f"<span style='color:{dot_color};font-size:18px;'>●</span> "
            f"Ollama: **{status_txt}** — `{config.OLLAMA_MODEL}`",
            unsafe_allow_html=True,
        )
        if not ollama_ok:
            st.caption("LLM reasoning unavailable. Using rule-based fallback.")

        try:
            from hitl.manager import HitlManager

            hitl_count = HitlManager().pending_count()
            if hitl_count > 0:
                st.warning(f"📥 {hitl_count} item(s) awaiting approval")
        except Exception:
            pass

        st.markdown("---")
        st.subheader("⏱️ Simulation Controls")
        st.markdown(f"**Time:** `{current_time.strftime('%Y-%m-%d %H:%M')}`")
        st.markdown(f"**Events:** `{st.session_state.time_cursor:,}` / `{len(df_full):,}`")

        step_size = st.slider("Step size (events/tick)", 1, 100, 10, key="sidebar_step")
        col1, col2 = st.columns(2)
        if col1.button("⏭️ Next Tick", key="sb_next"):
            advance_time(step_size)
            st.rerun()
        if col2.button("⏩ +500", key="sb_ff"):
            advance_time(500)
            st.rerun()

        if st.button("🤖 Trigger Agents Now", key="sb_agents"):
            run_orchestrator(force=True)
            st.rerun()

        if st.button("↺ Reset", key="sb_reset"):
            reset_dashboard_state()
            st.rerun()

        st.toggle(
            "Pause auto-refresh",
            key="pause_auto_refresh",
            help="When enabled, the dashboard will not auto-refresh while you review or edit a page.",
        )
        if st.session_state.get("pause_auto_refresh", False):
            st.caption("Auto-refresh is paused.")
        elif st.session_state.get("_auto_refresh_supported", False):
            st.caption(
                f"Auto-refresh every {config.DASHBOARD['auto_refresh_secs']}s when idle. "
                f"Idle for {idle_secs}s."
            )
        else:
            st.caption("Auto-refresh unavailable in this Streamlit version.")

        _render_system_health()


def _arm_auto_refresh() -> None:
    st.session_state["_auto_refresh_supported"] = False


def render_ollama_fallback_notice(feature_name: str) -> None:
    if st.session_state.get("_ollama_ok", True):
        return
    st.warning(
        f"Ollama is offline. {feature_name} is using deterministic fallback behavior until the model is available again."
    )


def bootstrap_page(page_title: str, page_icon: str = "🏭") -> dict:
    """Bootstrap shared dashboard state for any page in the multipage app."""
    _safe_set_page_config(page_title, page_icon)
    _ensure_theme()
    df_full = load_data()
    _initialise_session_state(df_full)
    _mark_user_interaction()
    df, current_time = _store_live_slice(df_full)
    run_orchestrator()
    st.session_state["_get_agent_log"] = get_agent_log
    st.session_state["_severity_color"] = severity_color
    st.session_state["_orch"] = orch
    render_sidebar()
    _arm_auto_refresh()
    return {
        "df": df,
        "df_full": df_full,
        "current_time": current_time,
        "orch_output": orch(),
        "ollama_ok": st.session_state.get("_ollama_ok", True),
    }
