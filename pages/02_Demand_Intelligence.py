"""
pages/02_Demand_Intelligence.py — Demand Intelligence (Forecaster Agent)
Phase 2: Ported from app.py with enhanced ML forecast chart and product/region tabs.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
import config

COLORS = st.session_state.get("_COLORS", {
    "healthy": "#00C896", "warning": "#FFA500", "critical": "#FF4C4C",
    "info": "#4A9EFF", "card_bg": "#1E1E2E",
})

df           = st.session_state.get("_df", pd.DataFrame())
current_time = st.session_state.get("_current_time", pd.Timestamp.now())


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


st.title("📈 Demand Intelligence (Forecaster Agent)")
st.markdown("Machine-learning demand forecasting, anomaly detection, and product/region breakdown.")

if df.empty:
    st.warning("No data available.")
    st.stop()

out          = orch()
forecast_out = out.get("forecast", {})

# ── Agent Narrative ────────────────────────────────────────────────────────────
risk_level = forecast_out.get("risk_level", "low")
summary    = forecast_out.get("summary", "Forecaster agent has not run yet.")
r2         = forecast_out.get("r_squared", 0.0)
badge_color = (
    COLORS["critical"] if risk_level == "high" else
    COLORS["warning"]  if risk_level == "medium" else
    COLORS["healthy"]
)

st.markdown(f"""
<div style="border:1px solid {badge_color}; border-left:6px solid {badge_color};
            border-radius:8px; padding:16px; background:{COLORS['card_bg']}; margin-bottom:16px;">
    <b style="color:{badge_color}; font-size:15px;">DEMAND RISK: {risk_level.upper()}</b>
    &nbsp;|&nbsp; Forecast Confidence (R²): <b>{r2*100:.1f}%</b><br/>
    <span style="font-size:14px; margin-top:6px; display:block;">{summary}</span>
</div>
""", unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
c1.metric("7-Day Forecast (units)", f"{forecast_out.get('forecast_qty', 0):,}")
c2.metric("Trend Slope",            f"{forecast_out.get('trend_slope', 0):+.1f} units/day")
c3.metric("Demand Spike Anomalies", forecast_out.get("anomaly_count", 0))

st.markdown("---")

# ── Main Forecast Chart (historical + ML projection) ──────────────────────────
st.subheader("📊 Demand Trend: Forecast vs Actual + 7-Day ML Projection")

daily = (
    df.set_index("Timestamp")
    .resample("D")
    .agg({"Forecasted_Demand": "sum", "Actual_Order_Qty": "sum"})
    .reset_index()
)

# Build ML projection using linear regression on last 14 days
try:
    from sklearn.linear_model import LinearRegression
    last14 = daily.tail(14).copy()
    X      = np.arange(len(last14)).reshape(-1, 1)
    y      = last14["Actual_Order_Qty"].values
    model  = LinearRegression().fit(X, y)
    proj_X = np.arange(len(last14), len(last14) + 7).reshape(-1, 1)
    proj_y = model.predict(proj_X)
    proj_dates = [daily["Timestamp"].max() + timedelta(days=i + 1) for i in range(7)]
    proj_df = pd.DataFrame({"Timestamp": proj_dates, "ML_Projection": proj_y})
    has_ml  = True
except ImportError:
    has_ml  = False
    proj_df = pd.DataFrame()

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=daily["Timestamp"], y=daily["Actual_Order_Qty"],
    name="Actual Orders", mode="lines",
    line=dict(color=COLORS["info"], width=2),
))
fig.add_trace(go.Scatter(
    x=daily["Timestamp"], y=daily["Forecasted_Demand"],
    name="Forecasted Demand", mode="lines",
    line=dict(color="#888", width=1.5, dash="dash"),
))
if has_ml and not proj_df.empty:
    fig.add_trace(go.Scatter(
        x=proj_df["Timestamp"], y=proj_df["ML_Projection"],
        name="7-Day ML Projection", mode="lines",
        line=dict(color=COLORS["warning"], width=2.5),
        fill="tozeroy", fillcolor=f"{COLORS['warning']}15",
    ))
fig.update_layout(
    plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE",
    xaxis_title="", yaxis_title="Units",
    legend=dict(bgcolor="#0E1117"),
)
st.plotly_chart(fig, use_container_width=True)

# ── Tabs: By Product | By Region ──────────────────────────────────────────────
st.markdown("---")
tab1, tab2 = st.tabs(["📦 By Product", "🌍 By Region"])

with tab1:
    st.subheader("Demand by Product Category")
    products = df["Product_Category"].unique()
    prod_cols = st.columns(min(3, len(products)))
    for i, prod in enumerate(sorted(products)):
        prod_df = (
            df[df["Product_Category"] == prod]
            .set_index("Timestamp")
            .resample("D")["Actual_Order_Qty"]
            .sum()
            .reset_index()
        )
        with prod_cols[i % 3]:
            mini_fig = px.line(
                prod_df, x="Timestamp", y="Actual_Order_Qty",
                title=prod[:30], height=200,
                color_discrete_sequence=[COLORS["info"]],
            )
            mini_fig.update_layout(
                plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE",
                showlegend=False, xaxis_title="", yaxis_title="",
                margin=dict(t=30, b=10, l=10, r=10),
            )
            st.plotly_chart(mini_fig, use_container_width=True)

with tab2:
    st.subheader("Demand Share by Region")
    region_demand = df.groupby("Region")["Actual_Order_Qty"].sum().reset_index()
    fig3 = px.pie(
        region_demand, names="Region", values="Actual_Order_Qty",
        hole=0.4, title="Demand Share by Region",
        color_discrete_sequence=px.colors.qualitative.Pastel,
    )
    fig3.update_layout(paper_bgcolor="#0E1117", font_color="#EEE")
    c_pie, c_tbl = st.columns([1, 1])
    with c_pie:
        st.plotly_chart(fig3, use_container_width=True)
    with c_tbl:
        region_demand["Share %"] = (
            region_demand["Actual_Order_Qty"] / region_demand["Actual_Order_Qty"].sum() * 100
        ).round(1)
        st.dataframe(
            region_demand.sort_values("Share %", ascending=False),
            use_container_width=True, hide_index=True,
        )

# ── Anomaly Alert Table ────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("⚠️ Demand Spike Anomalies (>30% over forecast)")

anomalies = df[df["Actual_Order_Qty"] > df["Forecasted_Demand"] * 1.30].copy()
if not anomalies.empty:
    anomalies["Spike %"] = (
        (anomalies["Actual_Order_Qty"] / anomalies["Forecasted_Demand"] - 1) * 100
    ).round(1)
    disp = anomalies[["Timestamp", "Order_ID", "Product_Category", "Region",
                       "Forecasted_Demand", "Actual_Order_Qty", "Spike %"]].tail(50)
    st.dataframe(disp, use_container_width=True, hide_index=True)
    st.error(f"🚨 {len(anomalies)} spike anomaly(ies) detected in current window.")
else:
    st.success("✅ No significant demand anomalies detected.")

# ── Recommended Action ─────────────────────────────────────────────────────────
if forecast_out.get("recommended_action"):
    st.info(f"💡 **Recommended Action:** {forecast_out['recommended_action']}")
