"""
app.py — Agentic Production Planning System
Main Streamlit entry point.

Architecture
------------
- Loads production data from SQLite (production.db).
- Maintains a time_cursor in session_state that simulates a live event stream.
- On each tick, runs OrchestratorAgent which calls all specialist agents in order.
- Stores the full output in st.session_state["orch_output"] — all pages read from this.
- Pages are rendered by the navigation radio in the sidebar.

Phase 1 changes
---------------
- Removed the old inline run_agents() function.
- Added OrchestratorAgent wiring: runs on tick advance or manual trigger.
- orch_output is cached per cursor value (agents only re-run when cursor changes).
- Ollama status check added to sidebar.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
import time
import sqlite3
import httpx
import logging

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

# Custom Colors
COLORS = {
    "healthy":    "#00C896",
    "warning":    "#FFA500",
    "critical":   "#FF4C4C",
    "info":       "#4A9EFF",
    "background": "#0E1117",
    "card_bg":    "#1E1E2E",
    "border":     "#2E2E4E",
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

import config

# ==========================================
# 📦 DATA LOADING
# ==========================================
@st.cache_data(ttl=5)
def load_data():
    try:
        conn = sqlite3.connect(config.DB_PATH)
        df = pd.read_sql_query("SELECT * FROM production_events", conn)
        conn.close()
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        df = df.dropna(subset=['Timestamp'])
        df = df.sort_values(by='Timestamp').reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"Failed to load data from production.db: {e}")
        return pd.DataFrame(columns=[
            'Timestamp','Order_ID','Product_Category','Region','Assigned_Facility',
            'Production_Line','Forecasted_Demand','Actual_Order_Qty','Workforce_Required',
            'Workforce_Deployed','Schedule_Status','Operator_Override_Flag',
            'Machine_Temperature_C','Machine_Vibration_Hz','Predicted_Time_To_Failure_Hrs',
            'Machine_OEE_Pct','Raw_Material_Inventory_Units','Inventory_Threshold',
            'Procurement_Action','Live_Supplier_Quote_USD','Grid_Pricing_Period',
            'Energy_Consumed_kWh','Carbon_Emissions_kg','Carbon_Cost_Penalty_USD'
        ])


df_full = load_data()


# ==========================================
# 🧠 SESSION STATE INITIALISATION
# ==========================================
if 'time_cursor' not in st.session_state:
    st.session_state.time_cursor = min(100, len(df_full))

if 'orch_output' not in st.session_state:
    st.session_state['orch_output'] = None

if 'orch_cursor' not in st.session_state:
    st.session_state['orch_cursor'] = -1   # force first run

if 'nlp_history' not in st.session_state:
    st.session_state['nlp_history'] = []

if 'dt_chat_history' not in st.session_state:
    st.session_state['dt_chat_history'] = []

if 'dt_scenarios' not in st.session_state:
    st.session_state['dt_scenarios'] = {}  # {"A": result, "B": result, "C": result}

if 'selected_plant' not in st.session_state:
    st.session_state['selected_plant'] = None


# ==========================================
# 📊 DATA SLICING (CURSOR)
# ==========================================
df           = df_full.iloc[:st.session_state.time_cursor].copy()
current_time = df['Timestamp'].max() if not df.empty else pd.Timestamp.now()


# ==========================================
# 🤖 ORCHESTRATOR WIRING
# ==========================================
def run_orchestrator(force: bool = False):
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
        with st.spinner("🤖 Orchestrator running all agents..."):
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


# Run orchestrator (skips if cursor hasn't changed)
run_orchestrator()


# ==========================================
# 🛠️ SHARED HELPERS
# ==========================================
def get_agent_log(limit: int = 500) -> pd.DataFrame:
    try:
        conn = sqlite3.connect(config.DB_PATH)
        log_df = pd.read_sql_query(
            f"SELECT * FROM agent_events ORDER BY logged_at DESC LIMIT {limit}", conn
        )
        conn.close()
        log_df['logged_at'] = pd.to_datetime(log_df['logged_at'])
        if 'facility_id' in log_df.columns:
            log_df.rename(columns={'facility_id': 'facility'}, inplace=True)
        return log_df
    except Exception:
        return pd.DataFrame(columns=[
            'logged_at','agent_name','severity','order_id','facility',
            'message','confidence_pct','action_taken'
        ])


def advance_time(steps: int = 10):
    if st.session_state.time_cursor + steps <= len(df_full):
        st.session_state.time_cursor += steps
    else:
        st.session_state.time_cursor = len(df_full)


def check_ollama() -> bool:
    """Returns True if Ollama is reachable."""
    try:
        r = httpx.get(config.OLLAMA_TAGS_URL, timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def severity_color(val: str) -> str:
    if val == 'WARNING':  return f'color: {COLORS["warning"]}; font-weight: bold;'
    if val == 'CRITICAL': return f'color: {COLORS["critical"]}; font-weight: bold;'
    return f'color: {COLORS["healthy"]}; font-weight: bold;'


def orch() -> dict:
    """Shortcut to get orchestrator output dict."""
    return st.session_state.get("orch_output") or {}


# ==========================================
# 🏠 PAGE 1: COMMAND CENTER
# ==========================================
def render_command_center():
    st.title("🏭 Command Center")
    st.markdown("Real-time oversight of all production facilities and AI agent activities.")

    out         = orch()
    final_status= out.get("final_status", "ALL_OK")
    health      = out.get("system_health", 0.0)
    conflicts   = out.get("conflicts", [])
    last_run    = out.get("last_run_at")

    # ── Orchestrator Status Banner ──────────────────────────────────────────
    banner_color = STATUS_COLORS.get(final_status, COLORS["info"])
    banner_icon  = STATUS_ICONS.get(final_status, "⚪")
    last_run_str = last_run.strftime('%Y-%m-%d %H:%M:%S') if isinstance(last_run, pd.Timestamp) else "Not yet run"
    n_conflicts  = len(conflicts)
    banner_text  = {
        "ALL_OK":     "ALL SYSTEMS GO — All agents healthy",
        "NEEDS_HITL": f"ATTENTION NEEDED — {n_conflicts} issue(s) require human review",
        "BLOCKED":    f"PRODUCTION BLOCKED — {n_conflicts} critical conflict(s). HITL review required",
    }.get(final_status, "")

    st.markdown(f"""
    <div style="background:{banner_color}22; border:2px solid {banner_color};
                border-radius:8px; padding:16px 20px; margin-bottom:20px;">
        <span style="font-size:22px; font-weight:bold; color:{banner_color};">
            {banner_icon} &nbsp; {banner_text}
        </span>
        <span style="float:right; color:#888; font-size:13px; margin-top:4px;">
            Last updated: {last_run_str} &nbsp;|&nbsp;
            Health Score: <b style="color:{banner_color};">{health:.0f}/100</b>
        </span>
    </div>
    """, unsafe_allow_html=True)

    # ── KPI Row ──────────────────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
    if not df.empty:
        on_time_pct   = (df['Schedule_Status'] == 'On-Time').mean() * 100
        log_df        = get_agent_log()
        active_alerts = len(log_df[log_df['severity'] != 'INFO'])
        last_24h      = df[df['Timestamp'] >= current_time - timedelta(hours=24)]
        carbon_penalty= last_24h['Carbon_Cost_Penalty_USD'].sum() if not last_24h.empty else 0
        wf_cov        = (df['Workforce_Deployed'].sum() / max(df['Workforce_Required'].sum(), 1)) * 100

        buyer_inv     = out.get("buyer_inventory", {})
        min_days      = min((v.get("days_remaining", 0) for v in buyer_inv.values()), default=0)

        col1.metric("On-Time Delivery",    f"{on_time_pct:.1f}%",   f"{on_time_pct-90:.1f}% vs Target")
        col2.metric("Active Alerts",       active_alerts)
        col3.metric("Carbon Penalty (24h)",f"${carbon_penalty:,.0f}")
        col4.metric("Min Inventory Left",  f"{min_days:.1f} days")
        col5.metric("Workforce Coverage",  f"{wf_cov:.1f}%")

    st.markdown("---")

    # ── Agent Health Grid ────────────────────────────────────────────────────
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
            "summary": forecast_out.get("summary", "Not yet run.")[:100],
            "metric":  f"Forecast: {forecast_out.get('forecast_qty', 0):,} units",
        },
        {
            "name":    "🔧 Mechanic",
            "status":  "critical" if mechanic_out.get("critical_facilities") else
                       "warning"  if mechanic_out.get("warning_facilities")  else "low",
            "summary": mechanic_out.get("summary", "Not yet run.")[:100],
            "metric":  f"{len(mechanic_out.get('critical_facilities', []))} critical facility(ies)",
        },
        {
            "name":    "📦 Buyer",
            "status":  "warning" if buyer_out.get("reorders_triggered", 0) > 0 else "low",
            "summary": f"{buyer_out.get('reorders_triggered', 0)} reorder(s) triggered",
            "metric":  f"${buyer_out.get('total_spend_requested_usd', 0):,.0f} requested",
        },
        {
            "name":    "🌱 Environmentalist",
            "status":  "low" if environ_out.get("compliance_flag", True) else "warning",
            "summary": environ_out.get("summary", "Not yet run.")[:100],
            "metric":  f"{environ_out.get('peak_penalty_pct', 0):.1f}% peak penalty ratio",
        },
        {
            "name":    "💰 Finance",
            "status":  "critical" if finance_out.get("health_score", 100) < 30 else
                       "warning"  if finance_out.get("health_score", 100) < 60 else "low",
            "summary": f"Health: {finance_out.get('health_score', 100):.1f}/100",
            "metric":  f"${finance_out.get('budget_status', {}).get('spent_usd', 0):,.0f} spent",
        },
        {
            "name":    "🗓️ Scheduler",
            "status":  "critical" if final_status == "BLOCKED" else
                       "warning"  if final_status == "NEEDS_HITL" else "low",
            "summary": f"{len(out.get('scheduler', {}))} plant plans generated",
            "metric":  f"System: {final_status}",
        },
    ]

    cols = st.columns(3)
    for i, card in enumerate(agent_cards):
        c = COLORS["critical"] if card["status"] == "critical" else \
            COLORS["warning"]  if card["status"] in ("warning", "medium", "high") else \
            COLORS["healthy"]
        with cols[i % 3]:
            st.markdown(f"""
            <div style="border:1px solid #333; border-left:4px solid {c};
                        border-radius:6px; padding:14px; background:{COLORS['card_bg']};
                        margin-bottom:12px;">
                <div style="font-size:15px; font-weight:bold; color:{c};">{card['name']}</div>
                <div style="font-size:12px; color:#aaa; margin:4px 0;">{card['summary']}</div>
                <div style="font-size:13px; color:#ddd;">{card['metric']}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")

    # ── Plant Overview Grid ──────────────────────────────────────────────────
    st.subheader("🌐 Plant Status")
    facilities = df['Assigned_Facility'].unique() if not df.empty else []
    buyer_inv  = out.get("buyer_inventory", {})
    mech_risks = out.get("mechanic", {}).get("facility_risks", {})
    sch_plans  = out.get("scheduler", {})

    if len(facilities) > 0:
        fcols = st.columns(min(len(facilities), 5))
        for i, fac in enumerate(list(facilities)[:5]):
            fac_df    = df[df['Assigned_Facility'] == fac]
            oee       = fac_df['Machine_OEE_Pct'].mean()
            risk_info = mech_risks.get(fac, {})
            risk_score= risk_info.get("risk_score", 0)
            risk_label= risk_info.get("status", "healthy").upper()
            inv_info  = buyer_inv.get(fac, {})
            inv_status= inv_info.get("status", "healthy")
            plan_info = sch_plans.get(fac, {})
            plan_thru = plan_info.get("expected_throughput", 0)

            oee_color  = COLORS['healthy'] if oee > 90 else \
                         COLORS['warning'] if oee > 80 else COLORS['critical']
            inv_emoji  = "✅" if inv_status=="healthy" else "⚠️" if inv_status=="low" else "🔴"
            risk_color = COLORS['critical'] if risk_label=="CRITICAL" else \
                         COLORS['warning']  if risk_label=="WARNING"  else COLORS['healthy']

            with fcols[i]:
                st.markdown(f"""
                <div style="border:1px solid #333; border-top:4px solid {oee_color};
                            border-radius:6px; padding:14px; background:{COLORS['card_bg']};">
                    <div style="font-weight:bold; font-size:14px;">
                        {fac.split(' - ')[0] if ' - ' in fac else fac}
                    </div>
                    <div style="font-size:12px; color:#aaa; margin-top:4px;">
                        OEE: <b style="color:{oee_color};">{oee:.1f}%</b>
                    </div>
                    <div style="font-size:12px; color:#aaa;">
                        Risk: <b style="color:{risk_color};">{risk_label} ({risk_score:.0f})</b>
                    </div>
                    <div style="font-size:12px; color:#aaa;">
                        Inventory: <b>{inv_emoji} {inv_status.upper()}</b>
                    </div>
                    <div style="font-size:12px; color:#aaa;">
                        Plan Thru: <b>{plan_thru:,} units</b>
                    </div>
                </div>
                """, unsafe_allow_html=True)

    st.markdown("---")

    # ── Active Conflicts ──────────────────────────────────────────────────────
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

    # ── Live Agent Activity Log ──────────────────────────────────────────────
    st.subheader("🕵️ Live Agent Activity Log")
    log_df = get_agent_log(limit=config.DASHBOARD["agent_log_display"])
    if not log_df.empty:
        styled = log_df.head(config.DASHBOARD["agent_log_display"]).style.map(
            severity_color, subset=['severity']
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.info("No agent activity logged yet.")


# ==========================================
# 📊 PAGE 2: DEMAND INTELLIGENCE
# ==========================================
def render_demand_intelligence():
    st.title("📈 Demand Intelligence (Forecaster Agent)")
    if df.empty:
        return st.warning("No data available.")

    out          = orch()
    forecast_out = out.get("forecast", {})

    # Agent Narrative
    risk_level = forecast_out.get("risk_level", "low")
    summary    = forecast_out.get("summary", "Forecaster agent has not run yet.")
    r2         = forecast_out.get("r_squared", 0.0)
    badge_color= COLORS["critical"] if risk_level=="high" else \
                 COLORS["warning"]  if risk_level=="medium" else COLORS["healthy"]

    st.markdown(f"""
    <div style="border:1px solid {badge_color}; border-left:5px solid {badge_color};
                border-radius:6px; padding:16px; background:{COLORS['card_bg']}; margin-bottom:16px;">
        <b style="color:{badge_color};">DEMAND RISK: {risk_level.upper()}</b>
        &nbsp;|&nbsp; Forecast Confidence (R²): <b>{r2*100:.1f}%</b><br/>
        <span style="font-size:14px;">{summary}</span>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("7-Day Forecast (units)", f"{forecast_out.get('forecast_qty', 0):,}")
    col2.metric("Trend Slope",            f"{forecast_out.get('trend_slope', 0):+.1f} units/day")
    col3.metric("Demand Spike Anomalies", forecast_out.get("anomaly_count", 0))

    st.markdown("---")
    st.markdown("Analyzing deviations between forecasted demand and actual orders.")

    daily_demand = (
        df.set_index('Timestamp')
        .resample('D')
        .agg({'Forecasted_Demand': 'sum', 'Actual_Order_Qty': 'sum'})
        .reset_index()
    )

    fig = px.line(
        daily_demand, x='Timestamp',
        y=['Forecasted_Demand', 'Actual_Order_Qty'],
        labels={'value': 'Units', 'variable': 'Metric'},
        title="Demand Trend: Forecast vs Actual",
        color_discrete_sequence=[COLORS['info'], COLORS['warning']],
    )
    st.plotly_chart(fig, use_container_width=True)

    tab1, tab2 = st.tabs(["📦 By Product", "🌍 By Region"])
    with tab1:
        prod_demand = (
            df.groupby('Product_Category')['Actual_Order_Qty'].sum()
            .reset_index()
            .sort_values('Actual_Order_Qty', ascending=False)
        )
        fig2 = px.bar(
            prod_demand, x='Product_Category', y='Actual_Order_Qty',
            title="Demand by Product Category", color='Actual_Order_Qty',
            color_continuous_scale="Blues",
        )
        st.plotly_chart(fig2, use_container_width=True)

    with tab2:
        region_demand = df.groupby('Region')['Actual_Order_Qty'].sum().reset_index()
        fig3 = px.pie(region_demand, names='Region', values='Actual_Order_Qty', hole=0.4,
                      title="Demand Share by Region")
        st.plotly_chart(fig3, use_container_width=True)

    # Anomaly Table
    st.subheader("⚠️ Demand Spike Anomalies (>30% over forecast)")
    anomalies = df[df['Actual_Order_Qty'] > df['Forecasted_Demand'] * 1.30]
    if not anomalies.empty:
        disp = anomalies[['Timestamp','Order_ID','Product_Category','Region',
                           'Forecasted_Demand','Actual_Order_Qty']].copy()
        disp['Spike %'] = ((disp['Actual_Order_Qty'] / disp['Forecasted_Demand'] - 1) * 100).round(1)
        st.dataframe(disp.tail(50), use_container_width=True, hide_index=True)
    else:
        st.success("No significant demand anomalies detected.")

    if forecast_out.get("recommended_action"):
        st.info(f"💡 **Recommended Action:** {forecast_out['recommended_action']}")


# ==========================================
# 📊 PAGE 3: INVENTORY & PROCUREMENT
# ==========================================
def render_inventory():
    st.title("📦 Inventory & Logistics (Buyer Agent)")
    if df.empty:
        return st.warning("No data available.")

    out      = orch()
    inv_data = out.get("buyer_inventory", {})
    buyer_out= out.get("buyer", {})

    # If orchestrator hasn't run, derive from df
    if not inv_data:
        st.warning("⚠️ Agent outputs not yet available. Showing raw data.")

    st.subheader("📊 Plant Inventory Status")

    if inv_data:
        cols = st.columns(min(len(inv_data), 3))
        for i, (plant, inv) in enumerate(inv_data.items()):
            status    = inv.get("status", "healthy")
            days_rem  = inv.get("days_remaining", 0)
            shortfall = inv.get("shortfall_units", 0)
            lead_days = inv.get("lead_days", 3)
            reorder   = inv.get("reorder_qty", 0)
            cost      = inv.get("cost_usd", 0)
            cur_stock = inv.get("current_stock", 0)
            threshold = inv.get("inventory_threshold", 20000)
            daily_use = inv.get("daily_use", 0)

            status_color = (
                COLORS["critical"] if status in ("critical", "emergency") else
                COLORS["warning"]  if status == "low" else
                COLORS["healthy"]
            )
            status_badge = {
                "healthy":   "✅ HEALTHY",
                "low":       "⚠️ LOW — Order Soon",
                "critical":  "🔴 CRITICAL — Order Now",
                "emergency": "🚨 EMERGENCY — Lead time exceeds stock!",
            }.get(status, status.upper())

            with cols[i % 3]:
                st.markdown(f"""
                <div style="border:1px solid #333; border-top:4px solid {status_color};
                            border-radius:6px; padding:14px; background:{COLORS['card_bg']};
                            margin-bottom:12px;">
                    <div style="font-weight:bold; font-size:14px; color:{status_color};">
                        {plant.split('(')[0].strip()}
                    </div>
                    <div style="font-size:12px; color:#aaa; line-height:1.8; margin-top:6px;">
                        Current Stock: <b style="color:#fff;">{cur_stock:,} units</b><br/>
                        Threshold: <b>{threshold:,} units</b><br/>
                        Daily Use: <b>{daily_use:.0f} units/day</b><br/>
                        Days Remaining: <b style="color:{status_color};">{days_rem:.1f} days</b><br/>
                        Shortfall: <b>{shortfall:,} units</b><br/>
                        Lead Time: <b>~{lead_days} days to receive</b><br/>
                    </div>
                    <div style="margin-top:8px; font-size:12px;">
                        Status: <b style="color:{status_color};">{status_badge}</b>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Emergency warning
                if status == "emergency":
                    st.error(
                        f"⚠️ **{plant.split('(')[0].strip()}**: Stock runs out in {days_rem:.1f} days, "
                        f"but lead time is ~{lead_days} days. Order immediately."
                    )
    else:
        # Fallback: show raw inventory chart from df
        latest_inv = df.groupby('Assigned_Facility').last().reset_index()
        fig = px.bar(latest_inv, x='Assigned_Facility',
                     y=['Raw_Material_Inventory_Units','Inventory_Threshold'],
                     barmode='overlay', title="Inventory vs Threshold")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Reorder table
    if inv_data:
        st.subheader("📋 Reorder Recommendations")
        reorder_rows = []
        for plant, inv in inv_data.items():
            if inv.get("reorder_qty", 0) > 0:
                reorder_rows.append({
                    "Plant":           plant.split("(")[0].strip(),
                    "Current Stock":   f"{inv['current_stock']:,}",
                    "Daily Use":       f"{inv['daily_use']:.0f}/day",
                    "Days Left":       f"{inv['days_remaining']:.1f}d",
                    "Shortfall":       f"{inv['shortfall_units']:,} units",
                    "Reorder Qty":     f"{inv['reorder_qty']:,} units",
                    "Est. Cost (USD)": f"${inv['cost_usd']:,.0f}",
                    "Lead Days":       f"~{inv['lead_days']} days",
                    "Status":          inv["status"].upper(),
                })
        if reorder_rows:
            st.dataframe(pd.DataFrame(reorder_rows), use_container_width=True, hide_index=True)
        else:
            st.success("All plants have sufficient inventory. No reorders needed.")

    st.markdown("---")

    # Procurement log from data
    st.subheader("📜 Procurement History (from production data)")
    procurement_events = df[df['Procurement_Action'] != 'None']
    if not procurement_events.empty:
        disp_cols = ['Timestamp','Assigned_Facility','Procurement_Action',
                     'Live_Supplier_Quote_USD','Raw_Material_Inventory_Units']
        st.dataframe(
            procurement_events[disp_cols].tail(20), use_container_width=True, hide_index=True
        )
    else:
        st.info("No procurement events in current data window.")


# ==========================================
# 📊 PAGE 4: PRODUCTION PLAN
# ==========================================
def render_production_schedule():
    st.title("🗓️ Production Plan (Scheduler Agent)")
    if df.empty:
        return st.warning("No data available.")

    out         = orch()
    sch_plans   = out.get("scheduler", {})
    plants      = out.get("plants", df['Assigned_Facility'].unique().tolist())
    mech_out    = out.get("mechanic", {})
    buyer_inv   = out.get("buyer_inventory", {})
    finance_out = out.get("finance", {})
    final_status= out.get("final_status", "ALL_OK")

    # ── Level A: Plant Overview Table ────────────────────────────────────────
    st.subheader("🏭 All Plants — Quick Overview")
    st.markdown("Click on a plant to see its detailed shift plan.")

    overview_rows = []
    mech_risks  = mech_out.get("facility_risks", {})
    for plant in plants:
        risk_info  = mech_risks.get(plant, {})
        inv_info   = buyer_inv.get(plant, {})
        plan_info  = sch_plans.get(plant, {})
        wf_df      = df[df["Assigned_Facility"] == plant]
        wf_pct     = (
            wf_df["Workforce_Deployed"].sum() /
            max(wf_df["Workforce_Required"].sum(), 1) * 100
        ) if not wf_df.empty else 0

        overview_rows.append({
            "Plant":          plant.split("(")[0].strip(),
            "Machine Risk":   f"{risk_info.get('status','?').upper()} ({risk_info.get('risk_score',0):.0f})",
            "Workforce %":    f"{wf_pct:.1f}%",
            "Stock Days":     f"{inv_info.get('days_remaining', 0):.1f}d",
            "Plan Status":    "⛔ Blocked" if risk_info.get("status")=="critical" else
                              "✅ Ready"   if plan_info.get("shift_plan") else "⏳ Pending",
            "Throughput":     f"{plan_info.get('expected_throughput', 0):,} units",
        })

    overview_df = pd.DataFrame(overview_rows)
    st.dataframe(overview_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Level B: Plant-Specific View ─────────────────────────────────────────
    st.subheader("🔍 Plant-Specific Shift Plan")
    selected = st.selectbox(
        "Select Plant",
        options=plants,
        index=0,
        key="plan_plant_selector",
    )
    if selected:
        st.session_state['selected_plant'] = selected

    if not selected:
        return

    plant_plan = sch_plans.get(selected, {})
    plant_risk = mech_risks.get(selected, {})
    plant_inv  = buyer_inv.get(selected, {})
    plant_wf   = df[df["Assigned_Facility"] == selected]
    wf_pct     = (
        plant_wf["Workforce_Deployed"].sum() /
        max(plant_wf["Workforce_Required"].sum(), 1) * 100
    ) if not plant_wf.empty else 0
    wf_dep     = int(plant_wf["Workforce_Deployed"].mean()) if not plant_wf.empty else 0
    wf_req     = int(plant_wf["Workforce_Required"].mean()) if not plant_wf.empty else 0

    # Readiness Gate
    mach_ok = plant_risk.get("status", "healthy") != "critical"
    wf_ok   = wf_pct >= 80
    inv_ok  = plant_inv.get("status", "healthy") in ("healthy", "low")
    fin_ok  = finance_out.get("health_score", 100) >= 30

    gate_rows = [
        ("MACHINE HEALTH",
         f"OEE {plant_risk.get('oee_pct', 0):.1f}% | Risk Score {plant_risk.get('risk_score', 0):.0f} | TTF: {plant_risk.get('ttf_hrs', 0):.0f} hrs",
         mach_ok),
        ("WORKFORCE",
         f"{wf_pct:.1f}% deployed ({wf_dep} / {wf_req} workers)",
         wf_ok),
        ("INVENTORY",
         f"{plant_inv.get('days_remaining', 0):.1f} days remaining | Status: {plant_inv.get('status','?').upper()}",
         inv_ok),
        ("FINANCE GATE",
         f"Health: {finance_out.get('health_score', 100):.1f}/100",
         fin_ok),
    ]

    all_gates_ok = all(ok for _, _, ok in gate_rows)
    gate_html = ""
    for label, detail, ok in gate_rows:
        icon  = "✅" if ok else "🔴"
        color = COLORS["healthy"] if ok else COLORS["critical"]
        gate_html += f"""<div style="margin:4px 0; font-size:13px;">
            {icon} <b style="color:{color};">{label}:</b> &nbsp; {detail}
        </div>"""

    overall_msg = (
        "→ PLANT IS CLEARED FOR PRODUCTION"
        if all_gates_ok else
        "→ Issues detected. Review before committing plan."
    )
    gate_color = COLORS["healthy"] if all_gates_ok else COLORS["warning"]

    st.markdown(f"""
    <div style="border:1px solid {gate_color}33; border-left:4px solid {gate_color};
                border-radius:6px; padding:14px; background:{COLORS['card_bg']}; margin-bottom:16px;">
        <b style="font-size:15px;">{selected.split('(')[0].strip()} — READINESS CHECK</b>
        {gate_html}
        <div style="margin-top:8px; color:{gate_color}; font-weight:bold;">{overall_msg}</div>
    </div>
    """, unsafe_allow_html=True)

    # Shift Plan Table
    st.subheader("📋 7-Day Shift Plan")
    shift_plan = plant_plan.get("shift_plan", [])
    if shift_plan:
        plan_df = pd.DataFrame(shift_plan)
        st.dataframe(plan_df, use_container_width=True, hide_index=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Planned Units", f"{plant_plan.get('expected_throughput', 0):,}")
        c2.metric("Utilisation",         f"{plant_plan.get('utilisation_pct', 0):.1f}%")
        c3.metric("Available Lines",    f"{len(plant_plan.get('available_facilities', []))} / 3")
    else:
        st.info("No shift plan generated yet. Facility may be blacklisted or agents are still initialising.")

    if st.button("📋 Submit Plan for Approval", key=f"submit_plan_{selected}"):
        from hitl.manager import HitlManager
        hm = HitlManager()
        hm.enqueue("ops", "Scheduler", {
            "plant":       selected,
            "shift_plan":  shift_plan,
            "throughput":  plant_plan.get("expected_throughput", 0),
            "utilisation": plant_plan.get("utilisation_pct", 0),
            "message":     f"7-day production plan for {selected} requires approval.",
        })
        st.success("✅ Plan submitted to HITL Inbox for approval.")

    st.subheader("🤖 Scheduler Agent Summary")
    st.info(plant_plan.get("summary", "No summary available."))
    if plant_plan.get("excluded_facilities"):
        st.warning(f"⛔ Excluded (blacklisted): {', '.join(plant_plan.get('excluded_facilities', []))}")


# ==========================================
# 📊 PAGE 5: MACHINE HEALTH
# ==========================================
def render_machine_health():
    st.title("🔧 Machine Health & OEE (Mechanic Agent)")
    if df.empty:
        return st.warning("No data available.")

    out        = orch()
    mech_out   = out.get("mechanic", {})
    fac_risks  = mech_out.get("facility_risks", {})
    plants     = out.get("plants", df['Assigned_Facility'].unique().tolist())

    selected = st.selectbox(
        "🏭 Select Plant",
        options=plants,
        index=0,
        key="mh_plant_selector",
    )
    if not selected:
        return

    risk_info = fac_risks.get(selected, {})
    risk_score= risk_info.get("risk_score", 0)
    risk_status= risk_info.get("status", "healthy")
    ttf_hrs   = risk_info.get("ttf_hrs", 0)
    oee_pct   = risk_info.get("oee_pct", 0)
    temp_c    = risk_info.get("temp_c", 0)

    risk_color = (
        COLORS["critical"] if risk_status == "critical" else
        COLORS["warning"]  if risk_status == "warning"  else
        COLORS["healthy"]
    )

    st.markdown(f"""
    <div style="border:1px solid #333; border-left:5px solid {risk_color};
                border-radius:6px; padding:16px; background:{COLORS['card_bg']}; margin-bottom:16px;">
        <b style="font-size:16px; color:{risk_color};">
            {selected.split('(')[0].strip()} — MACHINE HEALTH
        </b>
        <div style="font-size:13px; color:#aaa; line-height:2.0; margin-top:8px;">
            Risk Score: <b style="color:{risk_color};">{risk_score:.0f} / 100 — {risk_status.upper()}</b><br/>
            Average OEE: <b>{oee_pct:.1f}%</b><br/>
            Min. Predicted TTF: <b>{ttf_hrs:.1f} hrs</b><br/>
            Avg. Temperature: <b>{temp_c:.1f}°C</b>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Crisis Alert
    plant_df = df[df["Assigned_Facility"] == selected].tail(150)
    if not plant_df.empty and plant_df["Predicted_Time_To_Failure_Hrs"].min() < 24:
        min_ttf = plant_df["Predicted_Time_To_Failure_Hrs"].min()
        worst   = plant_df.loc[plant_df["Predicted_Time_To_Failure_Hrs"].idxmin()]
        st.error(
            f"🚨 **MACHINE FAILURE IMMINENT — {selected.split('(')[0].strip()}**\n\n"
            f"Predicted TTF = **{min_ttf:.1f} hrs** | "
            f"Temperature: **{worst['Machine_Temperature_C']:.1f}°C** | "
            f"Vibration: **{worst['Machine_Vibration_Hz']:.1f} Hz**\n\n"
            "This facility has been automatically blacklisted in the Production Plan. "
            "Rerouting to partner overflow is recommended."
        )
        if st.button("🔧 Schedule Emergency Maintenance", key=f"maint_{selected}"):
            from hitl.manager import HitlManager
            HitlManager().enqueue("maintenance", "Mechanic", {
                "facility": selected,
                "ttf_hrs":  float(min_ttf),
                "temp_c":   float(worst["Machine_Temperature_C"]),
                "vib_hz":   float(worst["Machine_Vibration_Hz"]),
                "message":  f"Emergency maintenance required at {selected}.",
            })
            st.success("✅ Emergency maintenance request sent to HITL Inbox.")

    # 4-Panel Charts
    st.markdown("---")
    st.subheader("📡 Sensor Telemetry")
    c1, c2 = st.columns(2)
    with c1:
        if not plant_df.empty:
            fig_ttf = px.line(plant_df, x='Timestamp', y='Predicted_Time_To_Failure_Hrs',
                              title="Predicted Time To Failure (hrs)")
            fig_ttf.add_hline(y=config.AGENT["ttf_critical_hrs"],  line_dash="dash",
                              line_color="red",    annotation_text="CRITICAL (24h)")
            fig_ttf.add_hline(y=config.AGENT["ttf_warning_hrs"],   line_dash="dot",
                              line_color="orange", annotation_text="WARNING (100h)")
            fig_ttf.update_layout(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE")
            st.plotly_chart(fig_ttf, use_container_width=True)

        fig_oee = px.line(plant_df, x='Timestamp', y='Machine_OEE_Pct', title="OEE %")
        fig_oee.add_hline(y=config.AGENT["oee_warning_pct"], line_dash="dot",
                          line_color="green",  annotation_text=f"Target ({config.AGENT['oee_warning_pct']}%)")
        fig_oee.update_layout(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE")
        st.plotly_chart(fig_oee, use_container_width=True)

    with c2:
        fig_temp = px.line(plant_df, x='Timestamp', y='Machine_Temperature_C', title="Temperature (°C)")
        fig_temp.add_hline(y=80, line_dash="dot", line_color="orange", annotation_text="⚠️ 80°C")
        fig_temp.update_layout(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE")
        st.plotly_chart(fig_temp, use_container_width=True)

        fig_vib = px.line(plant_df, x='Timestamp', y='Machine_Vibration_Hz', title="Vibration (Hz)")
        fig_vib.add_hline(y=55, line_dash="dot", line_color="orange", annotation_text="⚠️ 55 Hz")
        fig_vib.update_layout(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE")
        st.plotly_chart(fig_vib, use_container_width=True)

    # Mechanic Recommendations
    recs = mech_out.get("recommendations", [])
    plant_recs = [r for r in recs if r.get("facility","") == selected]
    if plant_recs:
        st.subheader("🛠️ Mechanic Agent Recommendations")
        for rec in plant_recs:
            st.info(f"**Action:** {rec.get('action','')} | "
                    f"**Est. Downtime:** {rec.get('estimated_downtime_hrs', '?')} hrs")
    if mech_out.get("summary"):
        with st.expander("📝 Full Mechanic Agent Summary"):
            st.write(mech_out["summary"])


# ==========================================
# 📊 PAGE 6: DIGITAL TWIN
# ==========================================
def render_digital_twin():
    st.title("🧬 Digital Twin Simulation")
    if df.empty:
        return st.warning("No data available.")

    out        = orch()
    plants     = out.get("plants", df['Assigned_Facility'].unique().tolist())

    from simulation.digital_twin import simulate, derive_defaults_from_agent_output

    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("⚙️ Configure Simulation")
        st.caption("Default values loaded live from agent outputs")

        selected_plant = st.selectbox("Select Plant", options=plants, key="dt_plant")
        defaults       = derive_defaults_from_agent_output(selected_plant, out, df)

        oee_val        = st.slider("OEE %",                 50,   100,  int(defaults["oee_pct"]),    key="dt_oee")
        wf_val         = st.slider("Workforce Availability %", 50, 100,  int(defaults["workforce_pct"]),key="dt_wf")
        forecast_val   = st.number_input("Demand to Meet (units)", 0, 50000, defaults["forecast_qty"], step=100, key="dt_fq")
        energy_val     = st.slider("Energy Price ($/kWh)",   0.05, 0.50, round(defaults["energy_price"],2), step=0.01, key="dt_ep")
        downtime_val   = st.slider("Machine Downtime Day 1 (hrs)", 0, 72, 0, step=2, key="dt_dt")
        opt_for        = st.selectbox("Optimise For", ["Time","Cost","Carbon"], key="dt_opt")
        buffer_pct     = st.slider("Demand Buffer %", 0, 30, 10, key="dt_buf") / 100.0

        run_sim = st.button("▶ Run Simulation", type="primary", key="dt_run")
        if st.button("💾 Save as Scenario A", key="dt_sa"):
            st.session_state["dt_scenarios"]["A"] = st.session_state.get("dt_result")
        if st.button("💾 Save as Scenario B", key="dt_sb"):
            st.session_state["dt_scenarios"]["B"] = st.session_state.get("dt_result")

    with col_right:
        if run_sim:
            result = simulate(
                plant_id=selected_plant,
                oee_pct=oee_val,
                workforce_pct=wf_val,
                forecast_qty=int(forecast_val),
                energy_price=energy_val,
                downtime_hrs=downtime_val,
                optimise_for=opt_for,
                horizon_days=config.SIMULATION["sim_days"],
                base_capacity=defaults.get("base_capacity", 2000),
                demand_buffer_pct=buffer_pct,
            )
            st.session_state["dt_result"] = result
        else:
            result = st.session_state.get("dt_result")

        if result:
            st.subheader(f"📊 Simulation Results — {result['plant_id'].split('(')[0].strip()}")

            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("Expected Output",      f"{result['expected_output_units']:,} units")
            rc2.metric("Target",               f"{result['target_qty']:,} units")
            rc3.metric("Shortfall",            f"-{result['shortfall_units']:,}" if result['shortfall_units'] else "✅ None",
                       delta_color="inverse")
            rc4, rc5, rc6 = st.columns(3)
            rc4.metric("Estimated Cost",       f"${result['cost_usd']:,.0f}")
            rc5.metric("Carbon Emissions",     f"{result['carbon_kg']:,.0f} kg CO₂")
            rc6.metric("Completion Day",       f"Day {result['completion_day']} of {config.SIMULATION['sim_days']}")

            # Trajectory Chart
            days = [f"Day {i+1}" for i in range(config.SIMULATION["sim_days"])]
            cum  = result["cumulative_breakdown"]
            tgt  = [result["target_qty"]] * config.SIMULATION["sim_days"]
            fig  = go.Figure()
            fig.add_trace(go.Scatter(x=days, y=cum, name="Cumulative Output",
                                     fill="tozeroy", line=dict(color=COLORS["info"])))
            fig.add_trace(go.Scatter(x=days, y=tgt, name="Target",
                                     line=dict(color=COLORS["critical"], dash="dash")))
            fig.update_layout(title="Production Trajectory", plot_bgcolor="#0E1117",
                              paper_bgcolor="#0E1117", font_color="#EEE")
            st.plotly_chart(fig, use_container_width=True)

            # Warnings
            for w in result.get("warnings", []):
                st.warning(w)

            # Optimisation Tips
            if result.get("optimise_suggestions"):
                st.subheader("💡 Optimisation Suggestions")
                for tip in result["optimise_suggestions"]:
                    st.info(tip)

        else:
            st.info("👈 Set parameters and click **▶ Run Simulation** to see results.")

    # Scenario Comparison
    scenarios = {k: v for k, v in st.session_state.get("dt_scenarios", {}).items() if v}
    if len(scenarios) >= 2:
        st.markdown("---")
        st.subheader("📊 Scenario Comparison")
        comp_rows = []
        for k, s in scenarios.items():
            comp_rows.append({
                "Scenario": k,
                "Output (units)": f"{s['expected_output_units']:,}",
                "Shortfall": f"{s['shortfall_units']:,}",
                "Cost (USD)": f"${s['cost_usd']:,.0f}",
                "Carbon (kg)": f"{s['carbon_kg']:,.0f}",
                f"Completion Day": f"Day {s['completion_day']}",
            })
        st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)

    # ── Mini Chat (Ollama post-simulation) ───────────────────────────────────
    st.markdown("---")
    st.subheader("💬 Ask Follow-up Questions About This Simulation")
    st.caption("Ask about this simulation — parameters are passed to Ollama as context.")

    if "dt_chat_history" not in st.session_state:
        st.session_state["dt_chat_history"] = []

    for msg in st.session_state["dt_chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if query := st.chat_input("e.g. What if workforce drops to 70%? Why is there a shortfall?"):
        st.session_state["dt_chat_history"].append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        cur_result = st.session_state.get("dt_result", {})
        context_str = (
            f"Plant: {cur_result.get('plant_id', 'unknown')}\n"
            f"Parameters: {cur_result.get('parameters_used', {})}\n"
            f"Results: output={cur_result.get('expected_output_units', 0)}, "
            f"shortfall={cur_result.get('shortfall_units', 0)}, "
            f"cost=${cur_result.get('cost_usd', 0)}, "
            f"carbon={cur_result.get('carbon_kg', 0)} kg\n"
            f"Warnings: {cur_result.get('warnings', [])}"
        ) if cur_result else "No simulation has been run yet."

        try:
            resp = httpx.post(
                config.OLLAMA_URL,
                json={
                    "model":  config.OLLAMA_MODEL,
                    "prompt": (
                        f"You are a production planning assistant.\n\n"
                        f"Current simulation context:\n{context_str}\n\n"
                        f"User question: {query}\n\n"
                        "Answer concisely in plain English. If the user wants to "
                        "change a parameter, say which slider to adjust and by how much."
                    ),
                    "stream": False,
                },
                timeout=config.OLLAMA_TIMEOUT,
            )
            answer = resp.json().get("response", "").strip() or "I couldn't generate a response."
        except Exception:
            answer = "⚠️ Ollama is offline. Cannot answer — please ensure the model is running."

        with st.chat_message("assistant"):
            st.markdown(answer)
        st.session_state["dt_chat_history"].append({"role": "assistant", "content": answer})


# ==========================================
# 📊 PAGE 7: MACHINE HEALTH (kept as alias)
# ==========================================
# render_machine_health is already defined above


# ==========================================
# 📊 PAGE 8: CARBON & ENERGY
# ==========================================
def render_carbon_dashboard():
    st.title("🌱 Carbon & Energy Dashboard (Environmentalist Agent)")
    if df.empty:
        return st.warning("No data available.")

    out         = orch()
    environ_out = out.get("environ", {})

    total_carbon  = environ_out.get("total_carbon_kg",   df["Carbon_Emissions_kg"].sum())
    total_penalty = environ_out.get("total_penalty_usd", df["Carbon_Cost_Penalty_USD"].sum())
    peak_penalty  = environ_out.get("peak_penalty_usd",  df[df["Grid_Pricing_Period"]=="Peak"]["Carbon_Cost_Penalty_USD"].sum())
    peak_pct      = environ_out.get("peak_penalty_pct",  0.0)
    compliant     = environ_out.get("compliance_flag",   True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total CO₂ Emissions",   f"{total_carbon:,.0f} kg")
    c2.metric("Total Carbon Penalty",  f"${total_penalty:,.0f}")
    c3.metric("Peak-Hour Penalty",     f"${peak_penalty:,.0f}")
    c4.metric("Compliance",            "✅ COMPLIANT" if compliant else "⚠️ NON-COMPLIANT")

    # Agent Assessment
    summary = environ_out.get("summary", "Environmentalist agent has not run yet.")
    badge   = COLORS["healthy"] if compliant else COLORS["warning"]
    st.markdown(f"""
    <div style="border-left:5px solid {badge}; padding:14px; background:{COLORS['card_bg']};
                border-radius:0 6px 6px 0; margin:16px 0;">
        <b style="color:{badge};">🌱 Environmentalist Agent Report</b><br/>
        <span style="font-size:14px;">{summary}</span>
    </div>
    """, unsafe_allow_html=True)

    for suggestion in environ_out.get("shift_suggestions", []):
        st.info(f"💡 {suggestion}")

    df['Hour']      = df['Timestamp'].dt.hour
    df['DayOfWeek'] = df['Timestamp'].dt.day_name()

    st.subheader("🔥 Energy Consumption Heatmap")
    heatmap_data = df.groupby(['DayOfWeek', 'Hour'])['Energy_Consumed_kWh'].mean().reset_index()
    fig_heat = px.density_heatmap(
        heatmap_data, x='Hour', y='DayOfWeek', z='Energy_Consumed_kWh',
        title="Avg Energy Usage (kWh) by Hour & Day",
        color_continuous_scale="Viridis",
        category_orders={"DayOfWeek": ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]}
    )
    fig_heat.add_vrect(x0=14, x1=20, fillcolor="red", opacity=0.15,
                       line_width=0, annotation_text="Peak Pricing")
    fig_heat.update_layout(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE")
    st.plotly_chart(fig_heat, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        fac_carbon = df.groupby("Assigned_Facility")["Carbon_Emissions_kg"].sum().reset_index()
        fig_fac = px.bar(fac_carbon, x="Carbon_Emissions_kg", y="Assigned_Facility",
                         orientation="h", title="Emissions by Facility", color="Carbon_Emissions_kg",
                         color_continuous_scale="Reds")
        fig_fac.update_layout(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE")
        st.plotly_chart(fig_fac, use_container_width=True)
    with c2:
        prod_carbon = df.groupby("Product_Category")["Carbon_Emissions_kg"].sum().reset_index()
        fig_prod = px.pie(prod_carbon, names="Product_Category", values="Carbon_Emissions_kg",
                          hole=0.4, title="Emissions by Product")
        st.plotly_chart(fig_prod, use_container_width=True)

    est_savings = environ_out.get("estimated_savings_usd", peak_penalty * 0.3)
    if est_savings > 0:
        st.info(
            f"💡 **Shift Optimisation Potential:** Moving Peak-hour batches to Off-Peak "
            f"could save approximately **${est_savings:,.0f}** in carbon penalties."
        )


# ==========================================
# 📊 PAGE 9: NLP INTERFACE
# ==========================================
def render_nl_interface():
    st.title("💬 Natural Language Interface")
    st.markdown("Ask the Agentic System questions or give commands in plain English.")

    out = orch()
    if "nlp_history" not in st.session_state:
        st.session_state["nlp_history"] = []

    for msg in st.session_state["nlp_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("meta"):
                st.caption(msg["meta"])

    if query := st.chat_input("Ask anything or give a command..."):
        st.session_state["nlp_history"].append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        # Build context
        finance_health = out.get("finance", {}).get("health_score", "?")
        forecast_qty   = out.get("forecast", {}).get("forecast_qty", "?")
        final_status   = out.get("final_status", "?")
        crit_facs      = out.get("mechanic", {}).get("critical_facilities", [])
        n_conflicts    = len(out.get("conflicts", []))

        system_context = (
            f"Current production system state:\n"
            f"- Orchestrator status: {final_status}\n"
            f"- Demand forecast (7-day): {forecast_qty} units\n"
            f"- Finance health: {finance_health}/100\n"
            f"- Critical facilities: {crit_facs or 'None'}\n"
            f"- Active conflicts: {n_conflicts}\n"
        )

        try:
            resp = httpx.post(
                config.OLLAMA_URL,
                json={
                    "model":  config.OLLAMA_MODEL,
                    "prompt": (
                        f"You are the Orchestrator AI for a global electronics factory.\n\n"
                        f"{system_context}\n"
                        f"User: {query}\n\n"
                        "Respond clearly and concisely. If the user asks about a specific agent "
                        "or metric, reference the data above. If they want to simulate a change, "
                        "tell them which page to use."
                    ),
                    "stream": False,
                },
                timeout=config.OLLAMA_TIMEOUT,
            )
            answer = resp.json().get("response", "").strip() or "I couldn't generate a response."
            agent_label = "Orchestrator Agent"
        except Exception:
            # Rule-based fallback
            q = query.lower()
            if "delay" in q or "late" in q:
                delayed = df[df['Schedule_Status']=='Delayed']
                answer  = f"There are currently {len(delayed)} delayed events. Most are due to capacity overflows or machine maintenance rerouting."
                agent_label = "Orchestrator Agent (fallback)"
            elif "fail" in q or "machine" in q or "ttf" in q:
                worst_ttf = df['Predicted_Time_To_Failure_Hrs'].min()
                answer = f"Most at-risk machine has Predicted TTF of {worst_ttf:.1f} hours. Check Machine Health page."
                agent_label = "Mechanic Agent (fallback)"
            elif "carbon" in q or "energy" in q:
                answer = f"Tracking {df['Carbon_Emissions_kg'].sum():,.0f} kg CO₂ total. Peak-hour penalties are ${df[df['Grid_Pricing_Period']=='Peak']['Carbon_Cost_Penalty_USD'].sum():,.0f}."
                agent_label = "Environmentalist (fallback)"
            elif "inventory" in q or "stock" in q:
                answer = f"Minimum inventory: {df['Raw_Material_Inventory_Units'].min():,} units. Check Inventory page for lead time analysis."
                agent_label = "Buyer Agent (fallback)"
            elif "demand" in q or "forecast" in q:
                answer = f"Demand forecast for next 7 days: {out.get('forecast', {}).get('forecast_qty', '?')} units."
                agent_label = "Forecaster Agent (fallback)"
            else:
                answer = f"System status: {final_status}. Finance health: {finance_health}/100. Ask about delays, inventory, carbon, or machine health."
                agent_label = "Orchestrator Agent (fallback)"

        with st.chat_message("assistant"):
            st.markdown(answer)
            st.caption(f"Agent: {agent_label}")
        st.session_state["nlp_history"].append({
            "role": "assistant",
            "content": answer,
            "meta": f"Agent: {agent_label}",
        })

        if len(st.session_state["nlp_history"]) > config.NLP.get("history_limit", 20) * 2:
            st.session_state["nlp_history"] = st.session_state["nlp_history"][-40:]

    # Department Heads Panel
    st.markdown("---")
    st.subheader("📋 Pending Human Approvals by Department")
    try:
        from hitl.manager import HitlManager
        counts = HitlManager().get_counts()
        heads  = [
            ("Operations Head",     "ops",         counts.get("ops", 0)),
            ("Supply Chain Head",   "procurement",  counts.get("procurement", 0)),
            ("CFO",                 "finance",      counts.get("finance", 0)),
            ("Plant Manager",       "maintenance",  counts.get("maintenance", 0)),
            ("Sustainability Head", "carbon",       counts.get("carbon", 0)),
        ]
        hcols = st.columns(len(heads))
        for i, (head, itype, cnt) in enumerate(heads):
            color = COLORS["critical"] if cnt > 2 else COLORS["warning"] if cnt > 0 else COLORS["healthy"]
            with hcols[i]:
                st.markdown(f"""
                <div style="text-align:center; border:1px solid #333; border-radius:6px;
                            padding:12px; background:{COLORS['card_bg']};">
                    <div style="font-size:22px; color:{color}; font-weight:bold;">{cnt}</div>
                    <div style="font-size:11px; color:#aaa;">{head}</div>
                    <div style="font-size:11px; color:#666;">{itype}</div>
                </div>
                """, unsafe_allow_html=True)
    except Exception as e:
        st.info("HITL counts unavailable.")


# ==========================================
# 📊 PAGE 10: HITL INBOX
# ==========================================
def render_hitl_inbox():
    st.title("📥 HITL Inbox — Human Approval Center")
    st.markdown("Every AI agent reports here. Review and approve or reject pending decisions.")

    try:
        from hitl.manager import HitlManager
        hm     = HitlManager()
        counts = hm.get_counts()
    except Exception as e:
        st.error(f"Could not connect to HITL manager: {e}")
        return

    total = counts.get("total", 0)
    if total == 0:
        st.success("✅ All agents are operating within approved parameters. No human review required.")
    else:
        st.warning(f"⚠️ {total} item(s) awaiting your review.")

    DEPT_TABS = [
        ("⚙️ Operations",       "ops",         "Orchestrator / Scheduler"),
        ("📦 Procurement",      "procurement",  "Buyer Agent"),
        ("💰 Finance",          "finance",      "Finance Agent"),
        ("🔧 Engineering",      "maintenance",  "Mechanic Agent"),
        ("🌱 Sustainability",   "carbon",       "Environmentalist Agent"),
    ]

    tabs = st.tabs([f"{label} ({counts.get(itype,0)})" for label, itype, _ in DEPT_TABS])

    for tab, (label, itype, source) in zip(tabs, DEPT_TABS):
        with tab:
            pending = hm.get_pending(item_type=itype)
            if not pending:
                st.success(f"✅ No pending {label.split()[-1]} items.")
            else:
                for item in pending:
                    payload  = item.get("payload", {})
                    created  = item.get("created_at", "")[:19]
                    item_id  = item["id"]
                    summary  = payload.get("message", payload.get("description", str(payload)[:120]))
                    facility = payload.get("facility", payload.get("plant", "All"))

                    st.markdown(f"""
                    <div style="border:1px solid #333; border-left:4px solid {COLORS['warning']};
                                border-radius:6px; padding:14px; background:{COLORS['card_bg']};
                                margin-bottom:12px;">
                        <b>{itype.upper()} — Item #{item_id}</b>
                        &nbsp;|&nbsp; Source: {item.get('source', source)}
                        &nbsp;|&nbsp; <span style="color:#888;">Submitted: {created}</span>
                        &nbsp;|&nbsp; Facility: {facility}
                        <br/><span style="font-size:13px; margin-top:6px; display:block;">{summary}</span>
                    </div>
                    """, unsafe_allow_html=True)

                    with st.expander(f"📂 Full Details — Item #{item_id}"):
                        st.json(payload)

                    ac1, ac2, ac3 = st.columns([2, 2, 3])
                    with ac3:
                        comment = st.text_input("Comment", key=f"comment_{item_id}", label_visibility="collapsed",
                                                placeholder="Add a comment (optional)")
                    with ac1:
                        if st.button(f"✅ Approve #{item_id}", key=f"approve_{item_id}", type="primary"):
                            if hm.approve(item_id, comment or "Approved", "Human Head"):
                                st.success(f"Item #{item_id} approved.")
                                st.rerun()
                    with ac2:
                        if st.button(f"❌ Reject #{item_id}", key=f"reject_{item_id}"):
                            if hm.reject(item_id, comment or "Rejected", "Human Head"):
                                st.warning(f"Item #{item_id} rejected.")
                                st.rerun()

            # Resolved history
            history = hm.get_history(limit=10, item_type=itype)
            if history:
                with st.expander("📜 Resolved History"):
                    hist_rows = [{
                        "ID": h["id"], "Status": h["status"].upper(),
                        "Resolved By": h.get("resolved_by",""),
                        "Comment": (h.get("comment","") or "")[:60],
                        "Resolved At": (h.get("resolved_at","") or "")[:19],
                    } for h in history]
                    st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)


# ==========================================
# 🔄 MAIN LOOP & NAVIGATION
# ==========================================
def main():

    # ── Sidebar ──────────────────────────────────────────────────────────────
    st.sidebar.title("🏭 Production System")
    st.sidebar.markdown("---")

    # Ollama Status
    ollama_ok = check_ollama()
    ollama_dot = f"<span style='color:{'#00C896' if ollama_ok else '#FF4C4C'};'>●</span>"
    ollama_txt = f"Ollama: **{'Online' if ollama_ok else 'Offline'}** — {config.OLLAMA_MODEL}"
    st.sidebar.markdown(f"{ollama_dot} {ollama_txt}", unsafe_allow_html=True)

    # HITL Badge
    try:
        from hitl.manager import HitlManager
        htl_count = HitlManager().pending_count()
        if htl_count > 0:
            st.sidebar.warning(f"📥 {htl_count} item(s) awaiting approval in HITL Inbox")
    except Exception:
        pass

    st.sidebar.markdown("---")

    # Pages
    pages = {
        "📊 Command Center":         render_command_center,
        "📈 Demand Intelligence":    render_demand_intelligence,
        "📦 Inventory & Logistics":  render_inventory,
        "🗓️ Production Plan":        render_production_schedule,
        "🔧 Machine Health":         render_machine_health,
        "🧬 Digital Twin":           render_digital_twin,
        "🌱 Carbon & Energy":        render_carbon_dashboard,
        "💬 NLP Interface":          render_nl_interface,
        "📥 HITL Inbox":             render_hitl_inbox,
    }
    selection = st.sidebar.radio("Navigate", list(pages.keys()))

    st.sidebar.markdown("---")
    st.sidebar.subheader("⏱️ Simulation Controls")
    st.sidebar.markdown(f"**Time:** `{current_time.strftime('%Y-%m-%d %H:00')}`")
    st.sidebar.markdown(f"**Events:** `{st.session_state.time_cursor:,}` / `{len(df_full):,}`")

    step_size = st.sidebar.slider("Step Size (events/tick)", 1, 100, 10)
    sc1, sc2 = st.sidebar.columns(2)

    if sc1.button("⏭️ Next Tick"):
        advance_time(step_size)
        st.rerun()
    if sc2.button("⏩ +500"):
        advance_time(500)
        st.rerun()

    if st.sidebar.button("🤖 Trigger Agents Now"):
        run_orchestrator(force=True)
        st.rerun()

    if st.sidebar.button("↺ Reset"):
        st.session_state.time_cursor = min(100, len(df_full))
        st.session_state["orch_output"] = None
        st.session_state["orch_cursor"] = -1
        st.session_state["nlp_history"] = []
        st.session_state["dt_chat_history"] = []
        st.session_state["dt_scenarios"] = {}
        try:
            conn = sqlite3.connect(config.DB_PATH)
            conn.execute("DELETE FROM agent_events;")
            conn.commit()
            conn.close()
        except Exception:
            pass
        st.rerun()

    # ── Render selected page ─────────────────────────────────────────────────
    pages[selection]()


if __name__ == "__main__":
    main()
