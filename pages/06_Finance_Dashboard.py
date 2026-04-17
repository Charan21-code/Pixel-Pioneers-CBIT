"""
pages/06_Finance_Dashboard.py — Finance Dashboard (Finance Agent)
Phase 2: Budget gauge, finance gate status, cost breakdown chart,
         risk score with actionable suggestions, approval history, HITL escalate.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import config

COLORS = st.session_state.get("_COLORS", {
    "healthy": "#00C896", "warning": "#FFA500", "critical": "#FF4C4C",
    "info": "#4A9EFF", "card_bg": "#1E1E2E",
})

df           = st.session_state.get("_df", pd.DataFrame())
current_time = st.session_state.get("_current_time", pd.Timestamp.now())


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


st.title("💰 Finance Dashboard (Finance Agent)")
st.markdown("Budget utilisation, gate decisions, risk scoring, and cost-reduction suggestions.")

if df.empty:
    st.warning("No data available.")
    st.stop()

out         = orch()
finance_out = out.get("finance", {})

budget_status = finance_out.get("budget_status", {})
monthly_budget = config.FINANCE["monthly_budget"]
spent_usd      = budget_status.get("spent_usd", df["Live_Supplier_Quote_USD"].sum() + df["Carbon_Cost_Penalty_USD"].sum())
remaining_usd  = monthly_budget - spent_usd
pct_used       = min(100, (spent_usd / monthly_budget) * 100) if monthly_budget > 0 else 0
health_score   = finance_out.get("health_score", 100)

# ── Budget Circular Gauge ──────────────────────────────────────────────────────
st.subheader("💵 Monthly Budget Utilisation")

gauge_color = (
    COLORS["critical"] if pct_used > 90 else
    COLORS["warning"]  if pct_used > 70 else
    COLORS["healthy"]
)

fig_gauge = go.Figure(go.Indicator(
    mode="gauge+number+delta",
    value=pct_used,
    number={"suffix": "%", "font": {"size": 36, "color": gauge_color}},
    delta={"reference": 70, "increasing": {"color": COLORS["critical"]},
           "decreasing": {"color": COLORS["healthy"]}},
    title={"text": "Budget Used", "font": {"color": "#EEE"}},
    gauge={
        "axis": {"range": [0, 100], "tickcolor": "#666"},
        "bar":  {"color": gauge_color},
        "steps": [
            {"range": [0, 70],  "color": "#1E3A2F"},
            {"range": [70, 90], "color": "#3A2800"},
            {"range": [90, 100],"color": "#3A0000"},
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

g1, g2, g3 = st.columns([1, 1, 1])
with g1:
    st.plotly_chart(fig_gauge, use_container_width=True)
with g2:
    st.metric("Total Budget",      f"${monthly_budget:,.0f}")
    st.metric("Spent (MTD)",       f"${spent_usd:,.0f}")
    st.metric("Remaining",         f"${remaining_usd:,.0f}",
              delta=f"{100 - pct_used:.1f}% left")
with g3:
    st.metric("Finance Health",    f"{health_score:.1f} / 100")
    proposals  = finance_out.get("proposed_plan_cost", 0)
    overhead   = proposals * config.FINANCE["overhead_multiplier"]
    gate_ok    = (spent_usd + overhead) <= monthly_budget
    gate_label = "✅ APPROVED" if gate_ok else "🔴 BLOCKED"
    gate_color = COLORS["healthy"] if gate_ok else COLORS["critical"]
    st.markdown(
        f"<div style='margin-top:8px; font-size:20px; font-weight:bold; "
        f"color:{gate_color};'>Finance Gate: {gate_label}</div>",
        unsafe_allow_html=True,
    )

# ── Finance Gate Status Block ──────────────────────────────────────────────────
st.markdown("---")
st.subheader("🚦 Finance Gate Status")

total_if_approved = spent_usd + overhead
gate_c = COLORS["healthy"] if gate_ok else COLORS["critical"]

st.markdown(f"""
<div style="border:1px solid {gate_c}55; border-left:5px solid {gate_c};
            border-radius:8px; padding:16px 20px; background:{COLORS['card_bg']}; margin-bottom:20px;">
    <b style="font-size:16px; color:{gate_c};">FINANCE GATE: {gate_label}</b>
    <div style="font-size:13px; color:#aaa; line-height:2.0; margin-top:10px;">
        This month's spend: <b style="color:#fff;">${spent_usd:,.0f} / ${monthly_budget:,.0f}
            ({pct_used:.1f}%)</b><br/>
        Proposed plan cost: <b>${proposals:,.0f}</b><br/>
        Overhead (15%): <b>+ ${overhead - proposals:,.0f}</b><br/>
        Total if approved: <b>${total_if_approved:,.0f}</b>
            (Remaining: <b style="color:{gate_c};">${monthly_budget - total_if_approved:,.0f}</b>)<br/>
        <br/>
        Decision: <b style="color:{gate_c};">{gate_label}
            {"— within budget" if gate_ok else "— budget would be exceeded"}</b>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Cost Breakdown Chart ───────────────────────────────────────────────────────
st.subheader("📊 Cost Breakdown Over Time")

df["_week"] = df["Timestamp"].dt.to_period("W").astype(str)
weekly = df.groupby("_week").agg(
    procurement=("Live_Supplier_Quote_USD", "sum"),
    carbon=("Carbon_Cost_Penalty_USD", "sum"),
).reset_index()

# Labour estimate: Workforce_Deployed × 8hrs × $15/hr assumed rate
labour_rate = 15.0
weekly_labour = df.copy()
weekly_labour["_week"] = weekly_labour["Timestamp"].dt.to_period("W").astype(str)
labour_weekly = (
    weekly_labour.groupby("_week")["Workforce_Deployed"].sum() * 8 * labour_rate
).reset_index(name="labour")
weekly = weekly.merge(labour_weekly, on="_week", how="left").fillna(0)

fig_cost = go.Figure()
fig_cost.add_trace(go.Bar(
    x=weekly["_week"], y=weekly["procurement"],
    name="Procurement",   marker_color=COLORS["info"],
))
fig_cost.add_trace(go.Bar(
    x=weekly["_week"], y=weekly["carbon"],
    name="Carbon Penalties", marker_color=COLORS["warning"],
))
fig_cost.add_trace(go.Bar(
    x=weekly["_week"], y=weekly["labour"],
    name="Labour (est.)", marker_color=COLORS["healthy"],
))
fig_cost.update_layout(
    barmode="stack", plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE",
    xaxis_title="Week", yaxis_title="USD",
    title="Weekly Cost Breakdown (Procurement + Carbon + Labour)",
)
st.plotly_chart(fig_cost, use_container_width=True)

# ── Risk Score + Suggestions ──────────────────────────────────────────────────
st.markdown("---")
st.subheader("🎯 Financial Risk Score")

risk_label_color = (
    COLORS["critical"] if health_score < 40 else
    COLORS["warning"]  if health_score < 70 else
    COLORS["healthy"]
)
risk_category = (
    "HIGH RISK"   if health_score < 40 else
    "MEDIUM RISK" if health_score < 70 else
    "LOW RISK"
)

st.markdown(f"""
<div style="border:1px solid #333; border-radius:8px; padding:16px; background:{COLORS['card_bg']};
            display:inline-block; margin-bottom:16px;">
    <span style="font-size:22px; font-weight:bold; color:{risk_label_color};">
        Financial Risk Score: {100 - health_score:.0f} / 100 — {risk_category}
    </span>
</div>
""", unsafe_allow_html=True)

suggestions = finance_out.get("suggestions", [])
if suggestions:
    st.subheader("💡 Cost Optimisation Suggestions")
    icons = ["🌙", "📦", "🔧", "🔄", "📊", "⚡"]
    for j, sug in enumerate(suggestions):
        icon = icons[j % len(icons)]
        st.markdown(f"""
        <div style="border:1px solid #333; border-left:4px solid {COLORS['info']};
                    border-radius:0 6px 6px 0; padding:12px 16px; background:{COLORS['card_bg']};
                    margin-bottom:8px;">
            <b style="color:{COLORS['info']};">{icon} &nbsp; Suggestion {j+1}</b><br/>
            <span style="font-size:13px;">{sug}</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.info("No cost-reduction suggestions yet. Run agents with more data to generate recommendations.")

# ── Escalate Button ────────────────────────────────────────────────────────────
st.markdown("---")
col_a, col_b = st.columns([1, 3])
with col_a:
    if st.button("🚨 Escalate to Finance Head", key="fin_escalate", type="primary"):
        try:
            from hitl.manager import HitlManager
            HitlManager().enqueue("finance", "Finance", {
                "monthly_spend": spent_usd,
                "budget":        monthly_budget,
                "pct_used":      pct_used,
                "health_score":  health_score,
                "message": (
                    f"Finance escalation: Monthly spend at {pct_used:.1f}% "
                    f"(${spent_usd:,.0f} / ${monthly_budget:,.0f}). "
                    f"Health score: {health_score:.1f}/100."
                ),
            })
            st.success("✅ Escalated to Finance Head via HITL Inbox.")
        except Exception as e:
            st.error(f"HITL submission failed: {e}")

# ── Finance Agent Narrative ────────────────────────────────────────────────────
fin_summary = finance_out.get("summary", "")
if fin_summary:
    with st.expander("🤖 Finance Agent Narrative"):
        st.info(fin_summary)

# ── Download ───────────────────────────────────────────────────────────────────
csv = weekly.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Download Cost Breakdown CSV",
    data=csv,
    file_name="cost_breakdown.csv",
    mime="text/csv",
    key="fin_dl",
)
