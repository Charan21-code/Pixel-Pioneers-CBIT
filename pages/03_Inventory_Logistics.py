"""
pages/03_Inventory_Logistics.py — Inventory & Logistics (Buyer Agent)
Phase 3: Full implementation.
  - 5 per-plant inventory status cards with lead-time logic
  - Lead Time Warning banners for emergency plants
  - Stock vs Threshold horizontal bar chart
  - Full Reorder Recommendations table
  - Procurement log (from df Procurement_Action)
  - Manual Purchase Order HITL form
  - Buyer Agent Narrative (Ollama, from buyer_out)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import config

# ── Colour palette ────────────────────────────────────────────────────────────
COLORS = st.session_state.get("_COLORS", {
    "healthy":  "#00C896",
    "warning":  "#FFA500",
    "critical": "#FF4C4C",
    "info":     "#4A9EFF",
    "card_bg":  "#1E1E2E",
})

PLOT_THEME = dict(
    plot_bgcolor="#0E1117",
    paper_bgcolor="#0E1117",
    font_color="#EEE",
)

df           = st.session_state.get("_df", pd.DataFrame())
current_time = st.session_state.get("_current_time", pd.Timestamp.now())


def orch() -> dict:
    return st.session_state.get("orch_output") or {}


# ── Page header ───────────────────────────────────────────────────────────────
st.title("📦 Inventory & Logistics")
st.markdown("Real-time inventory status, lead time analysis, and procurement workflow.")

if df.empty:
    st.warning("⚠️ No production data loaded yet. Advance the simulation clock from the sidebar.")
    st.stop()

out       = orch()
inv_data  = out.get("buyer_inventory", {})
buyer_out = out.get("buyer", {})

# ── Summary KPI row ───────────────────────────────────────────────────────────
n_critical  = sum(1 for v in inv_data.values() if v.get("status") in ("critical", "emergency"))
n_low       = sum(1 for v in inv_data.values() if v.get("status") == "low")
n_healthy   = sum(1 for v in inv_data.values() if v.get("status") == "healthy")
min_days    = min((v.get("days_remaining", 99) for v in inv_data.values()), default=0) if inv_data else 0
total_cost  = sum(v.get("cost_usd", 0) for v in inv_data.values()) if inv_data else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("✅ Healthy Plants",       n_healthy,  delta=None)
k2.metric("⚠️ Low Stock Plants",     n_low,      delta=None)
k3.metric("🔴 Critical/Emergency",  n_critical, delta=None)
k4.metric("⏱️ Lowest Days Remaining", f"{min_days:.1f}d")
k5.metric("💵 Est. Total Reorder Cost", f"${total_cost:,.0f}")

st.markdown("---")

# ── Inventory Status Cards (5 — one per plant) ────────────────────────────────
st.subheader("🏭 Plant Inventory Status")

STATUS_CONFIG = {
    "healthy":   {"icon": "✅", "label": "HEALTHY",          "css_key": "healthy"},
    "low":       {"icon": "⚠️",  "label": "LOW — Order Soon", "css_key": "warning"},
    "critical":  {"icon": "🔴", "label": "CRITICAL — Order Now",              "css_key": "critical"},
    "emergency": {"icon": "🚨", "label": "EMERGENCY — Lead Time Exceeds Stock!", "css_key": "critical"},
}

if inv_data:
    plant_keys = list(inv_data.keys())

    # Row 1: first 3 plants
    for row_start in range(0, len(plant_keys), 3):
        row_plants = plant_keys[row_start: row_start + 3]
        card_cols  = st.columns(3)

        for col_idx, plant in enumerate(row_plants):
            inv        = inv_data[plant]
            status     = inv.get("status", "healthy")
            cfg        = STATUS_CONFIG.get(status, STATUS_CONFIG["healthy"])
            s_color    = COLORS[cfg["css_key"]]
            days_rem   = inv.get("days_remaining", 0)
            cur_stock  = inv.get("current_stock",  0)
            threshold  = inv.get("inventory_threshold", 20000)
            daily_use  = inv.get("daily_use",  0)
            shortfall  = inv.get("shortfall_units", 0)
            lead_days  = inv.get("lead_days",  3)
            reorder_q  = inv.get("reorder_qty", 0)
            cost_usd   = inv.get("cost_usd",   0)

            # Progress bar pct (stock vs threshold)
            bar_pct = min(100, int(cur_stock / max(threshold, 1) * 100))
            bar_color = s_color

            # Lead time warning message
            if status == "emergency":
                lead_msg = f"🚨 Stock runs out in <b>{days_rem:.1f}d</b> — delivery takes <b>~{lead_days}d</b>. ORDER IMMEDIATELY."
            elif status == "critical":
                days_to_act = max(0, days_rem - lead_days)
                lead_msg = f"🔴 You must order within <b>{days_to_act:.0f} days</b> to avoid a production gap."
            elif status == "low":
                lead_msg = f"⚠️ Stock will last <b>{days_rem:.1f} days</b>. Plan to reorder soon."
            else:
                lead_msg = f"✅ Healthy stock levels. Next reorder not urgent."

            with card_cols[col_idx]:
                st.markdown(f"""
<div style="border:1px solid #333; border-top:5px solid {s_color};
border-radius:8px; padding:16px; background:{COLORS['card_bg']};
margin-bottom:12px; min-height:290px;">
<div style="font-weight:700; font-size:14px; color:{s_color}; margin-bottom:10px;">
🏭 {plant.split("(")[0].strip()}
<span style="font-size:11px; color:#888; font-weight:400;">
&nbsp;{plant[plant.find("("):] if "(" in plant else ""}
</span>
</div>

 Stock progress bar 
<div style="background:#333; border-radius:4px; height:6px; margin-bottom:12px;">
<div style="background:{bar_color}; border-radius:4px; height:6px; width:{bar_pct}%;"></div>
</div>

<div style="font-size:12px; color:#aaa; line-height:2.0;">
Current Stock:
<b style="color:#fff;">{cur_stock:,} units</b><br/>
Threshold:
<b>{threshold:,} units</b><br/>
Daily Consumption:
<b>{daily_use:.0f} units/day</b><br/>
Days Remaining:
<b style="color:{s_color};">{days_rem:.1f} days</b><br/>
Shortfall:
<b>{shortfall:,} units</b><br/>
Lead Time:
<b>~{lead_days} days to receive</b><br/>
Reorder Qty:
<b>{reorder_q:,} units</b><br/>
Est. Cost:
<b>${cost_usd:,.0f}</b>
</div>
<div style="margin-top:12px; font-size:12px; color:{s_color}; font-weight:600;">
{cfg['icon']} {cfg['label']}
</div>
<div style="margin-top:6px; font-size:11px; color:#aaa;">
{lead_msg}
</div>
</div>
""", unsafe_allow_html=True)

    # ── Emergency & Critical lead-time warning banners ────────────────────────
    urgent_plants = [
        (p, v) for p, v in inv_data.items()
        if v.get("status") in ("emergency", "critical")
    ]
    if urgent_plants:
        st.markdown("---")
        for plant, inv in urgent_plants:
            days_rem  = inv["days_remaining"]
            lead_days = inv["lead_days"]
            days_left = max(0, days_rem - lead_days)
            label = plant.split("(")[0].strip()

            if inv["status"] == "emergency":
                st.error(
                    f"🚨 **{label}**: Current stock will run out in **{days_rem:.1f} days**, "
                    f"but the estimated delivery takes **~{lead_days} days**. "
                    f"**Order immediately — you are out of buffer time.**"
                )
            else:
                st.warning(
                    f"⚠️ **{label}**: Current stock will run out in **{days_rem:.1f} days**, "
                    f"but the estimated delivery takes **~{lead_days} days**. "
                    f"You must order within the next **{days_left:.0f} days** "
                    f"to avoid a production stoppage."
                )

else:
    st.warning("⚠️ Agent outputs not yet available. Trigger agents from the sidebar (Next Tick).")
    # Raw fallback chart
    if "Raw_Material_Inventory_Units" in df.columns and "Inventory_Threshold" in df.columns:
        latest = df.groupby("Assigned_Facility").last().reset_index()
        fig_raw = go.Figure()
        fig_raw.add_trace(go.Bar(
            x=latest["Raw_Material_Inventory_Units"],
            y=latest["Assigned_Facility"],
            orientation="h", name="Current Stock",
            marker_color=COLORS["info"],
        ))
        threshold_val = latest["Inventory_Threshold"].max()
        fig_raw.add_vline(
            x=threshold_val, line_dash="dash", line_color=COLORS["critical"],
            annotation_text=f"Threshold ({threshold_val:,.0f})",
        )
        fig_raw.update_layout(**PLOT_THEME, title="Raw Inventory vs Threshold", height=280)
        st.plotly_chart(fig_raw, use_container_width=True)

# ── Stock vs Threshold Bar Chart ──────────────────────────────────────────────
if inv_data:
    st.markdown("---")
    st.subheader("📉 Stock vs Safety Threshold")

    bar_names  = []
    bar_stocks = []
    bar_colors = []
    threshold_val = 0

    for plant, inv in inv_data.items():
        bar_names.append(plant.split("(")[0].strip())
        bar_stocks.append(inv["current_stock"])
        threshold_val = max(threshold_val, inv.get("inventory_threshold", 20000))
        status = inv.get("status", "healthy")
        bar_colors.append(
            COLORS["critical"] if status in ("critical", "emergency") else
            COLORS["warning"]  if status == "low" else
            COLORS["healthy"]
        )

    fig_bar = go.Figure(go.Bar(
        x=bar_stocks, y=bar_names,
        orientation="h",
        marker_color=bar_colors,
        text=[f"{v:,} units" for v in bar_stocks],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Stock: %{x:,} units<extra></extra>",
    ))
    fig_bar.add_vline(
        x=threshold_val,
        line_dash="dash", line_color=COLORS["critical"], line_width=2,
        annotation_text=f"Threshold ({threshold_val:,})",
        annotation_font_color=COLORS["critical"],
        annotation_position="top right",
    )
    max_val = max(bar_stocks + [threshold_val]) * 1.15
    fig_bar.update_layout(
        **PLOT_THEME,
        title="Raw Material Stock by Plant (vs Safety Threshold)",
        xaxis=dict(title="Units", range=[0, max_val]),
        yaxis=dict(title=""),
        height=300,
        showlegend=False,
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# ── Reorder Recommendations Table ─────────────────────────────────────────────
st.markdown("---")
st.subheader("📋 Reorder Recommendations")

if inv_data:
    urgency_map = {
        "emergency": "🚨 EMERGENCY",
        "critical":  "🔴 Order Now",
        "low":       "🟡 Order Soon",
        "healthy":   "✅ OK",
    }

    reorder_rows = []
    for plant, inv in inv_data.items():
        status   = inv.get("status", "healthy")
        urgency  = urgency_map.get(status, status.upper())
        lead_str = f"~{inv['lead_days']} days" if inv.get("reorder_qty", 0) > 0 else "—"
        cost_str = f"${inv['cost_usd']:,.0f}" if inv.get("reorder_qty", 0) > 0 else "$0"

        reorder_rows.append({
            "Plant":            plant.split("(")[0].strip(),
            "Current Stock":    f"{inv['current_stock']:,}",
            "Daily Use":        f"{inv['daily_use']:.0f}/day",
            "Days Left":        f"{inv['days_remaining']:.1f}d",
            "Shortfall":        f"{inv['shortfall_units']:,} u" if inv['shortfall_units'] > 0 else "None",
            "Reorder Qty":      f"{inv['reorder_qty']:,} u"    if inv['reorder_qty'] > 0      else "—",
            "Est. Cost (USD)":  cost_str,
            "Lead Days":        lead_str,
            "Urgency":          urgency,
        })

    rdf = pd.DataFrame(reorder_rows)
    st.dataframe(rdf, use_container_width=True, hide_index=True)
else:
    st.info("Run agents to generate reorder recommendations.")

# ── Procurement History ────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📜 Procurement History")

if "Procurement_Action" in df.columns:
    proc_events = df[df["Procurement_Action"] != "None"].copy()
    if not proc_events.empty:
        disp_cols = [c for c in [
            "Timestamp", "Assigned_Facility", "Procurement_Action",
            "Live_Supplier_Quote_USD", "Raw_Material_Inventory_Units"
        ] if c in proc_events.columns]

        proc_disp = proc_events[disp_cols].tail(25).copy()
        proc_disp.rename(columns={
            "Assigned_Facility":          "Facility",
            "Procurement_Action":         "Action",
            "Live_Supplier_Quote_USD":    "Quote (USD)",
            "Raw_Material_Inventory_Units": "Stock at Time",
        }, inplace=True, errors="ignore")
        st.dataframe(proc_disp, use_container_width=True, hide_index=True)
    else:
        st.info("No procurement events in the current data window.")
else:
    st.info("Procurement_Action column not available in dataset.")

# ── Manual Purchase Order (HITL) ──────────────────────────────────────────────
st.markdown("---")
st.subheader("📝 Request Manual Purchase Order")

plants_list = list(inv_data.keys()) if inv_data else sorted(df["Assigned_Facility"].unique().tolist())
hc1, hc2, hc3 = st.columns([2, 1, 2])
with hc1:
    hitl_plant = st.selectbox("Select Plant", plants_list, key="inv_hitl_plant")
with hc2:
    hitl_qty   = st.number_input("Quantity (units)", min_value=0, step=1000, value=10000, key="inv_hitl_qty")
with hc3:
    hitl_note  = st.text_input("Reason / Note", placeholder="e.g. Emergency restock due to demand spike", key="inv_hitl_note")

if st.button("📤 Submit Purchase Order for Approval", key="inv_hitl_submit", type="primary"):
    try:
        from hitl.manager import HitlManager
        inv_snap = inv_data.get(hitl_plant, {})
        HitlManager().enqueue("procurement", "Buyer", {
            "plant":          hitl_plant,
            "reorder_qty":    hitl_qty,
            "days_remaining": inv_snap.get("days_remaining", 0),
            "lead_days":      inv_snap.get("lead_days", 3),
            "cost_usd":       hitl_qty * inv_snap.get("unit_price", 5.0),
            "note":           hitl_note or "Manual order request",
            "message": (
                f"Manual PO: {hitl_qty:,} units for {hitl_plant}. "
                f"Current stock: {inv_snap.get('current_stock', 0):,} units "
                f"({inv_snap.get('days_remaining', 0):.1f} days remaining). "
                f"Status: {inv_snap.get('status', 'unknown').upper()}."
            ),
        })
        st.success(f"✅ Purchase order for {hitl_qty:,} units ({hitl_plant}) submitted to HITL Inbox.")
    except Exception as e:
        st.error(f"HITL submission failed: {e}")

# ── Buyer Agent Narrative ──────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🤖 Buyer Agent Analysis")

# Try to find a meaningful Buyer narrative — check multiple possible keys
buyer_summary = (
    buyer_out.get("summary") or
    buyer_out.get("narrative") or
    ""
)

# Build a heuristic narrative if Ollama didn't provide one
if not buyer_summary and inv_data:
    crit_plants = [
        f"{p.split('(')[0].strip()} ({v['days_remaining']:.1f}d, ~{v['lead_days']}d lead)"
        for p, v in inv_data.items()
        if v.get("status") in ("critical", "emergency")
    ]
    low_plants = [
        p.split("(")[0].strip()
        for p, v in inv_data.items()
        if v.get("status") == "low"
    ]
    total_reorder_cost = sum(v.get("cost_usd", 0) for v in inv_data.values())
    reorders_triggered = buyer_out.get("reorders_triggered", 0)

    parts = []
    if crit_plants:
        parts.append(
            f"<b>Critical attention required</b> at: {', '.join(crit_plants)}. "
            f"These facilities are at risk of production stoppages."
        )
    if low_plants:
        parts.append(f"Inventory is <b>low but manageable</b> at: {', '.join(low_plants)}.")
    parts.append(
        f"A total of **{reorders_triggered} reorder(s)** have been triggered this cycle, "
        f"with an estimated procurement cost of **${total_reorder_cost:,.0f}**."
    )
    buyer_summary = " ".join(parts)
    buyer_summary = __import__("re").sub(r'\\*\\*(.*?)\\*\\*', r'<b>\\1</b>', buyer_summary)

if buyer_summary:
    st.markdown(f"""
<div style="border:1px solid {COLORS['info']}44; border-left:5px solid {COLORS['info']};
border-radius:8px; padding:14px 18px; background:#0D1B2A;">
<b style="color:{COLORS['info']}; font-size:13px;">🤖 Buyer Agent Narrative</b><br/>
<span style="font-size:13px; color:#CCC; line-height:1.8;">{buyer_summary}</span>
</div>
""", unsafe_allow_html=True)
else:
    st.info("🤖 Run agents (Next Tick) to generate Buyer Agent narrative.")
