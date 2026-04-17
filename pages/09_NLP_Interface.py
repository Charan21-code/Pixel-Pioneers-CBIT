"""
pages/09_NLP_Interface.py — Natural Language Control Center

Full-page NLP interface with:
  - Ollama intent routing plus deterministic fallback parsing
  - query / simulate / reconfigure / escalate / approve / reject flows
  - Digital Twin handoff for what-if scenarios
  - scheduler replan support from plain-English commands
  - HITL department overview and queue actions
"""

from __future__ import annotations

import json
from copy import deepcopy

import httpx
import pandas as pd
import streamlit as st

import config
from agents.scheduler import SchedulerAgent
from dashboard_runtime import bootstrap_page, render_ollama_fallback_notice
from hitl.manager import HitlManager
from nlp.control_center import (
    build_query_answer,
    coerce_json_object,
    find_plant_mention,
    heuristic_intent,
    select_hitl_item,
)
from simulation.digital_twin import derive_defaults_from_agent_output, simulate

bootstrap_page("NLP Interface", "💬")

COLORS = st.session_state.get(
    "_COLORS",
    {
        "healthy": "#00C896",
        "warning": "#FFA500",
        "critical": "#FF4C4C",
        "info": "#4A9EFF",
        "card_bg": "#1E1E2E",
    },
)

df = st.session_state.get("_df", pd.DataFrame())
current_time = st.session_state.get("_current_time", pd.Timestamp.now())


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


def _toast(message: str, icon: str | None = None) -> None:
    if hasattr(st, "toast"):
        st.toast(message, icon=icon)


def _recent_logs(limit: int = 8) -> list[dict]:
    getter = st.session_state.get("_get_agent_log")
    if not getter:
        return []
    try:
        log_df = getter(limit=limit)
        if log_df.empty:
            return []
        cols = [c for c in ["logged_at", "agent_name", "severity", "facility", "message"] if c in log_df.columns]
        return log_df[cols].fillna("").head(limit).to_dict("records")
    except Exception:
        return []


def _build_context_payload(out: dict, pending_items: list[dict], pending_counts: dict) -> dict:
    finance = out.get("finance", {})
    budget = finance.get("budget_status", {})
    mechanic = out.get("mechanic", {})
    buyer_inventory = out.get("buyer_inventory", {})
    inventory_watch = sorted(
        [
            {
                "plant": plant,
                "days_remaining": values.get("days_remaining", 0),
                "lead_days": values.get("lead_days", 0),
                "status": values.get("status", "unknown"),
            }
            for plant, values in buyer_inventory.items()
        ],
        key=lambda row: row["days_remaining"],
    )[:3]

    return {
        "selected_plant": st.session_state.get("selected_plant"),
        "final_status": out.get("final_status", "UNKNOWN"),
        "system_health": out.get("system_health", 0),
        "forecast": {
            "forecast_qty": out.get("forecast", {}).get("forecast_qty", 0),
            "trend_slope": out.get("forecast", {}).get("trend_slope", 0),
            "risk_level": out.get("forecast", {}).get("risk_level", "unknown"),
            "anomaly_count": out.get("forecast", {}).get("anomaly_count", 0),
        },
        "mechanic": {
            "critical_facilities": mechanic.get("critical_facilities", []),
            "warning_facilities": mechanic.get("warning_facilities", []),
        },
        "inventory_watch": inventory_watch,
        "finance": {
            "gate_decision": finance.get("gate_decision", "UNKNOWN"),
            "budget_used_pct": budget.get("pct_used", 0),
            "remaining_usd": budget.get("remaining_usd", 0),
            "risk_score": finance.get("risk_score", 0),
        },
        "conflicts": out.get("conflicts", [])[:5],
        "pending_hitl_counts": pending_counts,
        "pending_hitl_items": [
            {
                "id": item.get("id"),
                "item_type": item.get("item_type"),
                "source": item.get("source"),
                "payload": item.get("payload", {}),
            }
            for item in pending_items[:5]
        ],
        "recent_agent_log": _recent_logs(),
    }


def _ask_ollama_intent(query: str, out: dict, pending_items: list[dict], pending_counts: dict) -> dict:
    prompt = f"""You are the Orchestrator agent for a global electronics factory.

Current system state:
{json.dumps(_build_context_payload(out, pending_items, pending_counts), indent=2, default=str)}

The user said:
{query}

Respond ONLY with valid JSON matching this schema:
{{
  "intent": "query | simulate | reconfigure | escalate | approve | reject",
  "agent": "which agent handles this",
  "confidence_pct": 0-100,
  "params": {{
    "plant": "optional plant name",
    "item_type": "optional ops|procurement|finance|maintenance|carbon",
    "item_id": "optional integer id",
    "workforce_pct": "optional number",
    "oee_pct": "optional number",
    "forecast_qty": "optional integer",
    "energy_price": "optional number",
    "downtime_hrs": "optional number",
    "horizon_days": "optional integer",
    "optimise_for": "optional Time|Cost|Carbon",
    "demand_buffer_pct": "optional number",
    "comment": "optional comment for approve/reject"
  }},
  "response": "plain English answer to show the user",
  "action": "single sentence describing the system action"
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
        return coerce_json_object(response.json().get("response", ""))
    except Exception:
        return {}


def _merge_intents(heuristic: dict, llm: dict) -> dict:
    merged = {
        "intent": heuristic.get("intent", "query"),
        "agent": heuristic.get("agent", "Orchestrator Agent"),
        "confidence_pct": heuristic.get("confidence_pct", 60),
        "params": dict(heuristic.get("params", {})),
        "response": heuristic.get("response", ""),
        "action": heuristic.get("action", ""),
    }

    if llm.get("intent") in {"query", "simulate", "reconfigure", "escalate", "approve", "reject"}:
        merged["intent"] = llm["intent"]
    if llm.get("agent"):
        merged["agent"] = str(llm["agent"]).strip()
    if isinstance(llm.get("confidence_pct"), (int, float)):
        merged["confidence_pct"] = max(0, min(100, float(llm["confidence_pct"])))
    if isinstance(llm.get("params"), dict):
        for key, value in llm["params"].items():
            if value not in (None, "", []):
                merged["params"][key] = value
    if llm.get("response"):
        merged["response"] = str(llm["response"]).strip()
    if llm.get("action"):
        merged["action"] = str(llm["action"]).strip()
    return merged


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _valid_plants(out: dict) -> list[str]:
    return out.get("plants", sorted(df["Assigned_Facility"].unique().tolist()))


def _resolve_plant(parsed: dict, out: dict) -> str | None:
    plants = _valid_plants(out)
    plant = parsed.get("params", {}).get("plant")
    if plant in plants:
        return plant
    selected = st.session_state.get("selected_plant")
    if selected in plants:
        return selected
    return plants[0] if plants else None


def _summarise_params(params: dict) -> str:
    labels = {
        "plant": "Plant",
        "workforce_pct": "Workforce",
        "oee_pct": "OEE",
        "forecast_qty": "Forecast",
        "energy_price": "Energy Price",
        "downtime_hrs": "Downtime",
        "horizon_days": "Horizon",
        "optimise_for": "Optimise",
        "demand_buffer_pct": "Demand Buffer",
        "item_type": "Queue",
        "item_id": "Item",
    }
    parts = []
    for key in [
        "plant",
        "workforce_pct",
        "oee_pct",
        "forecast_qty",
        "energy_price",
        "downtime_hrs",
        "horizon_days",
        "optimise_for",
        "demand_buffer_pct",
        "item_type",
        "item_id",
    ]:
        if key not in params:
            continue
        value = params[key]
        if key in {"workforce_pct", "oee_pct", "demand_buffer_pct"}:
            suffix = "%" if key != "demand_buffer_pct" else "%"
            pct_value = float(value) * 100 if key == "demand_buffer_pct" and float(value) <= 1 else float(value)
            value = f"{pct_value:.0f}{suffix}"
        elif key == "energy_price":
            value = f"${float(value):.2f}/kWh"
        elif key == "downtime_hrs":
            value = f"{float(value):.0f} hrs"
        elif key == "forecast_qty":
            value = f"{int(value):,}"
        parts.append(f"{labels[key]}: {value}")
    return " | ".join(parts)


def _build_sim_kwargs(plant: str, out: dict, params: dict) -> dict:
    defaults = derive_defaults_from_agent_output(plant, out, df)
    forecast_qty = int(params.get("forecast_qty", defaults["forecast_qty"]))
    demand_buffer = float(params.get("demand_buffer_pct", defaults.get("demand_buffer_pct", 0.10)))
    if demand_buffer > 1:
        demand_buffer = demand_buffer / 100.0

    return {
        "plant_id": plant,
        "oee_pct": _clamp(float(params.get("oee_pct", defaults["oee_pct"])), 50.0, 100.0),
        "workforce_pct": _clamp(float(params.get("workforce_pct", defaults["workforce_pct"])), 50.0, 100.0),
        "forecast_qty": max(0, forecast_qty),
        "energy_price": _clamp(float(params.get("energy_price", defaults["energy_price"])), 0.05, 0.50),
        "downtime_hrs": _clamp(float(params.get("downtime_hrs", defaults["downtime_hrs"])), 0.0, 72.0),
        "optimise_for": str(params.get("optimise_for", defaults.get("optimise_for", "Time"))).title(),
        "horizon_days": int(_clamp(float(params.get("horizon_days", defaults["horizon_days"])), 3.0, 14.0)),
        "base_capacity": int(defaults.get("base_capacity", config.DIGITAL_TWIN["base_capacity"])),
        "demand_buffer_pct": _clamp(demand_buffer, 0.0, 0.30),
    }


def _run_simulation_command(parsed: dict, out: dict) -> tuple[str, str, dict, bool]:
    plant = _resolve_plant(parsed, out)
    if not plant:
        return "I couldn't find a plant to simulate.", "No simulation was run.", {}, False

    sim_kwargs = _build_sim_kwargs(plant, out, parsed.get("params", {}))
    result = simulate(**sim_kwargs)
    st.session_state["selected_plant"] = plant
    st.session_state.setdefault("dt_results", {})[plant] = result
    st.session_state["dt_result"] = result
    st.session_state["dt_result_plant"] = plant

    answer = parsed.get("response") or (
        f"{plant} would produce about {result['expected_output_units']:,} units over "
        f"{sim_kwargs['horizon_days']} days, with a shortfall of {result['shortfall_units']:,} units."
    )
    action = parsed.get("action") or (
        f"Digital Twin scenario updated for {plant.split('(')[0].strip()}. Open Page 7 to inspect the breakdown."
    )
    return answer, action, result.get("parameters_used", {}), True


def _scheduler_context_for(plant: str, out: dict, params: dict) -> dict:
    defaults = derive_defaults_from_agent_output(plant, out, df)
    n_plants = max(1, len(_valid_plants(out)))
    forecast_default = defaults["forecast_qty"]
    if not forecast_default and out.get("forecast", {}).get("forecast_qty"):
        forecast_default = int(out["forecast"]["forecast_qty"] / n_plants)

    demand_buffer = float(params.get("demand_buffer_pct", 0.10))
    if demand_buffer > 1:
        demand_buffer = demand_buffer / 100.0

    return {
        "forecast_qty_override": int(params.get("forecast_qty", forecast_default)),
        "oee_override": _clamp(float(params.get("oee_pct", defaults["oee_pct"])), 50.0, 100.0),
        "workforce_override": _clamp(float(params.get("workforce_pct", defaults["workforce_pct"])), 50.0, 100.0),
        "demand_buffer_pct": _clamp(demand_buffer, 0.0, 0.30),
        "optimise_for": str(params.get("optimise_for", "Time")).title(),
    }


def _run_reconfigure_command(parsed: dict, out: dict) -> tuple[str, str, dict, bool]:
    plants = _valid_plants(out)
    target_plant = parsed.get("params", {}).get("plant")
    target_plants = [target_plant] if target_plant in plants else plants

    if not target_plants:
        return "I couldn't find any plants to replan.", "No scheduler action was taken.", {}, False

    cached = deepcopy(st.session_state.get("orch_output") or out)
    applied_params = {}
    updated = []

    for plant in target_plants:
        plant_df = df[df["Assigned_Facility"] == plant].copy()
        if plant_df.empty:
            continue
        scheduler_params = _scheduler_context_for(plant, out, parsed.get("params", {}))
        plan_ctx = {
            "df": plant_df,
            "as_of_time": current_time,
            "mechanic": cached.get("mechanic", {}),
            "forecast": cached.get("forecast", {}),
            **scheduler_params,
        }
        new_plan = SchedulerAgent().run(plan_ctx)
        cached.setdefault("scheduler", {})[plant] = new_plan
        applied_params = {"plant": plant, **scheduler_params}
        updated.append(plant)

        if len(target_plants) == 1:
            st.session_state["selected_plant"] = plant
            st.session_state["dt_plan_override"] = {
                "plant": plant,
                "forecast_qty": scheduler_params["forecast_qty_override"],
                "oee_pct": scheduler_params["oee_override"],
                "workforce_pct": scheduler_params["workforce_override"],
                "demand_buffer_pct": scheduler_params["demand_buffer_pct"],
                "optimise_for": scheduler_params["optimise_for"],
                "applied_at": st.session_state.get("orch_cursor"),
            }

    if not updated:
        return "The scheduler couldn't build a new plan from that command.", "No scheduler plan was updated.", {}, False

    st.session_state["orch_output"] = cached
    short_names = [plant.split("(")[0].strip() for plant in updated]
    answer = parsed.get("response") or (
        f"Scheduler plans were rebuilt for {', '.join(short_names)}."
    )
    action = parsed.get("action") or (
        f"Updated {len(updated)} scheduler plan(s). Open Page 4 to review the latest production plan."
    )
    return answer, action, applied_params, True


def _escalation_payload(item_type: str, plant: str | None, query: str, out: dict) -> dict:
    payload = {
        "plant": plant,
        "query": query,
        "message": f"User-triggered escalation from NLP Interface: {query}",
        "final_status": out.get("final_status", "UNKNOWN"),
        "system_health": out.get("system_health", 0),
    }

    if item_type == "procurement":
        inventory = out.get("buyer_inventory", {})
        snapshot = inventory.get(plant) if plant else None
        if snapshot:
            payload.update(
                {
                    "days_remaining": snapshot.get("days_remaining", 0),
                    "lead_days": snapshot.get("lead_days", 0),
                    "reorder_qty": snapshot.get("reorder_qty", 0),
                    "cost_usd": snapshot.get("cost_usd", 0),
                }
            )
    elif item_type == "finance":
        finance = out.get("finance", {})
        payload.update(
            {
                "risk_score": finance.get("risk_score", 0),
                "gate_decision": finance.get("gate_decision", "UNKNOWN"),
                "budget_status": finance.get("budget_status", {}),
                "suggestion": (finance.get("suggestions") or [""])[0],
            }
        )
    elif item_type == "maintenance":
        risks = out.get("mechanic", {}).get("facility_risks", {})
        risk = risks.get(plant, {}) if plant else {}
        payload.update(
            {
                "facility": plant,
                "risk_score": risk.get("risk_score", 0),
                "ttf_hrs": risk.get("ttf_hrs", 0),
                "oee_pct": risk.get("oee_pct", 0),
                "temp_c": risk.get("temp_c", 0),
            }
        )
    elif item_type == "carbon":
        environ = out.get("environ", {})
        payload.update(
            {
                "peak_penalty_pct": environ.get("peak_penalty_pct", 0),
                "total_penalty_usd": environ.get("total_penalty_usd", 0),
                "recommendation": environ.get("recommendation", ""),
                "estimated_savings_usd": environ.get("estimated_savings_usd", 0),
            }
        )
    else:
        payload["conflicts"] = out.get("conflicts", [])[:3]

    return payload


def _run_escalate_command(parsed: dict, query: str, out: dict, hm: HitlManager) -> tuple[str, str, dict, bool]:
    params = parsed.get("params", {})
    item_type = params.get("item_type", "ops")
    if item_type not in {"ops", "procurement", "finance", "maintenance", "carbon"}:
        item_type = "ops"
    plant = params.get("plant")

    payload = _escalation_payload(item_type, plant, query, out)
    item_id = hm.enqueue(item_type, "NLP Interface", payload)
    success = item_id != -1
    answer = parsed.get("response") or (
        f"I flagged this for human review in the {item_type} queue."
        if success else
        "I couldn't submit that escalation to the HITL inbox."
    )
    action = parsed.get("action") or (
        f"Escalation pushed to HITL Inbox as item #{item_id}."
        if success else
        "Escalation failed."
    )
    return answer, action, {"item_type": item_type, "plant": plant, "item_id": item_id}, success


def _resolve_command(
    parsed: dict,
    query: str,
    out: dict,
    hm: HitlManager,
    approve: bool,
) -> tuple[str, str, dict, bool]:
    pending = hm.get_pending()
    item = select_hitl_item(query, pending, _valid_plants(out))
    if not item:
        verb = "approve" if approve else "reject"
        return f"I couldn't find a pending HITL item to {verb}.", "No queue item matched that request.", {}, False

    roles = {
        "ops": "Operations Head",
        "procurement": "Supply Chain Head",
        "finance": "CFO",
        "maintenance": "Plant Manager",
        "carbon": "Sustainability Head",
    }
    default_comment = "Approved via NLP command" if approve else "Rejected via NLP command"
    comment = parsed.get("params", {}).get("comment") or default_comment
    resolver = hm.approve if approve else hm.reject
    ok = resolver(item["id"], comment, roles.get(item.get("item_type"), "Human Head"))
    verb = "approved" if approve else "rejected"
    answer = parsed.get("response") or (
        f"Item #{item['id']} has been {verb}."
        if ok else
        f"I couldn't update item #{item['id']}."
    )
    action = parsed.get("action") or (
        f"{verb.title()} HITL item #{item['id']} in the {item.get('item_type', 'unknown')} queue."
        if ok else
        f"Failed to update HITL item #{item['id']}."
    )
    return answer, action, {"item_id": item["id"], "item_type": item.get("item_type"), "comment": comment}, ok


def _run_query_command(parsed: dict, query: str, out: dict, hm: HitlManager) -> tuple[str, str, dict, bool]:
    counts = hm.get_counts()
    answer, agent = build_query_answer(
        query,
        out,
        df,
        pending_counts=counts,
        selected_plant=st.session_state.get("selected_plant"),
    )
    if parsed.get("response"):
        answer = parsed["response"]
    return answer, "Read-only query answered from current orchestrator state.", {}, True if agent else True


def _execute_intent(parsed: dict, query: str, out: dict, hm: HitlManager) -> dict:
    intent = parsed.get("intent", "query")

    if intent == "simulate":
        answer, action, params_used, success = _run_simulation_command(parsed, out)
        agent = parsed.get("agent") or "Digital Twin"
    elif intent == "reconfigure":
        answer, action, params_used, success = _run_reconfigure_command(parsed, out)
        agent = parsed.get("agent") or "Scheduler Agent"
    elif intent == "escalate":
        answer, action, params_used, success = _run_escalate_command(parsed, query, out, hm)
        agent = parsed.get("agent") or "Orchestrator Agent"
    elif intent == "approve":
        answer, action, params_used, success = _resolve_command(parsed, query, out, hm, approve=True)
        agent = parsed.get("agent") or "HITL Manager"
    elif intent == "reject":
        answer, action, params_used, success = _resolve_command(parsed, query, out, hm, approve=False)
        agent = parsed.get("agent") or "HITL Manager"
    else:
        answer, action, params_used, success = _run_query_command(parsed, query, out, hm)
        _, fallback_agent = build_query_answer(query, out, df, pending_counts=hm.get_counts())
        agent = parsed.get("agent") or fallback_agent

    return {
        "answer": answer,
        "action": action,
        "params_used": params_used,
        "success": success,
        "agent": agent,
    }


st.title("Natural Language Control Center")
st.markdown(
    f"""
<div style="background:{COLORS['card_bg']}; border:1px solid #333; border-radius:10px;
padding:16px 18px; margin-bottom:20px;">
<b style="font-size:15px;">Talk to the Agentic System.</b> Ask questions, change plans,
trigger simulations, or resolve HITL items in plain English.<br/>
<span style="font-size:12px; color:#888;">
Ollama model: <code>{config.OLLAMA_MODEL}</code> | Digital Twin and scheduler fallbacks stay active even if the LLM is offline.
</span>
</div>
""",
    unsafe_allow_html=True,
)
render_ollama_fallback_notice("NLP routing")

out = orch()

if "nlp_history" not in st.session_state:
    st.session_state["nlp_history"] = []

if df.empty or not out:
    st.warning("No orchestrator output is available yet. Trigger the agents from the sidebar and try again.")
    st.stop()

with st.expander("How The NLP Router Works", expanded=False):
    st.markdown(
        "Your message is interpreted against the live orchestrator state, active HITL queue, and recent agent log."
    )
    st.code(
        """Intent schema:
{
  "intent": "query | simulate | reconfigure | escalate | approve | reject",
  "agent": "responsible agent",
  "params": {"plant": "...", "...": "..."},
  "response": "plain-English answer",
  "action": "system action taken"
}""",
        language="json",
    )
    intent_rows = [
        {"Intent": "query", "Example": "How many delays this week?", "Action": "Answer from current orchestrator state"},
        {"Intent": "simulate", "Example": "What if Foxconn goes offline for 8 hours?", "Action": "Run a Digital Twin scenario and save it"},
        {"Intent": "reconfigure", "Example": "Reduce workforce to 80% and replan Noida", "Action": "Rebuild scheduler plans with overrides"},
        {"Intent": "escalate", "Example": "Flag the Noida inventory situation", "Action": "Push an item to the HITL queue"},
        {"Intent": "approve", "Example": "Approve the procurement order for Noida", "Action": "Resolve a matching HITL item as approved"},
        {"Intent": "reject", "Example": "Reject the maintenance request because capacity is available elsewhere", "Action": "Resolve a matching HITL item as rejected"},
    ]
    st.dataframe(pd.DataFrame(intent_rows), use_container_width=True, hide_index=True)

st.markdown("---")

# ── Suggested queries (visible when chat is empty) ─────────────────────────────
if not st.session_state["nlp_history"]:
    st.markdown(
        "<div style='color:#aaa;font-size:13px;margin-bottom:10px;'>💡 "
        "<b>Suggested queries — click any to try:</b></div>",
        unsafe_allow_html=True,
    )
    _sug_rows = [
        [
            "🔍 How many delays this week?",
            "📦 What's Noida's inventory status?",
            "💰 What is the current finance risk score?",
            "🌱 What's the carbon compliance status?",
        ],
        [
            "🧬 What if Foxconn goes offline for 8 hours?",
            "⚙️ Reduce Noida workforce to 80% and replan",
            "🚨 Flag the Noida inventory situation",
            "✅ Approve the latest procurement order",
        ],
    ]
    for _ri, _row in enumerate(_sug_rows):
        _bcols = st.columns(len(_row))
        for _ci, _sug in enumerate(_row):
            if _bcols[_ci].button(
                _sug,
                key=f"nlp_sug_{_ri}_{_ci}",
                use_container_width=True,
            ):
                st.session_state["nlp_auto_query"] = _sug
                st.rerun()
    st.markdown("<br/>", unsafe_allow_html=True)

for msg in st.session_state["nlp_history"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        meta = msg.get("meta", {})
        if meta:
            caption_parts = []
            if meta.get("intent"):
                caption_parts.append(f"Intent: {meta['intent']}")
            if meta.get("agent"):
                caption_parts.append(f"Agent: {meta['agent']}")
            if meta.get("confidence_pct") is not None:
                caption_parts.append(f"Confidence: {float(meta['confidence_pct']):.0f}%")
            if caption_parts:
                st.caption(" | ".join(caption_parts))
            if meta.get("params_summary"):
                st.info(meta["params_summary"])
            if meta.get("action"):
                (st.success if meta.get("success") else st.warning)(meta["action"])


hm = HitlManager()
pending_counts = hm.get_counts()
pending_items = hm.get_pending()

# Support both manual typing and suggested-query buttons
_auto_q  = st.session_state.pop("nlp_auto_query", None)
_typed_q = st.chat_input("Ask anything or give a command...", key="nlp_chat_input_p9")
query    = _typed_q or _auto_q
if query:
    st.session_state["nlp_history"].append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    heuristic = heuristic_intent(
        query,
        _valid_plants(out),
        selected_plant=st.session_state.get("selected_plant"),
    )
    llm_parsed = _ask_ollama_intent(query, out, pending_items, pending_counts)
    parsed = _merge_intents(heuristic, llm_parsed)
    parsed_plant = parsed.get("params", {}).get("plant")
    valid_plants = _valid_plants(out)
    if parsed_plant not in valid_plants:
        resolved = find_plant_mention(str(parsed_plant or query), valid_plants)
        if resolved:
            parsed["params"]["plant"] = resolved
        elif heuristic.get("params", {}).get("plant") in valid_plants:
            parsed["params"]["plant"] = heuristic["params"]["plant"]
    result = _execute_intent(parsed, query, out, hm)

    params_summary = _summarise_params(result.get("params_used", {}))
    history_meta = {
        "intent": parsed.get("intent"),
        "agent": result.get("agent"),
        "confidence_pct": parsed.get("confidence_pct"),
        "action": result.get("action"),
        "params_summary": params_summary,
        "success": result.get("success", False),
    }

    with st.chat_message("assistant"):
        st.markdown(result["answer"])
        st.caption(
            f"Intent: {parsed.get('intent', 'query')} | "
            f"Agent: {result.get('agent', 'Orchestrator Agent')} | "
            f"Confidence: {float(parsed.get('confidence_pct', 0)):.0f}%"
        )
        if params_summary:
            st.info(params_summary)
        if result.get("action"):
            (st.success if result.get("success") else st.warning)(result["action"])

    if result.get("success") and result.get("action"):
        _toast(result["action"], icon="✅")

    st.session_state["nlp_history"].append(
        {
            "role": "assistant",
            "content": result["answer"],
            "meta": history_meta,
        }
    )

    limit = config.NLP.get("history_limit", 20) * 2
    if len(st.session_state["nlp_history"]) > limit:
        st.session_state["nlp_history"] = st.session_state["nlp_history"][-limit:]

if st.session_state["nlp_history"]:
    if st.button("Clear Chat History", key="nlp_clear_p9"):
        st.session_state["nlp_history"] = []
        st.rerun()

st.markdown("---")
st.subheader("Pending Human Approvals by Department")

heads = [
    ("Operations Head", "ops", "Production plans and orchestrator escalations"),
    ("Supply Chain Head", "procurement", "Manual and emergency purchase orders"),
    ("CFO", "finance", "Budget gate overrides and spend escalations"),
    ("Plant Manager", "maintenance", "Shutdowns, reroutes, and critical maintenance"),
    ("Sustainability Head", "carbon", "Carbon compliance and shift rescheduling"),
]

cols = st.columns(len(heads))
for idx, (head, item_type, description) in enumerate(heads):
    count = pending_counts.get(item_type, 0)
    color = (
        COLORS["critical"] if count > 2 else
        COLORS["warning"] if count > 0 else
        COLORS["healthy"]
    )
    with cols[idx]:
        st.markdown(
            f"""
<div style="text-align:center; border:1px solid #333; border-radius:8px; padding:14px;
background:{COLORS['card_bg']}; min-height:136px;">
  <div style="font-size:26px; color:{color}; font-weight:bold;">{count}</div>
  <div style="font-size:12px; color:#ddd; margin-top:4px;"><b>{head}</b></div>
  <div style="font-size:11px; color:#888; margin-top:6px;">{description}</div>
</div>
""",
            unsafe_allow_html=True,
        )
        if count > 0:
            if st.button(
                "📥 Go to Inbox",
                key=f"dept_nav_{idx}",
                use_container_width=True,
            ):
                try:
                    st.switch_page("pages/10_HITL_Inbox.py")
                except Exception:
                    st.info("Open '10 HITL Inbox' in the sidebar.")
        else:
            st.caption("✅ All Clear")
