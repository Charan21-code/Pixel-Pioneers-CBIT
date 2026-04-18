"""
config.py — Central configuration for the Factory Agent System.

All agents, the orchestrator, the digital twin, and the dashboard
import their thresholds and paths from here. Never hardcode these
values inside individual agent files.
"""

import os

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "production.db")

# ─────────────────────────────────────────────────────────────────────────────
# Ollama (local LLM)
# ─────────────────────────────────────────────────────────────────────────────
OLLAMA_MODEL    = "gemma4:e2b"
OLLAMA_URL      = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
OLLAMA_TIMEOUT  = 15.0   # seconds; keep short so fallback kicks in quickly

# ─────────────────────────────────────────────────────────────────────────────
# Finance thresholds (USD)
# ─────────────────────────────────────────────────────────────────────────────
FINANCE = {
    "auto_approve_max":   1_000,    # cost below this → instant approve
    "hitl_escalate_min":  10_000,   # cost above this → human review queue
    "monthly_budget":   2_000_000,  # realistic multi-plant global budget (USD/month)
    "overhead_multiplier": 1.15,    # 15% overhead added to every cost estimate
}

# ─────────────────────────────────────────────────────────────────────────────
# Agent decision thresholds
# ─────────────────────────────────────────────────────────────────────────────
AGENT = {
    # ForecasterAgent
    "demand_spike_pct":      0.30,   # actual > forecast * (1 + spike_pct) → anomaly

    # MechanicAgent
    "ttf_critical_hrs":      24,     # Predicted TTF below this → CRITICAL
    "ttf_warning_hrs":       100,    # Predicted TTF below this → WARNING
    "oee_warning_pct":       85,     # OEE below this adds +15 to risk score
    "risk_score_critical":   80,     # score >= this → facility blacklisted by Scheduler

    # BuyerAgent
    "inventory_safety_pct":  1.20,   # reorder when stock < threshold * this

    # EnvironmentalistAgent
    "carbon_peak_threshold": 300,    # USD carbon penalty above this → flag
    "peak_penalty_ratio":    0.40,   # peak penalty / total > this → non-compliant

    # SchedulerAgent
    "min_oee_for_assignment": 80,    # do not assign orders to facilities below this

    # BuyerAgent / Inventory
    "default_lead_days":      3,      # fallback delivery lead time if quote data unavailable
}

# ─────────────────────────────────────────────────────────────────────────────
# Viral Demand Shock
# ─────────────────────────────────────────────────────────────────────────────
VIRAL_SHOCK = {
    "api_url": "https://mock-social-api.demo/trends/latest", # Mock REST API endpoint
    "trending_keywords": ["Galaxy", "Taylor Swift", "Launch"],
    "surge_multiplier": 10.0,
    "mention_threshold": 10000,
}

# ─────────────────────────────────────────────────────────────────────────────
# Digital Twin (SimPy simulation)
# ─────────────────────────────────────────────────────────────────────────────
SIMULATION = {
    "delivery_prob_min": 0.75,   # below this → re-schedule
    "max_retries":       3,      # max re-simulation attempts before HITL
    "sim_days":          7,      # simulated horizon in days
}

# ─────────────────────────────────────────────────────────────────────────────
# Digital Twin (parameter-driven simulation defaults)
# ─────────────────────────────────────────────────────────────────────────────
DIGITAL_TWIN = {
    "base_capacity":      2000,   # default daily unit capacity per plant at 100% conditions
    "carbon_kg_per_kwh":  0.43,   # kg CO₂ per kWh consumed
    "kwh_per_unit":       2.8,    # kWh consumed per manufactured unit
    "demand_buffer_pct":  0.10,   # 10% safety buffer added to forecast target
    "scenario_slots":    3,       # max saved scenarios for comparison
}

# ─────────────────────────────────────────────────────────────────────────────
# NLP Interface
# ─────────────────────────────────────────────────────────────────────────────
NLP = {
    "history_limit":     20,    # max conversation turns kept in session_state
    "context_rows_max": 200,   # max rows of agent log fed to Ollama as context
}

# ─────────────────────────────────────────────────────────────────────────────
# HITL (Human-In-The-Loop)
# ─────────────────────────────────────────────────────────────────────────────
HITL = {
    "health_score_min": 30,  # Orchestrator routes to HITL if finance health < this
}

# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────
DASHBOARD = {
    "auto_refresh_secs":    30,   # st.rerun() interval for live updates
    "ollama_check_ttl_secs": 30,  # how often to re-ping Ollama for status
    "agent_log_display":    50,   # max rows shown in the agent activity log
}

# ─────────────────────────────────────────────────────────────────────────────
# Always-On Agent Loop
# ─────────────────────────────────────────────────────────────────────────────
AGENT_LOOP = {
    "interval_secs":      300,   # re-run all agents every 5 minutes
    "startup_delay_secs":   2,   # brief pause after uvicorn binds its port
}
