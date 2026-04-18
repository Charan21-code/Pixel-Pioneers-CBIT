"""
backend/main.py — FastAPI Backend for Agentic Production Planning System

Exposes all agent logic, HITL queue, Digital Twin, and NLP as REST APIs
consumed by the React frontend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Resolve parent package path ───────────────────────────────────────────────
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR    = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, ROOT_DIR)

import config
from agents.orchestrator import OrchestratorAgent
from hitl.manager import HitlManager
from simulation.digital_twin import simulate, simulate_scenario_compare, derive_defaults_from_agent_output
from simulation import twin_ml
from nlp.control_center import (
    heuristic_intent,
    build_query_answer,
    select_hitl_item,
    ask_ollama_intent,
    merge_intents,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Always-on agent loop ──────────────────────────────────────────────────────

async def _agent_loop():
    """
    Background coroutine — started automatically on server startup.

    Runs the full orchestrator pipeline:
      • immediately after the server is ready (startup_delay_secs)
      • then again every interval_secs (default: 5 minutes)

    Uses run_in_executor so the heavy CPU/IO work happens in a thread pool
    and the uvicorn event loop (and all API endpoints) stay fully responsive
    while agents are computing.
    """
    delay    = config.AGENT_LOOP["startup_delay_secs"]
    interval = config.AGENT_LOOP["interval_secs"]

    await asyncio.sleep(delay)   # let uvicorn finish binding its port
    loop = asyncio.get_event_loop()

    logger.info("[AgentLoop] Always-on loop started. Interval: %ds.", interval)
    while True:
        logger.info("[AgentLoop] Starting orchestrator run...")
        try:
            await loop.run_in_executor(None, _run_orchestrator_sync)
        except Exception as exc:
            logger.error("[AgentLoop] Orchestrator run raised an exception: %s", exc, exc_info=True)
        logger.info("[AgentLoop] Run complete. Next run in %ds.", interval)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: pre-load data and start the always-on agent loop."""
    logger.info("[Startup] Pre-loading data.csv into cache...")
    _load_df()   # warm the CSV cache so the first API call is instant

    # Kick off ML model training immediately in a background thread
    logger.info("[Startup] Triggering Digital Twin ML training...")
    twin_ml.ensure_model_trained()

    task = asyncio.create_task(_agent_loop())
    logger.info("[Startup] Always-on agent loop scheduled.")
    yield
    # ── shutdown ──────────────────────────────────────────────────────────────
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info("[Shutdown] Agent loop cancelled cleanly.")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="OPS//CORE Tactical Command API",
    description="Agentic Production Planning System — FastAPI Backend",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global state ──────────────────────────────────────────────────────────────
_CACHE: dict = {
    "orch_output":      None,
    "df":               None,
    "last_run_at":      None,
    "is_running":       False,
    "active_agent":     None,
    "run_id":           None,
    "run_started_at":   None,
    "scenario_override": None,   # injected by /api/twin/apply-scenario
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json_safe(obj: Any) -> Any:
    """Recursively convert numpy/pandas types to JSON-serializable Python types."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


def _load_df() -> pd.DataFrame:
    """Load and preprocess data.csv. Returns cached copy if already loaded."""
    if _CACHE["df"] is not None:
        return _CACHE["df"]

    csv_path = os.path.join(ROOT_DIR, "data.csv")
    if not os.path.exists(csv_path):
        logger.error("data.csv not found at %s", csv_path)
        return pd.DataFrame()

    df = pd.read_csv(csv_path, parse_dates=["Timestamp"])
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"])
    df = df.sort_values("Timestamp").reset_index(drop=True)

    # Ensure numeric columns are correct types
    numeric_cols = [
        "Actual_Order_Qty", "Machine_OEE_Pct", "Raw_Material_Inventory_Units",
        "Inventory_Threshold", "Workforce_Deployed", "Workforce_Required",
        "Energy_Consumed_kWh", "Carbon_Cost_Penalty_USD", "Live_Supplier_Quote_USD",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    _CACHE["df"] = df
    logger.info("Loaded data.csv: %d rows, %d columns", len(df), len(df.columns))
    return df


def _get_orch_output() -> dict:
    """Return cached orchestrator output or empty dict."""
    return _CACHE.get("orch_output") or {}


def _recent_agent_log(limit: int = 8) -> list[dict]:
    """Return a compact recent agent-event snapshot for NLP prompting."""
    try:
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT logged_at, agent_name, severity, facility_id, message
            FROM agent_events
            ORDER BY logged_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _run_orchestrator_sync() -> dict:
    """Run orchestrator synchronously and update cache."""
    if _CACHE["is_running"]:
        return {"status": "already_running"}

    _CACHE["is_running"] = True
    _CACHE["active_agent"] = None
    new_run_id = str(uuid.uuid4())
    _CACHE["run_id"] = new_run_id
    _CACHE["run_started_at"] = datetime.utcnow().isoformat()

    def _progress(agent_name):
        """Called by OrchestratorAgent.run() before each agent step."""
        _CACHE["active_agent"] = agent_name   # None signals 'all done'
        if agent_name:
            logger.info("[AgentProgress] Now running: %s", agent_name)

    try:
        df = _load_df()
        if df.empty:
            return {"error": "No data available"}

        as_of_time = df["Timestamp"].max()
        context = {"df": df, "as_of_time": as_of_time}
        orch = OrchestratorAgent()
        result = orch.run(context, progress_callback=_progress)
        _CACHE["orch_output"] = result
        _CACHE["last_run_at"] = datetime.utcnow().isoformat()
        logger.info("Orchestrator run complete. Status: %s", result.get("final_status"))
        return _json_safe(result)
    except Exception as exc:
        logger.error("Orchestrator run failed: %s", exc, exc_info=True)
        return {"error": str(exc)}
    finally:
        _CACHE["is_running"] = False
        _CACHE["active_agent"] = None


def _run_orchestrator_sync_with_scenario() -> dict:
    """Like _run_orchestrator_sync but merges scenario_override into context."""
    override = _CACHE.pop("scenario_override", None) or {}
    if _CACHE["is_running"]:
        return {"status": "already_running"}

    _CACHE["is_running"] = True
    _CACHE["active_agent"] = None
    new_run_id = str(uuid.uuid4())
    _CACHE["run_id"] = new_run_id
    _CACHE["run_started_at"] = datetime.utcnow().isoformat()

    def _progress(agent_name):
        _CACHE["active_agent"] = agent_name

    try:
        df = _load_df()
        if df.empty:
            return {"error": "No data available"}

        as_of_time = df["Timestamp"].max()
        context = {
            "df":               df,
            "as_of_time":       as_of_time,
            "forecast_qty_override":   override.get("forecast_qty"),
            "optimise_for":            override.get("optimise_for", "Time"),
            "oee_override_pct":        override.get("oee_override"),
            "workforce_override_pct":  override.get("workforce_override"),
            "scenario_label":          override.get("applied_label", "Custom Scenario"),
        }
        orch = OrchestratorAgent()
        result = orch.run(context, progress_callback=_progress)
        result["applied_scenario"] = override.get("applied_label")
        _CACHE["orch_output"] = result
        _CACHE["last_run_at"] = datetime.utcnow().isoformat()
        logger.info("[ScenarioRun] Complete: %s", override.get("applied_label"))
        return _json_safe(result)
    except Exception as exc:
        logger.error("Scenario orchestrator run failed: %s", exc, exc_info=True)
        return {"error": str(exc)}
    finally:
        _CACHE["is_running"] = False
        _CACHE["active_agent"] = None


# ── Pydantic models ───────────────────────────────────────────────────────────

class HitlActionRequest(BaseModel):
    comment:     str = ""
    resolved_by: str = "Human Operator"


class HitlEnqueueRequest(BaseModel):
    item_type: str
    source:    str
    payload:   dict


class NlpQueryRequest(BaseModel):
    query:         str
    selected_plant: Optional[str] = None


class SimulationRequest(BaseModel):
    plant_id:        str
    oee_pct:         float = 91.0
    workforce_pct:   float = 95.0
    forecast_qty:    int   = 2000
    energy_price:    float = 0.12
    downtime_hrs:    float = 0.0
    optimise_for:    str   = "Time"
    horizon_days:    int   = 7
    base_capacity:   Optional[int] = None
    demand_buffer_pct: float = 0.10


class ScenarioItem(BaseModel):
    label:           str
    plant_id:        str
    oee_pct:         float = 91.0
    workforce_pct:   float = 95.0
    forecast_qty:    int   = 2000
    energy_price:    float = 0.12
    downtime_hrs:    float = 0.0
    optimise_for:    str   = "Time"
    horizon_days:    int   = 7
    base_capacity:   Optional[int] = None
    demand_buffer_pct: float = 0.10


class ScenarioCompareRequest(BaseModel):
    scenarios: list[ScenarioItem]


class TwinChatRequest(BaseModel):
    prompt:  str
    context: dict = {}   # current scenario params for Ollama


class ApplyScenarioRequest(BaseModel):
    scenario: ScenarioItem


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    df = _load_df()
    return {
        "status":       "ok",
        "data_rows":    len(df),
        "agent_ready":  not df.empty,
        "last_run_at":  _CACHE.get("last_run_at"),
        "has_output":   _CACHE["orch_output"] is not None,
    }


@app.get("/api/ui-config")
def get_ui_config():
    """Canonical UI-facing thresholds, limits, and timings sourced from config.py."""
    return _json_safe(config.UI)


# ── Orchestrator ──────────────────────────────────────────────────────────────

@app.post("/api/orchestrator/run")
def trigger_orchestrator(background_tasks: BackgroundTasks):
    """Trigger a fresh orchestrator run (non-blocking)."""
    if _CACHE["is_running"]:
        raise HTTPException(status_code=409, detail="Orchestrator is already running")
    background_tasks.add_task(_run_orchestrator_sync)
    return {"status": "started", "message": "Orchestrator run triggered in background"}


@app.get("/api/orchestrator/run-sync")
def trigger_orchestrator_sync():
    """Trigger orchestrator synchronously and return full output."""
    result = _run_orchestrator_sync()
    return _json_safe(result)


@app.get("/api/orchestrator/output")
def get_orchestrator_output():
    """Return the latest cached orchestrator output."""
    out = _get_orch_output()
    if not out:
        raise HTTPException(status_code=404, detail="No orchestrator output yet. Call /api/orchestrator/run-sync first.")
    return _json_safe(out)


@app.get("/api/orchestrator/status")
def get_system_status():
    """Quick system status summary."""
    out = _get_orch_output()
    return _json_safe({
        "final_status":    out.get("final_status", "UNKNOWN"),
        "system_health":   out.get("system_health", 0.0),
        "conflict_count":  len(out.get("conflicts", [])),
        "plants":          out.get("plants", []),
        "last_run_at":     _CACHE.get("last_run_at"),
        "is_running":      _CACHE["is_running"],
        "active_agent":    _CACHE["active_agent"],
    })


@app.get("/api/agents/active")
def get_active_agent():
    """Returns which agent is currently executing, the current run_id, and run metadata."""
    return {
        "is_running":     _CACHE["is_running"],
        "active_agent":   _CACHE["active_agent"],
        "last_run_at":    _CACHE.get("last_run_at"),
        "run_id":         _CACHE.get("run_id"),
        "run_started_at": _CACHE.get("run_started_at"),
    }


# ── Plants & Overview ─────────────────────────────────────────────────────────

@app.get("/api/plants")
def get_plants():
    """Return list of all plants and their latest status."""
    df = _load_df()
    if df.empty:
        return {"plants": []}
    out = _get_orch_output()
    buyer_inv  = out.get("buyer_inventory", {})
    mech_risks = out.get("mechanic", {}).get("facility_risks", {})
    sch_plans  = out.get("scheduler", {})

    plants_list = []
    for fac in sorted(df["Assigned_Facility"].unique()):
        fac_df     = df[df["Assigned_Facility"] == fac]
        if not fac_df.empty:
            latest_row = fac_df.sort_values("Timestamp").iloc[-1]
            oee        = float(latest_row["Machine_OEE_Pct"])
            wf_dep     = float(latest_row["Workforce_Deployed"])
            wf_req     = float(latest_row["Workforce_Required"])
        else:
            oee        = 0.0
            wf_dep     = 0.0
            wf_req     = 1.0

        risk_info  = mech_risks.get(fac, {})
        inv_info   = buyer_inv.get(fac, {})
        plan_info  = sch_plans.get(fac, {})
        wf_pct     = (wf_dep / max(wf_req, 1)) * 100

        plants_list.append({
            "name":            fac,
            "short_name":      fac.split("(")[0].strip(),
            "oee_pct":         round(oee, 1),
            "risk_score":      risk_info.get("risk_score", 0),
            "risk_status":     risk_info.get("status", "healthy"),
            "inv_status":      inv_info.get("status", "healthy"),
            "inv_days":        inv_info.get("days_remaining", 0),
            "workforce_pct":   round(wf_pct, 1),
            "throughput":      plan_info.get("expected_throughput", 0),
            "plan_status":     "blocked" if risk_info.get("status") == "critical" else
                               "ready"   if plan_info.get("shift_plan")           else "pending",
        })
    return _json_safe({"plants": plants_list})


# ── Demand Intelligence ────────────────────────────────────────────────────────

@app.get("/api/demand")
def get_demand():
    """Demand intelligence data: time series, forecast, anomalies."""
    df  = _load_df()
    out = _get_orch_output()

    if df.empty:
        return {"error": "No data"}

    forecast = out.get("forecast", {})

    # Daily aggregated demand time series
    ts_df = (
        df.groupby(df["Timestamp"].dt.date)["Actual_Order_Qty"]
        .sum()
        .reset_index()
        .rename(columns={"Timestamp": "date", "Actual_Order_Qty": "qty"})
    )
    time_series = [
        {"date": str(row["date"]), "qty": int(row["qty"])}
        for _, row in ts_df.iterrows()
    ]

    # Per-facility weekly demand (downsampled from daily to keep chart readable)
    plant_series = {}
    for fac in df["Assigned_Facility"].unique():
        fac_df = df[df["Assigned_Facility"] == fac].copy()
        fac_df = fac_df.set_index("Timestamp").sort_index()
        fac_ts = (
            fac_df["Actual_Order_Qty"]
            .resample("W")           # one point per calendar week
            .sum()
            .reset_index()
        )
        plant_series[fac] = [
            {"date": str(r["Timestamp"])[:10], "qty": int(r["Actual_Order_Qty"])}
            for _, r in fac_ts.iterrows()
        ]

    anomaly_rows = forecast.get("anomaly_rows", [])
    if anomaly_rows and isinstance(anomaly_rows, pd.DataFrame):
        anomaly_rows = anomaly_rows.to_dict("records")

    return _json_safe({
        "forecast_qty":     forecast.get("forecast_qty", 0),
        "trend_slope":      forecast.get("trend_slope", 0.0),
        "r_squared":        forecast.get("r_squared", 0.0),
        "anomaly_count":    forecast.get("anomaly_count", 0),
        "risk_level":       forecast.get("risk_level", "low"),
        "summary":          forecast.get("summary", ""),
        "recommended_action": forecast.get("recommended_action", ""),
        "horizon_days":     forecast.get("horizon_days", 7),
        "time_series":      time_series,
        "plant_series":     plant_series,
        "anomaly_rows":     anomaly_rows,
        "schedule_status":  {
            "on_time":  int((df["Schedule_Status"] == "On-Time").sum()),
            "delayed":  int((df["Schedule_Status"] == "Delayed").sum()),
            "total":    len(df),
        },
    })


# ── Inventory & Logistics ─────────────────────────────────────────────────────

@app.get("/api/inventory")
def get_inventory():
    """Inventory & logistics data per plant."""
    df  = _load_df()
    out = _get_orch_output()

    buyer_inv = out.get("buyer_inventory", {})
    buyer_out = out.get("buyer", {})

    # Inventory time series for all plants
    inv_series = {}
    for fac in df["Assigned_Facility"].unique():
        fac_ts = (
            df[df["Assigned_Facility"] == fac]
            .groupby(df[df["Assigned_Facility"] == fac]["Timestamp"].dt.date)["Raw_Material_Inventory_Units"]
            .mean()
            .reset_index()
        )
        inv_series[fac] = [
            {"date": str(r["Timestamp"]), "stock": float(r["Raw_Material_Inventory_Units"])}
            for _, r in fac_ts.iterrows()
        ]

    # Supplier quote trends
    quote_series = (
        df.groupby(df["Timestamp"].dt.date)["Live_Supplier_Quote_USD"]
        .mean()
        .reset_index()
    )
    quotes = [
        {"date": str(r["Timestamp"]), "quote": float(r["Live_Supplier_Quote_USD"])}
        for _, r in quote_series.iterrows()
    ]

    return _json_safe({
        "buyer_inventory":        buyer_inv,
        "reorders":               buyer_out.get("reorders", []),
        "total_spend_requested":  buyer_out.get("total_spend_requested_usd", 0.0),
        "reorders_triggered":     buyer_out.get("reorders_triggered", 0),
        "facilities_checked":     buyer_out.get("facilities_checked", 0),
        "summary":                buyer_out.get("summary", ""),
        "narrative":              buyer_out.get("narrative", ""),
        "inv_time_series":        inv_series,
        "quote_time_series":      quotes,
    })


# ── Production Master Plan ────────────────────────────────────────────────────

@app.get("/api/production")
def get_production():
    """Production master plan data."""
    df  = _load_df()
    out = _get_orch_output()

    scheduler = out.get("scheduler", {})

    # Schedule status breakdown
    status_counts = (
        df.groupby(["Assigned_Facility", "Schedule_Status"])
        .size()
        .reset_index(name="count")
        .to_dict("records")
    ) if not df.empty else []

    # Order qty per facility per day
    production_ts = {}
    for fac in df["Assigned_Facility"].unique():
        fac_ts = (
            df[df["Assigned_Facility"] == fac]
            .groupby(df[df["Assigned_Facility"] == fac]["Timestamp"].dt.date)["Actual_Order_Qty"]
            .sum()
            .reset_index()
        )
        production_ts[fac] = [
            {"date": str(r["Timestamp"]), "qty": int(r["Actual_Order_Qty"])}
            for _, r in fac_ts.iterrows()
        ]

    return _json_safe({
        "scheduler":        scheduler,
        "status_counts":    status_counts,
        "production_ts":    production_ts,
        "conflicts":        out.get("conflicts", []),
        "final_status":     out.get("final_status", "UNKNOWN"),
    })


# ── Machine Health & OEE ──────────────────────────────────────────────────────

@app.get("/api/machines")
def get_machines():
    """Machine health and OEE data per plant."""
    df  = _load_df()
    out = _get_orch_output()

    mechanic = out.get("mechanic", {})

    # OEE time series per facility
    oee_series = {}
    for fac in df["Assigned_Facility"].unique():
        fac_ts = (
            df[df["Assigned_Facility"] == fac]
            .groupby(df[df["Assigned_Facility"] == fac]["Timestamp"].dt.date)["Machine_OEE_Pct"]
            .mean()
            .reset_index()
        )
        oee_series[fac] = [
            {"date": str(r["Timestamp"]), "oee": round(float(r["Machine_OEE_Pct"]), 1)}
            for _, r in fac_ts.iterrows()
        ]

    # Temperature & vibration data if available
    extra_cols = {}
    for col in ["Machine_Temperature_C", "Machine_Vibration_mm_s"]:
        if col in df.columns:
            col_ts = (
                df.groupby([df["Assigned_Facility"], df["Timestamp"].dt.date])[col]
                .mean()
                .reset_index()
            )
            extra_cols[col] = col_ts.rename(
                columns={"Assigned_Facility": "facility", "Timestamp": "date", col: "value"}
            ).to_dict("records")

    return _json_safe({
        "facility_risks":      mechanic.get("facility_risks", {}),
        "critical_facilities": mechanic.get("critical_facilities", []),
        "warning_facilities":  mechanic.get("warning_facilities", []),
        "recommendations":     mechanic.get("recommendations", []),
        "summary":             mechanic.get("summary", ""),
        "oee_time_series":     oee_series,
        "extra_telemetry":     extra_cols,
    })


# ── Finance Dashboard ─────────────────────────────────────────────────────────

@app.get("/api/finance")
def get_finance():
    """Finance dashboard data."""
    df  = _load_df()
    out = _get_orch_output()

    finance = out.get("finance", {})

    # Carbon penalty over time — resampled weekly to avoid dense/scattered charts
    penalty_ts = (
        df.set_index("Timestamp")["Carbon_Cost_Penalty_USD"]
        .resample("W")
        .sum()
        .reset_index()
    )
    penalties = [
        {"date": str(r["Timestamp"])[:10], "penalty": round(float(r["Carbon_Cost_Penalty_USD"]), 2)}
        for _, r in penalty_ts.iterrows()
    ]

    # Supplier quote cost over time — resampled weekly to avoid dense/scattered charts
    cost_ts = (
        df.set_index("Timestamp")["Live_Supplier_Quote_USD"]
        .resample("W")
        .mean()
        .reset_index()
    )
    costs = [
        {"date": str(r["Timestamp"])[:10], "cost": round(float(r["Live_Supplier_Quote_USD"]), 2)}
        for _, r in cost_ts.iterrows()
    ]

    # Monthly spend from DB
    try:
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        monthly_rows = conn.execute(
            "SELECT * FROM monthly_spend ORDER BY logged_at DESC LIMIT 50"
        ).fetchall()
        monthly_spend = [dict(r) for r in monthly_rows]
        conn.close()
    except Exception:
        monthly_spend = []

    alerts = []
    if finance.get("gate_decision") == "BLOCKED":
        alerts.append("Finance gate is currently BLOCKED.")
    if finance.get("budget_status", {}).get("over_budget"):
        alerts.append("Monthly operating spend is above the configured budget threshold.")
    if finance.get("risk_score", 0) >= 70:
        alerts.append("Financial risk score is elevated and needs review.")

    return _json_safe({
        "health_score":   finance.get("health_score", 100.0),
        "gate_decision":  finance.get("gate_decision", "APPROVED"),
        "risk_score":     finance.get("risk_score", 0),
        "budget_status":  finance.get("budget_status", {}),
        "alerts":         finance.get("alerts", []) or alerts,
        "summary":        finance.get("summary", ""),
        "suggestions":    finance.get("suggestions", []),
        "penalty_series": penalties,
        "cost_series":    costs,
        "monthly_spend":  monthly_spend,
    })


# ── Carbon & Energy ───────────────────────────────────────────────────────────

@app.get("/api/carbon")
def get_carbon():
    """Carbon and energy data."""
    df  = _load_df()
    out = _get_orch_output()

    environ = out.get("environ", {})

    # Energy time series
    energy_ts = (
        df.groupby(df["Timestamp"].dt.date)["Energy_Consumed_kWh"]
        .sum()
        .reset_index()
    )
    energy_series = [
        {"date": str(r["Timestamp"]), "kwh": round(float(r["Energy_Consumed_kWh"]), 1)}
        for _, r in energy_ts.iterrows()
    ]

    # Peak vs off-peak breakdown if Grid_Pricing_Period exists
    grid_breakdown = {}
    if "Grid_Pricing_Period" in df.columns and "Energy_Consumed_kWh" in df.columns:
        grid_breakdown = (
            df.groupby("Grid_Pricing_Period")["Energy_Consumed_kWh"]
            .sum()
            .to_dict()
        )

    # Per-facility carbon penalty
    facility_penalties = (
        df.groupby("Assigned_Facility")["Carbon_Cost_Penalty_USD"]
        .sum()
        .reset_index()
        .rename(columns={"Assigned_Facility": "facility", "Carbon_Cost_Penalty_USD": "total_penalty"})
        .to_dict("records")
    )

    return _json_safe({
        "total_carbon_kg":        environ.get("total_carbon_kg", 0.0),
        "total_energy_kwh":       environ.get("total_energy_kwh", 0.0),
        "total_penalty_usd":      environ.get("total_penalty_usd", 0.0),
        "peak_penalty_usd":       environ.get("peak_penalty_usd", 0.0),
        "off_peak_penalty_usd":   environ.get("off_peak_penalty_usd", 0.0),
        "peak_energy_kwh":        environ.get("peak_energy_kwh", 0.0),
        "off_peak_energy_kwh":    environ.get("off_peak_energy_kwh", 0.0),
        "peak_penalty_pct":       environ.get("peak_penalty_pct", 0.0),
        "compliance_flag":        environ.get("compliance_flag", True),
        "compliance_status":      environ.get("compliance_status", "COMPLIANT"),
        "shift_suggestions":      environ.get("shift_suggestions", []),
        "estimated_savings_usd":  environ.get("estimated_savings_usd", 0.0),
        "summary":                environ.get("summary", ""),
        "energy_time_series":     energy_series,
        "grid_breakdown":         grid_breakdown,
        "facility_penalties":     facility_penalties,
    })


# ── Agent Activity Log ────────────────────────────────────────────────────────

@app.get("/api/agents/log")
def get_agent_log(
    limit: int = 100,
    agent_name: Optional[str] = None,
    severity: Optional[str] = None,
    run_id: Optional[str] = None,
):
    """Agent activity log from agent_events table. Optionally filter by run_id."""
    try:
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        query  = "SELECT * FROM agent_events WHERE 1=1"
        params = []
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        query += f" ORDER BY logged_at DESC LIMIT {int(limit)}"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return {"log": [dict(r) for r in rows]}
    except Exception as exc:
        logger.error("get_agent_log failed: %s", exc)
        return {"log": []}


# ── Coordination ────────────────────────────────────────────────────────────────

@app.get("/api/coordination/messages")
def get_coordination_messages(run_id: Optional[str] = None):
    """All coordination messages for a run (or the current run if run_id is omitted)."""
    from agents.coordination_bus import CoordinationBus
    bus = CoordinationBus(config.DB_PATH)
    effective_run_id = run_id or _CACHE.get("run_id")
    if not effective_run_id:
        return {"messages": [], "run_id": None}
    messages = bus.get_all_for_run(effective_run_id)
    # Parse JSON payload strings
    for m in messages:
        if isinstance(m.get("payload"), str):
            try:
                m["payload"] = json.loads(m["payload"])
            except Exception:
                pass
        if isinstance(m.get("to_agent"), str):
            try:
                m["to_agent"] = json.loads(m["to_agent"])
            except Exception:
                pass
    return _json_safe({"messages": messages, "run_id": effective_run_id})


@app.get("/api/coordination/active")
def get_coordination_active():
    """Returns open coordination blockers and proposals for the current run."""
    from agents.coordination_bus import CoordinationBus
    bus = CoordinationBus(config.DB_PATH)
    run_id = _CACHE.get("run_id")
    if not run_id:
        return {"blockers": [], "proposals": [], "run_id": None}
    blockers  = bus.get_open_blockers(run_id)
    proposals = bus.get_proposals_for_finance(run_id)
    for m in blockers + proposals:
        if isinstance(m.get("payload"), str):
            try:
                m["payload"] = json.loads(m["payload"])
            except Exception:
                pass
    return _json_safe({"blockers": blockers, "proposals": proposals, "run_id": run_id})


@app.get("/api/coordination/thread/{blocker_id}")
def get_coordination_thread(blocker_id: int):
    """Full negotiation thread starting from a blocker message."""
    from agents.coordination_bus import CoordinationBus
    bus = CoordinationBus(config.DB_PATH)
    thread = bus.get_full_thread(blocker_id)
    return _json_safe({"thread": thread})


# ── HITL ──────────────────────────────────────────────────────────────────────

@app.get("/api/hitl/counts")
def get_hitl_counts():
    return HitlManager().get_counts()


@app.get("/api/hitl/pending")
def get_hitl_pending(item_type: Optional[str] = None):
    items = HitlManager().get_pending(item_type=item_type)
    return _json_safe({"items": items, "count": len(items)})


@app.get("/api/hitl/history")
def get_hitl_history(limit: int = 50, item_type: Optional[str] = None):
    items = HitlManager().get_history(limit=limit, item_type=item_type)
    return _json_safe({"items": items, "count": len(items)})


@app.post("/api/hitl/approve/{item_id}")
def approve_hitl_item(item_id: int, req: HitlActionRequest):
    ok = HitlManager().approve(item_id, comment=req.comment, approved_by=req.resolved_by)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found or already resolved")
    return {"status": "approved", "item_id": item_id}


@app.post("/api/hitl/reject/{item_id}")
def reject_hitl_item(item_id: int, req: HitlActionRequest):
    ok = HitlManager().reject(item_id, comment=req.comment, rejected_by=req.resolved_by)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found or already resolved")
    return {"status": "rejected", "item_id": item_id}


@app.post("/api/hitl/enqueue")
def enqueue_hitl_item(req: HitlEnqueueRequest):
    new_id = HitlManager().enqueue(
        item_type=req.item_type,
        source=req.source,
        payload=req.payload,
    )
    if new_id < 0:
        raise HTTPException(status_code=500, detail="Failed to enqueue HITL item")
    return {"status": "enqueued", "item_id": new_id}


# ── NLP Command Panel ─────────────────────────────────────────────────────────

@app.post("/api/nlp/query")
def process_nlp_query(req: NlpQueryRequest):
    """Process a natural-language command and return structured response."""
    df  = _load_df()
    out = _get_orch_output()

    plants = out.get("plants", sorted(df["Assigned_Facility"].unique().tolist()) if not df.empty else [])
    pending_items = HitlManager().get_pending()
    pending_counts = HitlManager().get_counts()

    # Parse intent
    heuristic = heuristic_intent(req.query, plants, req.selected_plant)
    llm_parsed = ask_ollama_intent(
        req.query,
        out,
        pending_items,
        pending_counts,
        selected_plant=req.selected_plant,
        recent_logs=_recent_agent_log(),
    )
    intent_data = merge_intents(heuristic, llm_parsed)

    # Build deterministic answer
    fallback_answer, fallback_agent = build_query_answer(
        req.query, out, df,
        pending_counts=pending_counts,
        selected_plant=req.selected_plant,
    )
    answer = intent_data.get("response") or fallback_answer
    agent_name = intent_data.get("agent") or fallback_agent

    # Handle actionable intents
    action_result = None
    intent = intent_data.get("intent", "query")
    params = intent_data.get("params", {})

    if intent in ("approve", "reject"):
        matched_item = select_hitl_item(req.query, pending_items, plants)
        if matched_item:
            item_id = matched_item.get("id")
            hm = HitlManager()
            if intent == "approve":
                ok = hm.approve(item_id, comment=params.get("comment", "Approved via NLP"), approved_by="NLP Interface")
            else:
                ok = hm.reject(item_id, comment=params.get("comment", "Rejected via NLP"), rejected_by="NLP Interface")
            action_result = {
                "action_taken": f"{intent.upper()} item #{item_id}",
                "item_type":    matched_item.get("item_type"),
                "success":      ok,
            }
            answer = f"{'✅' if ok else '❌'} {intent.capitalize()}ed HITL item #{item_id} ({matched_item.get('item_type', 'unknown')})."
        else:
            answer = "No matching HITL item found for that command."

    elif intent == "escalate":
        new_id = HitlManager().enqueue(
            item_type=params.get("item_type", "ops"),
            source="NLP Interface",
            payload={"query": req.query, "intent": intent_data},
        )
        action_result = {"action_taken": f"Escalated to HITL queue as item #{new_id}", "item_id": new_id}
        answer = f"🔔 Escalated to HITL queue as item #{new_id}."

    return _json_safe({
        "query":           req.query,
        "intent":          intent_data.get("intent"),
        "agent":           agent_name,
        "confidence_pct":  intent_data.get("confidence_pct"),
        "params":          params,
        "response":        answer,
        "action_result":   action_result,
        "action":          intent_data.get("action", ""),
        "timestamp":       datetime.utcnow().isoformat(),
    })


# ── Digital Twin Simulation ───────────────────────────────────────────────────

@app.get("/api/simulation/defaults/{plant_name:path}")
def get_simulation_defaults(plant_name: str):
    """Get live defaults for the Digital Twin sliders for a specific plant."""
    df  = _load_df()
    out = _get_orch_output()
    defaults = derive_defaults_from_agent_output(plant_name, out, df)
    return _json_safe(defaults)


@app.post("/api/simulation/run")
def run_simulation(req: SimulationRequest):
    """Run a Digital Twin simulation for a plant."""
    try:
        result = simulate(
            plant_id        = req.plant_id,
            oee_pct         = req.oee_pct,
            workforce_pct   = req.workforce_pct,
            forecast_qty    = req.forecast_qty,
            energy_price    = req.energy_price,
            downtime_hrs    = req.downtime_hrs,
            optimise_for    = req.optimise_for,
            horizon_days    = req.horizon_days,
            base_capacity   = req.base_capacity,
            demand_buffer_pct = req.demand_buffer_pct,
        )
        return _json_safe(result)
    except Exception as exc:
        logger.error("Simulation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/twin/scenarios")
def run_scenario_compare(req: ScenarioCompareRequest):
    """Run up to 4 scenarios and return comparison matrix."""
    if not req.scenarios:
        raise HTTPException(status_code=400, detail="No scenarios provided")
    try:
        scenario_dicts = [
            {
                "plant_id":          s.plant_id,
                "oee_pct":           s.oee_pct,
                "workforce_pct":     s.workforce_pct,
                "forecast_qty":      s.forecast_qty,
                "energy_price":      s.energy_price,
                "downtime_hrs":      s.downtime_hrs,
                "optimise_for":      s.optimise_for,
                "horizon_days":      s.horizon_days,
                "base_capacity":     s.base_capacity,
                "demand_buffer_pct": s.demand_buffer_pct,
            }
            for s in req.scenarios
        ]
        results = simulate_scenario_compare(scenario_dicts)
        # Attach original label to each result
        for i, r in enumerate(results):
            r["label"] = req.scenarios[i].label if i < len(req.scenarios) else f"Scenario {i+1}"
        return _json_safe({"results": results})
    except Exception as exc:
        logger.error("Scenario compare failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/twin/chat")
def twin_chat(req: TwinChatRequest):
    """Natural-language 'What if?' → Ollama extracts constraints → simulate."""
    import requests as _req
    ctx = req.context
    plant_id = ctx.get("plant_id", "Plant 1")
    prompt = f"""You are a digital twin assistant for a production planning system.

Current simulation context:
- Plant: {plant_id}
- OEE: {ctx.get('oee_pct', 91)}%
- Workforce: {ctx.get('workforce_pct', 95)}%
- Forecast demand: {ctx.get('forecast_qty', 2000)} units
- Downtime: {ctx.get('downtime_hrs', 0)} hours
- Optimise for: {ctx.get('optimise_for', 'Time')}
- Energy price: ${ctx.get('energy_price', 0.12)}/kWh
- Horizon: {ctx.get('horizon_days', 7)} days

User query: "{req.prompt}"

Extract parameter changes from the query and respond with ONLY this JSON:
{{
  "oee_pct": <float or null>,
  "workforce_pct": <float or null>,
  "forecast_qty": <int or null>,
  "downtime_hrs": <float or null>,
  "optimise_for": <"Time"|"Cost"|"Carbon" or null>,
  "energy_price": <float or null>,
  "horizon_days": <int or null>,
  "explanation": "One sentence explaining what changed and why"
}}

If no parameter maps to the query, set all numeric fields to null and explain in 'explanation'."""

    try:
        resp = _req.post(
            "http://localhost:11434/api/generate",
            json={"model": "llama3.2", "prompt": prompt, "stream": False, "format": "json"},
            timeout=30,
        )
        raw = resp.json().get("response", "{}")
        import json as _json
        changes = _json.loads(raw)
    except Exception:
        changes = {"explanation": "Could not parse your query. Please try rephrasing."}

    # Merge changes into current params
    new_params = dict(ctx)
    changed_fields = []
    for field in ["oee_pct", "workforce_pct", "forecast_qty", "downtime_hrs",
                  "optimise_for", "energy_price", "horizon_days"]:
        val = changes.get(field)
        if val is not None:
            new_params[field] = val
            changed_fields.append(field)

    # Run simulation with new params
    sim_result = None
    if changed_fields:
        try:
            sim_result = simulate(
                plant_id          = new_params.get("plant_id", plant_id),
                oee_pct           = float(new_params.get("oee_pct", 91)),
                workforce_pct     = float(new_params.get("workforce_pct", 95)),
                forecast_qty      = int(new_params.get("forecast_qty", 2000)),
                energy_price      = float(new_params.get("energy_price", 0.12)),
                downtime_hrs      = float(new_params.get("downtime_hrs", 0)),
                optimise_for      = str(new_params.get("optimise_for", "Time")),
                horizon_days      = int(new_params.get("horizon_days", 7)),
                base_capacity     = new_params.get("base_capacity"),
                demand_buffer_pct = float(new_params.get("demand_buffer_pct", 0.10)),
            )
        except Exception as exc:
            logger.warning("Twin chat simulation failed: %s", exc)

    return _json_safe({
        "explanation":     changes.get("explanation", ""),
        "changed_fields":  changed_fields,
        "new_params":      new_params,
        "simulation":      sim_result,
    })


@app.get("/api/twin/model/status")
def get_twin_model_status():
    """Return ML model training status, R², and feature importances."""
    return _json_safe(twin_ml.get_model_status())


@app.post("/api/twin/model/train")
def trigger_twin_model_training(background_tasks: BackgroundTasks):
    """Manually re-trigger ML model training."""
    twin_ml.ensure_model_trained(force=True)
    return {"status": "training_started"}


@app.post("/api/twin/apply-scenario")
def apply_scenario_to_live(req: ApplyScenarioRequest, background_tasks: BackgroundTasks):
    """
    Option B: Apply a scenario to the live schedule by injecting its parameters
    into the orchestrator context and triggering a fresh agent run.
    The scenario params override forecast_qty and optimise_for for this run.
    """
    if _CACHE["is_running"]:
        raise HTTPException(status_code=409, detail="Orchestrator is already running. Try again shortly.")

    s = req.scenario
    _CACHE["scenario_override"] = {
        "forecast_qty":       s.forecast_qty,
        "optimise_for":       s.optimise_for,
        "oee_override":       s.oee_pct,
        "workforce_override": s.workforce_pct,
        "applied_label":      s.label,
        "applied_at":         datetime.utcnow().isoformat(),
    }
    background_tasks.add_task(_run_orchestrator_sync_with_scenario)
    return {
        "status":   "started",
        "message":  f"Scenario '{s.label}' is being applied to the live schedule.",
        "scenario": s.label,
    }


# ── Summary endpoint for Command Center ───────────────────────────────────────

@app.get("/api/command-center")
def get_command_center():
    """All data needed by Command Center in one call."""
    df  = _load_df()
    out = _get_orch_output()

    # KPI metrics and Sparklines
    kpis = {}
    sparklines = {
        "otd": [],
        "inventory": [],
        "alerts": [],
        "health": [],
        "hitl": []
    }
    if not df.empty:
        kpis["on_time_pct"]      = round(float((df["Schedule_Status"] == "On-Time").mean() * 100), 1)
        kpis["workforce_pct"]    = round(float((df["Workforce_Deployed"].sum() / max(df["Workforce_Required"].sum(), 1)) * 100), 1)
        kpis["total_carbon_usd"] = round(float(df["Carbon_Cost_Penalty_USD"].sum()), 2)
        buyer_inv = out.get("buyer_inventory", {})
        kpis["min_inventory_days"] = round(
            min((v.get("days_remaining", 0) for v in buyer_inv.values()), default=0), 1
        ) if buyer_inv else 0.0

        try:
            dates = df["Timestamp"].dt.date
            otd_daily = df.groupby(dates).apply(lambda x: (x["Schedule_Status"] == "On-Time").mean() * 100)
            sparklines["otd"] = otd_daily.fillna(0).tolist()[-7:]
            
            inv_daily = df.groupby(dates)["Raw_Material_Inventory_Units"].mean()
            sparklines["inventory"] = inv_daily.fillna(0).tolist()[-7:]
            
            curr_health = out.get("system_health", 85.0)
            sparklines["health"] = [max(0, min(100, curr_health + (i-3)*1.5)) for i in range(7)]
        except Exception as e:
            logger.error(f"Sparkline calc error: {e}")

    # Agent log counts
    try:
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        alert_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM agent_events WHERE severity != 'INFO'"
        ).fetchone()
        kpis["active_alerts"] = alert_row["cnt"] if alert_row else 0

        alert_counts = conn.execute(
            "SELECT count(*) as c FROM agent_events WHERE severity != 'INFO' "
            "GROUP BY date(logged_at) ORDER BY date(logged_at) DESC LIMIT 7"
        ).fetchall()
        alerts_hist = [r["c"] for r in reversed(alert_counts)]
        sparklines["alerts"] = alerts_hist if alerts_hist else [0]*7

        conn.close()
    except Exception:
        kpis["active_alerts"] = 0
        sparklines["alerts"] = [0]*7

    hitl_counts = HitlManager().get_counts()
    curr_hitl = hitl_counts.get("total", 0)
    sparklines["hitl"] = [max(0, curr_hitl + i - 3) for i in range(7)]

    return _json_safe({
        "final_status":  out.get("final_status", "UNKNOWN"),
        "system_health": out.get("system_health", 0.0),
        "conflicts":     out.get("conflicts", []),
        "last_run_at":   _CACHE.get("last_run_at"),
        "is_running":    _CACHE["is_running"],
        "kpis":          kpis,
        "sparklines":    sparklines,
        "hitl_counts":   hitl_counts,
        "plants":        out.get("plants", []),
        "agents": {
            "forecast": {
                "forecast_qty": out.get("forecast", {}).get("forecast_qty", 0),
                "risk_level":   out.get("forecast", {}).get("risk_level", "low"),
                "summary":      (out.get("forecast", {}).get("summary", "") or "")[:140],
            },
            "mechanic": {
                "critical_count": len(out.get("mechanic", {}).get("critical_facilities", [])),
                "warning_count":  len(out.get("mechanic", {}).get("warning_facilities", [])),
                "summary":        (out.get("mechanic", {}).get("summary", "") or "")[:140],
            },
            "buyer": {
                "reorders_triggered": out.get("buyer", {}).get("reorders_triggered", 0),
                "total_spend_usd":    out.get("buyer", {}).get("total_spend_requested_usd", 0.0),
            },
            "environ": {
                "compliance_flag":   out.get("environ", {}).get("compliance_flag", True),
                "peak_penalty_pct":  out.get("environ", {}).get("peak_penalty_pct", 0.0),
                "summary":           (out.get("environ", {}).get("summary", "") or "")[:140],
            },
            "finance": {
                "health_score":  out.get("finance", {}).get("health_score", 100.0),
                "gate_decision": out.get("finance", {}).get("gate_decision", "APPROVED"),
                "spent_usd":     out.get("finance", {}).get("budget_status", {}).get("spent_usd", 0.0),
            },
            "scheduler": {
                "plant_count":  len(out.get("scheduler", {})),
                "ready_count":  len([p for p in out.get("scheduler", {}).values() if p.get("shift_plan")]),
                "avg_utilisation": round(
                    float(np.mean([p.get("utilisation_pct", 0) for p in out.get("scheduler", {}).values()]))
                    if out.get("scheduler") else 0.0,
                    1,
                ),
                "total_throughput": int(sum(
                    p.get("expected_throughput", 0)
                    for p in out.get("scheduler", {}).values()
                )),
            },
        },
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Pre-load data on startup
    _load_df()
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
