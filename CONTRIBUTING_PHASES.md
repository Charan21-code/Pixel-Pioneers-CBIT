# Factory Agent System — Team Integration & Phase Guide

Welcome to the Factory Agent System build! **Phase 1 (Config & DB)** and **Phase 2 (Base Agent interface)** are already completed and pushed.

To ensure we can all work in parallel without merge conflicts, the remaining work has been split into independent tracks. Find your assigned track below.

---

## 🛑 REQUIRED READING FOR ALL TEAMMATES
1. **Live-Data Contract**: Never query `production_events` directly from the database using SQL. Your agent's `run()` method will receive a `context` dictionary containing `context["df"]` (a pandas DataFrame). This is sliced to the current simulation time. Use this to prevent looking into the future.
2. **Inheritance**: Your agent must inherit from `BaseAgent` (in `agents/base_agent.py`).
3. **Configuration**: Never hardcode thresholds or parameters. Import them from `config.py`.
4. **Ollama Fallbacks**: `self.call_ollama()` returns `{}` on timeout or offline mode. Your agent **must** handle this and provide default rule-based values so the system doesn't crash.
5. **Signaling**: Call `self.publish_signal(...)` at least once at the end of your agent's run to log its decision to the dashboard.

---

## 🛠️ Track 1: Foundation Specialists (Forecaster & Mechanic)
**Dependencies:** None. Start immediately.

### Task 1: `agents/forecaster.py` (`ForecasterAgent`)
*   **Input**: `context["df"]`
*   **Logic**: Aggregate daily `Actual_Order_Qty`. Fit a simple `LinearRegression` (from `sklearn`) on the last 14 days and project the next 7 days.
*   **LLM Call**: Ask Ollama to summarize the trend and flag anomalies (using `config.AGENT["demand_spike_pct"]`).
*   **Output Dict**: Needs `forecast_qty`, `trend_slope`, `risk_level` (from LLM), and `summary`.

### Task 2: `agents/mechanic.py` (`MechanicAgent`)
*   **Input**: `context["df"]`
*   **Logic**: Group by `Assigned_Facility`. Find facilities where `Predicted_Time_To_Failure_Hrs` < `config.AGENT["ttf_critical_hrs"]`.
*   **LLM Call**: Pass the worst 3 facilities to Ollama for maintenance recommendations.
*   **Output Dict**: Needs `critical_facilities` (list of names) and `facility_risks` score mapping.

---

## 💰 Track 2: The Finance Cluster
**Dependencies:** None. Start immediately.

### Task 1: `agents/finance/` Sub-modules
*   **Implementation**: Create purely deterministic Python classes (no LLM calls, keep it <10ms):
    *   `budget_tracker.py`: Reads `monthly_spend` table, compares against `config.FINANCE["monthly_budget"]`.
    *   `cost_estimator.py`: Adds `config.FINANCE["overhead_multiplier"]` to requests.
    *   `risk_scorer.py`: Calculates risk 0-100 based on remaining budget.
    *   `approval_router.py`: Auto-approves (< $1k), Auto-rejects (over budget), or routes to HITL (> $10k).

### Task 2: `agents/finance/finance_agent.py` (`FinanceAgent`)
*   **Logic**: Wire the sub-modules together. Expose two methods: 
    *   `request_clearance(request_dict)` -> returns approval status and logs to `monthly_spend` if approved.
    *   `financial_health_score(plan_dict)` -> returns 0-100 system financial health.

---

## 🏭 Track 3: Advanced Operations (Buyer, Env, Scheduler)
**Dependencies**: `Buyer` needs `FinanceAgent` (Build simple mocks to unblock yourself until Track 2 is done). `Scheduler` needs `Forecaster` and `Mechanic` outputs.

### Task 1: `agents/buyer.py` (`BuyerAgent`)
*   **Input**: `context["df"]` and `context["forecast"]`
*   **Logic**: Check `Raw_Material_Inventory_Units` against thresholds. If low, formulate a reorder request.
*   **Integration**: You **must** call `FinanceAgent().request_clearance(...)` before generating a PO. If denied, trigger a `self.publish_signal` warning.

### Task 2: `agents/environmentalist.py` (`EnvironmentalistAgent`)
*   **Input**: `context["df"]`
*   **Logic**: Sum `Carbon_Cost_Penalty_USD` by peak/off-peak. Check if peak penalty ratio exceeds `config.AGENT["peak_penalty_ratio"]`.
*   **LLM Call**: Ask Ollama for shift rescheduling suggestions to reduce carbon footprint.

### Task 3: `agents/scheduler.py` (`SchedulerAgent`)
*   **Input**: `context["df"]`, `context["forecast"]`, `context["mechanic"]`
*   **Logic**: Assign `forecast_qty` to facilities. **Crucial**: Blacklist any facility listed in `context["mechanic"]["critical_facilities"]`. 

---

## 🔬 Track 4: Simulation & HITL Infrastructure
**Dependencies:** None. Start immediately.

### Task 1: `simulation/digital_twin.py` (`DigitalTwin`)
*   **Logic**: Use `simpy` to run a fast discrete-event simulation of the `SchedulerAgent`'s plan over `config.SIMULATION["sim_days"]`. Return `delivery_probability` and `utilisation_pct`. 

### Task 2: `hitl/approval_queue.py` (`ApprovalQueue`)
*   **Logic**: Simple CRUD wrapper around the `hitl_queue` SQLite table. Implement `list_pending()`, `approve(id)`, `reject(id)`, and a CLI interface (`python -m hitl.approval_queue list`).

---

## 🧠 Track 5: Orchestrator & UI Wiring (The Master Track)
**Dependencies:** Needs empty mock classes of all agents from Tracks 1-3 to start wiring.

### Task 1: `agents/orchestrator.py` (`OrchestratorAgent`)
*   **Logic**: The brain. In `run()`, use `asyncio.gather` or `ThreadPoolExecutor` to run `Forecaster`, `Mechanic`, and `Environmentalist` in parallel. Then run `Scheduler`. Then run `Buyer`. Run `FinanceAgent` last to score the plan.
*   **Conflict Resolution**: If simulation fails or budget fails, retry scheduling or push to `enqueue_hitl()`.

### Task 2: `app.py` (Streamlit UI Integration)
*   **Logic**: Replace the hardcoded `run_agents()` with the newly built `OrchestratorAgent`.
*   **Views**: Add the "Finance Dashboard" and "HITL Queue" views to the Streamlit app. 
*   **Chat**: Wire the NL Interface view directly to local Ollama using `httpx`.

---

## 🚀 Merge Strategy
1. Work in your local branches: `feature/track-1-mechanic`
2. Teammate 5 (Track 5) will provide mock outputs in `orchestrator.py` initially.
3. As each Track finishes, merge to `main`. Teammate 5 will swap the mock outputs with your real agent calls. 
