"""
pages/07_Digital_Twin.py — Digital Twin Simulation
Phase 2: Live-defaulted sliders from agent outputs, simulation results,
         production trajectory chart, scenario comparison, mini Ollama chat.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import httpx
import config

COLORS = st.session_state.get("_COLORS", {
    "healthy": "#00C896", "warning": "#FFA500", "critical": "#FF4C4C",
    "info": "#4A9EFF", "card_bg": "#1E1E2E",
})

df           = st.session_state.get("_df", pd.DataFrame())
current_time = st.session_state.get("_current_time", pd.Timestamp.now())


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


st.title("🧬 Digital Twin Simulation")
st.markdown("Parameter-driven plant simulation. Slider defaults are loaded live from agent outputs.")

if df.empty:
    st.warning("No data available.")
    st.stop()

out    = orch()
plants = out.get("plants", sorted(df["Assigned_Facility"].unique().tolist()))

from simulation.digital_twin import simulate, derive_defaults_from_agent_output

col_left, col_right = st.columns([1, 2])

with col_left:
    st.subheader("⚙️ Configure Simulation")
    st.caption("Default values loaded live from agent outputs")

    selected_plant = st.selectbox("Select Plant", options=plants, key="dt_plant_p7")
    defaults       = derive_defaults_from_agent_output(selected_plant, out, df)

    oee_val      = st.slider("OEE %",                    50,   100,  int(defaults["oee_pct"]),      key="dt_oee_p7")
    wf_val       = st.slider("Workforce Availability %", 50,   100,  int(defaults["workforce_pct"]), key="dt_wf_p7")
    forecast_val = st.number_input(
        "Demand to Meet (units)", 0, 50000, defaults["forecast_qty"], step=100, key="dt_fq_p7"
    )
    energy_val   = st.slider(
        "Energy Price ($/kWh)", 0.05, 0.50, round(defaults["energy_price"], 2), step=0.01, key="dt_ep_p7"
    )
    downtime_val = st.slider("Machine Downtime (hrs)", 0, 72, 0, step=2,            key="dt_dt_p7")
    opt_for      = st.selectbox("Optimise For", ["Time", "Cost", "Carbon"],         key="dt_opt_p7")
    buffer_pct   = st.slider("Demand Buffer %", 0, 30, 10,                          key="dt_buf_p7") / 100.0

    run_sim = st.button("▶ Run Simulation", type="primary", key="dt_run_p7")
    st.markdown("---")
    scol1, scol2, scol3 = st.columns(3)
    if scol1.button("💾 Save A", key="dt_sa_p7"):
        if st.session_state.get("dt_result"):
            st.session_state["dt_scenarios"]["A"] = st.session_state["dt_result"]
            st.success("Saved as Scenario A")
    if scol2.button("💾 Save B", key="dt_sb_p7"):
        if st.session_state.get("dt_result"):
            st.session_state["dt_scenarios"]["B"] = st.session_state["dt_result"]
            st.success("Saved as Scenario B")
    if scol3.button("💾 Save C", key="dt_sc_p7"):
        if st.session_state.get("dt_result"):
            st.session_state["dt_scenarios"]["C"] = st.session_state["dt_result"]
            st.success("Saved as Scenario C")

with col_right:
    if run_sim:
        with st.spinner(f"Running simulation for {selected_plant.split('(')[0].strip()}…"):
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
        rc1.metric("Expected Output",  f"{result['expected_output_units']:,} units")
        rc2.metric("Target",           f"{result['target_qty']:,} units")
        rc3.metric("Shortfall",
                   f"-{result['shortfall_units']:,}" if result["shortfall_units"] else "✅ None",
                   delta_color="inverse")
        rc4, rc5, rc6 = st.columns(3)
        rc4.metric("Estimated Cost",   f"${result['cost_usd']:,.0f}")
        rc5.metric("Carbon Emissions", f"{result['carbon_kg']:,.0f} kg CO₂")
        rc6.metric("Completion Day",   f"Day {result['completion_day']} of {config.SIMULATION['sim_days']}")

        # Trajectory Chart
        days = [f"Day {i+1}" for i in range(config.SIMULATION["sim_days"])]
        cum  = result["cumulative_breakdown"]
        tgt  = [result["target_qty"]] * config.SIMULATION["sim_days"]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=days, y=cum, name="Cumulative Output",
            fill="tozeroy", line=dict(color=COLORS["info"], width=2),
            fillcolor=f"{COLORS['info']}22",
        ))
        fig.add_trace(go.Scatter(
            x=days, y=tgt, name="Target",
            line=dict(color=COLORS["critical"], dash="dash", width=2),
        ))
        fig.update_layout(
            title="Production Trajectory",
            plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE",
            xaxis_title="", yaxis_title="Cumulative Units",
        )
        st.plotly_chart(fig, use_container_width=True)

        for w in result.get("warnings", []):
            st.warning(w)

        if result.get("optimise_suggestions"):
            st.subheader("💡 Optimisation Tips")
            for tip in result["optimise_suggestions"]:
                st.info(tip)

        # Apply to Production Plan
        if st.button("✅ Apply to Production Plan", key="dt_apply_p7"):
            st.session_state["selected_plant"]      = selected_plant
            st.session_state["dt_apply_oee"]        = oee_val
            st.session_state["dt_apply_workforce"]  = wf_val
            st.success(
                f"✅ Applied. Navigate to **Production Plan** to view the updated plan for "
                f"{selected_plant.split('(')[0].strip()}."
            )
    else:
        st.info("👈 Set parameters and click **▶ Run Simulation** to see results.")

# ── Scenario Comparison ────────────────────────────────────────────────────────
scenarios = {k: v for k, v in st.session_state.get("dt_scenarios", {}).items() if v}
if len(scenarios) >= 2:
    st.markdown("---")
    st.subheader("📊 Scenario Comparison")
    comp_rows = []
    for k, s in scenarios.items():
        comp_rows.append({
            "Scenario":       k,
            "Output (units)": f"{s['expected_output_units']:,}",
            "Shortfall":      f"{s['shortfall_units']:,}",
            "Cost (USD)":     f"${s['cost_usd']:,.0f}",
            "Carbon (kg)":    f"{s['carbon_kg']:,.0f}",
            "Completion Day": f"Day {s['completion_day']}",
        })
    st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)

# ── Mini Ollama Chat (post-simulation) ────────────────────────────────────────
st.markdown("---")
st.subheader("💬 Ask Follow-up Questions About This Simulation")
st.caption("Ask what-if questions or request explanations. Answers are grounded in current simulation context.")

if "dt_chat_history" not in st.session_state:
    st.session_state["dt_chat_history"] = []

for msg in st.session_state["dt_chat_history"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if query := st.chat_input("e.g. What if workforce drops to 70%? Why is there a shortfall?", key="dt_chat_input_p7"):
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
                    "You are a production planning assistant.\n\n"
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
