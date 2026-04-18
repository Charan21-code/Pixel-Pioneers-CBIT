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
OLLAMA_MODEL    = "qwen2.5:3b"
OLLAMA_URL      = "http://192.168.137.97:11434/api/generate"
OLLAMA_TAGS_URL = "http://192.168.137.97:11434/api/tags"
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
    "optimise_options": ["Time", "Cost", "Carbon"],
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

# ─────────────────────────────────────────────────────────────────────────────
# ERP Integration Layer
# ─────────────────────────────────────────────────────────────────────────────
ERP = {
    "adapter":                "sap_mock",  # "csv" | "sap_mock" | "odoo_mock"
    "poll_interval_secs":     30,          # how often erp_listener polls for events
    "write_enabled":          True,        # set False to disable all ERP writes
    "idempotency_window_hrs": 24,          # duplicate-push suppression window
    "audit_retention_days":   90,
}

# ─────────────────────────────────────────────────────────────────────────────
# Frontend / UI
# ─────────────────────────────────────────────────────────────────────────────
UI = {
    "app": {
        "brand_subtitle": "",
        "status_poll_ms": 15_000,
        "run_poll_startup_delay_ms": AGENT_LOOP["startup_delay_secs"] * 1000,
        "run_poll_interval_ms": 1_500,
        "run_poll_max_attempts": 60,
        "run_poll_min_attempts_before_exit": 2,
    },
    "command_center": {
        "refresh_ms": DASHBOARD["auto_refresh_secs"] * 1000,
        "agent_log_limit": 18,
        "system_health_nominal_min": 70,
        "inventory_critical_days": 3,
        "badge_nominal_min": 85,
        "badge_watch_min": 65,
        "oee_target_pct": 90,
        "oee_warning_pct": AGENT["min_oee_for_assignment"],
        "animation_stagger_ms": 90,
        "agent_labels": {
            "forecast": "Forecaster",
            "mechanic": "Mechanic",
            "buyer": "Buyer",
            "environ": "Environmentalist",
            "finance": "Finance",
            "scheduler": "Scheduler",
        },
        "agent_scores": {
            "forecast": {"high": 52, "medium": 74, "low": 91},
            "mechanic": {"critical_penalty": 25, "warning_penalty": 8, "minimum_score": 18},
            "buyer": {"base_score": 94, "reorder_penalty": 4, "minimum_score": 32},
            "environ": {"compliant": 88, "non_compliant": 54},
        },
    },
    "demand": {
        "forecast_horizon_days": SIMULATION["sim_days"],
        "moving_average_weeks": 4,
        "overview_tick_target": 14,
        "facility_tick_target": 10,
        "facility_palette": [
            "var(--primary)",
            "var(--signal)",
            "var(--tertiary)",
            "#D8922C",
            "var(--red)",
            "#8D6422",
        ],
    },
    "inventory": {
        "stock_healthy_pct": 80,
        "stock_warning_pct": 40,
        "reorders_display": 10,
        "quote_tick_target": 8,
        "quote_animation_ms": 800,
        "approved_decisions": ["auto_approve"],
        "blocked_decisions": ["hitl_escalate", "auto_reject"],
    },
    "machine_health": {
        "risk_progress_warning_min": 50,
        "risk_progress_critical_min": AGENT["risk_score_critical"],
        "oee_target_pct": 90,
        "oee_warning_pct": AGENT["min_oee_for_assignment"],
        "ttf_critical_hrs": AGENT["ttf_critical_hrs"],
        "ttf_warning_hrs": AGENT["ttf_warning_hrs"],
        "trend_y_axis_min": 60,
        "trend_y_axis_max": 105,
        "recommendations_display": 6,
    },
    "production": {
        "util_nominal_min": 90,
        "util_warning_min": 70,
        "target_utilisation_pct": 90,
        "shift_rows_display": 8,
        "weekly_tick_target": 12,
    },
    "finance": {
        "monthly_budget": FINANCE["monthly_budget"],
        "health_nominal_min": 70,
        "health_warning_min": 40,
        "risk_warning_min": 40,
        "risk_critical_min": 70,
        "budget_warning_pct": 80,
        "budget_critical_pct": 95,
        "alerts_display": 3,
        "monthly_spend_display": 6,
        "approved_gate_values": ["APPROVED", "AUTO_APPROVE"],
        "blocked_gate_values": ["BLOCKED", "HITL_REQUIRED"],
    },
    "carbon": {
        "trend_window_days": 14,
        "max_energy_ticks": 7,
    },
    "erp": {
        "default_adapter":  "sap_mock",   # shown in the ERP Integration banner
        "poll_interval_ms": 30 * 1000,    # mirrors ERP["poll_interval_secs"]
        "audit_display":    25,           # rows shown in the audit table
    },
    "digital_twin": {
        "optimise_options": DIGITAL_TWIN["optimise_options"],
        "default_params": {
            "oee_pct": 91.0,
            "workforce_pct": 95.0,
            "forecast_qty": DIGITAL_TWIN["base_capacity"],
            "energy_price": 0.12,
            "downtime_hrs": 0.0,
            "optimise_for": DIGITAL_TWIN["optimise_options"][0],
            "horizon_days": SIMULATION["sim_days"],
            "demand_buffer_pct": DIGITAL_TWIN["demand_buffer_pct"],
        },
        "ranges": {
            "oee_pct": {"min": 1, "max": 100, "step": 0.5},
            "workforce_pct": {"min": 1, "max": 100, "step": 0.5},
            "downtime_hrs": {"min": 0, "max": 24, "step": 0.5},
            "energy_price": {"min": 0.01, "max": 0.50, "step": 0.01},
            "demand_buffer_pct": {"min": 0, "max": 0.30, "step": 0.01},
            "horizon_days": {"min": 1, "max": 30, "step": 1},
        },
    },
}
