"""
pages/10_HITL_Inbox.py — Human-In-The-Loop Inbox

Department-specific review center for:
  - Operations
  - Procurement
  - Finance
  - Engineering
  - Sustainability
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard_runtime import bootstrap_page, render_ollama_fallback_notice
from hitl.manager import HitlManager

bootstrap_page("HITL Inbox", "📥")

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

ROLE_BY_TYPE = {
    "ops": "Operations Head",
    "procurement": "Supply Chain Head",
    "finance": "CFO",
    "maintenance": "Plant Manager",
    "carbon": "Sustainability Head",
}

DEPT_TABS = [
    ("⚙️ Operations", "ops", "Orchestrator / Scheduler", COLORS["info"]),
    ("📦 Procurement", "procurement", "Buyer Agent", COLORS["warning"]),
    ("💰 Finance", "finance", "Finance Agent", "#A78BFA"),
    ("🔧 Engineering", "maintenance", "Mechanic Agent", COLORS["critical"]),
    ("🌱 Sustainability", "carbon", "Environmentalist Agent", COLORS["healthy"]),
]


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


def _time_ago(value) -> str:
    try:
        ts = pd.to_datetime(value)
        if ts.tzinfo is not None:
            ts = ts.tz_convert(None)
        now = pd.Timestamp.utcnow().tz_localize(None)
        delta = now - ts
        minutes = max(0, int(delta.total_seconds() // 60))
        if minutes < 1:
            return "Submitted just now"
        if minutes < 60:
            return f"Submitted {minutes} min ago"
        hours = minutes // 60
        if hours < 24:
            return f"Submitted {hours} hrs ago"
        days = hours // 24
        return f"Submitted {days} day(s) ago"
    except Exception:
        return f"Submitted {str(value)[:19]}"


def _fmt_currency(value) -> str:
    try:
        return f"${float(value):,.0f}"
    except Exception:
        return "$0"


def _card_header(title: str, accent: str, source: str, created_label: str, facility: str | None = None) -> None:
    facility_line = (
        f"<div style='font-size:12px; color:#aaa; margin-top:4px;'>Plant / Facility: "
        f"<b style='color:#ddd;'>{facility}</b></div>"
        if facility else
        ""
    )
    st.markdown(
        f"""
<div style="border:1px solid #333; border-left:5px solid {accent}; border-radius:10px;
background:{COLORS['card_bg']}; padding:16px 18px; margin-bottom:14px;">
  <div style="display:flex; justify-content:space-between; align-items:center; gap:10px;">
    <div style="font-size:15px; font-weight:bold; color:{accent};">{title}</div>
    <div style="font-size:12px; color:#777;">{created_label}</div>
  </div>
  <div style="font-size:12px; color:#bbb; margin-top:4px;">Submitted by: <b>{source}</b></div>
  {facility_line}
</div>
""",
        unsafe_allow_html=True,
    )


def _resolve_buttons(
    hm: HitlManager,
    item: dict,
    approve_label: str,
    reject_label: str,
    comment_prefix_approve: str,
    comment_prefix_reject: str,
    extra_action: tuple[str, str, str] | None = None,
) -> None:
    item_id = item["id"]
    item_type = item.get("item_type")
    role = ROLE_BY_TYPE.get(item_type, "Human Head")

    if extra_action:
        b1, b2, b3, b4 = st.columns([2, 2, 2, 3])
        extra_label, extra_comment_prefix, extra_payload_suffix = extra_action
        comment_col = b4
    else:
        b1, b2, b3 = st.columns([2, 2, 3])
        comment_col = b3

    with comment_col:
        comment = st.text_input(
            "Comment",
            key=f"comment_{item_id}",
            label_visibility="collapsed",
            placeholder="Add a comment for the audit trail",
        )

    with b1:
        if st.button(approve_label, key=f"approve_{item_id}", type="primary", use_container_width=True):
            note = comment or comment_prefix_approve
            if hm.approve(item_id, note, role):
                st.success(f"Item #{item_id} approved.")
                st.rerun()

    with b2:
        if st.button(reject_label, key=f"reject_{item_id}", use_container_width=True):
            note = comment or comment_prefix_reject
            if hm.reject(item_id, note, role):
                st.warning(f"Item #{item_id} rejected.")
                st.rerun()

    if extra_action:
        with b3:
            if st.button(extra_label, key=f"extra_{item_id}", use_container_width=True):
                note = comment or extra_comment_prefix
                if hm.approve(item_id, f"{note} | {extra_payload_suffix}", role):
                    st.success(f"Item #{item_id} approved with modification.")
                    st.rerun()


def _render_operations_card(item: dict, hm: HitlManager, accent: str) -> None:
    payload = item.get("payload", {}) or {}
    shift_plan = payload.get("shift_plan", [])
    facility = payload.get("plant") or payload.get("facility") or payload.get("plant_id") or "All Plants"
    title = "📋 PRODUCTION PLAN APPROVAL" if shift_plan else "📋 OPERATIONS ESCALATION"

    _card_header(title, accent, item.get("source", "Scheduler"), _time_ago(item.get("created_at")), facility)

    throughput = payload.get("throughput", payload.get("expected_throughput", 0))
    utilisation = payload.get("utilisation", payload.get("utilisation_pct", 0))
    summary = payload.get("message") or payload.get("description") or "Operations item awaiting review."

    st.markdown(
        f"""
<div style="margin-top:-6px; margin-bottom:12px; line-height:1.7;">
  <b>Summary:</b> {summary}<br/>
  <b>Plan Size:</b> {int(throughput or 0):,} units
  &nbsp;|&nbsp;
  <b>Utilisation:</b> {float(utilisation or 0):.1f}%
</div>
""",
        unsafe_allow_html=True,
    )

    if shift_plan:
        with st.expander("View Full Shift Plan"):
            plan_df = pd.DataFrame(shift_plan)
            st.dataframe(plan_df, use_container_width=True, hide_index=True)
    else:
        with st.expander("View Details"):
            st.json(payload)

    _resolve_buttons(
        hm,
        item,
        "✅ Approve Plan",
        "❌ Reject — Request Revision",
        "Approved production plan",
        "Rejected production plan",
    )


def _render_procurement_card(item: dict, hm: HitlManager, out: dict, accent: str) -> None:
    payload = item.get("payload", {}) or {}
    plant = payload.get("plant") or payload.get("facility") or "Unknown Plant"
    qty = int(payload.get("reorder_qty", payload.get("qty", 0)) or 0)
    cost = float(payload.get("cost_usd", payload.get("estimated_cost_usd", payload.get("total_cost_usd", 0))) or 0)
    unit_price = float(cost / qty) if qty else float(payload.get("unit_price", 0) or 0)
    days_remaining = float(payload.get("days_remaining", 0) or 0)
    lead_days = float(payload.get("lead_days", 0) or 0)
    note = payload.get("note") or payload.get("message") or "Emergency order raised for review."

    finance = out.get("finance", {})
    budget = finance.get("budget_status", {})
    remaining = float(budget.get("remaining_usd", 0) or 0)
    within_budget = remaining >= cost if remaining else finance.get("gate_decision") == "APPROVED"
    finance_line = (
        f"✅ Within budget ({_fmt_currency(remaining)} remaining after current window)"
        if within_budget else
        "⚠️ Budget is tight — finance review recommended"
    )

    _card_header("📦 EMERGENCY PURCHASE ORDER", accent, item.get("source", "Buyer"), _time_ago(item.get("created_at")), plant)

    st.markdown(
        f"""
<div style="margin-top:-6px; margin-bottom:12px; line-height:1.7;">
  <b>Order:</b> {qty:,} raw material units<br/>
  <b>Supplier Quote:</b> {_fmt_currency(unit_price)} / unit
  &nbsp;→&nbsp;
  <b>Total:</b> {_fmt_currency(cost)}<br/>
  <b>Justification:</b> {days_remaining:.1f} days remaining, lead time ~{lead_days:.0f} days<br/>
  <b>Finance Check:</b> {finance_line}<br/>
  <b>Note:</b> {note}
</div>
""",
        unsafe_allow_html=True,
    )

    with st.expander("View Request Payload"):
        st.json(payload)

    modified_qty = st.number_input(
        "Modify Qty",
        min_value=0,
        step=1000,
        value=max(qty, 0),
        key=f"mod_qty_{item['id']}",
    )
    modified_cost = unit_price * modified_qty if unit_price else cost

    _resolve_buttons(
        hm,
        item,
        "✅ Approve PO",
        "❌ Reject",
        "Approved purchase order",
        "Rejected purchase order",
        extra_action=(
            "✏️ Modify Qty & Approve",
            "Approved with modified quantity",
            f"Modified quantity: {modified_qty:,} units | Estimated total: {_fmt_currency(modified_cost)}",
        ),
    )


def _render_finance_card(item: dict, hm: HitlManager, out: dict, accent: str) -> None:
    payload = item.get("payload", {}) or {}
    finance = out.get("finance", {})
    suggestion = payload.get("suggestion") or (finance.get("suggestions") or ["No specific suggestion available."])[0]

    _card_header("💰 BUDGET ESCALATION", accent, item.get("source", "Finance"), _time_ago(item.get("created_at")))

    st.markdown(
        f"""
<div style="margin-top:-6px; margin-bottom:12px; line-height:1.75;">
  <b>Issue:</b> Monthly spend at {float(payload.get('pct_used', finance.get('budget_status', {}).get('pct_used', 0))):.1f}% with manual review requested<br/>
  <b>Proposed Plan Adds:</b> {_fmt_currency(payload.get('proposed_plan_cost', finance.get('proposed_plan_cost', 0)))}<br/>
  <b>Gate Decision:</b> {payload.get('gate_decision', finance.get('gate_decision', 'UNKNOWN'))}<br/>
  <b>Risk Score:</b> {float(payload.get('risk_score', finance.get('risk_score', 0))):.0f} / 100<br/>
  <b>Suggestion:</b> {suggestion}
</div>
""",
        unsafe_allow_html=True,
    )

    with st.expander("Finance Details"):
        details = {
            "message": payload.get("message"),
            "monthly_spend": payload.get("monthly_spend"),
            "approved_spend": payload.get("approved_spend"),
            "budget": payload.get("budget"),
            "health_score": payload.get("health_score", finance.get("health_score")),
            "budget_status": finance.get("budget_status", {}),
        }
        st.json(details)

    _resolve_buttons(
        hm,
        item,
        "✅ Override & Approve",
        "❌ Block Plan",
        "Finance override approved",
        "Finance blocked the plan",
    )


def _render_maintenance_card(item: dict, hm: HitlManager, accent: str) -> None:
    payload = item.get("payload", {}) or {}
    facility = payload.get("facility") or payload.get("plant") or "Unknown Facility"
    ttf = float(payload.get("ttf_hrs", 0) or 0)
    temp = float(payload.get("temp_c", 0) or 0)
    vibration = float(payload.get("vib_hz", payload.get("vibration_hz", 0)) or 0)
    oee = float(payload.get("oee_pct", 0) or 0)
    impact = (
        f"Line failure likely within {ttf:.1f} hour(s)." if ttf > 0 else
        "Elevated maintenance risk is active."
    )

    _card_header("🔧 EMERGENCY MAINTENANCE REQUEST", accent, item.get("source", "Mechanic"), _time_ago(item.get("created_at")), facility)

    st.markdown(
        f"""
<div style="margin-top:-6px; margin-bottom:12px; line-height:1.75;">
  <b>Alert:</b> Predicted TTF = {ttf:.1f} hours<br/>
  <b>Temperature:</b> {temp:.1f}°C
  &nbsp;|&nbsp;
  <b>Vibration:</b> {vibration:.1f} Hz
  &nbsp;|&nbsp;
  <b>OEE:</b> {oee:.1f}%<br/>
  <b>Impact if ignored:</b> {impact}<br/>
  <b>Reroute Recommendation:</b> {payload.get('message', 'Move affected load to a healthier plant.')}
</div>
""",
        unsafe_allow_html=True,
    )

    with st.expander("Engineering Details"):
        st.json(payload)

    _resolve_buttons(
        hm,
        item,
        "✅ Approve Shutdown + Reroute",
        "❌ Continue (Override — RISK)",
        "Approved emergency shutdown and reroute",
        "Override accepted despite maintenance risk",
    )


def _render_carbon_card(item: dict, hm: HitlManager, out: dict, accent: str) -> None:
    payload = item.get("payload", {}) or {}
    environ = out.get("environ", {})
    peak_ratio = float(payload.get("peak_penalty_pct", environ.get("peak_penalty_pct", 0)) or 0)
    total_penalty = float(payload.get("total_penalty_usd", environ.get("total_penalty_usd", 0)) or 0)
    savings = float(payload.get("estimated_savings_usd", environ.get("estimated_savings_usd", 0)) or 0)
    recommendation = payload.get("recommendation") or environ.get("recommendation") or payload.get("message", "")

    _card_header("🌱 CARBON COMPLIANCE ALERT", accent, item.get("source", "Environmentalist"), _time_ago(item.get("created_at")))

    st.markdown(
        f"""
<div style="margin-top:-6px; margin-bottom:12px; line-height:1.75;">
  <b>Issue:</b> Peak penalty ratio {peak_ratio:.1f}% exceeds the threshold<br/>
  <b>This Window's Carbon Penalty:</b> {_fmt_currency(total_penalty)}<br/>
  <b>Recommended Action:</b> {recommendation}<br/>
  <b>Potential Savings:</b> {_fmt_currency(savings)}
</div>
""",
        unsafe_allow_html=True,
    )

    with st.expander("Sustainability Details"):
        st.json(payload)

    _resolve_buttons(
        hm,
        item,
        "✅ Apply Proposed Rescheduling",
        "❌ Continue As-Is",
        "Approved carbon rescheduling action",
        "Accepted current carbon exposure",
    )


def _render_history(hm: HitlManager, item_type: str, label: str) -> None:
    history = hm.get_history(limit=15, item_type=item_type)
    if not history:
        return

    with st.expander("Resolved History"):
        rows = [
            {
                "ID": item.get("id"),
                "Status": item.get("status", "").upper(),
                "Resolved By": item.get("resolved_by", ""),
                "Comment": item.get("comment", ""),
                "Resolved At": str(item.get("resolved_at", ""))[:19],
            }
            for item in history
        ]
        hist_df = pd.DataFrame(rows)
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
        st.download_button(
            f"Download {label} History CSV",
            data=hist_df.to_csv(index=False).encode("utf-8"),
            file_name=f"hitl_history_{item_type}.csv",
            mime="text/csv",
            key=f"dl_{item_type}",
        )


st.title("📥 HITL Inbox — Human Approval Center")
st.markdown(
    """
Every AI agent reports here when a decision exceeds its autonomous authority.
Review each item with the department-specific context below, then approve or reject it with a comment.
"""
)
render_ollama_fallback_notice("upstream agent summaries in approval payloads")

out = orch()
hm = HitlManager()
counts = hm.get_counts()
total = counts.get("total", 0)

# ── Status row + Refresh ───────────────────────────────────────────────────
_summary_col, _refresh_col = st.columns([5, 1])
with _summary_col:
    if total == 0:
        st.success(
            "✅ All agents are operating within approved parameters. "
            "No human review is currently required."
        )
    else:
        st.warning(
            f"⚠️ **{total} item(s) awaiting review** — "
            f"⚙️ Ops:{counts.get('ops',0)}  "
            f"📦 Procurement:{counts.get('procurement',0)}  "
            f"💰 Finance:{counts.get('finance',0)}  "
            f"🔧 Engineering:{counts.get('maintenance',0)}  "
            f"🌱 Sustainability:{counts.get('carbon',0)}"
        )
with _refresh_col:
    if st.button("🔄 Refresh", key="hitl_refresh_top", use_container_width=True):
        st.rerun()

resolved_history = hm.get_history(limit=5000)
if resolved_history:
    resolved_export = pd.DataFrame(
        [
            {
                "id": item.get("id"),
                "item_type": item.get("item_type"),
                "source": item.get("source"),
                "status": item.get("status"),
                "created_at": item.get("created_at"),
                "resolved_at": item.get("resolved_at"),
                "resolved_by": item.get("resolved_by"),
                "comment": item.get("comment"),
                "payload": item.get("payload"),
            }
            for item in resolved_history
        ]
    )
    st.download_button(
        "⬇️ Download Resolved History CSV",
        data=resolved_export.to_csv(index=False).encode("utf-8"),
        file_name="hitl_resolved_history.csv",
        mime="text/csv",
        key="hitl_dl_all_history",
    )

tab_labels = [f"{label} ({counts.get(item_type, 0)})" for label, item_type, _, _ in DEPT_TABS]
tabs = st.tabs(tab_labels)

for tab, (label, item_type, default_source, accent) in zip(tabs, DEPT_TABS):
    with tab:
        pending = hm.get_pending(item_type=item_type)

        if not pending:
            st.markdown(
                """
<div style="text-align:center; padding:30px; color:#777;">
  <div style="font-size:36px;">✅</div>
  <div style="font-size:14px; margin-top:8px;">No pending items in this department.</div>
</div>
""",
                unsafe_allow_html=True,
            )
        else:
            for item in pending:
                if item_type == "ops":
                    _render_operations_card(item, hm, accent)
                elif item_type == "procurement":
                    _render_procurement_card(item, hm, out, accent)
                elif item_type == "finance":
                    _render_finance_card(item, hm, out, accent)
                elif item_type == "maintenance":
                    _render_maintenance_card(item, hm, accent)
                elif item_type == "carbon":
                    _render_carbon_card(item, hm, out, accent)
                else:
                    _card_header("Queue Item", accent, item.get("source", default_source), _time_ago(item.get("created_at")))
                    st.json(item.get("payload", {}))

                st.markdown("<hr style='border:0; border-top:1px solid #222;'>", unsafe_allow_html=True)

        _render_history(hm, item_type, label.split()[-1])

st.markdown("---")
st.subheader("📊 HITL Queue Summary")

summary_cols = st.columns(len(DEPT_TABS) + 1)
summary_cols[0].metric("Total Pending", total)
for idx, (label, item_type, _, _) in enumerate(DEPT_TABS):
    count = counts.get(item_type, 0)
    summary_cols[idx + 1].metric(
        label.split()[-1],
        count,
        delta=("⚠️ Action needed" if count > 0 else "✅ Clear"),
        delta_color="off",
    )
# ── Manual Escalation Form ─────────────────────────────────────────────────
st.markdown("---")
with st.expander("📝 Manually Escalate an Issue to a Department Head", expanded=False):
    st.caption(
        "Use this form to push any ad-hoc issue into the HITL queue. "
        "The item will appear in the relevant department tab for review."
    )
    _m_dept_map = {
        "⚙️ Operations":       "ops",
        "📦 Procurement":       "procurement",
        "💰 Finance":           "finance",
        "🔧 Engineering":       "maintenance",
        "🌱 Sustainability":    "carbon",
    }
    _m_col1, _m_col2 = st.columns(2)
    with _m_col1:
        _m_dept_label = st.selectbox(
            "Department",
            options=list(_m_dept_map.keys()),
            key="me_dept",
        )
        _m_title = st.text_input("Issue Title", placeholder="e.g. Emergency reorder needed", key="me_title")
    with _m_col2:
        _m_source = st.text_input("Raised By", placeholder="e.g. Operations Manager", key="me_source")
        _m_plant  = st.text_input("Plant / Facility (optional)", key="me_plant")
    _m_message = st.text_area(
        "Details",
        placeholder="Describe the situation so the reviewer has full context.",
        height=100,
        key="me_message",
    )
    if st.button("📤 Submit to HITL Queue", key="me_submit", type="primary"):
        if _m_title and _m_source and _m_message:
            try:
                _m_item_type = _m_dept_map.get(_m_dept_label, "ops")
                _m_payload = {
                    "title":   _m_title,
                    "plant":   _m_plant or "All",
                    "message": _m_message,
                }
                HitlManager().enqueue(_m_item_type, _m_source, _m_payload)
                st.success(f"✅ Issue submitted to {_m_dept_label} inbox. Refresh the queue to see it.")
            except Exception as _exc:
                st.error(f"Submission failed: {_exc}")
        else:
            st.warning("Please fill in Title, Raised By, and Details before submitting.")
