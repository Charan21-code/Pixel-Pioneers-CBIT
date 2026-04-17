"""
pages/10_HITL_Inbox.py — Human-In-The-Loop Inbox
Phase 2: 5-department tab layout (Operations, Procurement, Finance, Engineering, Sustainability)
         with approve/reject/comment workflow, expandable payloads, resolved history,
         CSV download, and empty-state messaging.
"""

import streamlit as st
import pandas as pd
import config

COLORS = st.session_state.get("_COLORS", {
    "healthy": "#00C896", "warning": "#FFA500", "critical": "#FF4C4C",
    "info": "#4A9EFF", "card_bg": "#1E1E2E",
})


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


# ── Page Header ────────────────────────────────────────────────────────────────
st.title("📥 HITL Inbox — Human Approval Center")
st.markdown("""
Every AI agent reports here when a decision exceeds its autonomous authority.
Review, approve, or reject items below. All actions are logged with timestamps.
""")

try:
from hitl.manager import HitlManager
hm     = HitlManager()
counts = hm.get_counts()
except Exception as e:
st.error(f"Could not connect to HITL manager: {e}")
st.stop()

total = counts.get("total", 0)
if total == 0:
st.success(
"✅ All agents are operating within approved parameters. "
"No human review is currently required."
)
else:
st.warning(f"⚠️ **{total} item(s)** awaiting your review across all departments.")

# ── 5-Department Tabs ──────────────────────────────────────────────────────────
DEPT_TABS = [
("⚙️ Operations",      "ops",         "Orchestrator / Scheduler",   COLORS["info"]),
("📦 Procurement",     "procurement",  "Buyer Agent",                COLORS["warning"]),
("💰 Finance",         "finance",      "Finance Agent",              "#A78BFA"),
("🔧 Engineering",     "maintenance",  "Mechanic Agent",             COLORS["critical"]),
("🌱 Sustainability",  "carbon",       "Environmentalist Agent",     COLORS["healthy"]),
]

tab_labels = [
f"{label} ({counts.get(itype, 0)})"
for label, itype, _, _ in DEPT_TABS
]
tabs = st.tabs(tab_labels)

for tab, (label, itype, source, accent) in zip(tabs, DEPT_TABS):
with tab:
pending = hm.get_pending(item_type=itype)

if not pending:
st.markdown(f"""
<div style="text-align:center; padding:30px; color:#666;">
<div style="font-size:36px;">✅</div>
<div style="font-size:14px; margin-top:8px;">
        No pending {label.split()[-1]} items.
</div>
</div>
""", unsafe_allow_html=True)
        else:
            for item in pending:
                payload  = item.get("payload", {})
                created  = item.get("created_at", "")[:19]
                item_id  = item["id"]
                src      = item.get("source", source)
                summary  = payload.get(
                    "message",
                    payload.get("description", str(payload)[:150])
                )
                facility = payload.get("facility", payload.get("plant", "All"))

                # Item card
                st.markdown(f"""
<div style="border:1px solid #333; border-left:5px solid {accent};
                border-radius:8px; padding:16px 20px; background:{COLORS['card_bg']};
                margin-bottom:16px;">
<div style="display:flex; justify-content:space-between; align-items:center;">
<b style="font-size:15px; color:{accent};">
{itype.upper()} — Item #{item_id}
</b>
<span style="color:#666; font-size:12px;">
{src} &nbsp;|&nbsp; Submitted: {created}
</span>
</div>
<div style="font-size:12px; color:#aaa; margin-top:4px;">
            Facility / Plant: <b style="color:#ddd;">{facility}</b>
</div>
<div style="font-size:13px; margin-top:10px; line-height:1.6;">
{summary}
</div>
</div>
    """, unsafe_allow_html=True)

                # Expandable payload
                with st.expander(f"📂 Full Details — Item #{item_id}"):
                    st.json(payload)

                # Action row
                ac1, ac2, ac3 = st.columns([2, 2, 3])
                with ac3:
                    comment = st.text_input(
                        "Comment",
                        key=f"comment_{item_id}",
                        label_visibility="collapsed",
                        placeholder="Add a comment (optional)",
                    )
                with ac1:
                    if st.button(
                        f"✅ Approve #{item_id}",
                        key=f"approve_{item_id}",
                        type="primary",
                        use_container_width=True,
                    ):
                        if hm.approve(item_id, comment or "Approved", "Human Head"):
                            st.success(f"Item #{item_id} approved.")
                            st.rerun()
                with ac2:
                    if st.button(
                        f"❌ Reject #{item_id}",
                        key=f"reject_{item_id}",
                        use_container_width=True,
                    ):
                        if hm.reject(item_id, comment or "Rejected", "Human Head"):
                            st.warning(f"Item #{item_id} rejected.")
                            st.rerun()

                st.markdown("<hr style='border:0; border-top:1px solid #222;'>", unsafe_allow_html=True)

        # ── Resolved History ────────────────────────────────────────────────
        history = hm.get_history(limit=10, item_type=itype)
        if history:
            with st.expander("📜 Resolved History (last 10)"):
                hist_rows = [{
                    "ID":          h["id"],
                    "Status":      ("✅ APPROVED" if h["status"] == "approved" else "❌ REJECTED"),
                    "Resolved By": h.get("resolved_by", ""),
                    "Comment":     (h.get("comment", "") or "")[:80],
                    "Resolved At": (h.get("resolved_at", "") or "")[:19],
                } for h in history]
                hist_df = pd.DataFrame(hist_rows)
                st.dataframe(hist_df, use_container_width=True, hide_index=True)

                # Download resolved history
                csv = hist_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    f"⬇️ Download {label.split()[-1]} History CSV",
                    data=csv,
                    file_name=f"hitl_history_{itype}.csv",
                    mime="text/csv",
                    key=f"dl_{itype}",
                )

# ── Global Stats ──────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📊 HITL Queue Summary")

stat_cols = st.columns(len(DEPT_TABS) + 1)
stat_cols[0].metric("Total Pending", total)
for i, (label, itype, _, accent) in enumerate(DEPT_TABS):
    cnt = counts.get(itype, 0)
    stat_cols[i + 1].metric(
        label.split()[-1],
        cnt,
        delta=("⚠️ Action needed" if cnt > 0 else "✅ Clear"),
        delta_color="off",
    )
