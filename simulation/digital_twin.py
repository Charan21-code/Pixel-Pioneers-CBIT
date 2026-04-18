"""
simulation/digital_twin.py — Digital Twin Simulation Engine

Simulates 7-day (configurable) production output for a single plant
given operator-controlled parameters. All default values are passed
in from live agent outputs (not hardcoded) by the calling page.

Key design
----------
- Pure function: simulate() takes parameters → returns metrics dict.
- No side effects, no DB writes, no Ollama calls.
- The calling Streamlit page handles display and caching.
- Results are deterministic given the same inputs.

Model
-----
For each simulation day:
    day_capacity = base_capacity
                   × OEE_factor
                   × workforce_factor
                   × available_hours_factor   (reduced on downtime day)

Then:
    cost_usd   = total_output × unit_energy_cost × cost_per_kwh × overhead
    carbon_kg  = total_output × carbon_per_unit

Baseline capacity (base_capacity) is derived from the plant's recent
historical Actual_Order_Qty mean — so it reflects real production rates.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

import config
from simulation import twin_ml

logger = logging.getLogger(__name__)

# Physical constants (chemistry/engineering)
_CARBON_KG_PER_KWH   = 0.43    # kg CO₂ per kWh (grid average)
_KWH_PER_UNIT        = 2.8     # kWh consumed per manufactured unit (estimate)
_BASE_HOURS_PER_DAY  = 24      # total available hours
_MIN_BASE_CAPACITY   = 500     # floor so empty plants still simulate
_OVERHEAD_MULT       = config.FINANCE.get("overhead_multiplier", 1.15)
_DEFAULT_BASE_CAPACITY = config.DIGITAL_TWIN.get("base_capacity", 2000)


def simulate(
    plant_id:        str,
    oee_pct:         float,
    workforce_pct:   float,
    forecast_qty:    int,
    energy_price:    float,      # $/kWh
    downtime_hrs:    float,      # applied on Day 1 only
    optimise_for:    str,        # "Time" | "Cost" | "Carbon"
    horizon_days:    int  = 7,
    base_capacity:   Optional[int] = None,  # pass plant's daily avg if known
    demand_buffer_pct: float = 0.10,
) -> dict:
    """
    Run a digital-twin simulation for one plant over `horizon_days`.

    Parameters
    ----------
    plant_id        : human-readable plant name (for display)
    oee_pct         : Overall Equipment Effectiveness (0–100), live from MechanicAgent
    workforce_pct   : % of required workforce deployed (0–100), live from df
    forecast_qty    : total units to produce (from ForecasterAgent / n_plants share)
    energy_price    : cost per kWh in USD (live from df avg or slider)
    downtime_hrs    : machine downtime hours applied on Day 1 (0 = no downtime)
    optimise_for    : affects priority messaging; Cost reduces night shifts, Carbon caps daytime
    horizon_days    : number of simulation days (default 7)
    base_capacity   : daily unit capacity at 100% OEE and workforce (passed from agent; auto-derived if None)
    demand_buffer_pct : safety buffer added to forecast_qty target

    Returns
    -------
    dict with keys:
        expected_output_units : int     — total units produced over horizon
        target_qty            : int     — forecast_qty × (1 + buffer)
        shortfall_units       : int     — max(0, target - output)
        surplus_units         : int     — max(0, output - target)
        completion_day        : int     — day target is reached (horizon_days+1 if never)
        cost_usd              : float   — total estimated production cost
        carbon_kg             : float   — total estimated CO₂ emissions
        workforce_needed      : int     — absolute worker count needed
        daily_breakdown       : list    — per-day output list (len = horizon_days)
        cumulative_breakdown  : list    — cumulative output list
        daily_cost            : list    — per-day cost estimates
        daily_carbon          : list    — per-day carbon estimates
        parameters_used       : dict    — echo of all inputs for UI display
        warnings              : list    — human-readable warnings
        optimise_suggestions  : list    — context-specific tips based on optimise_for
    """
    # ── Validate inputs ───────────────────────────────────────────────────────
    oee_pct       = max(1.0,  min(100.0, float(oee_pct)))
    workforce_pct = max(1.0,  min(100.0, float(workforce_pct)))
    downtime_hrs  = max(0.0,  min(float(_BASE_HOURS_PER_DAY), float(downtime_hrs)))
    horizon_days  = max(1,    min(30, int(horizon_days)))
    forecast_qty  = max(0,    int(forecast_qty))
    energy_price  = max(0.01, float(energy_price))

    oee_factor       = oee_pct       / 100.0
    workforce_factor = workforce_pct / 100.0

    # ── Derive base capacity if not provided ──────────────────────────────────
    if base_capacity is None or base_capacity <= 0:
        # Reasonable default: 2,000 units/day for a primary plant at 100% conditions
        base_capacity = _DEFAULT_BASE_CAPACITY
    base_capacity = max(_MIN_BASE_CAPACITY, int(base_capacity))

    target_qty = int(forecast_qty * (1 + demand_buffer_pct))

    # ── ML correction factor (computed once, applied to every day) ────────────
    # Uses peak_ratio=0.4 as a reasonable default since we don't have live
    # timestamp data at simulation time.
    formula_day_est = int(base_capacity * oee_factor * workforce_factor)
    ml_correction, ml_confidence = twin_ml.get_correction_factor(
        facility       = plant_id,
        oee_pct        = oee_pct,
        workforce_pct  = workforce_pct,
        energy_price   = energy_price,
        downtime_hrs   = downtime_hrs,
        base_capacity  = base_capacity,
        demand_buffer_pct = demand_buffer_pct,
        peak_ratio     = 0.40,
        formula_output = max(formula_day_est, 1),
    )
    ml_active = ml_correction != 1.0

    # ── Day-by-day simulation ─────────────────────────────────────────────────
    daily_output    = []
    daily_cost_list = []
    daily_carbon_list = []
    warnings        = []
    cumulative      = 0
    completion_day  = horizon_days + 1  # default: target never reached

    for day_idx in range(horizon_days):
        day_num = day_idx + 1

        # Available hours this day (downtime only on Day 1)
        downtime_today = downtime_hrs if day_idx == 0 else 0.0
        available_hrs  = _BASE_HOURS_PER_DAY - downtime_today
        hours_factor   = available_hrs / _BASE_HOURS_PER_DAY

        # Day production = base × OEE × workforce × hours available
        day_units = int(base_capacity * oee_factor * workforce_factor * hours_factor)

        # Apply ML correction factor to bring formula into alignment with real data
        day_units = int(day_units * ml_correction)

        # Optimisation adjustments
        if optimise_for == "Cost":
            # Reduce night-shift premium (simulated as 5% cost reduction)
            day_units = int(day_units * 0.97)
        elif optimise_for == "Carbon":
            # Shift heavy loads off-peak (simulated as 8% output trade-off for carbon saving)
            day_units = int(day_units * 0.92)

        daily_output.append(day_units)

        # Cost and carbon per day
        kwh_day   = day_units * _KWH_PER_UNIT
        cost_day  = round(kwh_day * energy_price * _OVERHEAD_MULT, 2)
        carbon_day = round(day_units * _KWH_PER_UNIT * _CARBON_KG_PER_KWH, 2)

        daily_cost_list.append(cost_day)
        daily_carbon_list.append(carbon_day)

        # Cumulatives
        cumulative += day_units
        if completion_day > horizon_days and cumulative >= target_qty:
            completion_day = day_num

        # Warnings
        if downtime_today > 0 and day_idx == 0:
            warnings.append(
                f"Day 1: {downtime_today:.0f}hrs of downtime reduces capacity by "
                f"{(1 - hours_factor)*100:.0f}%."
            )

    total_output = sum(daily_output)
    shortfall    = max(0, target_qty - total_output)
    surplus      = max(0, total_output - target_qty)
    total_cost   = round(sum(daily_cost_list), 2)
    total_carbon = round(sum(daily_carbon_list), 2)
    workforce_needed = int(round(workforce_pct / 100.0 * 150))  # 150 = typical required workforce

    # Warnings for critical conditions
    if oee_pct < 80:
        warnings.append(f"OEE is low ({oee_pct:.1f}%). Consider maintenance to recover capacity.")
    if workforce_pct < 75:
        warnings.append(f"Workforce at {workforce_pct:.1f}% — output severely constrained.")
    if shortfall > 0:
        warnings.append(
            f"Production shortfall of {shortfall:,} units. "
            f"Target ({target_qty:,}) will NOT be met in {horizon_days} days."
        )
    if completion_day > horizon_days:
        warnings.append(
            f"At current parameters, the {target_qty:,}-unit target is never reached "
            f"within {horizon_days} days."
        )

    # Optimisation suggestions
    suggestions = _build_suggestions(
        optimise_for, oee_pct, workforce_pct, energy_price,
        shortfall, total_carbon, target_qty
    )

    return {
        "plant_id":              plant_id,
        "expected_output_units": total_output,
        "target_qty":            target_qty,
        "shortfall_units":       shortfall,
        "surplus_units":         surplus,
        "completion_day":        completion_day,
        "cost_usd":              total_cost,
        "carbon_kg":             total_carbon,
        "workforce_needed":      workforce_needed,
        "daily_breakdown":       daily_output,
        "cumulative_breakdown":  list(np.cumsum(daily_output).astype(int)),
        "daily_cost":            daily_cost_list,
        "daily_carbon":          daily_carbon_list,
        "utilisation_pct":       round(min(100.0, (total_output / max(total_output + shortfall, 1)) * 100), 1),
        "ml_correction_applied": ml_active,
        "ml_confidence":         round(ml_confidence, 3),
        "ml_r2":                 twin_ml.get_model_status().get("r2_score"),
        "parameters_used": {
            "oee_pct":          oee_pct,
            "workforce_pct":    workforce_pct,
            "forecast_qty":     forecast_qty,
            "target_qty":       target_qty,
            "energy_price":     energy_price,
            "downtime_hrs":     downtime_hrs,
            "optimise_for":     optimise_for,
            "horizon_days":     horizon_days,
            "base_capacity":    base_capacity,
            "demand_buffer_pct": demand_buffer_pct,
        },
        "warnings":              warnings,
        "optimise_suggestions":  suggestions,
    }


def simulate_scenario_compare(scenarios: list[dict]) -> list[dict]:
    """
    Run multiple scenarios and return all results for side-by-side comparison.

    Parameters
    ----------
    scenarios : list of parameter dicts (each matching simulate() kwargs)

    Returns
    -------
    list of simulate() result dicts, one per scenario
    """
    results = []
    for s in scenarios:
        try:
            results.append(simulate(**s))
        except Exception as exc:
            logger.warning("[DigitalTwin] Scenario failed: %s", exc)
            results.append({"error": str(exc)})
    return results


def derive_defaults_from_agent_output(
    plant: str,
    orch_output: dict,
    df: pd.DataFrame,
) -> dict:
    """
    Extract the live default values for the Digital Twin sliders
    from the current orchestrator output.

    Called by the Digital Twin Streamlit page before rendering sliders.

    Returns
    -------
    dict with keys matching simulate() parameters:
        oee_pct, workforce_pct, forecast_qty, energy_price,
        base_capacity, downtime_hrs (always 0 as starting point),
        optimise_for, horizon_days, demand_buffer_pct
    """
    defaults = {
        "oee_pct":        91.0,
        "workforce_pct":  95.0,
        "forecast_qty":   2000,
        "energy_price":   0.12,
        "base_capacity":  _DEFAULT_BASE_CAPACITY,
        "downtime_hrs":   0.0,
        "optimise_for":   "Time",
        "horizon_days":   config.SIMULATION["sim_days"],
        "demand_buffer_pct": config.DIGITAL_TWIN.get("demand_buffer_pct", 0.10),
    }

    try:
        # OEE from MechanicAgent per-facility output
        mechanic = orch_output.get("mechanic", {})
        facility_risks = mechanic.get("facility_risks", {})
        if plant in facility_risks:
            defaults["oee_pct"] = facility_risks[plant].get("oee_pct", 91.0)

        # Workforce % from df for this plant
        if not df.empty:
            plant_df = df[df["Assigned_Facility"] == plant]
            if not plant_df.empty:
                deployed  = plant_df["Workforce_Deployed"].sum()
                required  = plant_df["Workforce_Required"].sum()
                if required > 0:
                    defaults["workforce_pct"] = round((deployed / required) * 100, 1)

                # Base capacity: mean daily output for this plant
                plant_df = plant_df.copy()
                plant_df["_date"] = pd.to_datetime(plant_df["Timestamp"]).dt.date
                daily_avg = plant_df.groupby("_date")["Actual_Order_Qty"].sum().mean()
                if not np.isnan(daily_avg) and daily_avg > 0:
                    defaults["base_capacity"] = int(daily_avg)

                # Energy price: mean kWh cost from data
                energy_data = plant_df["Energy_Consumed_kWh"]
                qty_data    = plant_df["Actual_Order_Qty"].replace(0, np.nan)
                ratio = (energy_data / qty_data).replace([np.inf, -np.inf], np.nan).dropna()
                if len(ratio) > 0:
                    # cost per unit in kWh, convert to $/kWh rough estimate
                    avg_kwh_per_unit = ratio.mean()
                    # use a standard grid price ratio — Peak vs Off-Peak
                    peak_mask = plant_df["Grid_Pricing_Period"].str.lower() == "peak"
                    n_peak = peak_mask.sum()
                    n_total = len(plant_df)
                    peak_ratio = n_peak / n_total if n_total > 0 else 0.4
                    # Blend: off-peak ~$0.09, peak ~$0.22
                    defaults["energy_price"] = round(
                        (peak_ratio * 0.22) + ((1 - peak_ratio) * 0.09), 3
                    )

        # Forecast qty: ForecasterAgent total / number of plants
        forecast = orch_output.get("forecast", {})
        forecast_total = forecast.get("forecast_qty", 0)
        n_plants = max(1, len(orch_output.get("plants", [plant])))
        defaults["forecast_qty"] = max(1, int(forecast_total / n_plants))

    except Exception as exc:
        logger.warning("[DigitalTwin] derive_defaults_from_agent_output failed: %s", exc)

    return defaults


# ── Private helpers ───────────────────────────────────────────────────────────

def _build_suggestions(
    optimise_for:  str,
    oee_pct:       float,
    workforce_pct: float,
    energy_price:  float,
    shortfall:     int,
    total_carbon:  float,
    target_qty:    int,
) -> list[str]:
    """Return 2–4 contextual optimisation tips based on current parameters."""
    tips = []

    if optimise_for == "Time":
        if oee_pct < 90:
            oee_gain = int(target_qty * ((90 - oee_pct) / 100))
            tips.append(
                f"🔧 Raise OEE to 90% (from {oee_pct:.1f}%) to gain ~{oee_gain:,} additional units."
            )
        if workforce_pct < 95:
            tips.append(
                f"👷 Increase workforce to 95% (from {workforce_pct:.1f}%) to shorten completion by ~1 day."
            )
        if shortfall > 0:
            tips.append(
                f"⚡ Add a Night Shift on Day 3 to close the {shortfall:,}-unit shortfall."
            )

    elif optimise_for == "Cost":
        if energy_price > 0.15:
            saving = round(total_carbon * energy_price * 0.15, 0)
            tips.append(
                f"🌙 Shift 30% of production to Off-Peak hours to save ~${saving:,.0f} in energy costs."
            )
        if oee_pct < 85:
            tips.append(
                f"🔧 Preventive maintenance could raise OEE to 90% — "
                f"reducing rework cost by an estimated 12%."
            )
        tips.append(
            "📦 Consolidate purchase orders across plants for potential bulk discount (5–8%)."
        )

    elif optimise_for == "Carbon":
        carbon_saving = round(total_carbon * 0.25, 1)
        tips.append(
            f"🌱 Moving 25% of production to Off-Peak reduces CO₂ by ~{carbon_saving:,.0f} kg."
        )
        if energy_price > 0.20:
            tips.append(
                "⚡ Energy price is high — consider renewable energy procurement to offset peak penalties."
            )
        tips.append(
            "🕐 Night shifts (22:00–06:00) use off-peak grid pricing — "
            "schedule heavy production there."
        )

    return tips
