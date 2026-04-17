"""
pages/03_Inventory_Logistics.py — Inventory & Logistics (Buyer Agent)
Phase 2: Per-plant inventory cards with lead time, reorder table, procurement log, HITL form.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import config

COLORS = st.session_state.get("_COLORS", {
    "healthy": "#00C896", "warning": "#FFA500", "critical": "#FF4C4C",
    "info": "#4A9EFF", "card_bg": "#1E1E2E",
})

df           = st.session_state.get("_df", pd.DataFrame())
current_time = st.session_state.get("_current_time", pd.Timestamp.now())


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


st.title("📦 Inventory & Logistics (Buyer Agent)")
st.markdown("Real-time inventory status, lead time analysis, and procurement workflow.")

if df.empty:
    st.warning("No data available.")
    st.stop()

out      = orch()
inv_data = out.get("buyer_inventory", {})
buyer_out= out.get("buyer", {})

# ── Inventory Status Cards ─────────────────────────────────────────────────────
st.subheader("📊 Plant Inventory Status")

if inv_data:
    cols = st.columns(min(len(inv_data), 3))
    for i, (plant, inv) in enumerate(inv_data.items()):
        status    = inv.get("status", "healthy")
        days_rem  = inv.get("days_remaining", 0)
        shortfall = inv.get("shortfall_units", 0)
        lead_days = inv.get("lead_days", 3)
        reorder   = inv.get("reorder_qty", 0)
        cost      = inv.get("cost_usd", 0)
        cur_stock = inv.get("current_stock", 0)
        threshold = inv.get("inventory_threshold", 20000)
        daily_use = inv.get("daily_use", 0)

        status_color = (
            COLORS["critical"] if status in ("critical", "emergency") else
            COLORS["warning"]  if status == "low" else
            COLORS["healthy"]
        )
        status_badge = {
            "healthy":   "✅ HEALTHY",
            "low":       "⚠️ LOW — Order Soon",
            "critical":  "🔴 CRITICAL — Order Now",
            "emergency": "🚨 EMERGENCY — Lead time exceeds stock!",
        }.get(status, status.upper())

        with cols[i % 3]:
            st.markdown(f"""
            <div style="border:1px solid #333; border-top:5px solid {status_color};
                        border-radius:8px; padding:16px; background:{COLORS['card_bg']};
                        margin-bottom:12px; min-height:230px;">
                <div style="font-weight:bold; font-size:15px; color:{status_color}; margin-bottom:8px;">
                    🏭 {plant.split('(')[0].strip()}
                </div>
                <div style="font-size:12px; color:#aaa; line-height:2.0;">
                    Current Stock: <b style="color:#fff;">{cur_stock:,} units</b><br/>
                    Threshold: <b>{threshold:,} units</b><br/>
                    Daily Consumption: <b>{daily_use:.0f} units/day</b><br/>
                    Days Remaining: <b style="color:{status_color};">{days_rem:.1f} days</b><br/>
                    Shortfall: <b>{shortfall:,} units</b><br/>
                    Lead Time: <b>~{lead_days} days to receive</b>
                </div>
                <div style="margin-top:10px; font-size:13px;">
                    Status: <b style="color:{status_color};">{status_badge}</b>
                </div>
            </div>
            """, unsafe_allow_html=True)

            if status == "emergency":
                st.error(
                    f"⚠️ **{plant.split('(')[0].strip()}**: Stock expires in {days_rem:.1f}d, "
                    f"but lead time is ~{lead_days}d. **Order immediately!**"
                )

    # Lead time warning banner
    emergency_plants = [
        (p, v) for p, v in inv_data.items()
        if v.get("status") == "emergency"
    ]
    if emergency_plants:
        st.markdown("---")
        for plant, inv in emergency_plants:
            st.warning(
                f"⚠️ **{plant.split('(')[0].strip()}**: Current stock will run out in "
                f"**{inv['days_remaining']:.1f} days**, but the estimated delivery takes "
                f"**~{inv['lead_days']} days**. You must order within the next "
                f"**{max(0, inv['days_remaining'] - inv['lead_days']):.0f} days** "
                "to avoid a production stoppage."
            )
else:
    st.warning("⚠️ Agent outputs not yet available. Showing raw inventory data.")
    latest_inv = df.groupby("Assigned_Facility").last().reset_index()
    fig = px.bar(
        latest_inv, x="Assigned_Facility",
        y=["Raw_Material_Inventory_Units", "Inventory_Threshold"],
        barmode="overlay", title="Inventory vs Threshold",
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Stock vs Threshold Bar Chart ──────────────────────────────────────────────
if inv_data:
    st.markdown("---")
    st.subheader("📉 Stock vs Safety Threshold")
    bar_data = pd.DataFrame([
        {"Plant": p.split("(")[0].strip(),
         "Current Stock": v["current_stock"],
         "Threshold": v["inventory_threshold"]}
        for p, v in inv_data.items()
    ])
    fig_bar = px.bar(
        bar_data, x="Current Stock", y="Plant", orientation="h",
        color="Current Stock",
        color_continuous_scale=["#FF4C4C", "#FFA500", "#00C896"],
        title="Raw Material Stock by Plant",
    )
    max_val = max(bar_data["Threshold"].max(), bar_data["Current Stock"].max()) * 1.1
    fig_bar.add_vline(
        x=bar_data["Threshold"].max(),
        line_dash="dash", line_color="#FF4C4C",
        annotation_text=f"Threshold ({bar_data['Threshold'].max():,})",
    )
    fig_bar.update_layout(
        plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#EEE",
        xaxis_range=[0, max_val],
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# ── Reorder Table ─────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📋 Reorder Recommendations")

if inv_data:
    reorder_rows = []
    for plant, inv in inv_data.items():
        urgency = {
            "emergency": "🚨 EMERGENCY",
            "critical":  "🔴 Order Now",
            "low":       "🟡 Order Soon",
            "healthy":   "✅ OK",
        }.get(inv.get("status", "healthy"), "?")

        reorder_rows.append({
            "Plant":           plant.split("(")[0].strip(),
            "Current Stock":   f"{inv['current_stock']:,}",
            "Daily Use":       f"{inv['daily_use']:.0f}/day",
            "Days Left":       f"{inv['days_remaining']:.1f}d",
            "Shortfall":       f"{inv['shortfall_units']:,} units",
            "Reorder Qty":     f"{inv['reorder_qty']:,} units",
            "Est. Cost (USD)": f"${inv['cost_usd']:,.0f}",
            "Lead Days":       f"~{inv['lead_days']} days",
            "Urgency":         urgency,
        })

    reorder_df = pd.DataFrame(reorder_rows)
    st.dataframe(reorder_df, use_container_width=True, hide_index=True)

# ── Procurement Log ────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📜 Procurement History (from production data)")

procurement_events = df[df["Procurement_Action"] != "None"]
if not procurement_events.empty:
    disp_cols = [
        "Timestamp", "Assigned_Facility", "Procurement_Action",
        "Live_Supplier_Quote_USD", "Raw_Material_Inventory_Units",
    ]
    st.dataframe(
        procurement_events[disp_cols].tail(20), use_container_width=True, hide_index=True
    )
else:
    st.info("No procurement events in current data window.")

# ── Manual Order HITL Form ─────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📝 Request Manual Purchase Order")

plants_list = list(inv_data.keys()) if inv_data else sorted(df["Assigned_Facility"].unique().tolist())
hcol1, hcol2, hcol3 = st.columns([2, 1, 1])
with hcol1:
    hitl_plant = st.selectbox("Select Plant", plants_list, key="inv_hitl_plant")
with hcol2:
    hitl_qty   = st.number_input("Quantity (units)", min_value=0, step=1000, value=10000, key="inv_hitl_qty")
with hcol3:
    hitl_note  = st.text_input("Note", placeholder="Reason for manual order", key="inv_hitl_note")

if st.button("📤 Submit Purchase Order for Approval", key="inv_hitl_submit", type="primary"):
    try:
        from hitl.manager import HitlManager
        inv_snap = inv_data.get(hitl_plant, {})
        HitlManager().enqueue("procurement", "Buyer", {
            "plant":         hitl_plant,
            "reorder_qty":   hitl_qty,
            "days_remaining":inv_snap.get("days_remaining", 0),
            "lead_days":     inv_snap.get("lead_days", 3),
            "cost_usd":      hitl_qty * inv_snap.get("unit_price", 5.0),
            "note":          hitl_note or "Manual order request",
            "message": (
                f"Manual PO: {hitl_qty:,} units for {hitl_plant}. "
                f"Current stock: {inv_snap.get('current_stock', 0):,} units "
                f"({inv_snap.get('days_remaining', 0):.1f} days remaining)."
            ),
        })
        st.success("✅ Purchase order submitted to HITL Inbox (Procurement tab).")
    except Exception as e:
        st.error(f"HITL submission failed: {e}")

# ── Buyer Agent Narrative ──────────────────────────────────────────────────────
buyer_summary = buyer_out.get("summary", "")
if buyer_summary:
    st.markdown("---")
    st.subheader("🤖 Buyer Agent Narrative")
    st.info(buyer_summary)
