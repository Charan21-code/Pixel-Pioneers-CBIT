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
from simulation.digital_twin import simulate, derive_defaults_from_agent_output
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
    "orch_output":  None,
    "df":           None,
    "last_run_at":  None,
    "is_running":   False,
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
    try:
        df = _load_df()
        if df.empty:
            return {"error": "No data available"}

        as_of_time = df["Timestamp"].max()
        context = {"df": df, "as_of_time": as_of_time}
        orch = OrchestratorAgent()
        result = orch.run(context)
        _CACHE["orch_output"] = result
        _CACHE["last_run_at"] = datetime.utcnow().isoformat()
        logger.info("Orchestrator run complete. Status: %s", result.get("final_status"))
        return _json_safe(result)
    except Exception as exc:
        logger.error("Orchestrator run failed: %s", exc, exc_info=True)
        return {"error": str(exc)}
    finally:
        _CACHE["is_running"] = False


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
    })


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
        oee        = float(fac_df["Machine_OEE_Pct"].mean()) if not fac_df.empty else 0.0
        risk_info  = mech_risks.get(fac, {})
        inv_info   = buyer_inv.get(fac, {})
        plan_info  = sch_plans.get(fac, {})
        wf_dep     = float(fac_df["Workforce_Deployed"].sum()) if not fac_df.empty else 0
        wf_req     = float(fac_df["Workforce_Required"].sum()) if not fac_df.empty else 1
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
def get_agent_log(limit: int = 100, agent_name: Optional[str] = None, severity: Optional[str] = None):
    """Agent activity log from agent_events table."""
    try:
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        query  = "SELECT * FROM agent_events WHERE 1=1"
        params = []
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


# ── Summary endpoint for Command Center ───────────────────────────────────────

@app.get("/api/command-center")
def get_command_center():
    """All data needed by Command Center in one call."""
    df  = _load_df()
    out = _get_orch_output()

    # KPI metrics
    kpis = {}
    if not df.empty:
        kpis["on_time_pct"]      = round(float((df["Schedule_Status"] == "On-Time").mean() * 100), 1)
        kpis["workforce_pct"]    = round(float((df["Workforce_Deployed"].sum() / max(df["Workforce_Required"].sum(), 1)) * 100), 1)
        kpis["total_carbon_usd"] = round(float(df["Carbon_Cost_Penalty_USD"].sum()), 2)
        buyer_inv = out.get("buyer_inventory", {})
        kpis["min_inventory_days"] = round(
            min((v.get("days_remaining", 0) for v in buyer_inv.values()), default=0), 1
        ) if buyer_inv else 0.0

    # Agent log counts
    try:
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        alert_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM agent_events WHERE severity != 'INFO'"
        ).fetchone()
        kpis["active_alerts"] = alert_row["cnt"] if alert_row else 0
        conn.close()
    except Exception:
        kpis["active_alerts"] = 0

    hitl_counts = HitlManager().get_counts()

    return _json_safe({
        "final_status":  out.get("final_status", "UNKNOWN"),
        "system_health": out.get("system_health", 0.0),
        "conflicts":     out.get("conflicts", []),
        "last_run_at":   _CACHE.get("last_run_at"),
        "is_running":    _CACHE["is_running"],
        "kpis":          kpis,
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
