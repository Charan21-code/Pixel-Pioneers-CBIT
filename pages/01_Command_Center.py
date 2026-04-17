"""
pages/01_Command_Center.py — Command Center (Phase 2 / Phase 6 refactor)

Single-glance system overview:
  - Orchestrator status banner (ALL_OK / NEEDS_HITL / BLOCKED)
  - KPI row: On-Time Delivery, Active Alerts, Carbon Penalty, Min Inventory, Workforce
  - Plant overview grid: 5 plant cards with OEE, risk, inventory, plan status
  - Agent health grid: 6 agent cards with one-line summaries
  - Active conflict list
  - Live agent activity log (last 50 rows from agent_events)

All data is read from st.session_state populated by app.py.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

import config
from dashboard_runtime import bootstrap_page, render_ollama_fallback_notice
from hitl.manager import HitlManager

bootstrap_page("Command Center", "🏭")

# ── Theme ─────────────────────────────────────────────────────────────────────
COLORS = st.session_state.get("_COLORS", {
    "healthy":    "#00C896",
    "warning":    "#FFA500",
    "critical":   "#FF4C4C",
    "info":       "#4A9EFF",
    "background": "#0E1117",
    "card_bg":    "#1E1E2E",
    "border":     "#2E2E4E",
    "accent":     "#7C3AED",
})
STATUS_COLORS = st.session_state.get("_STATUS_COLORS", {
    "ALL_OK":     "#00C896",
    "NEEDS_HITL": "#FFA500",
    "BLOCKED":    "#FF4C4C",
})
STATUS_ICONS = st.session_state.get("_STATUS_ICONS", {
    "ALL_OK":     "🟢",
    "NEEDS_HITL": "🟡",
    "BLOCKED":    "🔴",
})

# ── Data from session_state ────────────────────────────────────────────────────
df           = st.session_state.get("_df",           pd.DataFrame())
current_time = st.session_state.get("_current_time", pd.Timestamp.now())
_get_log     = st.session_state.get("_get_agent_log")
_sev_color   = st.session_state.get("_severity_color")


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


def _get_agent_log(limit: int = 500) -> pd.DataFrame:
    if _get_log:
        try:
            return _get_log(limit=limit)
        except Exception:
            pass
    return pd.DataFrame(columns=[
        "logged_at", "agent_name", "severity", "order_id",
        "facility", "message", "confidence_pct", "action_taken",
    ])


def _severity_color(val: str) -> str:
    if _sev_color:
        return _sev_color(val)
    if val == "WARNING":
        return f"color:{COLORS['warning']}; font-weight:bold;"
    if val == "CRITICAL":
        return f"color:{COLORS['critical']}; font-weight:bold;"
    return f"color:{COLORS['healthy']}; font-weight:bold;"


def _nav(label: str, page: str, key: str) -> None:
    """Try st.switch_page; fall back to a caption."""
    if st.button(label, key=key):
        try:
            st.switch_page(f"pages/{page}.py")
        except Exception:
            st.info(f"Open '{page.replace('_', ' ')}' in the sidebar.")


# ── Orchestrator output ────────────────────────────────────────────────────────
out          = orch()
final_status = out.get("final_status", "ALL_OK")
health       = out.get("system_health", 0.0)
conflicts    = out.get("conflicts", [])
last_run     = out.get("last_run_at")

banner_color = STATUS_COLORS.get(final_status, COLORS["info"])
banner_icon  = STATUS_ICONS.get(final_status, "⚪")
last_run_str = (
    last_run.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(last_run, pd.Timestamp)
    else "Agents not yet run — click ▶ in the sidebar"
)
banner_text = {
    "ALL_OK":     "ALL SYSTEMS GO — All agents operating within approved parameters",
    "NEEDS_HITL": f"ATTENTION NEEDED — {len(conflicts)} issue(s) require human review",
    "BLOCKED":    f"PRODUCTION BLOCKED — {len(conflicts)} critical conflict(s). HITL review required",
}.get(final_status, "Awaiting first agent run")

# ── Page header ───────────────────────────────────────────────────────────────
st.title("🏭 Command Center")
st.markdown("Real-time oversight of all production facilities and AI agent activities.")
render_ollama_fallback_notice("agent summaries and recommendations")

# ── Orchestrator Status Banner ────────────────────────────────────────────────
st.markdown(f"""
<div style="background:{banner_color}22; border:2px solid {banner_color};
            border-radius:10px; padding:18px 24px; margin-bottom:24px;">
  <span style="font-size:22px; font-weight:bold; color:{banner_color};">
    {banner_icon} &nbsp; {banner_text}
  </span>
  <span style="float:right; color:#888; font-size:13px; margin-top:4px;">
    Last updated: {last_run_str} &nbsp;|&nbsp;
    Health Score: <b style="color:{banner_color};">{health:.0f} / 100</b>
  </span>
</div>
""", unsafe_allow_html=True)

# ── KPI Row ───────────────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)
if not df.empty:
    on_time_pct    = (df["Schedule_Status"] == "On-Time").mean() * 100
    log_df_kpi     = _get_agent_log()
    active_alerts  = int(len(log_df_kpi[log_df_kpi["severity"] != "INFO"])) if not log_df_kpi.empty else 0
    last_24h       = df[df["Timestamp"] >= current_time - timedelta(hours=24)]
    carbon_penalty = float(last_24h["Carbon_Cost_Penalty_USD"].sum()) if not last_24h.empty else 0
    wf_cov         = (df["Workforce_Deployed"].sum() / max(df["Workforce_Required"].sum(), 1)) * 100

    buyer_inv = out.get("buyer_inventory", {})
    min_days  = (
        min(v.get("days_remaining", 0) for v in buyer_inv.values())
        if buyer_inv else 0
    )

    col1.metric("On-Time Delivery",     f"{on_time_pct:.1f}%",  f"{on_time_pct-90:.1f}% vs 90% target")
    col2.metric("Active Alerts",        active_alerts,           delta="cleared" if active_alerts == 0 else None)
    col3.metric("Carbon Penalty (24h)", f"${carbon_penalty:,.0f}")
    col4.metric("Min Inventory Left",   f"{min_days:.1f} days")
    col5.metric("Workforce Coverage",   f"{wf_cov:.1f}%")
else:
    for col in (col1, col2, col3, col4, col5):
        col.metric("—", "—")

st.markdown("---")

# ── Plant Overview Grid ───────────────────────────────────────────────────────
st.subheader("🌐 Plant Status Overview")
st.caption("One card per production facility. Click **View Plan →** to open that plant's detailed production plan.")

facilities = df["Assigned_Facility"].unique().tolist() if not df.empty else []
buyer_inv  = out.get("buyer_inventory", {})
mech_risks = out.get("mechanic", {}).get("facility_risks", {})
sch_plans  = out.get("scheduler", {})

if facilities:
    fcols = st.columns(min(len(facilities), 5))
    for i, fac in enumerate(list(facilities)[:5]):
        fac_df     = df[df["Assigned_Facility"] == fac]
        oee        = fac_df["Machine_OEE_Pct"].mean() if not fac_df.empty else 0.0
        risk_info  = mech_risks.get(fac, {})
        risk_score = risk_info.get("risk_score", 0)
        risk_label = risk_info.get("status", "healthy").upper()
        inv_info   = buyer_inv.get(fac, {})
        inv_status = inv_info.get("status", "healthy")
        inv_days   = inv_info.get("days_remaining", 0)
        plan_info  = sch_plans.get(fac, {})
        plan_thru  = plan_info.get("expected_throughput", 0)

        wf_dep = fac_df["Workforce_Deployed"].sum() if not fac_df.empty else 0
        wf_req = fac_df["Workforce_Required"].sum() if not fac_df.empty else 1
        wf_pct = (wf_dep / max(wf_req, 1)) * 100

        oee_color  = (
            COLORS["healthy"]  if oee >= 90 else
            COLORS["warning"]  if oee >= 80 else
            COLORS["critical"]
        )
        inv_emoji  = (
            "✅" if inv_status == "healthy" else
            "⚠️" if inv_status == "low" else
            "🔴"
        )
        risk_color = (
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
            margin-bottom:8px; min-height:210px;">
  <div style="font-weight:bold; font-size:14px; margin-bottom:4px;">🏭 {fac.split("(")[0].strip()}</div>
  <div style="font-size:10px; color:#666; margin-bottom:10px;">{fac}</div>
  <div style="font-size:12px; color:#aaa; line-height:2.1;">
    OEE: <b style="color:{oee_color};">{oee:.1f}%</b><br/>
    Risk: <b style="color:{risk_color};">{risk_label} ({risk_score:.0f})</b><br/>
    Inventory: <b>{inv_emoji} {inv_status.upper()}</b> ({inv_days:.1f}d)<br/>
    Workforce: <b>{wf_pct:.1f}%</b><br/>
    Plan: <b>{plan_status}</b><br/>
    Throughput: <b>{plan_thru:,} units</b>
  </div>
</div>
""", unsafe_allow_html=True)
            if st.button("View Plan →", key=f"cc_plan_{i}", use_container_width=True):
                st.session_state["selected_plant"] = fac
                try:
                    st.switch_page("pages/04_Production_Plan.py")
                except Exception:
                    st.info("Navigate to 04 Production Plan in the sidebar.")
else:
    st.info("No facility data yet. Use **Trigger Agents Now** in the sidebar.")

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
        "status":  (
            "critical" if mechanic_out.get("critical_facilities") else
            "warning"  if mechanic_out.get("warning_facilities") else "low"
        ),
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
        "status":  (
            "critical" if finance_out.get("health_score", 100) < 30 else
            "warning"  if finance_out.get("health_score", 100) < 60 else "low"
        ),
        "summary": f"Health: {finance_out.get('health_score', 100):.1f}/100",
        "metric":  f"${finance_out.get('budget_status', {}).get('spent_usd', 0):,.0f} spent",
        "page":    "06_Finance_Dashboard",
    },
    {
        "name":    "🗓️ Scheduler",
        "status":  (
            "critical" if final_status == "BLOCKED" else
            "warning"  if final_status == "NEEDS_HITL" else "low"
        ),
        "summary": f"{len(out.get('scheduler', {}))} plant plans generated",
        "metric":  f"System: {final_status}",
        "page":    "04_Production_Plan",
    },
]

grid_cols = st.columns(3)
for i, card in enumerate(agent_cards):
    cval = (
        COLORS["critical"] if card["status"] in ("critical", "high") else
        COLORS["warning"]  if card["status"] in ("warning", "medium") else
        COLORS["healthy"]
    )
    with grid_cols[i % 3]:
        st.markdown(f"""
<div style="border:1px solid #333; border-left:4px solid {cval};
            border-radius:6px; padding:14px; background:{COLORS['card_bg']};
            margin-bottom:12px; min-height:88px;">
  <div style="font-size:15px; font-weight:bold; color:{cval};">{card['name']}</div>
  <div style="font-size:12px; color:#aaa; margin:4px 0;">{card['summary']}</div>
  <div style="font-size:13px; color:#ddd;">{card['metric']}</div>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Active Conflicts ──────────────────────────────────────────────────────────
if conflicts:
    st.subheader(f"⚡ Active Conflicts Detected ({len(conflicts)})")
    for c in conflicts:
        color = COLORS["critical"] if c["severity"] == "CRITICAL" else COLORS["warning"]
        agents_str = ", ".join(c.get("involved_agents", []))
        st.markdown(f"""
<div style="border-left:4px solid {color}; background:{color}11;
            padding:10px 14px; border-radius:0 6px 6px 0; margin-bottom:8px;">
  <b style="color:{color};">[{c['severity']}] {c['type'].replace('_',' ').title()}</b>
  &nbsp;|&nbsp; Agents: {agents_str}
  <br/><span style="font-size:13px;">{c['description']}</span>
  <br/><span style="font-size:12px; color:#aaa;">→ {c.get('action','')}</span>
</div>
""", unsafe_allow_html=True)

    if st.button("📥 Review in HITL Inbox", key="cc_hitl_cta"):
        try:
            st.switch_page("pages/10_HITL_Inbox.py")
        except Exception:
            st.info("Navigate to 10 HITL Inbox in the sidebar.")
else:
    st.success("✅ No cross-agent conflicts detected. All agents are operating within approved parameters.")

st.markdown("---")

# ── Live Agent Activity Log ───────────────────────────────────────────────────
st.subheader("🕵️ Live Agent Activity Log")
st.caption(f"Last {config.DASHBOARD['agent_log_display']} entries from all agents — colour-coded by severity.")

log_df = _get_agent_log(limit=config.DASHBOARD["agent_log_display"])
if not log_df.empty:
    cols_keep = [c for c in ["logged_at", "agent_name", "severity", "facility", "message"] if c in log_df.columns]
    display_df = log_df[cols_keep].head(config.DASHBOARD["agent_log_display"])
    if "severity" in display_df.columns:
        try:
            styled = display_df.style.map(_severity_color, subset=["severity"])
            st.dataframe(styled, use_container_width=True, hide_index=True)
        except Exception:
            st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.dataframe(display_df, use_container_width=True, hide_index=True)
else:
    st.info("No agent activity logged yet. Click **🤖 Trigger Agents Now** in the sidebar to run all agents.")

# ── HITL Pending Badge ────────────────────────────────────────────────────────
try:
    hitl_pending = HitlManager().pending_count()
    if hitl_pending > 0:
        st.markdown("---")
        st.warning(
            f"📥 **{hitl_pending} item(s) are awaiting human review** across all departments."
        )
        if st.button("Open HITL Inbox →", key="cc_hitl_open"):
            try:
                st.switch_page("pages/10_HITL_Inbox.py")
            except Exception:
                st.info("Navigate to 10 HITL Inbox in the sidebar.")
except Exception:
    pass
