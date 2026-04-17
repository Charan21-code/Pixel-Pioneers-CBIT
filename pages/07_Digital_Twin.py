"""
pages/07_Digital_Twin.py — Digital Twin Simulation
Phase 4: live-defaulted controls, trajectory comparison, saved scenarios,
         production-plan handoff, and follow-up what-if chat.
"""

import json
import re
from copy import deepcopy

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from agents.scheduler import SchedulerAgent
from simulation.digital_twin import derive_defaults_from_agent_output, simulate

COLORS = st.session_state.get("_COLORS", {
    "healthy": "#00C896",
    "warning": "#FFA500",
    "critical": "#FF4C4C",
    "info": "#4A9EFF",
    "card_bg": "#1E1E2E",
})

df = st.session_state.get("_df", pd.DataFrame())
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


def _sync_controls(selected_plant: str, defaults: dict) -> None:
    """Reset slider defaults whenever the plant or orchestrator context changes."""
    context_marker = (st.session_state.get("orch_cursor"), selected_plant)
    if st.session_state.get("dt_controls_context") == context_marker:
        return

    st.session_state["dt_oee_p7"] = int(round(defaults["oee_pct"]))
    st.session_state["dt_wf_p7"] = int(round(defaults["workforce_pct"]))
    st.session_state["dt_fq_p7"] = int(defaults["forecast_qty"])
    st.session_state["dt_ep_p7"] = round(float(defaults["energy_price"]), 2)
    st.session_state["dt_dt_p7"] = 0
    st.session_state["dt_opt_p7"] = defaults.get("optimise_for", "Time")
    st.session_state["dt_horizon_p7"] = int(defaults.get("horizon_days", config.SIMULATION["sim_days"]))
    st.session_state["dt_buf_p7"] = int(round(defaults.get("demand_buffer_pct", 0.10) * 100))
    st.session_state["dt_controls_context"] = context_marker


def _build_sim_kwargs(selected_plant: str, defaults: dict) -> dict:
    return {
        "plant_id": selected_plant,
        "oee_pct": float(st.session_state.get("dt_oee_p7", defaults["oee_pct"])),
        "workforce_pct": float(st.session_state.get("dt_wf_p7", defaults["workforce_pct"])),
        "forecast_qty": int(st.session_state.get("dt_fq_p7", defaults["forecast_qty"])),
        "energy_price": float(st.session_state.get("dt_ep_p7", defaults["energy_price"])),
        "downtime_hrs": float(st.session_state.get("dt_dt_p7", 0)),
        "optimise_for": str(st.session_state.get("dt_opt_p7", "Time")),
        "horizon_days": int(st.session_state.get("dt_horizon_p7", config.SIMULATION["sim_days"])),
        "base_capacity": int(defaults.get("base_capacity", config.DIGITAL_TWIN["base_capacity"])),
        "demand_buffer_pct": float(st.session_state.get("dt_buf_p7", 10)) / 100.0,
    }


def _build_baseline_kwargs(selected_plant: str, defaults: dict) -> dict:
    return {
        "plant_id": selected_plant,
        "oee_pct": float(defaults["oee_pct"]),
        "workforce_pct": float(defaults["workforce_pct"]),
        "forecast_qty": int(defaults["forecast_qty"]),
        "energy_price": float(defaults["energy_price"]),
        "downtime_hrs": 0.0,
        "optimise_for": defaults.get("optimise_for", "Time"),
        "horizon_days": int(st.session_state.get("dt_horizon_p7", defaults.get("horizon_days", config.SIMULATION["sim_days"]))),
        "base_capacity": int(defaults.get("base_capacity", config.DIGITAL_TWIN["base_capacity"])),
        "demand_buffer_pct": float(st.session_state.get("dt_buf_p7", 10)) / 100.0,
    }


def _results_store() -> dict:
    return st.session_state.setdefault("dt_results", {})


def _scenario_store() -> dict:
    return st.session_state.setdefault("dt_scenarios", {})


def _get_current_result(selected_plant: str):
    result = _results_store().get(selected_plant)
    if result:
        st.session_state["dt_result"] = result
        st.session_state["dt_result_plant"] = selected_plant
    return result


def _save_current_result(result: dict) -> None:
    store = _results_store()
    store[result["plant_id"]] = result
    st.session_state["dt_result"] = result
    st.session_state["dt_result_plant"] = result["plant_id"]


def _save_scenario(slot: str, result: dict) -> None:
    scenarios = _scenario_store().setdefault(result["plant_id"], {})
    scenarios[slot] = deepcopy(result)


def _extract_json_object(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {}


def _heuristic_followup(query: str) -> dict:
    lower = query.lower()
    overrides = {}

    patterns = {
        "workforce_pct": r"(?:workforce|staff|workers?).*?(\d{1,3}(?:\.\d+)?)\s*%",
        "oee_pct": r"\boee\b.*?(\d{1,3}(?:\.\d+)?)\s*%",
        "downtime_hrs": r"(?:downtime|down time).*?(\d{1,2}(?:\.\d+)?)\s*(?:hours|hour|hrs|hr)",
        "energy_price": r"(?:energy price|price per kwh|kwh price|electricity).*?(\d+(?:\.\d+)?)",
        "forecast_qty": r"(?:demand|target|units).*?(\d[\d,]*)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, lower)
        if not match:
            continue
        raw_value = match.group(1).replace(",", "")
        value = float(raw_value)
        overrides[key] = int(value) if key == "forecast_qty" else value

    horizon_match = re.search(r"(?:horizon|within|over)\D{0,10}(\d{1,2})\s*days?", lower)
    if horizon_match:
        overrides["horizon_days"] = int(horizon_match.group(1))

    if "optimi" in lower or "optimiz" in lower:
        if "carbon" in lower:
            overrides["optimise_for"] = "Carbon"
        elif "cost" in lower:
            overrides["optimise_for"] = "Cost"
        elif "time" in lower or "speed" in lower:
            overrides["optimise_for"] = "Time"

    if overrides:
        return {"intent": "recalculate", "overrides": overrides}
    return {"intent": "explain", "overrides": {}, "answer": ""}


def _ask_followup_ollama(query: str, current_params: dict, current_result: dict) -> dict:
    prompt = f"""You are helping a factory planner reason about a digital twin simulation.

Current simulation parameters:
{json.dumps(current_params, indent=2)}

Current simulation result:
{json.dumps({
    "expected_output_units": current_result.get("expected_output_units", 0),
    "target_qty": current_result.get("target_qty", 0),
    "shortfall_units": current_result.get("shortfall_units", 0),
    "completion_day": current_result.get("completion_day", 0),
    "cost_usd": current_result.get("cost_usd", 0),
    "carbon_kg": current_result.get("carbon_kg", 0),
    "warnings": current_result.get("warnings", []),
}, indent=2)}

User question:
{query}

Respond ONLY with valid JSON using this schema:
{{
  "intent": "recalculate" or "explain",
  "overrides": {{
    "oee_pct": number or null,
    "workforce_pct": number or null,
    "forecast_qty": number or null,
    "energy_price": number or null,
    "downtime_hrs": number or null,
    "optimise_for": "Time" or "Cost" or "Carbon" or null,
    "horizon_days": number or null
  }},
  "answer": "concise explanation for the user"
}}"""

    try:
        response = httpx.post(
            config.OLLAMA_URL,
            json={
                "model": config.OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=config.OLLAMA_TIMEOUT,
        )
        return _extract_json_object(response.json().get("response", ""))
    except Exception:
        return {}


def _sanitize_overrides(overrides: dict, current_params: dict) -> dict:
    cleaned = {}
    for key, value in (overrides or {}).items():
        if value in (None, ""):
            continue
        if key == "oee_pct":
            cleaned[key] = max(50.0, min(100.0, float(value)))
        elif key == "workforce_pct":
            cleaned[key] = max(50.0, min(100.0, float(value)))
        elif key == "forecast_qty":
            cleaned[key] = max(0, int(value))
        elif key == "energy_price":
            cleaned[key] = max(0.05, min(0.50, float(value)))
        elif key == "downtime_hrs":
            cleaned[key] = max(0.0, min(72.0, float(value)))
        elif key == "optimise_for":
            value = str(value).title()
            if value in {"Time", "Cost", "Carbon"}:
                cleaned[key] = value
        elif key == "horizon_days":
            cleaned[key] = max(3, min(14, int(value)))

    for key in ("oee_pct", "workforce_pct", "forecast_qty", "energy_price", "downtime_hrs", "optimise_for", "horizon_days"):
        cleaned.setdefault(key, current_params.get(key))
    return cleaned


def _build_recalc_answer(base_result: dict, new_result: dict, new_params: dict) -> str:
    delta_output = new_result["expected_output_units"] - base_result["expected_output_units"]
    delta_cost = new_result["cost_usd"] - base_result["cost_usd"]
    delta_carbon = new_result["carbon_kg"] - base_result["carbon_kg"]
    return (
        f"With OEE at {new_params['oee_pct']:.0f}% and workforce at {new_params['workforce_pct']:.0f}%, "
        f"expected output becomes {new_result['expected_output_units']:,} units "
        f"({delta_output:+,} vs current). Completion moves to Day {new_result['completion_day']} of "
        f"{new_params['horizon_days']}. Cost changes by ${delta_cost:,.0f} and carbon changes by "
        f"{delta_carbon:,.0f} kg."
    )


def _build_explanation_answer(query: str, result: dict) -> str:
    lower = query.lower()
    if "shortfall" in lower or "why" in lower:
        reasons = []
        params = result.get("parameters_used", {})
        if params.get("oee_pct", 100) < 95:
            reasons.append(f"OEE is {params.get('oee_pct', 0):.1f}%")
        if params.get("workforce_pct", 100) < 95:
            reasons.append(f"workforce coverage is {params.get('workforce_pct', 0):.1f}%")
        if params.get("downtime_hrs", 0) > 0:
            reasons.append(f"Day 1 loses {params.get('downtime_hrs', 0):.0f} downtime hours")
        reason_text = ", ".join(reasons) if reasons else "capacity is slightly below the target"
        return (
            f"The shortfall comes from {reason_text}. At the current settings the plant produces "
            f"{result['expected_output_units']:,} units against a target of {result['target_qty']:,}."
        )
    return (
        f"Current simulation lands at {result['expected_output_units']:,} units, costs "
        f"${result['cost_usd']:,.0f}, and emits {result['carbon_kg']:,.0f} kg CO2."
    )


def _apply_to_production_plan(selected_plant: str, result: dict, out: dict) -> tuple[bool, str]:
    try:
        params = result.get("parameters_used", {})
        st.session_state["selected_plant"] = selected_plant
        st.session_state["dt_plan_override"] = {
            "plant": selected_plant,
            "oee_pct": params.get("oee_pct"),
            "workforce_pct": params.get("workforce_pct"),
            "forecast_qty": params.get("forecast_qty"),
            "optimise_for": params.get("optimise_for", "Time"),
            "demand_buffer_pct": params.get("demand_buffer_pct", 0.0),
            "applied_at": st.session_state.get("orch_cursor"),
        }

        plant_df = df[df["Assigned_Facility"] == selected_plant].copy()
        plan_ctx = {
            "df": plant_df,
            "as_of_time": current_time,
            "mechanic": out.get("mechanic", {}),
            "forecast": out.get("forecast", {}),
            "forecast_qty_override": params.get("forecast_qty"),
            "oee_override": params.get("oee_pct"),
            "workforce_override": params.get("workforce_pct"),
            "demand_buffer_pct": params.get("demand_buffer_pct", 0.0),
            "optimise_for": params.get("optimise_for", "Time"),
        }
        new_plan = SchedulerAgent().run(plan_ctx)
        cached = deepcopy(st.session_state.get("orch_output") or {})
        cached.setdefault("scheduler", {})[selected_plant] = new_plan
        st.session_state["orch_output"] = cached
        return True, f"Applied to Production Plan for {selected_plant.split('(')[0].strip()}."
    except Exception as exc:
        return False, f"Apply failed: {exc}"


def _render_result_metrics(result: dict) -> None:
    params = result.get("parameters_used", {})
    st.subheader(f"Simulation Results — {result['plant_id'].split('(')[0].strip()}")
    st.caption(
        f"Parameters: OEE {params.get('oee_pct', 0):.1f}% | "
        f"Workforce {params.get('workforce_pct', 0):.1f}% | "
        f"Horizon {params.get('horizon_days', 0)} days | "
        f"Optimise for {params.get('optimise_for', 'Time')}"
    )

    shortfall_pct = (
        (result["shortfall_units"] / max(result["target_qty"], 1)) * 100
        if result["shortfall_units"] > 0 else 0.0
    )

    row1 = st.columns(4)
    row1[0].metric("Expected Output", f"{result['expected_output_units']:,} units")
    row1[1].metric("Completion", f"Day {result['completion_day']} of {params.get('horizon_days', 0)}")
    row1[2].metric(
        "Shortfall vs Target",
        f"{result['shortfall_units']:,} units" if result["shortfall_units"] else "None",
        delta=f"{shortfall_pct:.1f}%" if result["shortfall_units"] else None,
        delta_color="inverse",
    )
    row1[3].metric("Workers Needed", f"{result['workforce_needed']} / 150")

    row2 = st.columns(3)
    row2[0].metric("Estimated Cost", f"${result['cost_usd']:,.0f}")
    row2[1].metric("Carbon Emissions", f"{result['carbon_kg']:,.0f} kg CO2")
    row2[2].metric("Target Demand", f"{result['target_qty']:,} units")


def _render_trajectory_chart(result: dict, baseline_result: dict) -> None:
    current_days = [f"Day {i + 1}" for i in range(len(result["cumulative_breakdown"]))]
    baseline_days = [f"Day {i + 1}" for i in range(len(baseline_result["cumulative_breakdown"]))]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=baseline_days,
        y=baseline_result["cumulative_breakdown"],
        name="Live Baseline",
        line=dict(color="#A0A0A0", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=current_days,
        y=result["cumulative_breakdown"],
        name="Simulated Output",
        fill="tozeroy",
        line=dict(color=COLORS["info"], width=2),
        fillcolor=rgba(COLORS["info"], 0.14),
    ))
    fig.add_trace(go.Scatter(
        x=current_days,
        y=[result["target_qty"]] * len(current_days),
        name="Target Demand",
        line=dict(color=COLORS["critical"], dash="dash", width=2),
    ))
    fig.update_layout(
        title="Production Trajectory",
        plot_bgcolor="#0E1117",
        paper_bgcolor="#0E1117",
        font_color="#EEE",
        xaxis_title="",
        yaxis_title="Cumulative Units",
        legend_title="",
    )
    st.plotly_chart(fig, use_container_width=True)


st.title("Digital Twin Simulation")
st.markdown("Run plant-level what-if simulations using live defaults from the current agent outputs.")

if df.empty:
    st.warning("No data available.")
    st.stop()

out = orch()
plants = out.get("plants", sorted(df["Assigned_Facility"].unique().tolist()))

preferred_plant = st.session_state.get("selected_plant")
if st.session_state.get("dt_plant_p7") not in plants:
    st.session_state["dt_plant_p7"] = preferred_plant if preferred_plant in plants else plants[0]

col_left, col_right = st.columns([1, 2])

with col_left:
    st.subheader("Configure Simulation Parameters")
    st.caption("Default values reset from live agent outputs whenever the simulation state advances.")

    selected_plant = st.selectbox("Select Plant", options=plants, key="dt_plant_p7")
    st.session_state["selected_plant"] = selected_plant
    defaults = derive_defaults_from_agent_output(selected_plant, out, df)
    _sync_controls(selected_plant, defaults)

    st.slider("OEE %", 50, 100, value=st.session_state["dt_oee_p7"], key="dt_oee_p7")
    st.slider("Workforce Availability %", 50, 100, value=st.session_state["dt_wf_p7"], key="dt_wf_p7")
    st.number_input(
        "Demand to Meet (units)",
        0,
        50000,
        value=st.session_state["dt_fq_p7"],
        step=100,
        key="dt_fq_p7",
    )
    st.slider(
        "Energy Price ($/kWh)",
        0.05,
        0.50,
        value=st.session_state["dt_ep_p7"],
        step=0.01,
        key="dt_ep_p7",
    )
    st.slider("Machine Downtime (hrs)", 0, 72, value=st.session_state["dt_dt_p7"], step=2, key="dt_dt_p7")
    st.selectbox(
        "Optimise For",
        ["Time", "Cost", "Carbon"],
        index=["Time", "Cost", "Carbon"].index(st.session_state["dt_opt_p7"]),
        key="dt_opt_p7",
    )
    st.slider("Horizon (days)", 3, 14, value=st.session_state["dt_horizon_p7"], key="dt_horizon_p7")
    st.slider("Demand Buffer %", 0, 30, value=st.session_state["dt_buf_p7"], key="dt_buf_p7")

    run_sim = st.button("Run Simulation", type="primary", key="dt_run_p7")
    st.markdown("---")
    save_cols = st.columns(3)
    current_result = _get_current_result(selected_plant)
    for slot, col in zip(("A", "B", "C"), save_cols):
        if col.button(f"Save {slot}", key=f"dt_save_{slot}_p7"):
            if current_result:
                _save_scenario(slot, current_result)
                st.success(f"Saved as Scenario {slot}")

with col_right:
    if run_sim:
        with st.spinner(f"Running simulation for {selected_plant.split('(')[0].strip()}..."):
            current_result = simulate(**_build_sim_kwargs(selected_plant, defaults))
        _save_current_result(current_result)
    else:
        current_result = _get_current_result(selected_plant)

    baseline_result = simulate(**_build_baseline_kwargs(selected_plant, defaults))

    if current_result:
        _render_result_metrics(current_result)
        _render_trajectory_chart(current_result, baseline_result)

        for warning in current_result.get("warnings", []):
            st.warning(warning)

        if current_result.get("optimise_suggestions"):
            st.subheader("Optimisation Tips")
            for tip in current_result["optimise_suggestions"]:
                st.info(tip)

        if st.button("Apply to Production Plan", key="dt_apply_p7", type="primary"):
            ok, message = _apply_to_production_plan(selected_plant, current_result, out)
            if ok:
                st.success(message)
            else:
                st.error(message)
    else:
        st.info("Set the parameters and run a simulation to see the results.")

current_scenarios = _scenario_store().get(selected_plant, {})
comparison_results = {"Baseline": baseline_result}
comparison_results.update({f"Scenario {k}": v for k, v in current_scenarios.items()})

if len(comparison_results) >= 2:
    st.markdown("---")
    st.subheader("Scenario Comparison")
    metric_rows = []
    metrics = [
        ("Output", "expected_output_units", lambda v: f"{v:,}"),
        ("Cost", "cost_usd", lambda v: f"${v:,.0f}"),
        ("Carbon", "carbon_kg", lambda v: f"{v:,.0f} kg"),
        ("Completion", "completion_day", lambda v: f"Day {v}"),
        ("Shortfall", "shortfall_units", lambda v: f"{v:,}"),
    ]
    for label, key, formatter in metrics:
        row = {"Metric": label}
        for scenario_name, scenario_result in comparison_results.items():
            row[scenario_name] = formatter(scenario_result.get(key, 0))
        metric_rows.append(row)
    st.dataframe(pd.DataFrame(metric_rows), use_container_width=True, hide_index=True)

if current_result:
    st.markdown("---")
    st.subheader("Ask Follow-up Questions About This Simulation")
    st.caption("Ask a what-if question and the simulation will recalculate when possible.")

    if "dt_chat_history" not in st.session_state:
        st.session_state["dt_chat_history"] = []

    for msg in st.session_state["dt_chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if query := st.chat_input("e.g. What if workforce drops to 70%?", key="dt_chat_input_p7"):
        st.session_state["dt_chat_history"].append({"role": "user", "content": query})

        current_params = current_result.get("parameters_used", {})
        parsed = _ask_followup_ollama(query, current_params, current_result) or _heuristic_followup(query)
        if not parsed:
            parsed = _heuristic_followup(query)

        intent = parsed.get("intent", "explain")
        raw_overrides = parsed.get("overrides", {})

        if intent == "recalculate" or raw_overrides:
            new_params = _sanitize_overrides(raw_overrides, current_params)
            new_result = simulate(
                plant_id=selected_plant,
                oee_pct=new_params["oee_pct"],
                workforce_pct=new_params["workforce_pct"],
                forecast_qty=new_params["forecast_qty"],
                energy_price=new_params["energy_price"],
                downtime_hrs=new_params["downtime_hrs"],
                optimise_for=new_params["optimise_for"],
                horizon_days=new_params["horizon_days"],
                base_capacity=current_params.get("base_capacity", defaults.get("base_capacity", config.DIGITAL_TWIN["base_capacity"])),
                demand_buffer_pct=current_params.get("demand_buffer_pct", defaults.get("demand_buffer_pct", 0.10)),
            )
            answer = parsed.get("answer") or _build_recalc_answer(current_result, new_result, new_params)
            _save_current_result(new_result)
            for key, value in new_params.items():
                widget_key = {
                    "oee_pct": "dt_oee_p7",
                    "workforce_pct": "dt_wf_p7",
                    "forecast_qty": "dt_fq_p7",
                    "energy_price": "dt_ep_p7",
                    "downtime_hrs": "dt_dt_p7",
                    "optimise_for": "dt_opt_p7",
                    "horizon_days": "dt_horizon_p7",
                }.get(key)
                if widget_key:
                    st.session_state[widget_key] = value
        else:
            answer = parsed.get("answer") or _build_explanation_answer(query, current_result)

        st.session_state["dt_chat_history"].append({"role": "assistant", "content": answer})
        st.rerun()
