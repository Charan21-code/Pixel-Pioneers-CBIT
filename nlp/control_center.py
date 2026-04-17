"""
Utilities for the Natural Language Control Center.

This module keeps intent parsing and HITL item matching testable outside the
Streamlit UI layer.
"""

from __future__ import annotations

import json
import re
from typing import Iterable, Optional

import pandas as pd


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def coerce_json_object(raw: str) -> dict:
    """Extract the first JSON object from a noisy LLM response."""
    if not raw:
        return {}
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {}


def plant_aliases(plant: str) -> set[str]:
    """Return a set of search-friendly aliases for a plant name."""
    aliases = {_norm(plant)}
    stripped = re.sub(r"\(.*?\)", "", plant).strip()
    if stripped:
        aliases.add(_norm(stripped))
    words = [w for w in re.split(r"[^A-Za-z0-9]+", plant) if w]
    for word in words:
        if len(word) >= 4:
            aliases.add(_norm(word))
    for match in re.findall(r"\((.*?)\)", plant):
        if match:
            aliases.add(_norm(match))
    return {alias for alias in aliases if alias}


def find_plant_mention(query: str, plants: Iterable[str]) -> Optional[str]:
    """Best-effort match for short or full-form plant references."""
    query_norm = _norm(query)
    best_match = None
    best_score = 0
    for plant in plants:
        for alias in plant_aliases(plant):
            if alias and alias in query_norm:
                score = len(alias.replace(" ", ""))
                if score > best_score:
                    best_match = plant
                    best_score = score
    return best_match


def infer_item_type(query: str) -> Optional[str]:
    """Infer the HITL department from plain-English keywords."""
    query_norm = _norm(query)
    keyword_map = {
        "procurement": ("procurement", "purchase", "po", "supplier", "stock", "inventory", "order"),
        "finance": ("finance", "budget", "cfo", "cost", "spend"),
        "maintenance": ("maintenance", "machine", "ttf", "shutdown", "engineering", "repair", "reroute"),
        "carbon": ("carbon", "energy", "emission", "sustainability", "peak"),
        "ops": ("operations", "ops", "plan", "schedule", "production"),
    }
    for item_type, keywords in keyword_map.items():
        if any(keyword in query_norm for keyword in keywords):
            return item_type
    return None


def infer_source(query: str) -> Optional[str]:
    """Infer the submitting agent name from plain-English keywords."""
    query_norm = _norm(query)
    source_map = {
        "Scheduler": ("scheduler", "schedule", "plan"),
        "Buyer": ("buyer", "procurement", "purchase"),
        "Finance": ("finance", "cfo", "budget"),
        "Mechanic": ("mechanic", "maintenance", "machine", "ttf"),
        "Environmentalist": ("environmentalist", "carbon", "energy", "sustainability"),
        "Orchestrator": ("orchestrator", "operations", "system"),
    }
    for source, keywords in source_map.items():
        if any(keyword in query_norm for keyword in keywords):
            return source
    return None


def extract_comment(query: str) -> str:
    """Pick up an optional natural-language comment for approve/reject commands."""
    patterns = [
        r"(?:because|comment|note|reason)\s*[:\-]?\s*(.+)$",
        r"(?:saying|with comment)\s*[:\-]?\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(1).strip().strip(".")
    return ""


def extract_overrides(query: str) -> dict:
    """Extract numeric simulation or reconfiguration hints from a command."""
    lower = query.lower()
    overrides: dict = {}

    patterns = {
        "workforce_pct": r"(?:workforce|staff|workers?).*?(\d{1,3}(?:\.\d+)?)\s*%",
        "oee_pct": r"\boee\b.*?(\d{1,3}(?:\.\d+)?)\s*%",
        "downtime_hrs": r"(?:downtime|down time|offline).*?(\d{1,2}(?:\.\d+)?)\s*(?:hours|hour|hrs|hr)",
        "energy_price": r"(?:energy price|price per kwh|kwh price|electricity).*?(\d+(?:\.\d+)?)",
        "forecast_qty": r"(?:forecast|demand|target|units).*?(\d[\d,]*)",
        "demand_buffer_pct": r"(?:buffer|safety margin).*?(\d{1,2}(?:\.\d+)?)\s*%",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, lower)
        if not match:
            continue
        raw_value = match.group(1).replace(",", "")
        value = float(raw_value)
        overrides[key] = int(value) if key == "forecast_qty" else value

    day_match = re.search(r"(?:offline|downtime).*?(\d{1,2})\s*days?", lower)
    if day_match:
        overrides["downtime_hrs"] = int(day_match.group(1)) * 24
    elif "offline" in lower and "downtime_hrs" not in overrides:
        overrides["downtime_hrs"] = 24.0

    horizon_match = re.search(r"(?:horizon|within|over|for)\D{0,10}(\d{1,2})\s*days?", lower)
    if horizon_match:
        overrides["horizon_days"] = int(horizon_match.group(1))

    if (
        "optimi" in lower
        or "optimiz" in lower
        or " for cost" in lower
        or " for carbon" in lower
        or " for time" in lower
    ):
        if "carbon" in lower:
            overrides["optimise_for"] = "Carbon"
        elif "cost" in lower:
            overrides["optimise_for"] = "Cost"
        elif "time" in lower or "speed" in lower:
            overrides["optimise_for"] = "Time"

    return overrides


def heuristic_intent(query: str, plants: Iterable[str], selected_plant: str | None = None) -> dict:
    """Deterministic intent parser used when Ollama is offline or vague."""
    query_norm = _norm(query)
    plant = find_plant_mention(query, plants) or selected_plant
    item_type = infer_item_type(query)
    source = infer_source(query)
    comment = extract_comment(query)
    overrides = extract_overrides(query)

    intent = "query"
    agent = "Orchestrator Agent"
    confidence = 62

    if any(token in query_norm for token in ("approve", "accept", "clear", "sign off")):
        intent = "approve"
        agent = "HITL Manager"
        confidence = 84
    elif any(token in query_norm for token in ("reject", "deny", "decline", "block")):
        intent = "reject"
        agent = "HITL Manager"
        confidence = 84
    elif any(token in query_norm for token in ("escalate", "flag", "send to hitl", "send to inbox", "raise for approval")):
        intent = "escalate"
        agent = "Orchestrator Agent"
        confidence = 82
    elif (
        "what if" in query_norm
        or "simulate" in query_norm
        or "scenario" in query_norm
        or "offline" in query_norm
        or "downtime" in query_norm
    ):
        intent = "simulate"
        agent = "Digital Twin"
        confidence = 80
    elif (
        any(token in query_norm for token in ("replan", "reconfigure", "change", "set", "update", "reduce", "increase", "optimise", "optimize"))
        and overrides
    ):
        intent = "reconfigure"
        agent = "Scheduler Agent"
        confidence = 78

    params = {}
    if plant:
        params["plant"] = plant
    if item_type:
        params["item_type"] = item_type
    if source:
        params["source"] = source
    if comment:
        params["comment"] = comment
    params.update(overrides)

    id_match = re.search(r"(?:item|ticket|request|order|plan)\s*#?\s*(\d+)", query, re.IGNORECASE)
    if id_match:
        params["item_id"] = int(id_match.group(1))
        confidence = max(confidence, 90)

    if plant:
        confidence += 4
    if item_type and intent in {"approve", "reject", "escalate"}:
        confidence += 4
    if overrides and intent in {"simulate", "reconfigure"}:
        confidence += 6

    return {
        "intent": intent,
        "agent": agent,
        "params": params,
        "confidence_pct": min(confidence, 96),
        "response": "",
        "action": "",
    }


def select_hitl_item(
    query: str,
    pending_items: list[dict],
    plants: Iterable[str] | None = None,
) -> Optional[dict]:
    """Choose the pending HITL item that best matches a natural-language command."""
    if not pending_items:
        return None

    parsed = heuristic_intent(query, plants or [])
    explicit_id = parsed["params"].get("item_id")
    item_type = parsed["params"].get("item_type")
    plant = parsed["params"].get("plant")
    source = parsed["params"].get("source")

    if explicit_id is not None:
        for item in pending_items:
            if item.get("id") == explicit_id:
                return item

    best_item = None
    best_score = -1
    for item in pending_items:
        payload = item.get("payload", {}) or {}
        score = 0
        if item_type and item.get("item_type") == item_type:
            score += 40
        if source and source.lower() in str(item.get("source", "")).lower():
            score += 18

        payload_plant = payload.get("plant") or payload.get("facility")
        if plant and payload_plant == plant:
            score += 32
        elif plant and payload_plant and _norm(plant) in _norm(payload_plant):
            score += 22

        haystack = " ".join(
            [
                str(item.get("item_type", "")),
                str(item.get("source", "")),
                json.dumps(payload, default=str),
            ]
        )
        haystack_norm = _norm(haystack)
        if plant and _norm(plant) in haystack_norm:
            score += 8
        if item_type and item_type in haystack_norm:
            score += 5

        if score > best_score:
            best_score = score
            best_item = item

    if best_score <= 0 and len(pending_items) == 1:
        return pending_items[0]
    return best_item if best_score > 0 else None


def build_query_answer(
    query: str,
    out: dict,
    df: pd.DataFrame,
    pending_counts: Optional[dict] = None,
    selected_plant: str | None = None,
) -> tuple[str, str]:
    """Build a deterministic answer from current orchestrator state."""
    lower = query.lower()
    plants = out.get("plants", [])
    plant = find_plant_mention(query, plants) or selected_plant

    if any(token in lower for token in ("approval", "hitl", "pending")) and pending_counts:
        total = pending_counts.get("total", 0)
        if total == 0:
            return "There are no pending HITL approvals right now.", "HITL Manager"
        return (
            "Pending approvals: "
            f"{pending_counts.get('ops', 0)} operations, "
            f"{pending_counts.get('procurement', 0)} procurement, "
            f"{pending_counts.get('finance', 0)} finance, "
            f"{pending_counts.get('maintenance', 0)} maintenance, and "
            f"{pending_counts.get('carbon', 0)} sustainability.",
            "HITL Manager",
        )

    if any(token in lower for token in ("delay", "late", "on-time", "on time")):
        delayed = int((df["Schedule_Status"] == "Delayed").sum()) if not df.empty else 0
        on_time_pct = float((df["Schedule_Status"] == "On-Time").mean() * 100) if not df.empty else 0.0
        return (
            f"There are {delayed} delayed events in the current window, and on-time execution is {on_time_pct:.1f}%.",
            "Orchestrator Agent",
        )

    if any(token in lower for token in ("inventory", "stock", "lead", "supplier", "order", "procurement")):
        inventory = out.get("buyer_inventory", {})
        if plant and plant in inventory:
            inv = inventory[plant]
            return (
                f"{plant} has {inv.get('days_remaining', 0):.1f} days of stock left, "
                f"lead time is about {inv.get('lead_days', 0)} days, and the recommended reorder is "
                f"{inv.get('reorder_qty', 0):,} units (${inv.get('cost_usd', 0):,.0f}).",
                "Buyer Agent",
            )
        if inventory:
            worst_plant, worst = min(
                inventory.items(), key=lambda item: item[1].get("days_remaining", float("inf"))
            )
            return (
                f"The tightest inventory position is {worst_plant} with {worst.get('days_remaining', 0):.1f} days remaining "
                f"and a {worst.get('status', 'unknown').upper()} status.",
                "Buyer Agent",
            )

    if any(token in lower for token in ("machine", "maintenance", "ttf", "oee", "temperature", "vibration")):
        facility_risks = out.get("mechanic", {}).get("facility_risks", {})
        if plant and plant in facility_risks:
            risk = facility_risks[plant]
            return (
                f"{plant} is {risk.get('status', 'unknown').upper()} with risk score {risk.get('risk_score', 0):.0f}, "
                f"OEE {risk.get('oee_pct', 0):.1f}%, and TTF {risk.get('ttf_hrs', 0):.1f} hours.",
                "Mechanic Agent",
            )
        critical = out.get("mechanic", {}).get("critical_facilities", [])
        if critical:
            return (
                f"The most urgent maintenance attention is on {', '.join(critical[:3])}.",
                "Mechanic Agent",
            )

    if any(token in lower for token in ("budget", "finance", "cost", "money", "spend", "risk score")):
        finance = out.get("finance", {})
        budget = finance.get("budget_status", {})
        return (
            f"Finance gate is {finance.get('gate_decision', 'UNKNOWN')}, "
            f"budget usage is {budget.get('pct_used', 0):.1f}%, and financial risk is "
            f"{finance.get('risk_score', 0):.0f}/100.",
            "Finance Agent",
        )

    if any(token in lower for token in ("carbon", "energy", "emission", "peak")):
        environ = out.get("environ", {})
        return (
            f"Carbon compliance is {environ.get('compliance_status', 'UNKNOWN')}, "
            f"peak-hour penalties account for {environ.get('peak_penalty_pct', 0):.1f}% of the total, "
            f"and estimated savings are ${environ.get('estimated_savings_usd', 0):,.0f}.",
            "Environmentalist Agent",
        )

    if any(token in lower for token in ("demand", "forecast", "anomaly", "trend", "units")):
        forecast = out.get("forecast", {})
        return (
            f"The 7-day forecast is {forecast.get('forecast_qty', 0):,} units, "
            f"trend is {forecast.get('trend_slope', 0):+.1f} units/day, and "
            f"{forecast.get('anomaly_count', 0)} anomalies are currently flagged.",
            "Forecaster Agent",
        )

    if any(token in lower for token in ("plan", "schedule", "throughput", "utilisation", "utilization")):
        scheduler = out.get("scheduler", {})
        if plant and plant in scheduler:
            plan = scheduler[plant]
            return (
                f"{plant} is planned for {plan.get('expected_throughput', 0):,} units at "
                f"{plan.get('utilisation_pct', 0):.1f}% utilisation.",
                "Scheduler Agent",
            )

    return (
        f"System status is {out.get('final_status', 'UNKNOWN')} with health "
        f"{out.get('system_health', 0):.0f}/100 and {len(out.get('conflicts', []))} active conflicts.",
        "Orchestrator Agent",
    )
