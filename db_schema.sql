-- ============================================================
-- DATABASE: production_planning
-- ============================================================
CREATE DATABASE production_planning;
\c production_planning;

-- ============================================================
-- 1. MASTER TABLES (dimension / reference data)
-- ============================================================

CREATE TABLE facilities (
    facility_id     SERIAL PRIMARY KEY,
    facility_name   TEXT NOT NULL UNIQUE,        -- e.g. "Noida Plant (India) - Primary"
    country         TEXT,
    facility_type   TEXT CHECK (facility_type IN ('Primary', 'Partner', 'Partner Overflow')),
    max_capacity    INT,
    timezone        TEXT
);

CREATE TABLE production_lines (
    line_id         SERIAL PRIMARY KEY,
    facility_id     INT REFERENCES facilities(facility_id),
    line_name       TEXT NOT NULL,               -- "Line 1 (High Speed)" etc.
    line_type       TEXT CHECK (line_type IN ('High Speed', 'Standard', 'Heavy Duty')),
    max_throughput  INT                          -- units / 2-hr shift
);

CREATE TABLE products (
    product_id      SERIAL PRIMARY KEY,
    product_category TEXT NOT NULL UNIQUE,       -- "Galaxy S Smartphone" etc.
    base_workforce_required INT,                 -- 80 or 150
    carbon_rate_kg_per_kwh NUMERIC(6,4)
);

CREATE TABLE regions (
    region_id       SERIAL PRIMARY KEY,
    region_name     TEXT NOT NULL UNIQUE         -- "USA", "India", etc.
);

-- ============================================================
-- 2. CORE TRANSACTION TABLE
-- ============================================================

CREATE TABLE production_events (
    event_id                BIGSERIAL PRIMARY KEY,
    timestamp               TIMESTAMPTZ NOT NULL,
    order_id                TEXT NOT NULL UNIQUE,
    product_id              INT REFERENCES products(product_id),
    region_id               INT REFERENCES regions(region_id),
    facility_id             INT REFERENCES facilities(facility_id),
    line_id                 INT REFERENCES production_lines(line_id),

    -- Demand
    forecasted_demand       INT,
    actual_order_qty        INT,
    demand_deviation_pct    NUMERIC(6,2) GENERATED ALWAYS AS
                            (ROUND(100.0 * (actual_order_qty - forecasted_demand)
                             / NULLIF(forecasted_demand, 0), 2)) STORED,

    -- Workforce
    workforce_required      INT,
    workforce_deployed      INT,
    workforce_coverage_pct  NUMERIC(5,2) GENERATED ALWAYS AS
                            (ROUND(100.0 * workforce_deployed
                             / NULLIF(workforce_required, 0), 2)) STORED,

    -- Schedule
    schedule_status         TEXT CHECK (schedule_status IN
                            ('On-Time','Delayed','Rerouted','Maintenance Reroute')),
    operator_override_flag  BOOLEAN DEFAULT FALSE,

    -- Machine Health
    machine_temp_c          NUMERIC(7,4),
    machine_vibration_hz    NUMERIC(7,4),
    predicted_ttf_hrs       NUMERIC(10,4),
    machine_oee_pct         NUMERIC(7,4),

    -- Inventory
    raw_material_inventory  INT,
    inventory_threshold     INT DEFAULT 20000,

    -- Procurement
    procurement_action      TEXT,
    live_supplier_quote_usd NUMERIC(8,2),

    -- Energy & Carbon
    grid_pricing_period     TEXT CHECK (grid_pricing_period IN ('Peak','Off-Peak')),
    energy_consumed_kwh     NUMERIC(10,2),
    carbon_emissions_kg     NUMERIC(10,2),
    carbon_cost_penalty_usd NUMERIC(10,2)
);

-- ============================================================
-- 3. AGENT LOG TABLE
-- ============================================================

CREATE TABLE agent_events (
    log_id          BIGSERIAL PRIMARY KEY,
    logged_at       TIMESTAMPTZ DEFAULT NOW(),
    agent_name      TEXT NOT NULL,      -- 'Forecaster','Mechanic','Buyer','Environmentalist','Orchestrator'
    severity        TEXT CHECK (severity IN ('INFO','WARNING','CRITICAL')),
    order_id        TEXT REFERENCES production_events(order_id) ON DELETE SET NULL,
    facility_id     INT REFERENCES facilities(facility_id),
    message         TEXT NOT NULL,
    confidence_pct  NUMERIC(5,2),
    action_taken    TEXT
);

-- ============================================================
-- 4. PROCUREMENT LOG TABLE
-- ============================================================

CREATE TABLE procurement_log (
    proc_id         BIGSERIAL PRIMARY KEY,
    triggered_at    TIMESTAMPTZ DEFAULT NOW(),
    facility_id     INT REFERENCES facilities(facility_id),
    product_id      INT REFERENCES products(product_id),
    supplier_name   TEXT,
    quantity_ordered INT,
    unit_price_usd  NUMERIC(8,2),
    total_cost_usd  NUMERIC(12,2) GENERATED ALWAYS AS
                    (quantity_ordered * unit_price_usd) STORED,
    eta_days        INT,
    status          TEXT DEFAULT 'Pending'
);

-- ============================================================
-- 5. USEFUL VIEWS
-- ============================================================

CREATE VIEW v_facility_kpis AS
SELECT
    f.facility_name,
    DATE_TRUNC('day', pe.timestamp) AS day,
    COUNT(*)                        AS total_orders,
    ROUND(AVG(pe.machine_oee_pct),2) AS avg_oee_pct,
    SUM(pe.energy_consumed_kwh)     AS total_energy_kwh,
    SUM(pe.carbon_cost_penalty_usd) AS total_carbon_penalty,
    ROUND(100.0 * SUM(CASE WHEN pe.schedule_status='On-Time' THEN 1 ELSE 0 END)
          / COUNT(*), 2)            AS on_time_delivery_pct
FROM production_events pe
JOIN facilities f USING (facility_id)
GROUP BY 1,2;

CREATE VIEW v_demand_anomalies AS
SELECT
    order_id, timestamp, product_category_name, region_name,
    forecasted_demand, actual_order_qty, demand_deviation_pct
FROM production_events pe
JOIN products  pr USING (product_id)
JOIN regions   r  USING (region_id)
WHERE demand_deviation_pct > 30;

-- ============================================================
-- 6. INDEXES
-- ============================================================

CREATE INDEX idx_pe_timestamp    ON production_events (timestamp);
CREATE INDEX idx_pe_facility     ON production_events (facility_id);
CREATE INDEX idx_pe_status       ON production_events (schedule_status);
CREATE INDEX idx_pe_grid_period  ON production_events (grid_pricing_period);
CREATE INDEX idx_ae_agent        ON agent_events (agent_name);
CREATE INDEX idx_ae_severity     ON agent_events (severity);
