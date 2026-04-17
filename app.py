"""
app.py — Agentic Production Planning System
Slim entry point: loads data, runs orchestrator, exposes sidebar.
All page rendering has moved to pages/ directory.

Phase 2 changes
---------------
- Converted to multi-page app (pages/ directory structure).
- This file is now the shared foundation: data, session state, sidebar.
- Pages import shared helpers from this module via st.session_state.
"""

import streamlit as st
import pandas as pd
import sqlite3
import httpx
import logging
import time

import config

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Agentic Production Planning System",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Shared color palette (pages import from session_state)
COLORS = {
    "healthy":    "#00C896",
    "warning":    "#FFA500",
    "critical":   "#FF4C4C",
    "info":       "#4A9EFF",
    "background": "#0E1117",
    "card_bg":    "#1E1E2E",
    "border":     "#2E2E4E",
    "accent":     "#7C3AED",
}

STATUS_COLORS = {
    "ALL_OK":     COLORS["healthy"],
    "NEEDS_HITL": COLORS["warning"],
    "BLOCKED":    COLORS["critical"],
}

STATUS_ICONS = {
    "ALL_OK":     "🟢",
    "NEEDS_HITL": "🟡",
    "BLOCKED":    "🔴",
}

# Store in session so pages can access
st.session_state["_COLORS"]        = COLORS
st.session_state["_STATUS_COLORS"] = STATUS_COLORS
st.session_state["_STATUS_ICONS"]  = STATUS_ICONS

# ==========================================
# 📦 DATA LOADING
# ==========================================
@st.cache_data(ttl=5)
def load_data() -> pd.DataFrame:
    try:
        conn = sqlite3.connect(config.DB_PATH)
        df = pd.read_sql_query("SELECT * FROM production_events", conn)
        conn.close()
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
        df = df.dropna(subset=["Timestamp"])
        df = df.sort_values(by="Timestamp").reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"Failed to load data from production.db: {e}")
        return pd.DataFrame(columns=[
            "Timestamp","Order_ID","Product_Category","Region","Assigned_Facility",
            "Production_Line","Forecasted_Demand","Actual_Order_Qty","Workforce_Required",
            "Workforce_Deployed","Schedule_Status","Operator_Override_Flag",
            "Machine_Temperature_C","Machine_Vibration_Hz","Predicted_Time_To_Failure_Hrs",
            "Machine_OEE_Pct","Raw_Material_Inventory_Units","Inventory_Threshold",
            "Procurement_Action","Live_Supplier_Quote_USD","Grid_Pricing_Period",
            "Energy_Consumed_kWh","Carbon_Emissions_kg","Carbon_Cost_Penalty_USD",
        ])


df_full = load_data()

# ==========================================
# 🧠 SESSION STATE INITIALISATION
# ==========================================
if "time_cursor" not in st.session_state:
    st.session_state.time_cursor = min(100, len(df_full))

if "orch_output" not in st.session_state:
    st.session_state["orch_output"] = None

if "orch_cursor" not in st.session_state:
    st.session_state["orch_cursor"] = -1   # force first run

if "nlp_history" not in st.session_state:
    st.session_state["nlp_history"] = []

if "dt_chat_history" not in st.session_state:
    st.session_state["dt_chat_history"] = []

if "dt_scenarios" not in st.session_state:
    st.session_state["dt_scenarios"] = {}

if "selected_plant" not in st.session_state:
    st.session_state["selected_plant"] = None

if "dt_result" not in st.session_state:
    st.session_state["dt_result"] = None

# ==========================================
# 📊 DATA SLICING (CURSOR)
# ==========================================
df           = df_full.iloc[: st.session_state.time_cursor].copy()
current_time = df["Timestamp"].max() if not df.empty else pd.Timestamp.now()

# Expose to pages via session_state
st.session_state["_df"]           = df
st.session_state["_df_full"]      = df_full
st.session_state["_current_time"] = current_time


# ==========================================
# 🤖 ORCHESTRATOR WIRING
# ==========================================
def run_orchestrator(force: bool = False) -> None:
    """
    Run all agents via OrchestratorAgent.
    Only re-runs when cursor advances (or force=True) to avoid redundant Ollama calls.
    Results cached in st.session_state["orch_output"].
    """
    cursor = st.session_state.time_cursor

    if not force and st.session_state.get("orch_cursor") == cursor:
        return   # nothing changed — use cached output

    if df.empty:
        st.session_state["orch_output"] = None
        st.session_state["orch_cursor"] = cursor
        return

    try:
        from agents.orchestrator import OrchestratorAgent
        with st.spinner("🤖 Orchestrator running all agents…"):
            orch = OrchestratorAgent()
            result = orch.run({"df": df, "as_of_time": current_time})
        st.session_state["orch_output"] = result
        st.session_state["orch_cursor"] = cursor
        logger.info(
            "[app] Orchestrator complete. Status=%s Health=%.1f",
            result.get("final_status", "?"),
            result.get("system_health", 0),
        )
    except Exception as exc:
        logger.error("[app] OrchestratorAgent failed: %s", exc)
        st.session_state["orch_output"] = None
        st.session_state["orch_cursor"] = cursor


run_orchestrator()


# ==========================================
# 🛠️  SHARED HELPERS (available to pages)
# ==========================================
def get_agent_log(limit: int = 500) -> pd.DataFrame:
    try:
        conn   = sqlite3.connect(config.DB_PATH)
        log_df = pd.read_sql_query(
            f"SELECT * FROM agent_events ORDER BY logged_at DESC LIMIT {limit}", conn
        )
        conn.close()
        log_df["logged_at"] = pd.to_datetime(log_df["logged_at"])
        if "facility_id" in log_df.columns:
            log_df.rename(columns={"facility_id": "facility"}, inplace=True)
        return log_df
    except Exception:
        return pd.DataFrame(columns=[
            "logged_at","agent_name","severity","order_id","facility",
            "message","confidence_pct","action_taken",
        ])


def advance_time(steps: int = 10) -> None:
    if st.session_state.time_cursor + steps <= len(df_full):
        st.session_state.time_cursor += steps
    else:
        st.session_state.time_cursor = len(df_full)


def check_ollama() -> bool:
    try:
        r = httpx.get(config.OLLAMA_TAGS_URL, timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def severity_color(val: str) -> str:
    if val == "WARNING":  return f"color: {COLORS['warning']}; font-weight: bold;"
    if val == "CRITICAL": return f"color: {COLORS['critical']}; font-weight: bold;"
    return f"color: {COLORS['healthy']}; font-weight: bold;"


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


# Store helpers in session_state so pages can re-use them
st.session_state["_get_agent_log"]    = get_agent_log
st.session_state["_severity_color"]   = severity_color
st.session_state["_orch"]             = orch


# ==========================================
# 🏠 COMMAND CENTER (default / home page)
# ==========================================
def render_command_center():
    # Import and delegate to pages/01_Command_Center.py logic inline
    # (this keeps the home page accessible at the root URL)
    import importlib, sys, os
    page_path = os.path.join(os.path.dirname(__file__), "pages", "01_Command_Center.py")
    spec = importlib.util.spec_from_file_location("cmd_center", page_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)


# ==========================================
# 🔄 SIDEBAR  (shared across all pages)
# ==========================================
with st.sidebar:
    st.title("🏭 Production System")
    st.markdown("---")

    # Ollama status
    ollama_ok  = check_ollama()
    dot_color  = COLORS["healthy"] if ollama_ok else COLORS["critical"]
    status_txt = "Online" if ollama_ok else "Offline"
    st.markdown(
        f"<span style='color:{dot_color};font-size:18px;'>●</span> "
        f"Ollama: **{status_txt}** — `{config.OLLAMA_MODEL}`",
        unsafe_allow_html=True,
    )

    # HITL badge
    try:
        from hitl.manager import HitlManager
        htl_count = HitlManager().pending_count()
        if htl_count > 0:
            st.warning(f"📥 {htl_count} item(s) awaiting approval")
    except Exception:
        pass

    st.markdown("---")
    st.subheader("⏱️ Simulation Controls")
    st.markdown(f"**Time:** `{current_time.strftime('%Y-%m-%d %H:00')}`")
    st.markdown(f"**Events:** `{st.session_state.time_cursor:,}` / `{len(df_full):,}`")

    step_size = st.slider("Step size (events/tick)", 1, 100, 10, key="sidebar_step")
    sc1, sc2  = st.columns(2)

    if sc1.button("⏭️ Next Tick", key="sb_next"):
        advance_time(step_size)
        st.rerun()
    if sc2.button("⏩ +500", key="sb_ff"):
        advance_time(500)
        st.rerun()

    if st.button("🤖 Trigger Agents Now", key="sb_agents"):
        run_orchestrator(force=True)
        st.rerun()

    if st.button("↺ Reset", key="sb_reset"):
        st.session_state.time_cursor      = min(100, len(df_full))
        st.session_state["orch_output"]   = None
        st.session_state["orch_cursor"]   = -1
        st.session_state["nlp_history"]   = []
        st.session_state["dt_chat_history"] = []
        st.session_state["dt_scenarios"]  = {}
        st.session_state["dt_result"]     = None
        try:
            conn = sqlite3.connect(config.DB_PATH)
            conn.execute("DELETE FROM agent_events;")
            conn.commit()
            conn.close()
        except Exception:
            pass
        st.rerun()

    # System health indicator
    out = orch()
    health = out.get("system_health", 0)
    final_status = out.get("final_status", "ALL_OK")
    if out:
        st.markdown("---")
        hcol = STATUS_COLORS.get(final_status, COLORS["info"])
        st.markdown(
            f"<div style='background:{hcol}22;border:1px solid {hcol};border-radius:6px;"
            f"padding:8px 12px;text-align:center;'>"
            f"<span style='color:{hcol};font-weight:bold;font-size:13px;'>"
            f"{STATUS_ICONS.get(final_status,'⚪')} {final_status.replace('_',' ')}</span><br/>"
            f"<span style='font-size:11px;color:#aaa;'>Health: {health:.0f}/100</span>"
            f"</div>",
            unsafe_allow_html=True,
        )


# ==========================================
# RENDER HOME (Command Center shown at root)
# ==========================================
# Pages in the pages/ folder handle their own rendering.
# The root app.py shows the Command Center.

out         = orch()
COLORS      = st.session_state["_COLORS"]
final_status= out.get("final_status", "ALL_OK")
health      = out.get("system_health", 0.0)
conflicts   = out.get("conflicts", [])
last_run    = out.get("last_run_at")

banner_color = STATUS_COLORS.get(final_status, COLORS["info"])
banner_icon  = STATUS_ICONS.get(final_status, "⚪")
last_run_str = (
    last_run.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(last_run, pd.Timestamp)
    else "Not yet run"
)
banner_text = {
    "ALL_OK":     "ALL SYSTEMS GO — All agents healthy",
    "NEEDS_HITL": f"ATTENTION NEEDED — {len(conflicts)} issue(s) require human review",
    "BLOCKED":    f"PRODUCTION BLOCKED — {len(conflicts)} critical conflict(s). HITL review required",
}.get(final_status, "")

st.title("🏭 Command Center")
st.markdown("Real-time oversight of all production facilities and AI agent activities.")

st.markdown(f"""
<div style="background:{banner_color}22; border:2px solid {banner_color};
            border-radius:10px; padding:18px 24px; margin-bottom:24px;">
    <span style="font-size:22px; font-weight:bold; color:{banner_color};">
        {banner_icon} &nbsp; {banner_text}
    </span>
    <span style="float:right; color:#888; font-size:13px; margin-top:4px;">
        Last updated: {last_run_str} &nbsp;|&nbsp;
        Health Score: <b style="color:{banner_color};">{health:.0f}/100</b>
    </span>
</div>
""", unsafe_allow_html=True)

# ── KPI Row ──────────────────────────────────────────────────────────────────
from datetime import timedelta
col1, col2, col3, col4, col5 = st.columns(5)
if not df.empty:
    on_time_pct    = (df["Schedule_Status"] == "On-Time").mean() * 100
    log_df         = get_agent_log()
    active_alerts  = len(log_df[log_df["severity"] != "INFO"])
    last_24h       = df[df["Timestamp"] >= current_time - timedelta(hours=24)]
    carbon_penalty = last_24h["Carbon_Cost_Penalty_USD"].sum() if not last_24h.empty else 0
    wf_cov         = (df["Workforce_Deployed"].sum() / max(df["Workforce_Required"].sum(), 1)) * 100

    buyer_inv = out.get("buyer_inventory", {})
    min_days  = min((v.get("days_remaining", 0) for v in buyer_inv.values()), default=0)

    col1.metric("On-Time Delivery",     f"{on_time_pct:.1f}%",   f"{on_time_pct-90:.1f}% vs Target")
    col2.metric("Active Alerts",        active_alerts)
    col3.metric("Carbon Penalty (24h)", f"${carbon_penalty:,.0f}")
    col4.metric("Min Inventory Left",   f"{min_days:.1f} days")
    col5.metric("Workforce Coverage",   f"{wf_cov:.1f}%")

st.markdown("---")

# ── Plant Overview Grid ───────────────────────────────────────────────────────
st.subheader("🌐 Plant Status Overview")
st.caption("Click ▶ to navigate to that plant's detailed production plan.")

facilities = df["Assigned_Facility"].unique().tolist() if not df.empty else []
buyer_inv  = out.get("buyer_inventory", {})
mech_risks = out.get("mechanic", {}).get("facility_risks", {})
sch_plans  = out.get("scheduler", {})

if facilities:
    fcols = st.columns(min(len(facilities), 5))
    for i, fac in enumerate(list(facilities)[:5]):
        fac_df      = df[df["Assigned_Facility"] == fac]
        oee         = fac_df["Machine_OEE_Pct"].mean() if not fac_df.empty else 0
        risk_info   = mech_risks.get(fac, {})
        risk_score  = risk_info.get("risk_score", 0)
        risk_label  = risk_info.get("status", "healthy").upper()
        inv_info    = buyer_inv.get(fac, {})
        inv_status  = inv_info.get("status", "healthy")
        inv_days    = inv_info.get("days_remaining", 0)
        plan_info   = sch_plans.get(fac, {})
        plan_thru   = plan_info.get("expected_throughput", 0)

        oee_color   = (
            COLORS["healthy"]  if oee >= 90 else
            COLORS["warning"]  if oee >= 80 else
            COLORS["critical"]
        )
        inv_emoji   = "✅" if inv_status == "healthy" else "⚠️" if inv_status == "low" else "🔴"
        risk_color  = (
            COLORS["critical"] if risk_label in ("CRITICAL",) else
            COLORS["warning"]  if risk_label in ("WARNING", "MEDIUM") else
            COLORS["healthy"]
        )
        plan_status = (
            "⛔ Blocked" if risk_label == "CRITICAL" else
            "✅ Ready"   if plan_info.get("shift_plan") else
            "⏳ Pending"
        )

        with fcols[i]:
            st.markdown(f"""
            <div style="border:1px solid #333; border-top:4px solid {oee_color};
                        border-radius:8px; padding:16px; background:{COLORS['card_bg']};
                        margin-bottom:12px; min-height:170px;">
                <div style="font-weight:bold; font-size:14px; margin-bottom:8px;">
                    🏭 {fac.split("(")[0].strip()}
                </div>
                <div style="font-size:12px; color:#aaa; line-height:2.0;">
                    OEE: <b style="color:{oee_color};">{oee:.1f}%</b><br/>
                    Risk: <b style="color:{risk_color};">{risk_label} ({risk_score:.0f})</b><br/>
                    Inventory: <b>{inv_emoji} {inv_status.upper()}</b> ({inv_days:.1f}d)<br/>
                    Plan: <b>{plan_status}</b><br/>
                    Throughput: <b>{plan_thru:,} units</b>
                </div>
            </div>
            """, unsafe_allow_html=True)
else:
    st.info("No facility data loaded yet.")

st.markdown("---")

# ── Agent Health Grid ─────────────────────────────────────────────────────────
st.subheader("🤖 Agent Health Summary")
forecast_out = out.get("forecast", {})
mechanic_out = out.get("mechanic", {})
buyer_out    = out.get("buyer", {})
environ_out  = out.get("environ", {})
finance_out  = out.get("finance", {})

agent_cards = [
    {
        "name":    "📈 Forecaster",
        "status":  forecast_out.get("risk_level", "low"),
        "summary": (forecast_out.get("summary", "Not yet run.") or "")[:120],
        "metric":  f"Forecast: {forecast_out.get('forecast_qty', 0):,} units",
        "page":    "02_Demand_Intelligence",
    },
    {
        "name":    "🔧 Mechanic",
        "status":  "critical" if mechanic_out.get("critical_facilities") else
                   "warning"  if mechanic_out.get("warning_facilities")  else "low",
        "summary": (mechanic_out.get("summary", "Not yet run.") or "")[:120],
        "metric":  f"{len(mechanic_out.get('critical_facilities', []))} critical plant(s)",
        "page":    "05_Machine_Health",
    },
    {
        "name":    "📦 Buyer",
        "status":  "warning" if buyer_out.get("reorders_triggered", 0) > 0 else "low",
        "summary": f"{buyer_out.get('reorders_triggered', 0)} reorder(s) triggered",
        "metric":  f"${buyer_out.get('total_spend_requested_usd', 0):,.0f} requested",
        "page":    "03_Inventory_Logistics",
    },
    {
        "name":    "🌱 Environmentalist",
        "status":  "low" if environ_out.get("compliance_flag", True) else "warning",
        "summary": (environ_out.get("summary", "Not yet run.") or "")[:120],
        "metric":  f"{environ_out.get('peak_penalty_pct', 0):.1f}% peak penalty ratio",
        "page":    "08_Carbon_Energy",
    },
    {
        "name":    "💰 Finance",
        "status":  "critical" if finance_out.get("health_score", 100) < 30 else
                   "warning"  if finance_out.get("health_score", 100) < 60 else "low",
        "summary": f"Health: {finance_out.get('health_score', 100):.1f}/100",
        "metric":  f"${finance_out.get('budget_status', {}).get('spent_usd', 0):,.0f} spent",
        "page":    "06_Finance_Dashboard",
    },
    {
        "name":    "🗓️ Scheduler",
        "status":  "critical" if final_status == "BLOCKED" else
                   "warning"  if final_status == "NEEDS_HITL" else "low",
        "summary": f"{len(out.get('scheduler', {}))} plant plans generated",
        "metric":  f"System: {final_status}",
        "page":    "04_Production_Plan",
    },
]

cols = st.columns(3)
for i, card in enumerate(agent_cards):
    cval = (
        COLORS["critical"] if card["status"] in ("critical", "high") else
        COLORS["warning"]  if card["status"] in ("warning", "medium") else
        COLORS["healthy"]
    )
    with cols[i % 3]:
        st.markdown(f"""
        <div style="border:1px solid #333; border-left:4px solid {cval};
                    border-radius:6px; padding:14px; background:{COLORS['card_bg']};
                    margin-bottom:12px;">
            <div style="font-size:15px; font-weight:bold; color:{cval};">{card['name']}</div>
            <div style="font-size:12px; color:#aaa; margin:4px 0;">{card['summary']}</div>
            <div style="font-size:13px; color:#ddd;">{card['metric']}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# ── Active Conflicts ──────────────────────────────────────────────────────────
if conflicts:
    st.subheader("⚡ Active Conflicts Detected")
    for c in conflicts:
        color = COLORS["critical"] if c["severity"] == "CRITICAL" else COLORS["warning"]
        st.markdown(f"""
        <div style="border-left:4px solid {color}; background:{color}11;
                    padding:10px 14px; border-radius:0 6px 6px 0; margin-bottom:8px;">
            <b style="color:{color};">[{c['severity']}] {c['type'].replace('_',' ').title()}</b>
            &nbsp;|&nbsp; Agents: {', '.join(c.get('involved_agents', []))}
            <br/><span style="font-size:13px;">{c['description']}</span>
            <br/><span style="font-size:12px; color:#aaa;">→ {c.get('action','')}</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.success("✅ No cross-agent conflicts detected.")

st.markdown("---")

# ── Live Agent Activity Log ───────────────────────────────────────────────────
st.subheader("🕵️ Live Agent Activity Log")
log_df = get_agent_log(limit=config.DASHBOARD["agent_log_display"])
if not log_df.empty:
    styled = log_df.head(config.DASHBOARD["agent_log_display"]).style.map(
        severity_color, subset=["severity"]
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)
else:
    st.info("No agent activity logged yet.")
