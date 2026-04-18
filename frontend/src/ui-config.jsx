import { createContext, useContext, useEffect, useState } from 'react'
import * as api from './api/client'

export const DEFAULT_UI_CONFIG = {
  app: {
    brand_subtitle: '',
    status_poll_ms: 15000,
    run_poll_startup_delay_ms: 2000,
    run_poll_interval_ms: 1500,
    run_poll_max_attempts: 60,
    run_poll_min_attempts_before_exit: 2,
  },
  command_center: {
    refresh_ms: 30000,
    agent_log_limit: 18,
    system_health_nominal_min: 70,
    inventory_critical_days: 3,
    badge_nominal_min: 85,
    badge_watch_min: 65,
    oee_target_pct: 90,
    oee_warning_pct: 80,
    animation_stagger_ms: 90,
    agent_labels: {
      forecast: 'Forecaster',
      mechanic: 'Mechanic',
      buyer: 'Buyer',
      environ: 'Environmentalist',
      finance: 'Finance',
      scheduler: 'Scheduler',
    },
    agent_scores: {
      forecast: { high: 52, medium: 74, low: 91 },
      mechanic: { critical_penalty: 25, warning_penalty: 8, minimum_score: 18 },
      buyer: { base_score: 94, reorder_penalty: 4, minimum_score: 32 },
      environ: { compliant: 88, non_compliant: 54 },
    },
  },
  demand: {
    forecast_horizon_days: 7,
    moving_average_weeks: 4,
    overview_tick_target: 14,
    facility_tick_target: 10,
    facility_palette: ['var(--primary)', 'var(--signal)', 'var(--tertiary)', '#D8922C', 'var(--red)', '#8D6422'],
  },
  inventory: {
    stock_healthy_pct: 80,
    stock_warning_pct: 40,
    reorders_display: 10,
    quote_tick_target: 8,
    quote_animation_ms: 800,
    approved_decisions: ['auto_approve'],
    blocked_decisions: ['hitl_escalate', 'auto_reject'],
  },
  machine_health: {
    risk_progress_warning_min: 50,
    risk_progress_critical_min: 80,
    oee_target_pct: 90,
    oee_warning_pct: 80,
    ttf_critical_hrs: 24,
    ttf_warning_hrs: 100,
    trend_y_axis_min: 60,
    trend_y_axis_max: 105,
    recommendations_display: 6,
  },
  production: {
    util_nominal_min: 90,
    util_warning_min: 70,
    target_utilisation_pct: 90,
    shift_rows_display: 8,
    weekly_tick_target: 12,
  },
  finance: {
    monthly_budget: 2000000,
    health_nominal_min: 70,
    health_warning_min: 40,
    risk_warning_min: 40,
    risk_critical_min: 70,
    budget_warning_pct: 80,
    budget_critical_pct: 95,
    alerts_display: 3,
    monthly_spend_display: 6,
    approved_gate_values: ['APPROVED', 'AUTO_APPROVE'],
    blocked_gate_values: ['BLOCKED', 'HITL_REQUIRED'],
  },
  carbon: {
    trend_window_days: 14,
    max_energy_ticks: 7,
  },
  digital_twin: {
    optimise_options: ['Time', 'Cost', 'Carbon'],
    default_params: {
      oee_pct: 91,
      workforce_pct: 95,
      forecast_qty: 2000,
      energy_price: 0.12,
      downtime_hrs: 0,
      optimise_for: 'Time',
      horizon_days: 7,
      demand_buffer_pct: 0.1,
    },
    ranges: {
      oee_pct: { min: 1, max: 100, step: 0.5 },
      workforce_pct: { min: 1, max: 100, step: 0.5 },
      downtime_hrs: { min: 0, max: 24, step: 0.5 },
      energy_price: { min: 0.01, max: 0.5, step: 0.01 },
      demand_buffer_pct: { min: 0, max: 0.3, step: 0.01 },
      horizon_days: { min: 1, max: 30, step: 1 },
    },
  },
}

const UiConfigContext = createContext({
  uiConfig: DEFAULT_UI_CONFIG,
  loading: true,
})

function isPlainObject(value) {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

function mergeUiConfig(base, override) {
  if (!isPlainObject(base) || !isPlainObject(override)) return override ?? base

  const merged = { ...base }
  Object.keys(override).forEach((key) => {
    const nextValue = override[key]
    merged[key] = isPlainObject(base[key]) && isPlainObject(nextValue)
      ? mergeUiConfig(base[key], nextValue)
      : nextValue
  })
  return merged
}

export function UiConfigProvider({ children }) {
  const [uiConfig, setUiConfig] = useState(DEFAULT_UI_CONFIG)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true

    api.getUiConfig()
      .then((config) => {
        if (!alive || !config) return
        setUiConfig((current) => mergeUiConfig(current, config))
      })
      .catch(() => { })
      .finally(() => {
        if (alive) setLoading(false)
      })

    return () => {
      alive = false
    }
  }, [])

  return (
    <UiConfigContext.Provider value={{ uiConfig, loading }}>
      {children}
    </UiConfigContext.Provider>
  )
}

export function useUiConfig() {
  return useContext(UiConfigContext)
}
