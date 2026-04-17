# MASTER IMPLEMENTATION PLAN
## Agentic Production Planning System
### CBIT Hackathon | Streamlit + Ollama (gemma4:e2b)
### Final Version — Post-Review

---

## Quick Reference: What Changed from Draft

| Location | Change Made |
|----------|------------|
| Page 3 — Inventory | Added lead time calculator: if short, estimate X days to receive extra units |
| Page 4 — Production Plan | Each plant gets its OWN plan. Overview page → click plant → plant-specific detail |
| Page 4 — Gantt Chart | **Removed** |
| Page 5 — Machine Health | Plant-specific only. Dropdown selects plant, then shows all machine data for that one plant |
| Page 6 — Finance | Added actionable cost-reduction suggestions alongside the risk score |
| Page 7 — Digital Twin | All default slider values pulled **live** from agent outputs, not hardcoded |
| Page 7 — Digital Twin | Added an embedded mini-chat (Ollama) for follow-up questions after simulation runs |
| Page 9 — NLP Interface | Kept as its own dedicated full page (unchanged) |

---

## System Architecture (Final)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          STREAMLIT APP                                   │
│                                                                          │
│  Page 1      Page 2       Page 3        Page 4       Page 5             │
│  Command     Demand       Inventory &   Production   Machine            │
│  Center      Intel        Logistics     Plan         Health             │
│  (overview)  (Forecaster) (Buyer)       (Scheduler)  (Mechanic)         │
│                           + Lead Time   PLANT VIEW   PLANT VIEW         │
│                                                                          │
│  Page 6      Page 7       Page 8        Page 9       Page 10   Page 11  │
│  Finance     Digital      Carbon &      NLP          HITL      Plant    │
│  Dashboard   Twin         Energy        Interface    Inbox     Explorer │
│  + Suggestions + Mini-Chat (Environ.)   (Full Page)  (All)     (bonus)  │
│                                                                          │
│  ──────────────────── SIDEBAR (All Pages) ────────────────────────────  │
│  Clock | Agents Status | Next Tick | Fast Forward | Reset | Ollama dot  │
└─────────────────────────────────────────────────────────────────────────┘
                               │
                       OrchestratorAgent
                       (agents/orchestrator.py)
                               │
        ┌──────────┬───────────┼──────────────┬─────────────┐
        │          │           │              │             │
   Forecaster  Mechanic    Buyer      Environmentalist  Finance
        │          │           │              │             │
        └──────────┴───────────┴──────────────┴─────────────┘
                               │
                         SchedulerAgent
                    (per-plant plans generated)
                               │
                          HITL Queue
                   (hitl_queue table in SQLite)
```

---

## Data Flow Summary

```
data.csv → production.db → time_cursor → df (sliced)
                                              │
                                    OrchestratorAgent.run(df)
                                              │
                               st.session_state["orch_output"]
                                   {
                                     "forecast":   {...},
                                     "mechanic":   {plant_id: {...}},
                                     "buyer":      {plant_id: {...}},
                                     "environ":    {...},
                                     "finance":    {...},
                                     "scheduler":  {plant_id: shift_plan},
                                     "final_status": "ALL_OK|NEEDS_HITL|BLOCKED"
                                   }
                                              │
                          All 11 pages READ from this single dict
                         (agents only re-run when cursor advances)
```

---

---

# PHASE 1 — FOUNDATION
### Files to build before any page

---

## 1.1 — `agents/orchestrator.py` (NEW)

The central brain. Runs all agents in dependency order, detects conflicts, escalates to HITL.

```
Run Order:
  1. ForecasterAgent   → demand forecast, anomalies
  2. MechanicAgent     → per-plant risk score, blacklist
  3. BuyerAgent        → per-plant inventory status, reorder list
  4. EnvironmentalistAgent → carbon compliance
  5. FinanceAgent      → budget check, gate decision
  6. SchedulerAgent    → PER-PLANT 7-day shift plans (uses all above)
  7. Conflict Detection
  8. HITL Escalations
```

**Key output structure:**
```python
{
  "forecast":    {forecast_qty, trend_slope, risk_level, summary, anomaly_count},
  "mechanic":    {
                   "Noida Plant (India)":    {risk_score, status, ttf_min, oee_avg, temp_avg, vib_avg},
                   "Gumi (Korea)":           {risk_score, status, ...},
                   "Thai Nguyen (Vietnam)":  {risk_score, status, ...},
                   "Foxconn (Taiwan)":       {risk_score, status, ...},
                   "Queretaro (Mexico)":     {risk_score, status, ...},
                 },
  "buyer":       {
                   "Noida Plant (India)":    {current_stock, daily_use, days_remaining, reorder_qty, lead_days, cost_usd},
                   ... (one entry per plant)
                 },
  "environ":     {compliance_status, peak_ratio, total_carbon_kg, total_penalty_usd, recommendation},
  "finance":     {monthly_spend, budget_remaining, gate_decision, risk_score, suggestions[]},
  "scheduler":   {
                   "Noida Plant (India)":    {shift_plan[], utilisation_pct, expected_throughput},
                   ... (one plan per plant)
                 },
  "conflicts":   [{type, description, severity, involved_agents}],
  "final_status": "ALL_OK" | "NEEDS_HITL" | "BLOCKED",
  "system_health": 0–100,
  "last_run_at": timestamp
}
```

**Conflict Detection Rules:**
| Rule | Trigger | Action |
|------|---------|--------|
| Schedule-Maintenance conflict | Mechanic blacklists plant X but Scheduler assigned work to X | Remove X from its plan |
| Resource-Inventory conflict | Buyer says < 3 days stock but plan runs 7 days | Cap plan + HITL |
| Finance-Procurement conflict | Budget exhausted but Buyer submitted PO | Block PO + HITL |
| Demand-Capacity conflict | Forecast +30% but all plants at full utilisation | Suggest partner overflow |

---

## 1.2 — `hitl/manager.py` (NEW)

```python
class HitlManager:
    def get_pending(self, item_type=None) -> list[dict]
    def approve(self, item_id: int, comment: str, approved_by: str) -> bool
    def reject(self, item_id: int, comment: str, rejected_by: str) -> bool
    def get_history(self, limit=50) -> list[dict]
```

All methods read/write to the `hitl_queue` table in `production.db`.

---

## 1.3 — `simulation/digital_twin.py` (NEW)

```python
def simulate(
    plant_id: str,
    oee_pct: float,          # from mechanic agent output (real-time)
    workforce_pct: float,    # from df Workforce_Deployed/Required (real-time)
    forecast_qty: int,       # from forecaster agent output (real-time)
    energy_price: float,     # from df Grid_Pricing_Period average (real-time)
    downtime_hrs: float,     # user input (starts at 0)
    optimise_for: str,       # "Time" | "Cost" | "Carbon"
    horizon_days: int = 7
) -> dict:
    """
    Returns:
      expected_output_units, shortfall_units, completion_day,
      cost_usd, carbon_kg, workforce_needed, daily_breakdown[]
    """
```

---

## 1.4 — `app.py` (MODIFIED)

- Remove the old `run_agents()` function entirely
- On every tick advance: `orch_output = OrchestratorAgent().run({"df": df, "as_of_time": current_time})`
- Store in `st.session_state["orch_output"]`
- Each page imports and reads from `st.session_state["orch_output"]`

---

---

# PHASE 2 — CORE PAGES
### Pages 1, 4, 5

---

## PAGE 1 — Command Center

**Purpose:** Single-glance system status. Entry point. No deep analysis here — links out to detailed pages.

### Layout

#### Top: Orchestrator Status Banner (full width)
```
┌────────────────────────────────────────────────────────────────────────┐
│  🟢  ALL SYSTEMS GO  |  Last updated: 2024-01-15 14:00                 │
│  OR                                                                     │
│  🟡  ATTENTION NEEDED  |  2 warnings from Mechanic + Buyer agents      │
│  OR                                                                     │
│  🔴  PRODUCTION BLOCKED  |  Finance gate closed. HITL review required  │
└────────────────────────────────────────────────────────────────────────┘
```

#### KPI Row (5 cards)
| Card | Source | Formula |
|------|--------|---------|
| On-Time Delivery % | `Schedule_Status` column | count("On-Time")/total*100 |
| Active Alerts | `agent_events` DB | count(severity != "INFO") |
| 24h Carbon Penalty | `Carbon_Cost_Penalty_USD` | sum(last 24h) |
| Lowest Inventory (days) | buyer output | min(days_remaining across all plants) |
| Workforce Coverage % | `Workforce_Deployed/Required` | sum(deployed)/sum(required)*100 |

#### Plant Overview Grid (5 cards — one per plant)
Each card shows:
- Plant name + location
- OEE % (colour coded: green ≥ 90, yellow ≥ 80, red < 80)
- Machine Risk: LOW / MEDIUM / CRITICAL (from mechanic output)
- Inventory Status: ✅ OK / ⚠️ Low / 🔴 Critical (from buyer output)
- Plan Status: ✅ Ready / 🟡 Pending Approval / ⛔ Blocked
- **"View Plant Details →"** button (navigates to Page 4 with that plant pre-selected)

#### Agent Health Grid (6 cards in 2 rows)
One card per: Forecaster, Mechanic, Buyer, Environmentalist, Finance, Scheduler.
Each shows: agent name, last-run severity dot, one-line latest summary, link to that page.

#### Live Agent Log (bottom, scrollable)
Last 50 rows from `agent_events` table, colour-coded by severity.

#### Sidebar (same on all pages)
- 🕐 Simulation time
- 📊 Events: X / 10,000
- Slider: Step size (1–100)
- ▶ Next Tick
- ⏩ Fast Forward (+500)
- ↺ Reset
- 🟢/🔴 Ollama status dot + model name
- 🤖 Trigger All Agents Now button

---

## PAGE 4 — Production Plan (Scheduler Agent)

**Redesigned based on feedback: Plant-specific plans, no Gantt chart.**

### Layout: Two-Level Structure

#### Level A — Plant Overview (default view)

A summary table showing all 5 plants in one row each:

| Plant | Machine Risk | Workforce% | Stock Days | Plan Status | Actions |
|-------|-------------|-----------|-----------|-------------|---------|
| Noida Plant (India) | 🟢 LOW (32) | 94.1% | 12.4d | ✅ Ready | [View Plan] |
| Gumi (Korea) | 🟢 LOW (28) | 97.3% | 18.1d | ✅ Ready | [View Plan] |
| Thai Nguyen (Vietnam) | 🟡 MED (61) | 89.2% | 8.7d | ✅ Ready | [View Plan] |
| Foxconn (Taiwan) | 🔴 CRIT (84) | 91.0% | 15.3d | ⛔ Blocked | [View Details] |
| Queretaro (Mexico) | 🟢 LOW (45) | 88.5% | 9.2d | 🟡 Pending | [View Plan] |

Clicking **[View Plan]** on any row drops down to Level B for that specific plant.

---

#### Level B — Plant-Specific Detail View

**Triggered by:** clicking "View Plan" on a plant card, OR using the **plant dropdown** at the top of the page.

```
Selected Plant: [Noida Plant (India) ▼]   ← dropdown to switch plants
```

**Section B1: Plant Readiness Gate**

4 status bars specific to the selected plant:
```
┌─────────────────────────────────────────────────────────────────┐
│  NOIDA PLANT (INDIA) — READINESS CHECK                          │
│                                                                  │
│  ✅ MACHINE HEALTH:   OEE 91.5% | Risk Score 32 | TTF: 312 hrs  │
│  ✅ WORKFORCE:        94.1% deployed (141 / 150 workers)         │
│  ⚠️  INVENTORY:       8.7 days remaining (threshold: 20,000u)   │
│  ✅ FINANCE GATE:     Approved ($38,400 within budget)           │
│                                                                  │
│  → PLANT IS CLEARED FOR PRODUCTION (with inventory watch)       │
└─────────────────────────────────────────────────────────────────┘
```

Data sources:
- Machine Health: `mechanic["Noida Plant (India)"]["oee_avg"]`, `["risk_score"]`, `["ttf_min"]`
- Workforce: `df[df["Assigned_Facility"] == plant]["Workforce_Deployed"].sum()` / `Workforce_Required.sum()`
- Inventory: `buyer["Noida Plant (India)"]["days_remaining"]` and `["current_stock"]`
- Finance Gate: `finance["gate_decision"]`

**Section B2: Plan Constraints (Sliders for THIS plant)**

| Slider | Default (from agent) | Range | Effect |
|--------|---------------------|-------|--------|
| OEE % | `mechanic[plant]["oee_avg"]` (live) | 50–100 | Scales throughput |
| Workforce Availability | `(deployed/required)*100` (live) | 50–100 | Shift capacity |
| Demand Buffer | 10% | 0–30% | Adds safety margin over forecast_qty |
| Optimise For | dropdown | Time / Cost / Carbon | Scheduler priority |

All defaults are read from `st.session_state["orch_output"]` — **updated on every agent run**.

**"⟳ Generate Plan for This Plant"** button → re-runs SchedulerAgent with the above slider overrides for this specific plant only. Shows spinner: *"Scheduler Agent building plan for Noida Plant via Ollama..."*

**Section B3: Plant Shift Plan Table (Editable)**

This table is ONLY for the selected plant's 7 days:

| Day | Shift | Production Line | Product | Assigned Units | Workers | Notes |
|-----|-------|----------------|---------|---------------|---------|-------|
| Day 1 | AM | Line 1 (High Speed) | Galaxy S Smartphone | 1,850 | 150 | ✅ |
| Day 1 | PM | Line 2 (Standard) | Galaxy A Smartphone | 1,400 | 150 | ✅ |
| Day 1 | Night | Line 3 (Heavy Duty) | Galaxy Tab | 820 | 80 | ✅ |
| Day 2 | AM | Line 1 (High Speed) | Galaxy S Smartphone | 1,850 | 150 | ✅ |
| ... | ... | ... | ... | ... | ... | ... |

Editable columns: `Assigned Units`, `Product`, `Shift`.
Non-editable: `Day`, `Production Line`, `Workers` (auto-calculated from Workforce%).
Rows where machine risk is CRITICAL → greyed out with tooltip "Line unavailable due to maintenance risk."

**"↺ Recalculate"** button → re-runs with the manually edited values as overrides.

**Section B4: Plant Plan Summary**
3 metrics (no Gantt):
- Total Planned Units: X
- Lines Used: X / 3
- Estimated Completion: Day X of 7

**Section B5: Submit for Approval**
"📋 Submit Noida Plant Plan for Approval" → pushes to `hitl_queue` with `item_type="production_plan"` and `source="Scheduler"`.

---

## PAGE 5 — Machine Health & OEE (Mechanic Agent)

**Redesigned: Plant-specific with dropdown.**

### Layout

#### Plant Selector (top, prominent)
```
Select Plant:  [ Noida Plant (India) ▼ ]
```

Everything below updates to show ONLY data for the selected plant.

#### Plant Health Summary Card (for selected plant)
```
┌─────────────────────────────────────────────────────────────────┐
│  NOIDA PLANT (INDIA) — MACHINE HEALTH                           │
│                                                                  │
│  Risk Score:  32 / 100  🟢 LOW                                  │
│  Average OEE: 91.5%                                             │
│  Min TTF:     278 hrs (next 24hrs are safe)                     │
│  Avg Temp:    74.8°C   (normal)                                 │
│  Avg Vibration: 51.3 Hz (normal)                               │
│                                                                  │
│  Mechanic Agent: "All lines at Noida are operating within       │
│  normal parameters. Preventive check recommended in 11 days."   │
└─────────────────────────────────────────────────────────────────┘
```

Risk Score formula (for the SELECTED plant only):
```
score = max(0, 85 - oee_avg) * 0.5
      + max(0, (500 - ttf_min) / 500) * 40
      + max(0, temp_avg - 80) * 2
      + max(0, vib_avg - 55) * 1
```

#### 4-Panel Sensor Charts (last 100 rows, filtered to selected plant)

Chart 1 — Predicted Time To Failure (hrs)
- Line chart: `Predicted_Time_To_Failure_Hrs` over time
- Red dashed line at 24hrs (CRITICAL threshold, from `config.AGENT["ttf_critical_hrs"]`)
- Yellow dashed line at 100hrs (WARNING threshold)
- Annotated spikes: if TTF < 24 at any point, a red dot with tooltip

Chart 2 — OEE %
- Line chart: `Machine_OEE_Pct` over time
- Green reference line at 85% (from `config.AGENT["oee_warning_pct"]`)

Chart 3 — Machine Temperature (°C)
- Line chart: `Machine_Temperature_C`
- Yellow line at 80°C warning
- If any value > 90°C → red alert zone shaded

Chart 4 — Machine Vibration (Hz)
- Line chart: `Machine_Vibration_Hz`
- Yellow line at 55Hz warning

#### Crisis Event Alert Box
If ANY row in selected plant's data has `Predicted_Time_To_Failure_Hrs < 24`:
```
┌────────────────────────────────────────────────────────────────────────┐
│  🚨 MACHINE FAILURE IMMINENT — NOIDA PLANT                             │
│                                                                         │
│  Predicted TTF has dropped to 1.0 hrs on Line 2 (Standard)             │
│  Temperature: 95.3°C | Vibration: 85.8Hz                               │
│                                                                         │
│  ➔ Mechanic Agent has flagged this for CRITICAL escalation.            │
│  ➔ This line has been automatically blacklisted in the Production Plan. │
│  ➔ Rerouting to partner overflow is recommended.                        │
│                                                                         │
│  [🔧 Schedule Emergency Maintenance — Sends to HITL Inbox]             │
└────────────────────────────────────────────────────────────────────────┘
```
(This triggers from the synthetic crisis event in data.csv around row 500)

#### Recommended Maintenance Window (for selected plant)
Simple table derived from MechanicAgent:
| Line | Next Maintenance Recommended | Est. Downtime | Priority |
|------|---------------------------|---------------|---------|
| Line 2 (Standard) | Day 2 Off-Peak (22:00–06:00) | 4 hrs | 🔴 Critical |
| Line 1 (High Speed) | Day 5 Off-Peak | 2 hrs | 🟡 Medium |

#### Switch Plant
"← Back to All Plants" link returns to the Page 5 default state (all plants listed).
Dropdown at top always allows switching.

---

---

# PHASE 3 — INTELLIGENCE PAGES
### Pages 2, 3, 6

---

## PAGE 2 — Demand Intelligence (Forecaster Agent)

### Layout

#### Agent Narrative Box
Ollama-generated text from ForecasterAgent in a styled card:
> *"Demand is rising at +142 units/day. Galaxy S Smartphones are the primary driver with a 34% share. 6 spike anomalies were detected in the past 14 days..."*

Risk badge: LOW / MEDIUM / HIGH. R² Confidence: 78%.

#### Main Forecast Chart
- Historical `Actual_Order_Qty` (solid blue)
- Historical `Forecasted_Demand` (dashed grey)
- 7-day ML projection (solid orange + shaded confidence band)

ML Method: `sklearn.LinearRegression` fitted on last 14 days of daily `Actual_Order_Qty` totals.

#### Tabs: By Product | By Region

**Tab A — By Product (6 products):**
6 mini line charts (one per product category):
- Galaxy S Smartphone
- Galaxy A Smartphone
- Galaxy Tab
- Neo QLED TV
- EcoBubble Washing Machine
- Bespoke Refrigerator

Each mini chart: historical demand + 7-day projection line.

**Tab B — By Region (10 regions):**
Donut chart of demand share + sortable table with % of total.

#### Anomaly Alert Table
Rows where `Actual_Order_Qty > Forecasted_Demand * 1.30`:
| Order_ID | Product | Region | Forecast | Actual | Spike % |
|----------|---------|--------|----------|--------|---------|
| ORD-100006 | Galaxy S | Malaysia (SEA) | 5,117 | 7,675 | +50.0% |

Highlighted red. Count shown as metric: "X spike anomalies detected".

#### Recommended Action
Green info box with `recommended_action` from Ollama.

---

## PAGE 3 — Inventory & Logistics (Buyer Agent)

**Updated with lead time feature.**

### Layout

#### Inventory Status Cards (5 cards — one per plant)

Each card:
```
┌───────────────────────────────────────────────┐
│  🏭 NOIDA PLANT (INDIA)                       │
│                                               │
│  Current Stock:    15,489 units               │
│  Threshold:        20,000 units               │
│  Daily Consumption: 2,407 units/day           │
│  Days Remaining:   6.4 days  ⚠️ LOW           │
│                                               │
│  Shortfall:        4,511 units needed         │
│  Lead Time:        ~3 days to receive         │
│                                               │
│  Status:  ⚠️ ORDER NOW — Stock expires before │
│           lead time completes                 │
└───────────────────────────────────────────────┘
```

**Calculations explained:**
- `current_stock` = latest `Raw_Material_Inventory_Units` for this plant
- `daily_consumption` = mean of `Actual_Order_Qty` (this plant's rows) × (24/2) ÷ units_per_order
- `days_remaining` = `current_stock / daily_consumption`
- `shortfall_units` = max(0, `Inventory_Threshold * 1.20` - `current_stock`)
  - The 1.20 safety buffer from `config.AGENT["inventory_safety_pct"]`
- `lead_days` = estimated days to receive the raw material
  - Derived from `Live_Supplier_Quote_USD` as a proxy:
    - Quote $0 → stock was available (0 days)
    - Quote > $0 and < $5.25 → standard order (~4 days avg)
    - Quote ≥ $5.25 → premium/urgent order (~2 days)
  - Default fallback from `config`: `AGENT["default_lead_days"] = 3`
- **Status Logic:**
  - If `days_remaining > 14` → ✅ Healthy (no action)
  - If `days_remaining > lead_days + 2` → 🟡 Low (plan to order soon)
  - If `days_remaining <= lead_days + 2` → 🔴 Critical — Order immediately
  - If `days_remaining <= lead_days` → 🚨 EMERGENCY — Lead time exceeds remaining stock

#### Stock vs Threshold Bar Chart
Horizontal bar chart for all 5 plants:
- Each bar = current `Raw_Material_Inventory_Units`
- Red vertical dashed line = `Inventory_Threshold` (20,000)
- Bars below the line coloured red

#### What We Need to Order — Reorder Table

| Plant | Current Stock | Daily Use | Days Left | Shortfall | Reorder Qty | Est. Cost | Lead Days | Urgency |
|-------|--------------|-----------|-----------|-----------|------------|-----------|----------|---------|
| Noida Plant | 15,489 | 2,407/day | 6.4d | 4,511u | 34,000u | $183,940 | ~3 days | 🔴 Order Now |
| Thai Nguyen | 21,084 | 2,250/day | 9.4d | 0 | 0 | $0 | — | ✅ OK |
| Foxconn | 11,523 | 1,980/day | 5.8d | 8,477u | 28,000u | $147,280 | ~3 days | 🔴 Order Now |

Columns explained:
- **Shortfall** = how many units below the `Threshold * 1.20` safety level
- **Reorder Qty** = enough to cover next 14 days of consumption: `(14 × daily_use) - current_stock`
- **Est. Cost** = `Reorder_Qty × avg(Live_Supplier_Quote_USD)` for that plant
- **Lead Days** = estimated days to receive (explained above)

**Lead Time Warning Banner:**
If any plant has `days_remaining < lead_days`:
```
⚠️  NOIDA PLANT: Current stock will run out in 6.4 days,
    but the estimated delivery takes ~3 days. You must order
    within the next 3 days to avoid a production stoppage.
```

#### Procurement Log
Table filtered to rows where `Procurement_Action = "Auto-Ordered via API"`:
Columns: Timestamp, Plant, Action, Quote_USD, Stock at time.

#### Request Manual Order (HITL)
Per plant:
- "Select Plant" + "Enter Qty" + "Submit for Approval"
- Pushes to `hitl_queue` with all details

#### Buyer Agent Narrative (Ollama)
*"Inventory at Noida Plant is critically low at 15,489 units — 6.4 days remaining. Given a procurement lead time of ~3 days, an emergency order of 34,000 units is recommended immediately to avoid a production gap. Estimated cost: $183,940 at current supplier rates..."*

---

## PAGE 6 — Finance Dashboard (Finance Agent)

**Updated with actionable cost-reduction suggestions.**

### Layout

#### Budget Meter (Circular Gauge)
- Total budget: $500,000 (`config.FINANCE["monthly_budget"]`)
- Spent: sum of all `Live_Supplier_Quote_USD` + `Carbon_Cost_Penalty_USD` + labour est.
- Remaining: difference
- Colour: green (<70%), yellow (70–90%), red (>90%)

#### Finance Gate Status Block
```
┌──────────────────────────────────────────────────────────┐
│  FINANCE GATE:  ✅ APPROVED  /  🔴 BLOCKED               │
│                                                           │
│  This month's spend:  $412,000 / $500,000  (82.4%)      │
│  Proposed plan cost:  $43,500                            │
│  Overhead (15%):      + $6,525                           │
│  Total if approved:   $462,025  (Remaining: $37,975)     │
│                                                           │
│  Decision: ✅ APPROVED — within budget                   │
└──────────────────────────────────────────────────────────┘
```

Gate logic:
- `BLOCKED` if `(current_spend + proposed_cost * overhead) > monthly_budget`
- `APPROVED` otherwise

#### Cost Breakdown Chart
Stacked bar chart over time (grouped by week):
- Procurement costs (from `Live_Supplier_Quote_USD`)
- Carbon penalties (from `Carbon_Cost_Penalty_USD`)
- Labour estimate (Workforce_Deployed × 8hrs × assumed rate)

#### Financial Risk Score + Suggestions

**Risk Score card:**
```
Financial Risk Score:  67 / 100  —  MEDIUM RISK
```

Score formula (from `agents/finance/risk_scorer.py`):
```
= OEE deviation penalty    (poor OEE → higher rework cost)
+ supply shortage cost     (days_remaining < 7 = risk)
+ demand overshoot cost    (actual > forecast * 1.3 → excess production)
+ carbon penalty exposure  (Peak-hour ratio)
```

**Actionable Suggestions (NEW — Ollama generates these):**

Below the risk score, a styled list of specific money-saving recommendations:
```
💡 COST OPTIMISATION SUGGESTIONS

  1. 🌙  Shift Peak-hour batches to Off-Peak
        Potential saving: ~$12,400/month in carbon penalties
        How: Move Galaxy A batches from 14:00–20:00 → 22:00–06:00
        Effort: Low (reschedule 2 shifts per plant)

  2. 📦  Consolidate Foxconn & Queretaro procurement orders
        Potential saving: ~$8,200 in supplier quotes (bulk discount)
        How: Combine two separate POs into one larger order
        Effort: Medium (requires Buyer agent override + HITL approval)

  3. 🔧  Preventive maintenance before failure
        Potential saving: ~$24,000 in emergency repair costs
        How: Schedule Line 2 maintenance at Noida during upcoming Off-Peak window
        Effort: Low (schedule already has a 4-hr gap on Day 3 Night shift)

  4. 🔄  Reduce partner overflow dependency
        Potential saving: ~$15,000/month (partner rates are 18% higher)
        How: Increase Primary plant utilisation to 96% before using Foxconn/Queretaro
        Effort: Medium (requires OEE improvement at Thai Nguyen first)
```

These suggestions are generated by `FinanceAgent._ask_ollama()` using the current month's cost data as input.

#### Approval History Table
From `monthly_spend` DB table: approved POs, who approved, amount, date.

#### Escalate Button
"🚨 Escalate to Finance Head" → creates `hitl_queue` entry with `item_type="finance"`.

#### Finance Agent Narrative (Ollama)
Full paragraph summary of financial health.

---

---

# PHASE 4 — SIMULATION & ENVIRONMENT
### Pages 7, 8

---

## PAGE 7 — Digital Twin Simulation

**Updated: All defaults from agent outputs (real-time). Added mini Ollama chat after simulation.**

### Layout: Two Columns

#### Left Column — Parameter Panel

**Title:** "🧬 Configure Simulation Parameters"
**Subtitle:** "Default values are loaded live from agent outputs"

| Parameter | Default Source | Range | Widget |
|-----------|---------------|-------|--------|
| Select Plant | all plants | dropdown | `st.selectbox` |
| OEE % | `mechanic[plant]["oee_avg"]` | 50–100 | `st.slider` |
| Workforce Availability % | `(Workforce_Deployed/Required)*100` from df for selected plant | 50–100 | `st.slider` |
| Demand to Meet (units) | `forecast["forecast_qty"]` / 5 (per plant share) | 0–50,000 | `st.number_input` |
| Energy Price per kWh | avg of `Energy_Consumed_kWh / Actual_Order_Qty` from df | $0.05–$0.50 | `st.slider` |
| Machine Downtime (hrs) | 0 (user always starts fresh) | 0–72 | `st.slider` |
| Optimise For | "Time" | dropdown | `st.selectbox` |
| Horizon (days) | 7 | 3–14 | `st.slider` |

**Important:** Each slider's `value=` parameter is set from `st.session_state["orch_output"]`, NOT from hardcoded defaults. On every agent run (Next Tick), the sliders' defaults reset to match the new agent outputs.

**[▶ Run Simulation]** button — triggers `simulation/digital_twin.py`

**[💾 Save as Scenario A/B/C]** buttons — for comparison table.

---

#### Right Column — Simulation Results

Appears after "Run Simulation" is clicked:

```
┌─────────────────────────────────────────────────────┐
│  SIMULATION RESULTS — NOIDA PLANT                   │
│  Parameters: OEE 91.5% | Workforce 94% | 7 days     │
│                                                      │
│  📦 Expected Output:       8,640 units               │
│  📅 Completion:            Day 5 of 7                │
│  ⚠️  Shortfall vs Target:  -360 units (4.0%)         │
│  💰 Estimated Cost:        $38,400                   │
│  🌱 Carbon Emissions:      3,720 kg CO₂              │
│  👷 Workers Needed:         141 / 150                │
└─────────────────────────────────────────────────────┘
```

**Production Trajectory Chart** (area chart):
- X: Day 1 → Day 7
- Y: Cumulative units
- Line 1: Target demand line (dashed red)
- Line 2: Simulated output (solid blue fill)
- Line 3: Without any parameter changes (grey, for comparison)

**Scenario Comparison Table** (if 2+ scenarios saved):
| Metric | Baseline | Scenario A | Scenario B |
|--------|----------|-----------|-----------|
| Output | 8,640 | 7,980 | 9,250 |
| Cost | $38,400 | $31,200 | $44,100 |
| Carbon | 3,720 kg | 2,840 kg | 4,210 kg |
| Completion | Day 5 | Day 6 | Day 4 |

**[✅ Apply to Production Plan]** — sends slider values to Page 4 via `st.session_state`, re-runs scheduler for the selected plant.

---

#### Bottom: Mini Ollama Chat (NEW — after simulation runs)

Appears below the results section with a separator:

```
─────────────────────────────────────────────────────
💬  Ask follow-up questions about this simulation
─────────────────────────────────────────────────────
```

Chat input: `st.chat_input("e.g. What if I reduce workforce to 70%?")`

**How It Works:**
1. User types a follow-up question
2. The question + current simulation parameters + simulation results are packaged into a prompt
3. Sent to Ollama with context: current slider values, output metrics, plant name
4. Ollama interprets the question:
   - If it's a "what if" → extracts the parameter change, re-runs simulation, displays new results
   - If it's a pure question → answers in plain English using simulation context
5. Response shown in `st.chat_message("assistant")` style

**Example exchanges:**
```
User:  "What if I reduce workforce to 70%?"
→ Ollama detects: "recalculate" intent, workforce_pct=70
→ Simulation re-runs with workforce_pct=70
→ Shows: "At 70% workforce, expected output drops to 6,048 units (-30%).
          Completion pushed to Day 7. Carbon savings: 1,120 kg."

User:  "Why is there a shortfall?"
→ Ollama answers: "The 360-unit shortfall is due to OEE being 91.5%
                   instead of 100% — 8.5% of capacity is lost to
                   machine downtime and quality losses. Raising OEE to 95%
                   (via better maintenance) would close this gap."

User:  "How can I hit 9,000 units?"
→ Ollama answers: "To reach 9,000 units, you need either:
                   (a) OEE ≥ 95.6% — increase by 4.1% via maintenance
                   (b) Add 1 extra shift on Day 3 Night
                   (c) Reduce demand buffer from 10% to 5%"
```

Chat history is stored in `st.session_state["dt_chat_history"]` — persists during the session.

---

## PAGE 8 — Carbon & Energy Dashboard (Environmentalist Agent)

### Layout

#### Carbon KPI Cards (4 cards)
| Card | Formula |
|------|---------|
| Total CO₂ Emitted | `sum(Carbon_Emissions_kg)` |
| Total Penalty Paid | `sum(Carbon_Cost_Penalty_USD)` |
| Peak-hour Penalty | `sum where Grid_Pricing_Period == "Peak"` |
| Compliance Status | `peak_penalty/total > 0.40` → ⚠️ Non-Compliant |

#### Energy Heatmap (Plotly density_heatmap)
- X: Hour of day (0–23)
- Y: Day of week
- Z: mean `Energy_Consumed_kWh`
- Red translucent box on hours 14–20: "Peak Pricing Zone"

#### Emissions by Facility
Horizontal bar chart: `Carbon_Emissions_kg` per facility, sorted descending.

#### Emissions by Product  
Pie chart: `Carbon_Emissions_kg` grouped by `Product_Category`.

#### Environmentalist Agent Assessment Block
```
┌────────────────────────────────────────────────────────────────────┐
│  🌱 ENVIRONMENTALIST AGENT REPORT                                   │
│                                                                     │
│  Compliance:  ⚠️ PARTIALLY NON-COMPLIANT                           │
│  Peak ratio:  43.1%  (threshold: 40%)                              │
│                                                                     │
│  Key Finding: Thai Nguyen plant is running heavy Galaxy S batches  │
│  during peak hours (14:00–18:00 daily), inflating penalties.       │
│                                                                     │
│  Recommendation: Move 6,000 units of Galaxy S production from       │
│  PM shifts to Night shifts across 3 days. Expected saving: $12,400. │
└────────────────────────────────────────────────────────────────────┘
```

#### Shift Timing Optimiser Tool
- Slider: "% of Peak shifts to move to Off-Peak" (0–100%)
- Live metric showing:
  - Estimated carbon penalty saved: `peak_penalty × pct × 0.75`
  - Energy cost saved: `peak_energy × pct × 0.60`

---

---

# PHASE 5 — NLP & HITL
### Pages 9, 10

---

## PAGE 9 — NLP Interface (Full Dedicated Page)

**This is the main NLP page. Separate from the Digital Twin mini-chat.**

### Layout

#### Purpose Banner
```
💬 Natural Language Control Center
Talk to the Agentic System. Ask questions. Change plans. Trigger agent re-runs.
```

#### Conversation Panel (full width)

`st.chat_input("Ask anything or give a command...")` at top.

Chat bubbles (using `st.chat_message`):
- User queries: right-aligned, blue
- Agent responses: left-aligned, grey, labelled with agent name

#### How Ollama NLP Works

The user's message + full orchestrator context (all agent outputs) is sent to Ollama:

```
System prompt:
  You are the Orchestrator agent for a global electronics factory.
  Current system state:
    - Forecast: {forecast_qty} units, risk: {risk_level}
    - Mechanic: {blacklisted_plants} plants blacklisted
    - Budget used: {monthly_spend} of ${monthly_budget}
    - Plan status: {final_status}
  
  The user said: "{user_message}"

  Respond with JSON:
  {
    "intent":    "query | simulate | reconfigure | escalate | approve | reject",
    "agent":     "which agent handles this",
    "params":    {any parameter changes extracted},
    "response":  "plain English answer to show the user",
    "action":    "what action to take in the system"
  }
```

#### Intent-to-Action Table

| Detected Intent | System Action | Example Query |
|----------------|--------------|---------------|
| `query` | Answer from current orch output | "How many delays this week?" |
| `simulate` | Update Digital Twin sliders + re-run | "What if Foxconn goes offline?" |
| `reconfigure` | Re-run specific agent with new params | "Reduce workforce to 80% and replan" |
| `escalate` | Push to HITL queue | "Flag the Noida inventory situation" |
| `approve` | Call `HitlManager.approve()` | "Approve the procurement order" |
| `reject` | Call `HitlManager.reject()` | "Reject the plan from Mechanic" |

#### Response Display
After Ollama responds, the system shows:
- Agent's plain-English answer
- Agent responsible badge
- Confidence % 
- If an action was taken: a green toast notification ("✅ Plan updated. View on Page 4.")
- If a parameter changed: "⟳ Agents are re-running with new parameters..."

#### Department Heads Notification Panel
Below the chat section:

```
📋 PENDING HUMAN APPROVALS BY DEPARTMENT

  Operations Head     │ 2 items pending  │ [Go to Inbox]
  Supply Chain Head   │ 1 PO pending     │ [Go to Inbox]
  CFO                 │ 1 escalation     │ [Go to Inbox]
  Plant Manager       │ 3 maintenance    │ [Go to Inbox]
  Sustainability Head │ 0 items          │ [All Clear ✅]
```

#### NLP Chat History
Persisted in `st.session_state["nlp_history"]` (last 20 messages).
Cleared on Reset.

---

## PAGE 10 — HITL Inbox

**The human approval center. All agents report to their human head here.**

### HITL Flow

```
Any Agent
  → detects issue requiring human decision
  → calls BaseAgent.enqueue_hitl(item_type, payload)
  → row inserted in hitl_queue table
         {id, created_at, item_type="ops|procurement|finance|maintenance|carbon",
          source="AgentName", payload=JSON, status="pending"}

Page 10
  → HitlManager.get_pending() reads from hitl_queue
  → Groups by item_type
  → Displays in the relevant tab
  → Human clicks Approve/Reject + adds comment
  → HitlManager.approve(id, comment) or .reject(id, comment)
  → status updated to "approved"/"rejected"
  → resolved_at timestamp written
  → agent that submitted can now re-run with the decision
```

### Layout: 5 Tabs

**Tab 1 — Operations (Scheduler / Orchestrator items)**

Each pending item card:
```
┌──────────────────────────────────────────────────────────────────┐
│  📋  PRODUCTION PLAN APPROVAL  —  Submitted 14 mins ago          │
│  Submitted by: Scheduler Agent                                   │
│  Plant: Noida Plant (India)                                      │
│                                                                  │
│  Summary: 7-day plan | 8,640 units | 3 shifts/day               │
│                                                                  │
│  ▼ View Full Shift Plan                                          │
│  [expandable table with the full 21-row shift plan]              │
│                                                                  │
│  💬 Comment: [                                    ]              │
│  [✅ Approve Plan]  [❌ Reject — Request Revision]               │
└──────────────────────────────────────────────────────────────────┘
```

**Tab 2 — Procurement (Buyer Agent items)**

Each card:
```
┌──────────────────────────────────────────────────────────────────┐
│  📦  EMERGENCY PURCHASE ORDER  —  Submitted 2 mins ago           │
│  Submitted by: Buyer Agent                                       │
│  Plant: Noida Plant (India)                                      │
│                                                                  │
│  Order: 34,000 raw material units                                │
│  Supplier Quote: $5.41/unit  →  Total: $183,940                  │
│  Justification: 6.4 days remaining, lead time ~3 days            │
│  Finance check: ✅ Within budget ($37,975 remaining after PO)    │
│                                                                  │
│  💬 Comment: [                                    ]              │
│  [✅ Approve PO]  [❌ Reject]  [✏️ Modify Qty]                  │
└──────────────────────────────────────────────────────────────────┘
```

**Tab 3 — Finance (Finance Agent items)**

Each card:
```
┌──────────────────────────────────────────────────────────────────┐
│  💰  BUDGET ESCALATION  —  Submitted 5 mins ago                  │
│  Submitted by: Finance Agent                                     │
│                                                                  │
│  Issue: Monthly spend at 82.4% with 12 days remaining           │
│  Proposed plan adds: $43,500                                     │
│  Post-plan budget used: 91.1%  (approaching limit)              │
│  Risk Score: 67 / 100 (MEDIUM)                                  │
│                                                                  │
│  💡 Finance Agent Suggestion: Defer Queretaro order by 4 days   │
│     to reduce this month's exposure by ~$18,000                 │
│                                                                  │
│  [✅ Override & Approve]  [❌ Block Plan]  [📊 Finance Details]  │
└──────────────────────────────────────────────────────────────────┘
```

**Tab 4 — Engineering (Mechanic Agent items)**

Each card:
```
┌──────────────────────────────────────────────────────────────────┐
│  🔧  EMERGENCY MAINTENANCE REQUEST  —  Submitted NOW             │
│  Submitted by: Mechanic Agent                                    │
│  Plant: Foxconn (Taiwan) — Line 2 (Standard)                    │
│                                                                  │
│  Alert: Predicted TTF = 1.0 hours                               │
│  Temperature: 95.3°C  |  Vibration: 85.8 Hz                    │
│  OEE at time of alert: 72.1%                                    │
│                                                                  │
│  Impact if ignored: Line failure within 1 hour.                 │
│  Estimated repair downtime: 8–12 hours.                         │
│  Reroute recommendation: Move 2,400 units to Queretaro.         │
│                                                                  │
│  [✅ Approve Shutdown + Reroute]  [❌ Continue (Override — RISK)]│
└──────────────────────────────────────────────────────────────────┘
```

**Tab 5 — Sustainability (Environmentalist Agent items)**

Each card:
```
┌──────────────────────────────────────────────────────────────────┐
│  🌱  CARBON COMPLIANCE ALERT  —  Submitted 8 mins ago            │
│  Submitted by: Environmentalist Agent                            │
│                                                                  │
│  Issue: Peak penalty ratio 43.1% exceeds 40% threshold          │
│  This month's carbon penalty: $24,800                           │
│  Recommended action: Shift 2 PM batches to Night shifts         │
│  Savings if implemented: ~$12,400                               │
│                                                                  │
│  [✅ Apply Proposed Rescheduling]  [❌ Continue As-Is]           │
└──────────────────────────────────────────────────────────────────┘
```

#### Resolved History (bottom of any tab)
Expandable section: table of all approved/rejected items, by whom, with comment and timestamp.

#### Empty State
When all tabs are clear:
```
✅ All agents are operating within approved parameters.
   No human review is currently required.
```

---

---

# PHASE 6 — POLISH & INTEGRATION

### Auto-refresh
Every `config.DASHBOARD["auto_refresh_secs"]` = 30 seconds, `st.rerun()` is called
(only if user has not interacted in the last 30s, to avoid interrupting edits).

### Multi-Page App Structure (Recommended)
Convert to `pages/` directory structure:
```
pages/
  01_command_center.py
  02_demand_intelligence.py
  03_inventory_logistics.py
  04_production_plan.py
  05_machine_health.py
  06_finance_dashboard.py
  07_digital_twin.py
  08_carbon_energy.py
  09_nlp_interface.py
  10_hitl_inbox.py
app.py          ← only sidebar + orchestrator runner
```

### Error States (Ollama Offline)
Every agent's narrative box has a fallback:
- If Ollama unreachable: show heuristic fallback text (all agents already implement `_heuristic_summary()`)
- Sidebar shows 🔴 Ollama Offline dot with: "LLM reasoning unavailable. Using rule-based fallback."

### Export Options
- Page 4 (Production Plan): Download shift plan as CSV
- Page 6 (Finance): Download cost breakdown as CSV
- Page 10 (HITL): Download resolved history as CSV

---

---

# COMPLETE PHASED BUILD ORDER

## Phase 1 — Foundation (Build First, Everything Depends On This)
- [ ] Create `agents/orchestrator.py` with full per-plant run sequence
- [ ] Create `hitl/manager.py` (`get_pending`, `approve`, `reject`)
- [ ] Create `simulation/digital_twin.py` (parameter-driven simulation function)
- [ ] Modify `app.py`: remove `run_agents()`, wire `OrchestratorAgent`, store in `session_state`
- [ ] Add Ollama status indicator to sidebar
- [ ] Update `config.py`: add `default_lead_days`, `dt_chat` keys

## Phase 2 — Command Center & Machine Health
- [ ] Build **Page 1** (Command Center) — Orchestrator banner, plant overview grid, agent health
- [ ] Build **Page 5** (Machine Health) — Plant dropdown, 4-panel charts, risk score per plant

## Phase 3 — Production Plan
- [ ] Build **Page 4** (Production Plan) — Level A overview table + Level B plant-specific view
- [ ] Implement readiness gate with live data from mechanic/buyer/finance outputs
- [ ] Implement editable shift plan table (per-plant, `st.data_editor`)
- [ ] Wire slider defaults from `st.session_state["orch_output"]`
- [ ] Remove Gantt chart entirely

## Phase 4 — Intelligence Pages
- [ ] Build **Page 2** (Demand Intelligence) — Rebuild with ML forecast + product/region tabs
- [ ] Build **Page 3** (Inventory) — Redo with lead time calculator + reorder table + urgency logic
- [ ] Build **Page 6** (Finance) — New page: budget gauge, gate status, risk score + suggestions

## Phase 5 — Simulation & Environment
- [ ] Build **Page 7** (Digital Twin) — Slider panel with live defaults + mini Ollama chat
- [ ] Build **Page 8** (Carbon) — Compliance assessment + shift optimiser

## Phase 6 — NLP & HITL
- [ ] Build **Page 9** (NLP Interface) — Full chat with intent routing to agents
- [ ] Build **Page 10** (HITL Inbox) — 5 department tabs with approve/reject

## Phase 7 — Polish
- [ ] Auto-refresh implementation
- [ ] Multi-page `pages/` directory refactor
- [ ] Graceful Ollama-offline fallback on every page
- [ ] Export (CSV) buttons on Pages 4, 6, 10

---

## Summary: All Features Mapped

| Your Feature | Page | Agent | Status in Plan |
|-------------|------|-------|---------------|
| Demand Forecasting (ML) | Page 2 | Forecaster | ✅ Full detail |
| Inventory Analysis + Lead Time | Page 3 | Buyer | ✅ Full detail incl. lead days |
| Production Plan (editable, per-plant) | Page 4 | Scheduler | ✅ Plant-specific, Level A+B |
| Machine/Workforce Readiness Gate | Page 4 + 5 | Mechanic | ✅ Gate banner + plant dropdown |
| Finance Agent + Suggestions | Page 6 | Finance | ✅ Budget + gate + suggestions |
| Orchestrator Supervisor | All pages | Orchestrator | ✅ Conflict detection + HITL |
| Digital Twin (EMI-style sliders) | Page 7 | Simulation | ✅ Live defaults + mini-chat |
| Carbon & Emissions | Page 8 | Environmentalist | ✅ Compliance + optimiser |
| NLP Interface (full page) | Page 9 | All (Ollama) | ✅ Intent routing + chat |
| HITL Inbox (per-department) | Page 10 | All | ✅ 5 tabs + approve/reject |
| Digital Twin follow-up chat | Page 7 (bottom) | Ollama | ✅ Mini-chat after simulation |
