"""
pages/06_Finance_Dashboard.py — Finance Dashboard (Finance Agent)
Phase 3: Full implementation.
  - Budget circular gauge + 3-column KPI row
  - Finance Gate Status block (with proposed cost + overhead breakdown)
  - Weekly cost breakdown stacked bar chart (Procurement + Carbon + Labour)
  - Financial Risk Score card
  - Actionable Cost Optimisation Suggestions (from Ollama / FinanceAgent)
  - Approval History Table (from monthly_spend DB table)
  - Escalate to Finance Head (HITL)
  - Finance Agent Narrative (from Ollama / FinanceAgent)
  - CSV download
"""

import sqlite3
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import config

# ── Colour palette ────────────────────────────────────────────────────────────
COLORS = st.session_state.get("_COLORS", {
    "healthy":  "#00C896",
    "warning":  "#FFA500",
    "critical": "#FF4C4C",
    "info":     "#4A9EFF",
    "card_bg":  "#1E1E2E",
})

PLOT_THEME = dict(
    plot_bgcolor="#0E1117",
    paper_bgcolor="#0E1117",
    font_color="#EEE",
)

df           = st.session_state.get("_df", pd.DataFrame())
current_time = st.session_state.get("_current_time", pd.Timestamp.now())


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


# ── Page header ───────────────────────────────────────────────────────────────
st.title("💰 Finance Dashboard")
st.markdown("Budget utilisation, gate decisions, risk scoring, and cost-reduction suggestions.")

if df.empty:
    st.warning("⚠️ No production data loaded yet. Advance the simulation clock from the sidebar.")
    st.stop()

out         = orch()
finance_out = out.get("finance", {})

# ── Derive core financial numbers ─────────────────────────────────────────────
monthly_budget    = config.FINANCE["monthly_budget"]
budget_status     = finance_out.get("budget_status", {})

# Fall back to computing from df if agents haven't run yet
spent_usd = budget_status.get("spent_usd")
if spent_usd is None:
    try:
        spent_usd = float(df["Live_Supplier_Quote_USD"].sum() + df["Carbon_Cost_Penalty_USD"].sum())
    except Exception:
        spent_usd = 0.0

remaining_usd     = monthly_budget - spent_usd
pct_used          = min(100.0, (spent_usd / monthly_budget * 100)) if monthly_budget > 0 else 0.0
health_score      = finance_out.get("health_score",      max(0, 100 - pct_used))
risk_score        = finance_out.get("risk_score",         0.0)
gate_decision     = finance_out.get("gate_decision",      "APPROVED")
proposed_cost     = finance_out.get("proposed_plan_cost", 0.0)
overhead_cost     = proposed_cost * config.FINANCE["overhead_multiplier"]
total_if_approved = spent_usd + overhead_cost
gate_ok           = gate_decision == "APPROVED"

# ── Section 1: Budget Gauge + KPIs ─────────────────────────────────────────────
st.subheader("💵 Monthly Budget Utilisation")

gauge_color = (
    COLORS["critical"] if pct_used > 90 else
    COLORS["warning"]  if pct_used > 70 else
    COLORS["healthy"]
)

fig_gauge = go.Figure(go.Indicator(
    mode="gauge+number+delta",
    value=pct_used,
    number={"suffix": "%", "font": {"size": 40, "color": gauge_color}},
    delta={
        "reference": 70,
        "increasing": {"color": COLORS["critical"]},
        "decreasing": {"color": COLORS["healthy"]},
    },
    title={"text": "Budget Used", "font": {"color": "#EEE", "size": 14}},
    gauge={
        "axis":      {"range": [0, 100], "tickcolor": "#555", "tickwidth": 1},
        "bar":       {"color": gauge_color, "thickness": 0.25},
        "bgcolor":   "#1E1E2E",
        "bordercolor": "#333",
        "steps": [
            {"range": [0,  70], "color": "#1A2E20"},
            {"range": [70, 90], "color": "#2E1E08"},
            {"range": [90, 100],"color": "#2E0808"},
        ],
        "threshold": {
            "line": {"color": COLORS["critical"], "width": 3},
            "thickness": 0.85,
            "value": 90,
        },
    },
))
fig_gauge.update_layout(
    paper_bgcolor="#0E1117", font_color="#EEE", height=280,
    margin=dict(t=20, b=20, l=30, r=30),
)

col_gauge, col_kpi1, col_kpi2 = st.columns([1.1, 1, 1])

with col_gauge:
    st.plotly_chart(fig_gauge, use_container_width=True)

with col_kpi1:
    st.metric("💰 Total Budget",    f"${monthly_budget:,.0f}")
    st.metric("📤 Spent (MTD)",     f"${spent_usd:,.0f}",
              delta=f"{pct_used:.1f}% used")
    st.metric("💵 Remaining",       f"${remaining_usd:,.0f}",
              delta=f"{100 - pct_used:.1f}% left")

with col_kpi2:
    st.metric("🏥 Finance Health",  f"{health_score:.1f} / 100")
    st.metric("⚠️ Risk Score",      f"{risk_score:.0f} / 100")
    gate_color = COLORS["healthy"] if gate_ok else COLORS["critical"]
    gate_label = "✅ APPROVED" if gate_ok else "🔴 BLOCKED"
    st.markdown(
        f"<div style='margin-top:8px; font-size:18px; font-weight:bold; "
        f"color:{gate_color};'>Finance Gate: {gate_label}</div>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ── Section 2: Finance Gate Status Block ──────────────────────────────────────
st.subheader("🚦 Finance Gate Status")

gate_c = COLORS["healthy"] if gate_ok else COLORS["critical"]
gate_icon = "✅ APPROVED" if gate_ok else "🔴 BLOCKED"
gate_reason = "within budget" if gate_ok else "would exceed budget"
remaining_after = monthly_budget - total_if_approved

st.markdown(f"""
<div style="border:1px solid {gate_c}44; border-left:6px solid {gate_c};
            border-radius:8px; padding:18px 22px; background:{COLORS['card_bg']}; margin-bottom:20px;">
    <b style="font-size:16px; color:{gate_c};">FINANCE GATE: {gate_icon}</b>
    <div style="font-size:13px; color:#aaa; line-height:2.2; margin-top:12px;">
        This month's spend:
            <b style="color:#fff;">${spent_usd:,.0f} / ${monthly_budget:,.0f}
            ({pct_used:.1f}%)</b><br/>
        Proposed plan cost:
            <b>${proposed_cost:,.0f}</b><br/>
        Overhead ({int((config.FINANCE['overhead_multiplier']-1)*100)}%):
            <b>+ ${overhead_cost - proposed_cost:,.0f}</b><br/>
        Total if approved:
            <b>${total_if_approved:,.0f}</b>
            &nbsp;(Remaining: <b style="color:{gate_c};">${remaining_after:,.0f}</b>)<br/>
        <br/>
        Decision: <b style="color:{gate_c};">{gate_icon} — {gate_reason}</b>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Section 3: Cost Breakdown Chart ──────────────────────────────────────────
st.subheader("📊 Cost Breakdown Over Time")

df["_week"] = df["Timestamp"].dt.to_period("W").astype(str)
weekly      = df.groupby("_week").agg(
    procurement=("Live_Supplier_Quote_USD",  "sum"),
    carbon=     ("Carbon_Cost_Penalty_USD",  "sum"),
).reset_index()

labour_rate = 15.0  # $15/hr assumed
labour_weekly = (
    df.copy()
    .assign(_week=lambda d: d["Timestamp"].dt.to_period("W").astype(str))
    .groupby("_week")["Workforce_Deployed"].sum()
    .mul(8 * labour_rate)
    .reset_index(name="labour")
)
weekly = weekly.merge(labour_weekly, on="_week", how="left").fillna(0)

fig_cost = go.Figure()
fig_cost.add_trace(go.Bar(
    x=weekly["_week"], y=weekly["procurement"],
    name="Procurement",       marker_color=COLORS["info"],
))
fig_cost.add_trace(go.Bar(
    x=weekly["_week"], y=weekly["carbon"],
    name="Carbon Penalties",  marker_color=COLORS["warning"],
))
fig_cost.add_trace(go.Bar(
    x=weekly["_week"], y=weekly["labour"],
    name="Labour (est.)",     marker_color=COLORS["healthy"],
))
fig_cost.update_layout(
    **PLOT_THEME,
    barmode="stack",
    xaxis_title="Week", yaxis_title="USD",
    title="Weekly Cost Breakdown (Procurement + Carbon + Labour)",
    legend=dict(bgcolor="#0E1117", bordercolor="#333", borderwidth=1),
    height=340,
)
st.plotly_chart(fig_cost, use_container_width=True)

st.markdown("---")

# ── Section 4: Financial Risk Score ──────────────────────────────────────────
st.subheader("🎯 Financial Risk Score")

risk_category = (
    "HIGH RISK"   if risk_score > 65 else
    "MEDIUM RISK" if risk_score > 35 else
    "LOW RISK"
)
risk_color = (
    COLORS["critical"] if risk_score > 65 else
    COLORS["warning"]  if risk_score > 35 else
    COLORS["healthy"]
)

# Risk score gauge bar
pct_risk = int(risk_score)
r1, r2 = st.columns([2, 3])
with r1:
    st.markdown(f"""
<div style="border:1px solid #333; border-radius:10px; padding:18px 22px;
            background:{COLORS['card_bg']}; text-align:center;">
    <div style="font-size:42px; font-weight:800; color:{risk_color};">
        {risk_score:.0f}
    </div>
    <div style="font-size:13px; color:#aaa;">out of 100</div>
    <div style="font-size:15px; font-weight:700; color:{risk_color}; margin-top:6px;">
        {risk_category}
    </div>
    <!-- Risk bar -->
    <div style="background:#333; border-radius:6px; height:10px; margin-top:14px;">
        <div style="background:{risk_color}; border-radius:6px; height:10px;
                    width:{pct_risk}%; transition:width 0.4s;"></div>
    </div>
    <div style="font-size:11px; color:#666; margin-top:6px;">
        0 (safe) ──────────── 100 (critical)
    </div>
</div>
""", unsafe_allow_html=True)

with r2:
    st.markdown(f"""
<div style="font-size:13px; color:#aaa; line-height:2.0; padding-top:8px;">
    <b style="color:#CCC;">Risk Score Components:</b><br/>
    🏭 OEE deviation penalty &nbsp; — poor OEE raises rework cost<br/>
    📦 Supply shortage penalty &nbsp; — critical/emergency plants<br/>
    📈 Demand overshoot penalty &nbsp; — spike anomalies detected<br/>
    🌱 Carbon penalty exposure &nbsp; — peak-hour ratio<br/>
    💸 Budget burn rate &nbsp; — spend above 80% threshold<br/>
</div>
""", unsafe_allow_html=True)

# ── Section 5: Cost Optimisation Suggestions ──────────────────────────────────
st.markdown("---")
st.subheader("💡 Cost Optimisation Suggestions")

suggestions = finance_out.get("suggestions", [])
SUGGESTION_ICONS = ["🌙", "📦", "🔧", "🔄", "📊", "⚡", "🏭", "🌱"]

if suggestions:
    for j, sug in enumerate(suggestions):
        icon = SUGGESTION_ICONS[j % len(SUGGESTION_ICONS)]
        # Try to highlight potential savings if mentioned in the text
        st.markdown(f"""
<div style="border:1px solid #333; border-left:5px solid {COLORS['info']};
            border-radius:0 8px 8px 0; padding:14px 18px; background:{COLORS['card_bg']};
            margin-bottom:10px;">
    <b style="color:{COLORS['info']}; font-size:14px;">{icon} &nbsp; Suggestion {j + 1}</b><br/>
    <span style="font-size:13px; color:#CCC; line-height:1.8;">{sug}</span>
</div>
""", unsafe_allow_html=True)
else:
    st.markdown(f"""
<div style="border:1px solid #333; border-radius:8px; padding:16px; background:{COLORS['card_bg']};
            color:#888; text-align:center;">
    💡 Run agents (Next Tick) to generate cost-reduction suggestions from the Finance AI.
</div>
""", unsafe_allow_html=True)

# ── Section 6: Approval History Table ─────────────────────────────────────────
st.markdown("---")
st.subheader("📋 Approved Spend History")

try:
    with sqlite3.connect(config.DB_PATH) as conn:
        spend_df = pd.read_sql(
            "SELECT id, logged_at, amount_usd, description, cleared_by "
            "FROM monthly_spend ORDER BY logged_at DESC LIMIT 50",
            conn,
        )
    if not spend_df.empty:
        spend_df.rename(columns={
            "id":          "#",
            "logged_at":   "Timestamp",
            "amount_usd":  "Amount (USD)",
            "description": "Description",
            "cleared_by":  "Approval Token",
        }, inplace=True)
        spend_df["Amount (USD)"] = spend_df["Amount (USD)"].apply(lambda x: f"${x:,.2f}")
        spend_df["Approval Token"] = spend_df["Approval Token"].apply(
            lambda x: str(x)[:16] + "…" if x and len(str(x)) > 16 else x
        )
        st.dataframe(spend_df, use_container_width=True, hide_index=True)

        total_logged = spend_df.shape[0]
        st.caption(f"Showing last {total_logged} approved spend entries from the database.")
    else:
        st.info("No approved spend entries yet. Procurement approvals will appear here.")
except Exception as e:
    st.warning(f"Could not load approval history: {e}")

# ── Section 7: Escalate Button ────────────────────────────────────────────────
st.markdown("---")
col_esc, col_info = st.columns([1, 3])
with col_esc:
    if st.button("🚨 Escalate to Finance Head", key="fin_escalate", type="primary"):
        try:
            from hitl.manager import HitlManager
            HitlManager().enqueue("finance", "Finance", {
                "monthly_spend":  spent_usd,
                "budget":         monthly_budget,
                "pct_used":       pct_used,
                "health_score":   health_score,
                "risk_score":     risk_score,
                "gate_decision":  gate_decision,
                "message": (
                    f"Finance escalation: Monthly spend at {pct_used:.1f}% "
                    f"(${spent_usd:,.0f} / ${monthly_budget:,.0f}). "
                    f"Health score: {health_score:.1f}/100. "
                    f"Risk score: {risk_score:.0f}/100. "
                    f"Finance gate: {gate_decision}."
                ),
            })
            st.success("✅ Escalated to Finance Head via HITL Inbox.")
        except Exception as e:
            st.error(f"HITL submission failed: {e}")

with col_info:
    st.markdown(
        "<small style='color:#888;'>Escalating notifies the Finance Head via the HITL Inbox "
        "and adds an entry to the approval queue for manual review.</small>",
        unsafe_allow_html=True,
    )

# ── Section 8: Finance Agent Narrative ────────────────────────────────────────
fin_summary = finance_out.get("summary", "")

# Build heuristic fallback if agent hasn't run
if not fin_summary:
    risk_label = "HIGH" if risk_score > 65 else "MEDIUM" if risk_score > 35 else "LOW"
    fin_summary = (
        f"Monthly spend is at **{pct_used:.1f}%** (${spent_usd:,.0f} of ${monthly_budget:,.0f}). "
        f"Finance gate is **{gate_decision}** — proposed plan cost of ${proposed_cost:,.0f} "
        f"{'fits within' if gate_ok else 'exceeds'} the remaining budget. "
        f"Financial risk is **{risk_label}** ({risk_score:.0f}/100); "
        f"{'review cost-optimisation suggestions above.' if suggestions else 'trigger agents to generate suggestions.'}"
    )

if fin_summary:
    st.markdown("---")
    st.subheader("🤖 Finance Agent Narrative")
    st.markdown(f"""
<div style="border:1px solid {COLORS['info']}44; border-left:5px solid {COLORS['info']};
            border-radius:8px; padding:14px 18px; background:#0D1B2A;">
    <span style="font-size:13px; color:#CCC; line-height:1.8;">{fin_summary}</span>
</div>
""", unsafe_allow_html=True)

# ── CSV Download ──────────────────────────────────────────────────────────────
st.markdown("---")
csv = weekly.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Download Weekly Cost Breakdown (CSV)",
    data=csv,
    file_name="cost_breakdown.csv",
    mime="text/csv",
    key="fin_dl",
)
