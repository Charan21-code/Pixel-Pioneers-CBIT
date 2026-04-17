"""
pages/02_Demand_Intelligence.py — Demand Intelligence (Forecaster Agent)
Phase 3: Full implementation.
  - Agent narrative card with risk badge + R² confidence
  - Main forecast chart: historical actual (blue), historical forecast (grey-dash),
    7-day ML projection (orange) with shaded confidence band
  - Tabs: By Product (6 mini charts each with projection line) | By Region (donut + table)
  - Anomaly alert table (>30% over forecast)
  - Recommended Action box (from Ollama / agent)
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
import config

# ── Colour palette (falls back if app.py hasn't set session_state colours) ──
COLORS = st.session_state.get("_COLORS", {
    "healthy":  "#00C896",
    "warning":  "#FFA500",
    "critical": "#FF4C4C",
    "info":     "#4A9EFF",
    "card_bg":  "#1E1E2E",
    "purple":   "#A78BFA",
})

df           = st.session_state.get("_df", pd.DataFrame())
current_time = st.session_state.get("_current_time", pd.Timestamp.now())

PLOT_THEME = dict(
    plot_bgcolor="#0E1117",
    paper_bgcolor="#0E1117",
    font_color="#EEE",
    legend=dict(bgcolor="#0E1117", bordercolor="#333", borderwidth=1),
)


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


# ── Page header ──────────────────────────────────────────────────────────────
st.title("📈 Demand Intelligence")
st.markdown("Machine-learning demand forecasting, anomaly detection, and product/region breakdown.")

if df.empty:
    st.warning("⚠️ No production data loaded yet. Advance the simulation clock from the sidebar.")
    st.stop()

out          = orch()
forecast_out = out.get("forecast", {})

# ── KPI metrics row ──────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
k1.metric("7-Day Forecast (units)",  f"{forecast_out.get('forecast_qty', 0):,}")
k2.metric("Trend Slope",             f"{forecast_out.get('trend_slope', 0):+.1f} units/day")
k3.metric("R² Confidence",           f"{forecast_out.get('r_squared', 0)*100:.1f}%")
k4.metric("Spike Anomalies Detected", forecast_out.get("anomaly_count", 0))

st.markdown("---")

# ── Agent Narrative Banner ───────────────────────────────────────────────────
risk_level  = forecast_out.get("risk_level", "low")
summary     = forecast_out.get("summary", "Run the agents (Next Tick) to generate a demand forecast.")
r2          = forecast_out.get("r_squared", 0.0)

badge_color = (
    COLORS["critical"] if risk_level == "high"   else
    COLORS["warning"]  if risk_level == "medium" else
    COLORS["healthy"]
)
risk_icon   = "🔴" if risk_level == "high" else "🟡" if risk_level == "medium" else "🟢"

st.markdown(f"""
<div style="border:1px solid {badge_color}44; border-left:6px solid {badge_color};
            border-radius:8px; padding:18px 20px; background:{COLORS['card_bg']}; margin-bottom:8px;">
    <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:10px;">
        <span style="font-size:16px; font-weight:700; color:{badge_color};">
            {risk_icon} DEMAND RISK: {risk_level.upper()}
        </span>
        <span style="background:{badge_color}22; color:{badge_color}; border:1px solid {badge_color}55;
                     border-radius:20px; padding:2px 12px; font-size:13px; font-weight:600;">
            R² Confidence: {r2*100:.1f}%
        </span>
    </div>
    <div style="font-size:14px; color:#CCC; line-height:1.7;">
        {summary}
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Main Forecast Chart ───────────────────────────────────────────────────────
st.subheader("📊 Forecast vs Actual + 7-Day ML Projection")

# Resample to daily
daily = (
    df.set_index("Timestamp")
    .resample("D")
    .agg({"Forecasted_Demand": "sum", "Actual_Order_Qty": "sum"})
    .reset_index()
)

# Build ML projection with confidence band (±1 std of residuals)
has_ml    = False
proj_df   = pd.DataFrame()
upper_df  = pd.DataFrame()
lower_df  = pd.DataFrame()

try:
    from sklearn.linear_model import LinearRegression

    last14 = daily.tail(14).copy()
    if len(last14) >= 4:
        X     = np.arange(len(last14)).reshape(-1, 1)
        y     = last14["Actual_Order_Qty"].values
        model = LinearRegression().fit(X, y)

        # Residual std for confidence band
        y_pred    = model.predict(X)
        residuals = y - y_pred
        std_err   = np.std(residuals)

        proj_X     = np.arange(len(last14), len(last14) + 7).reshape(-1, 1)
        proj_y     = model.predict(proj_X)
        proj_dates = [daily["Timestamp"].max() + timedelta(days=i + 1) for i in range(7)]

        proj_df  = pd.DataFrame({"Timestamp": proj_dates, "ML_Projection": proj_y})
        upper_df = pd.DataFrame({"Timestamp": proj_dates, "Upper": proj_y + 1.5 * std_err})
        lower_df = pd.DataFrame({"Timestamp": proj_dates, "Lower": np.clip(proj_y - 1.5 * std_err, 0, None)})
        has_ml   = True
except Exception:
    pass

fig = go.Figure()

# Actual orders (solid blue)
fig.add_trace(go.Scatter(
    x=daily["Timestamp"], y=daily["Actual_Order_Qty"],
    name="Actual Orders", mode="lines",
    line=dict(color=COLORS["info"], width=2.5),
))

# Historical forecast (dashed grey)
fig.add_trace(go.Scatter(
    x=daily["Timestamp"], y=daily["Forecasted_Demand"],
    name="Forecasted Demand", mode="lines",
    line=dict(color="#888", width=1.5, dash="dash"),
    opacity=0.7,
))

if has_ml and not proj_df.empty:
    # Confidence band — upper boundary (transparent, no legend)
    fig.add_trace(go.Scatter(
        x=upper_df["Timestamp"], y=upper_df["Upper"],
        name="Confidence Band", mode="lines",
        line=dict(color=COLORS["warning"], width=0),
        showlegend=True,
        hoverinfo="skip",
    ))
    # Confidence band — lower boundary (filled to upper)
    fig.add_trace(go.Scatter(
        x=lower_df["Timestamp"], y=lower_df["Lower"],
        name="Confidence Band Lower", mode="lines",
        line=dict(color=COLORS["warning"], width=0),
        fill="tonexty",
        fillcolor=f"{COLORS['warning']}22",
        showlegend=False,
        hoverinfo="skip",
    ))
    # ML projection line (solid orange)
    fig.add_trace(go.Scatter(
        x=proj_df["Timestamp"], y=proj_df["ML_Projection"],
        name="7-Day ML Projection", mode="lines+markers",
        line=dict(color=COLORS["warning"], width=3, dash="dot"),
        marker=dict(size=6, color=COLORS["warning"]),
    ))

# Vertical divider between historical and projection
if has_ml:
    fig.add_vline(
        x=str(daily["Timestamp"].max()),
        line_dash="dash", line_color="#555", line_width=1,
        annotation_text="Projection →", annotation_position="top right",
        annotation_font_color="#888",
    )

fig.update_layout(
    **PLOT_THEME,
    xaxis_title="Date", yaxis_title="Units",
    height=380,
)
st.plotly_chart(fig, use_container_width=True)

# ── Tabs: By Product | By Region ──────────────────────────────────────────────
st.markdown("---")
tab_prod, tab_region = st.tabs(["📦 By Product", "🌍 By Region"])

with tab_prod:
    st.subheader("Demand by Product Category")

    products = sorted(df["Product_Category"].unique().tolist()) if "Product_Category" in df.columns else []
    if not products:
        st.info("No product category data available.")
    else:
        # 2 rows × 3 cols layout
        cols_per_row = 3
        for row_start in range(0, len(products), cols_per_row):
            row_products = products[row_start: row_start + cols_per_row]
            mini_cols    = st.columns(cols_per_row)
            for col_idx, prod in enumerate(row_products):
                prod_daily = (
                    df[df["Product_Category"] == prod]
                    .set_index("Timestamp")
                    .resample("D")["Actual_Order_Qty"]
                    .sum()
                    .reset_index()
                )
                # Quick per-product projection
                proj_line_dates = []
                proj_line_vals  = []
                try:
                    from sklearn.linear_model import LinearRegression as LR
                    tail_p   = prod_daily.tail(14)
                    if len(tail_p) >= 4:
                        Xp    = np.arange(len(tail_p)).reshape(-1, 1)
                        yp    = tail_p["Actual_Order_Qty"].values
                        mp    = LR().fit(Xp, yp)
                        px_   = np.arange(len(tail_p), len(tail_p) + 7).reshape(-1, 1)
                        py_   = mp.predict(px_)
                        proj_line_dates = [prod_daily["Timestamp"].max() + timedelta(days=i + 1) for i in range(7)]
                        proj_line_vals  = py_.tolist()
                except Exception:
                    pass

                with mini_cols[col_idx]:
                    mini_fig = go.Figure()
                    mini_fig.add_trace(go.Scatter(
                        x=prod_daily["Timestamp"],
                        y=prod_daily["Actual_Order_Qty"],
                        mode="lines", name="Actual",
                        line=dict(color=COLORS["info"], width=1.5),
                        showlegend=False,
                    ))
                    if proj_line_dates:
                        mini_fig.add_trace(go.Scatter(
                            x=proj_line_dates, y=proj_line_vals,
                            mode="lines", name="Proj",
                            line=dict(color=COLORS["warning"], width=1.5, dash="dot"),
                            showlegend=False,
                        ))
                    mini_fig.update_layout(
                        **PLOT_THEME,
                        title=dict(text=prod[:28], font=dict(size=12, color="#CCC")),
                        height=180,
                        margin=dict(t=30, b=10, l=10, r=10),
                        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
                        yaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=9)),
                    )
                    st.plotly_chart(mini_fig, use_container_width=True)

with tab_region:
    st.subheader("Demand Share by Region")

    region_col = "Region" if "Region" in df.columns else None
    if region_col is None:
        st.info("No region data in current dataset.")
    else:
        region_demand = df.groupby(region_col)["Actual_Order_Qty"].sum().reset_index()
        region_demand["Share %"] = (
            region_demand["Actual_Order_Qty"] / region_demand["Actual_Order_Qty"].sum() * 100
        ).round(1)
        region_demand = region_demand.sort_values("Share %", ascending=False)

        fig_pie = go.Figure(go.Pie(
            labels=region_demand[region_col],
            values=region_demand["Actual_Order_Qty"],
            hole=0.45,
            textinfo="label+percent",
            marker=dict(colors=px.colors.qualitative.Pastel),
            hovertemplate="<b>%{label}</b><br>%{value:,} units<br>%{percent}<extra></extra>",
        ))
        fig_pie.update_layout(
            **PLOT_THEME,
            showlegend=False,
            height=340,
            margin=dict(t=10, b=10, l=10, r=10),
        )

        c_pie, c_tbl = st.columns([1, 1])
        with c_pie:
            st.plotly_chart(fig_pie, use_container_width=True)
        with c_tbl:
            disp = region_demand[[region_col, "Actual_Order_Qty", "Share %"]].copy()
            disp.columns = ["Region", "Total Orders", "Share %"]
            disp["Total Orders"] = disp["Total Orders"].apply(lambda x: f"{x:,}")
            disp["Share %"]      = disp["Share %"].apply(lambda x: f"{x:.1f}%")
            st.dataframe(disp, use_container_width=True, hide_index=True)

# ── Anomaly Alert Table ────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("⚠️ Demand Spike Anomalies (>30% over forecast)")

spike_threshold = 1 + config.AGENT["demand_spike_pct"]
anomalies = df[df["Actual_Order_Qty"] > df["Forecasted_Demand"] * spike_threshold].copy()

if not anomalies.empty:
    anomalies["Spike %"] = (
        (anomalies["Actual_Order_Qty"] / anomalies["Forecasted_Demand"] - 1) * 100
    ).round(1)

    # Select display columns (graceful if some are missing)
    display_cols = []
    for col in ["Timestamp", "Order_ID", "Product_Category", "Region",
                "Assigned_Facility", "Forecasted_Demand", "Actual_Order_Qty", "Spike %"]:
        if col in anomalies.columns:
            display_cols.append(col)

    disp_anoms = anomalies[display_cols].tail(50).copy()
    # Rename for display
    disp_anoms.rename(columns={
        "Product_Category":  "Product",
        "Assigned_Facility": "Facility",
        "Forecasted_Demand": "Forecast",
        "Actual_Order_Qty":  "Actual",
    }, inplace=True)

    # Summary metrics
    a1, a2, a3 = st.columns(3)
    a1.metric("🚨 Total Spike Events",   len(anomalies))
    a2.metric("📈 Max Spike %",          f"{anomalies['Spike %'].max():.1f}%")
    a3.metric("💥 Avg Spike % (excess)", f"{anomalies['Spike %'].mean():.1f}%")

    st.dataframe(
        disp_anoms.sort_values("Spike %", ascending=False),
        use_container_width=True, hide_index=True,
    )

    st.error(
        f"🚨 **{len(anomalies)} demand spike anomaly(ies)** detected in the current data window. "
        f"Largest spike: **{anomalies['Spike %'].max():.1f}%** over forecast — "
        f"immediate review recommended."
    )
else:
    st.success("✅ No significant demand anomalies detected in the current data window.")

# ── Recommended Action ─────────────────────────────────────────────────────────
recommended_action = forecast_out.get("recommended_action", "")
if recommended_action:
    st.markdown("---")
    st.markdown(f"""
<div style="border:1px solid {COLORS['healthy']}55; border-left:5px solid {COLORS['healthy']};
            border-radius:8px; padding:14px 18px; background:#0D2B22;">
    <b style="color:{COLORS['healthy']}; font-size:14px;">💡 Recommended Action</b><br/>
    <span style="font-size:13px; color:#CCC;">{recommended_action}</span>
</div>
""", unsafe_allow_html=True)
