"""
pages/09_NLP_Interface.py — Natural Language Control Center
Phase 2: Full dedicated NLP page with Ollama intent routing, action dispatch,
         department heads panel, and persistent chat history.
"""

import streamlit as st
import pandas as pd
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


# ── Page Header ────────────────────────────────────────────────────────────────
st.title("💬 Natural Language Control Center")
st.markdown("""
<div style="background:#1E1E2E; border:1px solid #333; border-radius:8px; padding:14px 18px; margin-bottom:20px;">
    <b style="font-size:15px;">Talk to the Agentic System.</b> Ask questions, change plans, trigger agent re-runs, or approve/reject HITL items — all in plain English.<br/>
    <span style="font-size:12px; color:#888;">Powered by Ollama · Model: <code>{model}</code></span>
</div>
""".format(model=config.OLLAMA_MODEL), unsafe_allow_html=True)

out = orch()

if "nlp_history" not in st.session_state:
    st.session_state["nlp_history"] = []

# ── Intent → Action Table (collapsible) ───────────────────────────────────────
with st.expander("📋 Supported Commands & Intents", expanded=False):
    intent_rows = [
        {"Intent": "`query`",       "Example": "How many delays this week?",         "Action": "Answer from current orch output"},
        {"Intent": "`simulate`",    "Example": "What if Foxconn goes offline?",       "Action": "Update Digital Twin sliders + re-run"},
        {"Intent": "`reconfigure`", "Example": "Reduce workforce to 80% and replan", "Action": "Re-run specific agent with new params"},
        {"Intent": "`escalate`",    "Example": "Flag the Noida inventory situation", "Action": "Push to HITL queue"},
        {"Intent": "`approve`",     "Example": "Approve the procurement order",      "Action": "Call HitlManager.approve()"},
        {"Intent": "`reject`",      "Example": "Reject the plan from Mechanic",      "Action": "Call HitlManager.reject()"},
    ]
    st.dataframe(pd.DataFrame(intent_rows), use_container_width=True, hide_index=True)

st.markdown("---")

# ── Chat History ──────────────────────────────────────────────────────────────
for msg in st.session_state["nlp_history"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("meta"):
            st.caption(msg["meta"])

# ── Chat Input + Processing ───────────────────────────────────────────────────
if query := st.chat_input("Ask anything or give a command…", key="nlp_chat_input_p9"):
    st.session_state["nlp_history"].append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    # Build system context
    finance_health = out.get("finance", {}).get("health_score", "?")
    forecast_qty   = out.get("forecast", {}).get("forecast_qty", "?")
    final_status   = out.get("final_status", "?")
    crit_facs      = out.get("mechanic", {}).get("critical_facilities", [])
    n_conflicts    = len(out.get("conflicts", []))
    budget_status  = out.get("finance", {}).get("budget_status", {})
    pct_used       = budget_status.get("pct_used", 0)
    inv_data       = out.get("buyer_inventory", {})
    min_days       = min((v.get("days_remaining", 0) for v in inv_data.values()), default=0)

    system_context = (
        f"Current production system state:\n"
        f"- Orchestrator status: {final_status}\n"
        f"- Demand forecast (7-day): {forecast_qty} units\n"
        f"- Finance health: {finance_health}/100 | Budget used: {pct_used:.1f}%\n"
        f"- Critical facilities: {crit_facs or 'None'}\n"
        f"- Active conflicts: {n_conflicts}\n"
        f"- Minimum inventory remaining: {min_days:.1f} days\n"
    )

    answer      = ""
    agent_label = "Orchestrator Agent"
    action_taken = None

    try:
        resp = httpx.post(
            config.OLLAMA_URL,
            json={
                "model":  config.OLLAMA_MODEL,
                "prompt": (
                    f"You are the Orchestrator AI for a global Samsung electronics factory.\n\n"
                    f"{system_context}\n"
                    f"The user said: \"{query}\"\n\n"
                    "Respond with valid JSON only (no other text):\n"
                    "{\n"
                    "  \"intent\": \"query | simulate | reconfigure | escalate | approve | reject\",\n"
                    "  \"agent\": \"which agent handles this\",\n"
                    "  \"params\": {},\n"
                    "  \"response\": \"plain English answer to show the user\",\n"
                    "  \"action\": \"what action to take in the system\"\n"
                    "}"
                ),
                "stream": False,
            },
            timeout=config.OLLAMA_TIMEOUT,
        )
        raw = resp.json().get("response", "").strip()

        # Try to parse JSON; fall back to plain text
        import json, re
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            parsed   = json.loads(json_match.group())
            answer   = parsed.get("response", raw)
            intent   = parsed.get("intent", "query")
            agent_label = f"{parsed.get('agent', 'Orchestrator Agent')} (Ollama)"

            # ── Intent dispatch ──────────────────────────────────────────────
            if intent == "escalate":
                try:
                    from hitl.manager import HitlManager
                    HitlManager().enqueue("ops", "NLP Interface", {
                        "query":   query,
                        "message": f"User-triggered escalation: {query}",
                    })
                    action_taken = "✅ Escalation pushed to HITL Inbox (Operations tab)."
                except Exception as e:
                    action_taken = f"⚠️ HITL escalation failed: {e}"

            elif intent == "approve":
                try:
                    from hitl.manager import HitlManager
                    pending = HitlManager().get_pending()
                    if pending:
                        first = pending[0]
                        HitlManager().approve(first["id"], "Approved via NLP", "NLP Interface")
                        action_taken = f"✅ Approved item #{first['id']} via NLP command."
                    else:
                        action_taken = "ℹ️ No pending HITL items to approve."
                except Exception as e:
                    action_taken = f"⚠️ Approve failed: {e}"

            elif intent == "reject":
                try:
                    from hitl.manager import HitlManager
                    pending = HitlManager().get_pending()
                    if pending:
                        first = pending[0]
                        HitlManager().reject(first["id"], "Rejected via NLP", "NLP Interface")
                        action_taken = f"❌ Rejected item #{first['id']} via NLP command."
                    else:
                        action_taken = "ℹ️ No pending HITL items to reject."
                except Exception as e:
                    action_taken = f"⚠️ Reject failed: {e}"
        else:
            answer = raw or "I couldn't generate a structured response."

    except Exception:
        # Rule-based fallback
        q = query.lower()
        if any(k in q for k in ("delay", "late", "on-time")):
            delayed = df[df["Schedule_Status"] == "Delayed"] if not df.empty else pd.DataFrame()
            answer  = (
                f"There are currently **{len(delayed)} delayed events** in the current window. "
                "Most are due to capacity overflows or machine maintenance rerouting."
            )
            agent_label = "Orchestrator Agent (fallback)"
        elif any(k in q for k in ("fail", "machine", "ttf", "maintenance")):
            worst_ttf = df["Predicted_Time_To_Failure_Hrs"].min() if not df.empty else 0
            answer    = (
                f"Most at-risk machine has **Predicted TTF of {worst_ttf:.1f} hours**. "
                "Navigate to the **Machine Health** page for full sensor data."
            )
            agent_label = "Mechanic Agent (fallback)"
        elif any(k in q for k in ("carbon", "energy", "emission", "peak")):
            carbon_total = df["Carbon_Emissions_kg"].sum() if not df.empty else 0
            peak_penalty = df[df["Grid_Pricing_Period"] == "Peak"]["Carbon_Cost_Penalty_USD"].sum() if not df.empty else 0
            answer = (
                f"Tracking **{carbon_total:,.0f} kg CO₂** total. "
                f"Peak-hour carbon penalties: **${peak_penalty:,.0f}**. "
                "See the Carbon & Energy page for full compliance analysis."
            )
            agent_label = "Environmentalist (fallback)"
        elif any(k in q for k in ("inventory", "stock", "order", "lead")):
            min_stock = df["Raw_Material_Inventory_Units"].min() if not df.empty else 0
            answer    = (
                f"Minimum inventory across plants: **{min_stock:,} units**. "
                "Navigate to **Inventory & Logistics** for lead-time analysis and reorder recommendations."
            )
            agent_label = "Buyer Agent (fallback)"
        elif any(k in q for k in ("demand", "forecast", "units")):
            fq = out.get("forecast", {}).get("forecast_qty", "?")
            answer = f"7-day demand forecast: **{fq} units**. Trend: {out.get('forecast',{}).get('trend_slope', 0):+.1f} units/day."
            agent_label = "Forecaster Agent (fallback)"
        elif any(k in q for k in ("budget", "finance", "cost", "money")):
            answer = (
                f"Finance health score: **{finance_health}/100**. "
                f"Budget utilisation: **{pct_used:.1f}%**. "
                "See the Finance Dashboard for complete breakdown."
            )
            agent_label = "Finance Agent (fallback)"
        else:
            answer = (
                f"System status: **{final_status}**. "
                f"Finance health: **{finance_health}/100**. "
                f"Conflicts: **{n_conflicts}**. "
                "Ask about delays, inventory, carbon, demand forecasts, or machine health."
            )
            agent_label = "Orchestrator Agent (fallback)"

    with st.chat_message("assistant"):
        st.markdown(answer)
        st.caption(f"🤖 Agent: {agent_label}")
        if action_taken:
            if "✅" in action_taken:
                st.success(action_taken)
            else:
                st.warning(action_taken)

    st.session_state["nlp_history"].append({
        "role": "assistant",
        "content": answer,
        "meta": f"Agent: {agent_label}",
    })

    # Trim history
    limit = config.NLP.get("history_limit", 20) * 2
    if len(st.session_state["nlp_history"]) > limit:
        st.session_state["nlp_history"] = st.session_state["nlp_history"][-limit:]

# ── Clear history button ───────────────────────────────────────────────────────
if st.session_state["nlp_history"]:
    if st.button("🗑️ Clear Chat History", key="nlp_clear_p9"):
        st.session_state["nlp_history"] = []
        st.rerun()

# ── Department Heads Notification Panel ───────────────────────────────────────
st.markdown("---")
st.subheader("📋 Pending Human Approvals by Department")

try:
    from hitl.manager import HitlManager
    counts = HitlManager().get_counts()
    heads  = [
        ("⚙️ Operations Head",      "ops",         counts.get("ops", 0)),
        ("📦 Supply Chain Head",    "procurement",  counts.get("procurement", 0)),
        ("💰 CFO",                  "finance",      counts.get("finance", 0)),
        ("🔧 Plant Manager",        "maintenance",  counts.get("maintenance", 0)),
        ("🌱 Sustainability Head",  "carbon",       counts.get("carbon", 0)),
    ]
    hcols = st.columns(len(heads))
    for i, (head, itype, cnt) in enumerate(heads):
        color = COLORS["critical"] if cnt > 2 else COLORS["warning"] if cnt > 0 else COLORS["healthy"]
        with hcols[i]:
            st.markdown(f"""
            <div style="text-align:center; border:1px solid #333; border-radius:8px;
                        padding:14px; background:{COLORS['card_bg']};">
                <div style="font-size:26px; color:{color}; font-weight:bold;">{cnt}</div>
                <div style="font-size:11px; color:#ddd; margin-top:4px;">{head}</div>
                <div style="font-size:11px; color:#666;">{itype}</div>
                {"<div style='font-size:11px; color:" + COLORS['healthy'] + ";margin-top:4px;'>All Clear ✅</div>" if cnt == 0 else ""}
            </div>
            """, unsafe_allow_html=True)
except Exception:
    st.info("HITL counts unavailable.")
