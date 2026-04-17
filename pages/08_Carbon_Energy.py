"""
pages/08_Carbon_Energy.py — Carbon & Energy Dashboard (Environmentalist Agent)
Phase 4: compliance KPIs, energy heatmap, emissions charts, assessment block,
         and shift timing optimiser.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

import config
from dashboard_runtime import bootstrap_page, render_ollama_fallback_notice

bootstrap_page("Carbon & Energy", "🌱")

COLORS = st.session_state.get("_COLORS", {
    "healthy": "#00C896",
    "warning": "#FFA500",
    "critical": "#FF4C4C",
    "info": "#4A9EFF",
    "card_bg": "#1E1E2E",
})

df = st.session_state.get("_df", pd.DataFrame())


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


st.title("Carbon & Energy Dashboard")
st.markdown("Track peak-hour emissions, compliance risk, and timing changes that reduce carbon penalties.")
render_ollama_fallback_notice("environmental recommendations")

if df.empty:
    st.warning("No data available.")
    st.stop()

out = orch()
environ_out = out.get("environ", {})

total_carbon = environ_out.get("total_carbon_kg", float(df["Carbon_Emissions_kg"].sum()))
total_penalty = environ_out.get("total_penalty_usd", float(df["Carbon_Cost_Penalty_USD"].sum()))
peak_penalty = environ_out.get(
    "peak_penalty_usd",
    float(df[df["Grid_Pricing_Period"] == "Peak"]["Carbon_Cost_Penalty_USD"].sum()),
)
peak_pct = environ_out.get("peak_penalty_pct", 0.0)
compliant = environ_out.get("compliance_flag", True)
compliance_status = environ_out.get("compliance_status", "COMPLIANT" if compliant else "PARTIALLY NON-COMPLIANT")
key_finding = environ_out.get("key_finding", "Environmentalist agent has not produced a hotspot assessment yet.")
recommendation = environ_out.get("recommendation", "No timing change recommendation available.")
summary = environ_out.get("summary", "Environmentalist agent has not run yet.")
hotspot = environ_out.get("hotspot", {})
estimated_savings = environ_out.get("estimated_savings_usd", 0.0)
peak_energy_kwh = environ_out.get("peak_energy_kwh", 0.0)

# ── KPI Cards ─────────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
k1.metric("Total CO2 Emitted", f"{total_carbon:,.0f} kg")
k2.metric("Total Penalty Paid", f"${total_penalty:,.0f}")
k3.metric("Peak-hour Penalty", f"${peak_penalty:,.0f}", delta=f"{peak_pct:.1f}% of total", delta_color="off")
k4.metric("Compliance Status", "Compliant" if compliant else "Attention Needed")

# ── Assessment Block ──────────────────────────────────────────────────────────
badge = COLORS["healthy"] if compliant else COLORS["warning"]
hotspot_label = " / ".join(
    value for value in [hotspot.get("facility"), hotspot.get("product")] if value and value != "N/A"
)
hotspot_line = hotspot_label if hotspot_label else "No dominant hotspot detected"

st.markdown(f"""
<div style="border-left:6px solid {badge}; padding:16px 20px; background:{COLORS['card_bg']};
border-radius:0 8px 8px 0; margin:16px 0;">
<b style="color:{badge}; font-size:15px;">Environmentalist Agent Report</b><br/>
<span style="font-size:13px; color:#bbb;">
Compliance: <b style="color:{badge};">{compliance_status}</b>
&nbsp;|&nbsp; Peak ratio: <b>{peak_pct:.1f}%</b>
&nbsp;|&nbsp; Est. saving: <b>${estimated_savings:,.0f}</b>
</span><br/><br/>
<span style="font-size:13px;"><b>Key finding:</b> {key_finding}</span><br/>
<span style="font-size:13px;"><b>Recommendation:</b> {recommendation}</span><br/>
<span style="font-size:12px; color:#9aa0aa;"><b>Hotspot:</b> {hotspot_line}</span><br/>
<span style="font-size:12px; color:#9aa0aa;">{summary}</span>
</div>
""", unsafe_allow_html=True)

for suggestion in environ_out.get("shift_suggestions", []):
    st.info(suggestion)

# ── Energy Heatmap ─────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("Energy Consumption Heatmap")
st.caption("Average energy by hour and weekday. The red band highlights the peak pricing window (14:00–20:00).")

df_h = df.copy()
df_h["Hour"] = df_h["Timestamp"].dt.hour
df_h["DayOfWeek"] = df_h["Timestamp"].dt.day_name()

heat_data = df_h.groupby(["DayOfWeek", "Hour"])["Energy_Consumed_kWh"].mean().reset_index()
fig_heat = px.density_heatmap(
    heat_data,
    x="Hour",
    y="DayOfWeek",
    z="Energy_Consumed_kWh",
    color_continuous_scale="Viridis",
    category_orders={"DayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]},
)
fig_heat.add_vrect(
    x0=14,
    x1=20,
    fillcolor="red",
    opacity=0.15,
    line_width=0,
    annotation_text="Peak Pricing Zone",
)
fig_heat.update_layout(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE")
st.plotly_chart(fig_heat, use_container_width=True)

# ── Emissions by Facility & Product ───────────────────────────────────────────
st.markdown("---")
c1, c2 = st.columns(2)

with c1:
    st.subheader("Emissions by Facility")
    fac_carbon = (
        df.groupby("Assigned_Facility")["Carbon_Emissions_kg"]
        .sum()
        .reset_index()
        .sort_values("Carbon_Emissions_kg", ascending=True)
    )
    fig_fac = px.bar(
        fac_carbon,
        x="Carbon_Emissions_kg",
        y="Assigned_Facility",
        orientation="h",
        color="Carbon_Emissions_kg",
        color_continuous_scale="Reds",
    )
    fig_fac.update_layout(
        plot_bgcolor="#0E1117",
        paper_bgcolor="#0E1117",
        font_color="#EEE",
        xaxis_title="kg CO2",
        yaxis_title="",
    )
    st.plotly_chart(fig_fac, use_container_width=True)

with c2:
    st.subheader("Emissions by Product")
    prod_carbon = df.groupby("Product_Category")["Carbon_Emissions_kg"].sum().reset_index()
    fig_prod = px.pie(
        prod_carbon,
        names="Product_Category",
        values="Carbon_Emissions_kg",
        hole=0.42,
        color_discrete_sequence=px.colors.qualitative.Set3,
    )
    fig_prod.update_layout(paper_bgcolor="#0E1117", font_color="#EEE")
    st.plotly_chart(fig_prod, use_container_width=True)

# ── Shift Timing Optimiser ─────────────────────────────────────────────────────
st.markdown("---")
st.subheader("Shift Timing Optimiser")
st.caption("Estimate how much peak-hour penalty can be reduced by moving production to off-peak shifts.")

opt_pct = st.slider("% of Peak shifts to move to Off-Peak", 0, 100, 30, key="carbon_opt_slider") / 100.0
carbon_saved = peak_penalty * opt_pct * 0.75
energy_saved = peak_energy_kwh * opt_pct * 0.60 * 0.12
shifted_energy = peak_energy_kwh * opt_pct * 0.60

o1, o2, o3 = st.columns(3)
o1.metric("Est. Carbon Penalty Saved", f"${carbon_saved:,.0f}")
o2.metric("Est. Energy Cost Saved", f"${energy_saved:,.0f}")
o3.metric("Peak Energy Shifted", f"{shifted_energy:,.0f} kWh")

if opt_pct > 0:
    total_saved = carbon_saved + energy_saved
    st.success(
        f"Moving {opt_pct*100:.0f}% of peak-hour shifts could save about ${total_saved:,.0f} "
        f"while shifting roughly {shifted_energy:,.0f} kWh to off-peak periods."
    )

# ── HITL Escalation ───────────────────────────────────────────────────────────
if not compliant:
    st.markdown("---")
    if st.button("Submit Carbon Alert to Sustainability Head", key="carbon_hitl", type="primary"):
        try:
            from hitl.manager import HitlManager

            HitlManager().enqueue("carbon", "Environmentalist", {
                "peak_penalty_pct": peak_pct,
                "total_penalty_usd": total_penalty,
                "key_finding": key_finding,
                "recommendation": recommendation,
                "shift_suggestions": environ_out.get("shift_suggestions", []),
                "message": (
                    f"Carbon compliance alert: peak ratio is {peak_pct:.1f}% "
                    f"against a {config.AGENT['peak_penalty_ratio']*100:.0f}% threshold."
                ),
            })
            st.success("Carbon alert submitted to the HITL inbox.")
        except Exception as exc:
            st.error(f"HITL submission failed: {exc}")
