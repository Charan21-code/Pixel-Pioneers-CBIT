"""Root entry point for the multipage dashboard."""

from __future__ import annotations

import streamlit as st

from dashboard_runtime import bootstrap_page

bootstrap_page("Agentic Production Planning System", "🏭")

try:
    st.switch_page("pages/01_Command_Center.py")
except AttributeError:
    st.title("🏭 Agentic Production Planning System")
    st.markdown("Use the sidebar or the links below to open a dashboard page.")
    st.markdown("---")
    nav_pages = [
        ("🏭 Command Center", "pages/01_Command_Center.py"),
        ("📈 Demand Intelligence", "pages/02_Demand_Intelligence.py"),
        ("📦 Inventory & Logistics", "pages/03_Inventory_Logistics.py"),
        ("🗓️ Production Plan", "pages/04_Production_Plan.py"),
        ("🔧 Machine Health", "pages/05_Machine_Health.py"),
        ("💰 Finance Dashboard", "pages/06_Finance_Dashboard.py"),
        ("🧬 Digital Twin", "pages/07_Digital_Twin.py"),
        ("🌱 Carbon & Energy", "pages/08_Carbon_Energy.py"),
        ("💬 NLP Interface", "pages/09_NLP_Interface.py"),
        ("📥 HITL Inbox", "pages/10_HITL_Inbox.py"),
    ]
    rows = [nav_pages[i:i + 2] for i in range(0, len(nav_pages), 2)]
    for row in rows:
        cols = st.columns(len(row))
        for col, (label, path) in zip(cols, row):
            col.page_link(path, label=label, use_container_width=True)
except Exception:
    st.info("Open **01 Command Center** from the sidebar to start the dashboard.")
