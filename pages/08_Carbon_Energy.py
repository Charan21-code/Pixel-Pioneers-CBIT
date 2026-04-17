"""
pages/08_Carbon_Energy.py — Carbon & Energy Dashboard (Environmentalist Agent)
Phase 2: Carbon KPIs, energy heatmap, emissions charts, agent assessment block,
         shift timing optimiser tool.
"""

import streamlit as st
import pandas as pd
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


st.title("🌱 Carbon & Energy Dashboard (Environmentalist Agent)")
st.markdown("Emissions tracking, compliance status, and shift optimisation recommendations.")

if df.empty:
    st.warning("No data available.")
    st.stop()

out         = orch()
environ_out = out.get("environ", {})

total_carbon  = environ_out.get("total_carbon_kg",   df["Carbon_Emissions_kg"].sum())
total_penalty = environ_out.get("total_penalty_usd", df["Carbon_Cost_Penalty_USD"].sum())
peak_penalty  = environ_out.get("peak_penalty_usd",  df[df["Grid_Pricing_Period"] == "Peak"]["Carbon_Cost_Penalty_USD"].sum())
peak_pct      = environ_out.get("peak_penalty_pct",  0.0)
compliant     = environ_out.get("compliance_flag",   True)

# ── KPI Cards ─────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total CO₂ Emissions",  f"{total_carbon:,.0f} kg",    help="Sum of Carbon_Emissions_kg")
c2.metric("Total Carbon Penalty", f"${total_penalty:,.0f}",     help="Sum of Carbon_Cost_Penalty_USD")
c3.metric("Peak-Hour Penalty",    f"${peak_penalty:,.0f}",      help="Penalty incurred during peak pricing hours")
c4.metric("Compliance Status",
          "✅ COMPLIANT" if compliant else "⚠️ NON-COMPLIANT",
          delta=f"Peak ratio: {peak_pct:.1f}%",
          delta_color="off")

# ── Agent Assessment Block ─────────────────────────────────────────────────────
summary    = environ_out.get("summary", "Environmentalist agent has not run yet.")
badge      = COLORS["healthy"] if compliant else COLORS["warning"]
comp_label = "✅ COMPLIANT" if compliant else "⚠️ PARTIALLY NON-COMPLIANT"

st.markdown(f"""
<div style="border-left:6px solid {badge}; padding:16px 20px; background:{COLORS['card_bg']};
            border-radius:0 8px 8px 0; margin:16px 0;">
    <b style="color:{badge}; font-size:15px;">🌱 Environmentalist Agent Report</b><br/>
    <span style="font-size:13px; color:#aaa;">Compliance: <b style="color:{badge};">{comp_label}</b>
        &nbsp;|&nbsp; Peak ratio: <b>{peak_pct:.1f}%</b>
        (threshold: {config.AGENT['peak_penalty_ratio']*100:.0f}%)</span><br/>
    <span style="font-size:13px; margin-top:8px; display:block;">{summary}</span>
</div>
""", unsafe_allow_html=True)

for suggestion in environ_out.get("shift_suggestions", []):
    st.info(f"💡 {suggestion}")

# ── Energy Heatmap ─────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🔥 Energy Consumption Heatmap")
st.caption("Average kWh consumed by hour of day and day of week. Red band = Peak pricing zone (14:00–20:00).")

df_h = df.copy()
df_h["Hour"]      = df_h["Timestamp"].dt.hour
df_h["DayOfWeek"] = df_h["Timestamp"].dt.day_name()

heat_data = df_h.groupby(["DayOfWeek", "Hour"])["Energy_Consumed_kWh"].mean().reset_index()
fig_heat  = px.density_heatmap(
    heat_data, x="Hour", y="DayOfWeek", z="Energy_Consumed_kWh",
    title="Avg Energy Usage (kWh) by Hour & Day",
    color_continuous_scale="Viridis",
    category_orders={"DayOfWeek": ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]},
)
fig_heat.add_vrect(
    x0=14, x1=20, fillcolor="red", opacity=0.15,
    line_width=0, annotation_text="Peak Pricing",
)
fig_heat.update_layout(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE")
st.plotly_chart(fig_heat, use_container_width=True)

# ── Emissions by Facility & Product ───────────────────────────────────────────
st.markdown("---")
c1, c2 = st.columns(2)

with c1:
    st.subheader("🏭 Emissions by Facility")
    fac_carbon = df.groupby("Assigned_Facility")["Carbon_Emissions_kg"].sum().reset_index()
    fac_carbon  = fac_carbon.sort_values("Carbon_Emissions_kg", ascending=True)
    fig_fac = px.bar(
        fac_carbon, x="Carbon_Emissions_kg", y="Assigned_Facility",
        orientation="h", color="Carbon_Emissions_kg",
        color_continuous_scale="Reds",
    )
    fig_fac.update_layout(
        plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE",
        xaxis_title="kg CO₂", yaxis_title="",
    )
    st.plotly_chart(fig_fac, use_container_width=True)

with c2:
    st.subheader("📦 Emissions by Product")
    prod_carbon = df.groupby("Product_Category")["Carbon_Emissions_kg"].sum().reset_index()
    fig_prod = px.pie(
        prod_carbon, names="Product_Category", values="Carbon_Emissions_kg",
        hole=0.4,
        color_discrete_sequence=px.colors.qualitative.Set3,
    )
    fig_prod.update_layout(paper_bgcolor="#0E1117", font_color="#EEE")
    st.plotly_chart(fig_prod, use_container_width=True)

# ── Shift Timing Optimiser ─────────────────────────────────────────────────────
st.markdown("---")
st.subheader("⚡ Shift Timing Optimiser")
st.caption("Estimate savings from moving Peak-hour batches to Off-Peak shifts.")

opt_pct = st.slider("% of Peak shifts to move to Off-Peak", 0, 100, 30, key="carbon_opt_slider") / 100.0

carbon_saved = peak_penalty * opt_pct * 0.75
energy_saved = environ_out.get("peak_energy_kwh", 0) * opt_pct * 0.60 * 0.12  # ~$0.12/kWh differential

oct1, oct2 = st.columns(2)
oct1.metric("Est. Carbon Penalty Saved / Month",  f"${carbon_saved:,.0f}")
oct2.metric("Est. Energy Cost Saved / Month",     f"${energy_saved:,.0f}")

if opt_pct > 0:
    total_saved = carbon_saved + energy_saved
    st.success(
        f"💡 Moving **{opt_pct*100:.0f}%** of peak-hour shifts to off-peak could save "
        f"approximately **${total_saved:,.0f}/month** in combined carbon and energy costs."
    )

# HITL escalation
if not compliant:
    st.markdown("---")
    if st.button("📤 Submit Carbon Alert to Sustainability Head", key="carbon_hitl", type="primary"):
        try:
            from hitl.manager import HitlManager
            HitlManager().enqueue("carbon", "Environmentalist", {
                "peak_penalty_pct":  peak_pct,
                "total_penalty_usd": total_penalty,
                "shift_suggestions": environ_out.get("shift_suggestions", []),
                "message": (
                    f"Carbon compliance alert: Peak penalty ratio is {peak_pct:.1f}% "
                    f"(threshold {config.AGENT['peak_penalty_ratio']*100:.0f}%). "
                    f"Total penalty: ${total_penalty:,.0f}."
                ),
            })
            st.success("✅ Carbon alert submitted to HITL Inbox (Sustainability tab).")
        except Exception as e:
            st.error(f"HITL submission failed: {e}")
