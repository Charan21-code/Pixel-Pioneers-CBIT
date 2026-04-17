"""
pages/05_Machine_Health.py — Machine Health & OEE (Mechanic Agent)
Phase 2: Plant dropdown, 4-panel sensor charts, crisis alert box,
         maintenance window table, risk score card per plant.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import config

# ── Shared state ──────────────────────────────────────────────────────────────
COLORS = st.session_state.get("_COLORS", {
    "healthy": "#00C896", "warning": "#FFA500", "critical": "#FF4C4C",
    "info": "#4A9EFF", "card_bg": "#1E1E2E",
})

df           = st.session_state.get("_df", pd.DataFrame())
current_time = st.session_state.get("_current_time", pd.Timestamp.now())


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


def rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return f"rgba(74,158,255,{alpha})"
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ── Page ──────────────────────────────────────────────────────────────────────
st.title("🔧 Machine Health & OEE (Mechanic Agent)")
st.markdown("Per-plant sensor telemetry, risk assessment, and maintenance recommendations.")

if df.empty:
    st.warning("No data available. Advance the time cursor to load data.")
    st.stop()

out       = orch()
mech_out  = out.get("mechanic", {})
fac_risks = mech_out.get("facility_risks", {})
plants    = out.get("plants", sorted(df["Assigned_Facility"].unique().tolist()))

# ── Plant Selector ─────────────────────────────────────────────────────────────
selected = st.selectbox(
    "🏭 Select Plant",
    options=plants,
    index=0,
    key="mh_plant_selector_p5",
)
if not selected:
    st.stop()

# ── Plant Health Summary Card ─────────────────────────────────────────────────
risk_info   = fac_risks.get(selected, {})
risk_score  = risk_info.get("risk_score", 0)
risk_status = risk_info.get("status", "healthy")
ttf_hrs     = risk_info.get("ttf_hrs", 999)
oee_pct     = risk_info.get("oee_pct", 0)
temp_c      = risk_info.get("temp_c", 0)
vib_hz      = risk_info.get("vib_hz", 0)

risk_color = (
    COLORS["critical"] if risk_status == "critical" else
    COLORS["warning"]  if risk_status in ("warning", "medium") else
    COLORS["healthy"]
)

risk_badge = {
    "critical": "🔴 CRITICAL",
    "warning":  "🟡 WARNING",
    "medium":   "🟡 WARNING",
}.get(risk_status, "🟢 LOW")

ttf_note = "⚠️ Failure imminent!" if ttf_hrs < 24 else (
    "🟡 Watch closely" if ttf_hrs < 100 else "✅ Next 24hrs are safe"
)

mechanic_summary = mech_out.get("summary", "Mechanic agent has not run yet.")

st.markdown(f"""
<div style="border:1px solid #333; border-left:6px solid {risk_color};
border-radius:8px; padding:20px; background:{COLORS['card_bg']}; margin-bottom:20px;">
<b style="font-size:18px; color:{risk_color};">
{selected.split('(')[0].strip().upper()} — MACHINE HEALTH
</b>
<div style="font-size:13px; color:#aaa; line-height:2.2; margin-top:10px;">
Risk Score: <b style="color:{risk_color};">{risk_score:.0f} / 100 — {risk_badge}</b><br/>
Average OEE: <b>{oee_pct:.1f}%</b><br/>
Min TTF: <b>{ttf_hrs:.1f} hrs</b> &nbsp; <span style="color:#aaa;font-size:12px;">({ttf_note})</span><br/>
Avg Temperature: <b>{temp_c:.1f}°C</b><br/>
Avg Vibration: <b>{vib_hz:.1f} Hz</b>
</div>
<div style="margin-top:12px; font-size:12px; color:#888; font-style:italic;">
Mechanic Agent: "{(mechanic_summary or '')[:200]}"
</div>
</div>
""", unsafe_allow_html=True)

# ── Crisis Alert ───────────────────────────────────────────────────────────────
plant_df = df[df["Assigned_Facility"] == selected].tail(150).copy()

if not plant_df.empty and plant_df["Predicted_Time_To_Failure_Hrs"].min() < 24:
    min_ttf = plant_df["Predicted_Time_To_Failure_Hrs"].min()
    worst   = plant_df.loc[plant_df["Predicted_Time_To_Failure_Hrs"].idxmin()]

    st.markdown(f"""
<div style="border:2px solid {COLORS['critical']}; background:{COLORS['critical']}15;
    border-radius:8px; padding:16px 20px; margin-bottom:20px;">
<b style="font-size:16px; color:{COLORS['critical']};">
🚨 MACHINE FAILURE IMMINENT — {selected.split('(')[0].strip()}
</b>
<div style="font-size:13px; margin-top:8px; line-height:1.8;">
Predicted TTF has dropped to <b style="color:{COLORS['critical']};">{min_ttf:.1f} hrs</b><br/>
Temperature: <b>{worst['Machine_Temperature_C']:.1f}°C</b> &nbsp;|&nbsp;
Vibration: <b>{worst['Machine_Vibration_Hz']:.1f} Hz</b><br/>
<br/>
➔ <b>Mechanic Agent has flagged this for CRITICAL escalation.</b><br/>
➔ This facility has been automatically blacklisted in the Production Plan.<br/>
➔ Rerouting to partner overflow is recommended.
</div>
</div>
""", unsafe_allow_html=True)

    if st.button(
        "🔧 Schedule Emergency Maintenance — Sends to HITL Inbox",
        key=f"mh_maint_{selected}",
        type="primary",
    ):
        try:
            from hitl.manager import HitlManager
            HitlManager().enqueue("maintenance", "Mechanic", {
                "facility": selected,
                "ttf_hrs":  float(min_ttf),
                "temp_c":   float(worst["Machine_Temperature_C"]),
                "vib_hz":   float(worst["Machine_Vibration_Hz"]),
                "message":  f"Emergency maintenance required at {selected}. TTF = {min_ttf:.1f} hrs.",
            })
            st.success("✅ Emergency maintenance request sent to HITL Inbox (Engineering tab).")
        except Exception as e:
            st.error(f"HITL submission failed: {e}")

# ── 4-Panel Sensor Charts ─────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📡 Sensor Telemetry — Last 150 Events")

chart_theme = dict(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE")

if plant_df.empty:
    st.warning("No sensor data for this plant in the current time window.")
else:
    c1, c2 = st.columns(2)

    # Chart 1 — TTF
    with c1:
        fig_ttf = go.Figure()
        fig_ttf.add_trace(go.Scatter(
            x=plant_df["Timestamp"], y=plant_df["Predicted_Time_To_Failure_Hrs"],
            mode="lines", name="Predicted TTF",
            line=dict(color=COLORS["info"], width=2),
            fill="tozeroy", fillcolor=rgba(COLORS["info"], 0.13),
        ))
        fig_ttf.add_hline(
            y=config.AGENT["ttf_critical_hrs"], line_dash="dash",
            line_color=COLORS["critical"], annotation_text="CRITICAL (24h)",
        )
        fig_ttf.add_hline(
            y=config.AGENT["ttf_warning_hrs"], line_dash="dot",
            line_color=COLORS["warning"], annotation_text="WARNING (100h)",
        )
        # Highlight points below critical threshold
        danger_pts = plant_df[plant_df["Predicted_Time_To_Failure_Hrs"] < 24]
        if not danger_pts.empty:
            fig_ttf.add_trace(go.Scatter(
                x=danger_pts["Timestamp"], y=danger_pts["Predicted_Time_To_Failure_Hrs"],
                mode="markers", name="⚠️ Critical Point",
                marker=dict(color=COLORS["critical"], size=10, symbol="x"),
            ))
        fig_ttf.update_layout(
            title="Predicted Time To Failure (hrs)", **chart_theme,
            xaxis_title="", yaxis_title="Hours",
        )
        st.plotly_chart(fig_ttf, use_container_width=True)

    # Chart 2 — OEE
    with c2:
        fig_oee = go.Figure()
        fig_oee.add_trace(go.Scatter(
            x=plant_df["Timestamp"], y=plant_df["Machine_OEE_Pct"],
            mode="lines", name="OEE %",
            line=dict(color=COLORS["healthy"], width=2),
        ))
        fig_oee.add_hline(
            y=config.AGENT["oee_warning_pct"], line_dash="dot",
            line_color=COLORS["warning"],
            annotation_text=f"Target ({config.AGENT['oee_warning_pct']}%)",
        )
        fig_oee.update_layout(
            title="Overall Equipment Effectiveness (%)", **chart_theme,
            xaxis_title="", yaxis_title="%",
        )
        st.plotly_chart(fig_oee, use_container_width=True)

    c3, c4 = st.columns(2)

    # Chart 3 — Temperature
    with c3:
        fig_temp = go.Figure()
        fig_temp.add_trace(go.Scatter(
            x=plant_df["Timestamp"], y=plant_df["Machine_Temperature_C"],
            mode="lines", name="Temperature",
            line=dict(color=COLORS["warning"], width=2),
        ))
        fig_temp.add_hline(y=80, line_dash="dot", line_color=COLORS["warning"],
                           annotation_text="⚠️ 80°C Warning")
        # Shade danger zone above 90°C
        if plant_df["Machine_Temperature_C"].max() > 90:
            fig_temp.add_hrect(
                y0=90, y1=plant_df["Machine_Temperature_C"].max() + 5,
                fillcolor=COLORS["critical"], opacity=0.15, line_width=0,
                annotation_text="🔴 Danger Zone",
            )
        fig_temp.update_layout(
            title="Machine Temperature (°C)", **chart_theme,
            xaxis_title="", yaxis_title="°C",
        )
        st.plotly_chart(fig_temp, use_container_width=True)

    # Chart 4 — Vibration
    with c4:
        fig_vib = go.Figure()
        fig_vib.add_trace(go.Scatter(
            x=plant_df["Timestamp"], y=plant_df["Machine_Vibration_Hz"],
            mode="lines", name="Vibration",
            line=dict(color="#A78BFA", width=2),
        ))
        fig_vib.add_hline(y=55, line_dash="dot", line_color=COLORS["warning"],
                          annotation_text="⚠️ 55 Hz Warning")
        fig_vib.update_layout(
            title="Machine Vibration (Hz)", **chart_theme,
            xaxis_title="", yaxis_title="Hz",
        )
        st.plotly_chart(fig_vib, use_container_width=True)

# ── Recommended Maintenance Window ────────────────────────────────────────────
st.markdown("---")
st.subheader("🛠️ Recommended Maintenance Windows")

recs       = mech_out.get("recommendations", []) or []
plant_recs = [r for r in recs if r.get("facility", "") == selected]

if plant_recs:
    mw_rows = []
    for rec in plant_recs:
        mw_rows.append({
            "Line / Asset":            rec.get("facility", selected),
            "Next Maintenance":        rec.get("action", "Preventive check"),
            "Est. Downtime (hrs)":     rec.get("estimated_downtime_hrs", "?"),
            "Priority":                ("🔴 Critical" if rec.get("priority", "medium") == "critical"
                                        else "🟡 Medium"),
        })
    st.dataframe(pd.DataFrame(mw_rows), use_container_width=True, hide_index=True)
else:
    # Generate lightweight table from risk data
    risk_score_val = risk_info.get("risk_score", 0)
    if risk_score_val >= 80:
        st.error("🔴 Immediate maintenance recommended — facility is at CRITICAL risk.")
    elif risk_score_val >= 40:
        st.warning("🟡 Preventive maintenance scheduled within the next 5 days.")
    else:
        st.success("✅ No immediate maintenance required. Next check in 11 days.")

    fallback_rows = [
        {"Line": "Line 2 (Standard)",     "Recommendation": "Preventive check",
         "Window": "Day 2 Off-Peak (22:00–06:00)", "Est. Downtime": "4 hrs",
         "Priority": "🟡 Medium" if risk_score_val < 80 else "🔴 Critical"},
        {"Line": "Line 1 (High Speed)",   "Recommendation": "Sensor calibration",
         "Window": "Day 5 Off-Peak",               "Est. Downtime": "2 hrs",
         "Priority": "🟢 Low"},
    ]
    st.dataframe(pd.DataFrame(fallback_rows), use_container_width=True, hide_index=True)

# Full summary expander
if mech_out.get("summary"):
    with st.expander("📝 Full Mechanic Agent Summary"):
        st.write(mech_out["summary"])
