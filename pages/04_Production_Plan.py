"""
pages/04_Production_Plan.py — Production Plan (Scheduler Agent)
Phase 2: Level A overview table + Level B plant-specific view.

Features
--------
- Level A: summary table for all 5 plants (machine risk, workforce%, stock days, plan status)
- Level B: plant-specific readiness gate (4 checks), plan constraints sliders,
           editable 7-day shift plan table, summary metrics, HITL submit button
- Slider defaults pulled live from orch_output (not hardcoded)
- Gantt chart: REMOVED (replaced with summary metrics)
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import sqlite3
import config
from dashboard_runtime import bootstrap_page, render_ollama_fallback_notice

bootstrap_page("Production Plan", "🗓️")

# ── Shared state ──────────────────────────────────────────────────────────────
COLORS = st.session_state.get("_COLORS", {
    "healthy": "#00C896", "warning": "#FFA500", "critical": "#FF4C4C",
    "info": "#4A9EFF", "card_bg": "#1E1E2E",
})

df           = st.session_state.get("_df", pd.DataFrame())
df_full      = st.session_state.get("_df_full", pd.DataFrame())
current_time = st.session_state.get("_current_time", pd.Timestamp.now())


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


# ── Page ──────────────────────────────────────────────────────────────────────
st.title("🗓️ Production Plan (Scheduler Agent)")
st.markdown("Per-plant 7-day shift plans with readiness gating and inline approval workflow.")
render_ollama_fallback_notice("Scheduler planning")

if df.empty:
    st.warning("No data available. Advance the time cursor to load data.")
    st.stop()

out          = orch()
sch_plans    = out.get("scheduler", {})
plants       = out.get("plants", sorted(df["Assigned_Facility"].unique().tolist()))
mech_out     = out.get("mechanic", {})
mech_risks   = mech_out.get("facility_risks", {})
buyer_inv    = out.get("buyer_inventory", {})
finance_out  = out.get("finance", {})

# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL A — PLANT OVERVIEW TABLE
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("🏭 All Plants — Quick Overview")
st.caption("Review the status of all plants. Select a plant below to drill into its shift plan.")

overview_rows = []
for plant in plants:
    risk_info  = mech_risks.get(plant, {})
    inv_info   = buyer_inv.get(plant, {})
    plan_info  = sch_plans.get(plant, {})
    wf_df      = df[df["Assigned_Facility"] == plant]
    wf_pct     = (
        wf_df["Workforce_Deployed"].sum() /
        max(wf_df["Workforce_Required"].sum(), 1) * 100
    ) if not wf_df.empty else 0.0

    risk_status = risk_info.get("status", "healthy").upper()
    risk_score  = risk_info.get("risk_score", 0)
    inv_days    = inv_info.get("days_remaining", 0)

    plan_status = (
        "⛔ Blocked"  if risk_status in ("CRITICAL",) else
        "✅ Ready"    if plan_info.get("shift_plan") else
        "🟡 Pending"
    )

    risk_emoji = (
        "🔴" if risk_status == "CRITICAL" else
        "🟡" if risk_status in ("WARNING", "MEDIUM") else
        "🟢"
    )

    overview_rows.append({
        "Plant":        plant.split("(")[0].strip(),
        "Machine Risk": f"{risk_emoji} {risk_status} ({risk_score:.0f})",
        "Workforce %":  f"{wf_pct:.1f}%",
        "Stock Days":   f"{inv_days:.1f}d",
        "Plan Status":  plan_status,
        "Throughput":   f"{plan_info.get('expected_throughput', 0):,} units",
    })

overview_df = pd.DataFrame(overview_rows)
st.dataframe(overview_df, use_container_width=True, hide_index=True)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL B — PLANT-SPECIFIC DETAIL
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("🔍 Plant-Specific Shift Plan")

preferred_plant = st.session_state.get("selected_plant")
if st.session_state.get("plan_plant_selector_p4") not in plants:
    st.session_state["plan_plant_selector_p4"] = (
        preferred_plant if preferred_plant in plants else plants[0]
    )

selected = st.selectbox("Select Plant", options=plants, key="plan_plant_selector_p4")
if selected:
    st.session_state["selected_plant"] = selected

if not selected:
    st.stop()

plant_plan  = sch_plans.get(selected, {})
plant_risk  = mech_risks.get(selected, {})
plant_inv   = buyer_inv.get(selected, {})
plant_wf    = df[df["Assigned_Facility"] == selected]

wf_dep  = int(plant_wf["Workforce_Deployed"].mean()) if not plant_wf.empty else 0
wf_req  = int(plant_wf["Workforce_Required"].mean()) if not plant_wf.empty else 1
wf_pct  = (plant_wf["Workforce_Deployed"].sum() / max(plant_wf["Workforce_Required"].sum(), 1) * 100) if not plant_wf.empty else 0

# ── Section B1: Readiness Gate ─────────────────────────────────────────────────
mach_ok = plant_risk.get("status", "healthy") not in ("critical",)
wf_ok   = wf_pct >= 80
inv_ok  = plant_inv.get("status", "healthy") in ("healthy", "low")
fin_ok  = finance_out.get("health_score", 100) >= 30

gate_rows = [
    ("MACHINE HEALTH",
     f"OEE {plant_risk.get('oee_pct', 0):.1f}% | "
     f"Risk Score {plant_risk.get('risk_score', 0):.0f} | "
     f"TTF: {plant_risk.get('ttf_hrs', 0):.0f} hrs",
     mach_ok),
    ("WORKFORCE",
     f"{wf_pct:.1f}% deployed ({wf_dep} / {wf_req} workers)",
     wf_ok),
    ("INVENTORY",
     f"{plant_inv.get('days_remaining', 0):.1f} days remaining | "
     f"Threshold: {plant_inv.get('inventory_threshold', 20000):,} u | "
     f"Status: {plant_inv.get('status','?').upper()}",
     inv_ok),
    ("FINANCE GATE",
     f"Health: {finance_out.get('health_score', 100):.1f}/100",
     fin_ok),
]

all_ok    = all(ok for _, _, ok in gate_rows)
gate_html = ""
for label, detail, ok in gate_rows:
    icon  = "✅" if ok else "🔴"
    color = COLORS["healthy"] if ok else COLORS["critical"]
    gate_html += (
        f"<div style='margin:6px 0; font-size:13px;'>"
        f"{icon} <b style='color:{color};'>{label}:</b> &nbsp; {detail}"
        f"</div>"
    )

gate_color  = COLORS["healthy"] if all_ok else COLORS["warning"]
overall_msg = (
    "→ PLANT IS CLEARED FOR PRODUCTION"
    if all_ok else
    "→ Issues detected. Review before committing plan."
)

st.markdown(f"""
<div style="border:1px solid {gate_color}55; border-left:5px solid {gate_color};
border-radius:8px; padding:16px 20px; background:{COLORS['card_bg']}; margin-bottom:20px;">
<b style="font-size:16px;">{selected.split('(')[0].strip().upper()} — READINESS CHECK</b>
{gate_html}
<div style="margin-top:10px; color:{gate_color}; font-weight:bold; font-size:14px;">
{overall_msg}
</div>
</div>
""", unsafe_allow_html=True)

# ── Section B2: Plan Constraint Sliders ───────────────────────────────────────
st.subheader("⚙️ Plan Constraints")
st.caption("Defaults pulled live from agent outputs. Adjust then regenerate.")

# Live defaults from orch output
plan_override = st.session_state.get("dt_plan_override") or {}
override_active = plan_override.get("plant") == selected

live_oee = float(plan_override.get("oee_pct", plant_risk.get("oee_pct", 90)) if override_active else plant_risk.get("oee_pct", 90))
live_wf = float(plan_override.get("workforce_pct", min(100, max(50, wf_pct))) if override_active else min(100, max(50, wf_pct)))
live_buf = int(round((plan_override.get("demand_buffer_pct", 0.10) if override_active else 0.10) * 100))
live_opt = plan_override.get("optimise_for", "Time") if override_active else "Time"
live_fq = int(plan_override.get("forecast_qty", out.get("forecast", {}).get("forecast_qty", 10000) // max(1, len(plants))))

slider_context = (
    st.session_state.get("orch_cursor"),
    selected,
    plan_override.get("applied_at") if override_active else None,
)
if st.session_state.get("p4_controls_context") != slider_context:
    st.session_state["p4_oee"] = int(min(100, max(50, live_oee)))
    st.session_state["p4_wf"] = int(min(100, max(50, live_wf)))
    st.session_state["p4_buf"] = int(min(30, max(0, live_buf)))
    st.session_state["p4_opt"] = live_opt if live_opt in ["Time", "Cost", "Carbon"] else "Time"
    st.session_state["p4_controls_context"] = slider_context

if override_active:
    st.info(
        f"Digital Twin parameters are loaded for {selected.split('(')[0].strip()} "
        f"with a demand target of {live_fq:,} units."
    )

sl1, sl2, sl3 = st.columns(3)
with sl1:
    oee_slider = st.slider(
        "OEE %",
        min_value=50, max_value=100,
        value=st.session_state["p4_oee"],
        help="Defaults from MechanicAgent live output",
        key="p4_oee",
    )
with sl2:
    wf_slider = st.slider(
        "Workforce Availability %",
        min_value=50, max_value=100,
        value=st.session_state["p4_wf"],
        help="Defaults from live Workforce_Deployed / Required",
        key="p4_wf",
    )
with sl3:
    buf_slider = st.slider(
        "Demand Buffer %",
        min_value=0, max_value=30,
        value=st.session_state["p4_buf"],
        help="Safety margin added over forecast quantity",
        key="p4_buf",
    )

opt_for = st.selectbox(
    "Optimise For",
    ["Time", "Cost", "Carbon"],
    index=["Time", "Cost", "Carbon"].index(st.session_state["p4_opt"]),
    key="p4_opt",
)

if st.button("⟳ Generate Plan for This Plant", key=f"p4_gen_{selected}", type="primary"):
    try:
        with st.spinner(f"Scheduler Agent building plan for {selected.split('(')[0].strip()} via Ollama…"):
            from agents.scheduler import SchedulerAgent
            plant_df_s = df[df["Assigned_Facility"] == selected].copy()
            plan_ctx   = {
                "df":          plant_df_s,
                "as_of_time":  current_time,
                "mechanic":    mech_out,
                "forecast":    out.get("forecast", {}),
                "forecast_qty_override": live_fq,
                # Overrides from sliders
                "oee_override":       oee_slider,
                "workforce_override": wf_slider,
                "demand_buffer_pct":  buf_slider / 100,
                "optimise_for":       opt_for,
            }
            new_plan = SchedulerAgent().run(plan_ctx)
        # Patch into session
        cached = st.session_state["orch_output"] or {}
        cached.setdefault("scheduler", {})[selected] = new_plan
        st.session_state["orch_output"] = cached
        st.success(f"✅ New plan generated for {selected.split('(')[0].strip()}.")
        st.rerun()
    except Exception as e:
        st.error(f"Scheduler failed: {e}")

# ── Section B3: Editable Shift Plan ───────────────────────────────────────────
st.markdown("---")
st.subheader("📋 7-Day Shift Plan")

shift_plan = plant_plan.get("shift_plan", [])

if shift_plan:
    plan_df = pd.DataFrame(shift_plan)
    # Determine columns available
    editable_cols = [c for c in ["Assigned_Units", "Product", "Shift"] if c in plan_df.columns]
    disabled_cols = [c for c in plan_df.columns if c not in editable_cols]

    # Flag critical rows (blacklisted facility)
    blacklisted = set(mech_out.get("critical_facilities", []) or [])
    if "facility" in plan_df.columns:
        plan_df["_blocked"] = plan_df["facility"].isin(blacklisted)
    else:
        plan_df["_blocked"] = False

    edited_df = st.data_editor(
        plan_df.drop(columns=["_blocked"], errors="ignore"),
        use_container_width=True,
        hide_index=True,
        disabled=disabled_cols,
        num_rows="fixed",
        key=f"p4_plan_editor_{selected}",
    )

    if st.button("↺ Recalculate with Edits", key=f"p4_recalc_{selected}"):
        st.info("Recalculation with manual edits is queued. Trigger agents to incorporate changes.")

    st.markdown("---")
    # ── Section B4: Plan Summary ───────────────────────────────────────────────
    st.subheader("📊 Plan Summary")
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Total Planned Units",  f"{plant_plan.get('expected_throughput', 0):,}")
    mc2.metric("Plant Utilisation",    f"{plant_plan.get('utilisation_pct', 0):.1f}%")
    mc3.metric("Available Lines",      f"{len(plant_plan.get('available_facilities', []))} / 3")

    if plant_plan.get("excluded_facilities"):
        st.warning(
            f"⛔ Excluded (blacklisted): {', '.join(plant_plan.get('excluded_facilities', []))}"
        )

    # Download CSV
    csv = edited_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download Shift Plan CSV",
        data=csv,
        file_name=f"shift_plan_{selected.split('(')[0].strip().replace(' ','_')}.csv",
        mime="text/csv",
        key=f"p4_dl_{selected}",
    )
else:
    st.info(
        "No shift plan generated yet. "
        "The facility may be blacklisted or agents are still initialising."
    )

# ── Section B5: Submit for Approval ───────────────────────────────────────────
st.markdown("---")
st.subheader("📤 Submit for Approval")

if st.button(
    f"📋 Submit {selected.split('(')[0].strip()} Plan for Approval",
    key=f"p4_submit_{selected}",
    type="primary",
):
    try:
        from hitl.manager import HitlManager
        HitlManager().enqueue("ops", "Scheduler", {
            "plant":       selected,
            "shift_plan":  shift_plan,
            "throughput":  plant_plan.get("expected_throughput", 0),
            "utilisation": plant_plan.get("utilisation_pct", 0),
            "message":     f"7-day production plan for {selected} requires approval.",
        })
        st.success("✅ Plan submitted to HITL Inbox (Operations tab).")
    except Exception as e:
        st.error(f"HITL submission failed: {e}")

# Scheduler summary
if plant_plan.get("summary"):
    with st.expander("🤖 Scheduler Agent Summary"):
        st.info(plant_plan["summary"])
