import { useState, useEffect, useCallback, useMemo } from 'react'
import { AlertTriangle, Activity, ShieldAlert, CheckCircle2, Play } from 'lucide-react'
import * as api from '../api/client'
import { useUiConfig } from '../ui-config'

const STATUS_VIEW = {
  ALL_OK: { label: 'NOMINAL', tone: 'nominal', icon: CheckCircle2, text: 'Global ecosystem is operating inside target tolerances.' },
  NEEDS_HITL: { label: 'WARNING', tone: 'warning', icon: AlertTriangle, text: 'Human review required for priority decisions and overrides.' },
  BLOCKED: { label: 'CRITICAL', tone: 'critical', icon: ShieldAlert, text: 'System is blocked by unresolved critical dependencies.' },
  UNKNOWN: { label: 'INITIALIZING', tone: 'warning', icon: Activity, text: 'Awaiting first completed cycle from orchestration engine.' },
}

function Sparkline({ points }) {
  if (!points || points.length === 0) return null
  const max = Math.max(...points)
  const min = Math.min(...points)
  const spread = Math.max(max - min, 1)

  const coords = points
    .map((value, idx) => {
      const x = (idx / (points.length - 1)) * 100
      const y = 100 - ((value - min) / spread) * 100
      return `${x},${y}`
    })
    .join(' ')

  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="ops-sparkline">
      <polyline points={coords} />
    </svg>
  )
}

function OeeGauge({ value, thresholds }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0))
  const radius = 30
  const circumference = 2 * Math.PI * radius
  const strokeDashoffset = circumference * (1 - pct / 100)
  const targetPct = thresholds?.oee_target_pct ?? 90
  const warningPct = thresholds?.oee_warning_pct ?? 80
  const color = pct >= targetPct ? 'var(--green)' : pct >= warningPct ? 'var(--amber)' : 'var(--red)'

  return (
    <svg viewBox="0 0 84 84" className="ops-oee-gauge" role="img" aria-label={`OEE ${pct.toFixed(1)} percent`}>
      <circle cx="42" cy="42" r={radius} className="ops-oee-bg" />
      <circle
        cx="42"
        cy="42"
        r={radius}
        className="ops-oee-fill"
        style={{ strokeDasharray: circumference, strokeDashoffset, stroke: color }}
      />
      <text x="42" y="47" textAnchor="middle">
        {pct.toFixed(0)}%
      </text>
    </svg>
  )
}

function computeAgentScore(key, payload, scoring) {
  if (!payload) return 0
  const forecastScores = scoring?.forecast || {}
  const mechanicScores = scoring?.mechanic || {}
  const buyerScores = scoring?.buyer || {}
  const environScores = scoring?.environ || {}

  if (key === 'forecast') {
    if (payload.risk_level === 'high') return forecastScores.high ?? 52
    if (payload.risk_level === 'medium') return forecastScores.medium ?? 74
    return forecastScores.low ?? 91
  }
  if (key === 'mechanic') {
    const critical = Number(payload.critical_count || 0)
    const warning = Number(payload.warning_count || 0)
    const criticalPenalty = mechanicScores.critical_penalty ?? 25
    const warningPenalty = mechanicScores.warning_penalty ?? 8
    const minimumScore = mechanicScores.minimum_score ?? 18
    return Math.max(100 - critical * criticalPenalty - warning * warningPenalty, minimumScore)
  }
  if (key === 'buyer') {
    const reorders = Number(payload.reorders_triggered || 0)
    const baseScore = buyerScores.base_score ?? 94
    const reorderPenalty = buyerScores.reorder_penalty ?? 4
    const minimumScore = buyerScores.minimum_score ?? 32
    return Math.max(baseScore - reorders * reorderPenalty, minimumScore)
  }
  if (key === 'environ') {
    return payload.compliance_flag
      ? (environScores.compliant ?? 88)
      : (environScores.non_compliant ?? 54)
  }
  if (key === 'finance') {
    return Number(payload.health_score || 0)
  }
  if (key === 'scheduler') {
    return Number(payload.avg_utilisation || 0)
  }
  return 0
}

function agentBadge(score, thresholds) {
  if (score >= (thresholds?.badge_nominal_min ?? 85)) return { text: 'Nominal', cls: 'ops-badge-ok' }
  if (score >= (thresholds?.badge_watch_min ?? 65)) return { text: 'Watch', cls: 'ops-badge-warn' }
  return { text: 'Critical', cls: 'ops-badge-critical' }
}

function severityForRow(row) {
  const raw = String(row?.severity || row?.level || row?.status || '').toLowerCase()
  if (raw.includes('critical') || raw.includes('error')) return 'critical'
  if (raw.includes('warn') || raw.includes('hitl')) return 'warning'
  return 'nominal'
}

function toFeedRows(agentLog, conflicts) {
  if (Array.isArray(agentLog) && agentLog.length > 0) {
    return agentLog.map((row, idx) => ({
      id: row.id || `${row.timestamp || row.created_at || idx}`,
      at: row.timestamp || row.created_at || new Date().toISOString(),
      source: row.agent || row.source || row.component || 'System',
      event: row.message || row.event || row.action || JSON.stringify(row),
      severity: severityForRow(row),
    }))
  }

  if (Array.isArray(conflicts) && conflicts.length > 0) {
    return conflicts.map((conflict, idx) => ({
      id: `conflict-${idx}`,
      at: new Date().toISOString(),
      source: conflict.type || 'Conflict Engine',
      event: conflict.description || conflict.action || 'Conflict raised',
      severity: String(conflict.severity || '').toLowerCase() === 'critical' ? 'critical' : 'warning',
    }))
  }

  return []
}

export default function CommandCenter({ onRunAgents, running }) {
  const { uiConfig } = useUiConfig()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [plants, setPlants] = useState([])
  const [feedRows, setFeedRows] = useState([])

  const ccConfig = uiConfig.command_center || {}
  const agentLabels = ccConfig.agent_labels || {}

  const load = useCallback(async () => {
    setError(null)
    try {
      const [cc, pl, logs] = await Promise.all([
        api.getCommandCenter(),
        api.getPlants(),
        api.getAgentLog({ limit: ccConfig.agent_log_limit || 18 }).catch(() => []),
      ])

      setSnapshot(cc)
      setPlants(pl?.plants || [])
      setFeedRows(toFeedRows(logs?.items || logs?.log || logs || [], cc?.conflicts || []))
    } catch (e) {
      setError(e.message || 'Failed to load command center')
    } finally {
      setLoading(false)
    }
  }, [ccConfig.agent_log_limit])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const id = setInterval(load, ccConfig.refresh_ms || 30000)
    return () => clearInterval(id)
  }, [ccConfig.refresh_ms, load])

  const metrics = useMemo(() => {
    const kpis = snapshot?.kpis || {}
    const hitl = snapshot?.hitl_counts || {}
    return [
      { key: 'otd', label: 'On-Time Delivery', value: `${Number(kpis.on_time_pct || 0).toFixed(1)}%`, numeric: Number(kpis.on_time_pct || 0), tone: 'nominal' },
      { key: 'alerts', label: 'Active Alerts', value: Number(kpis.active_alerts || 0).toLocaleString(), numeric: Number(kpis.active_alerts || 0), tone: Number(kpis.active_alerts || 0) > 0 ? 'critical' : 'nominal' },
      { key: 'health', label: 'System Health', value: `${Number(snapshot?.system_health || 0).toFixed(0)}/100`, numeric: Number(snapshot?.system_health || 0), tone: Number(snapshot?.system_health || 0) >= (ccConfig.system_health_nominal_min ?? 70) ? 'nominal' : 'warning' },
      { key: 'inventory', label: 'Min Inventory Days', value: `${Number(kpis.min_inventory_days || 0).toFixed(1)}d`, numeric: Number(kpis.min_inventory_days || 0), tone: Number(kpis.min_inventory_days || 0) < (ccConfig.inventory_critical_days ?? 3) ? 'critical' : 'warning' },
      { key: 'hitl', label: 'Pending HITL', value: Number(hitl.total || 0).toLocaleString(), numeric: Number(hitl.total || 0), tone: Number(hitl.total || 0) > 0 ? 'warning' : 'nominal' },
    ]
  }, [ccConfig.inventory_critical_days, ccConfig.system_health_nominal_min, snapshot])

  const agentMatrix = useMemo(() => {
    const agents = snapshot?.agents || {}
    return Object.entries(agentLabels).map(([key, name]) => {
      const payload = agents[key] || {}
      const score = computeAgentScore(key, payload, ccConfig.agent_scores)
      return {
        key,
        name,
        score,
        badge: agentBadge(score, ccConfig),
      }
    })
  }, [agentLabels, ccConfig, snapshot])

  if (loading) return <div className="loading-overlay"><div className="spinner" /><span>Loading Command Center...</span></div>
  if (error) return <div className="error-box">{error}</div>

  const status = snapshot?.final_status || 'UNKNOWN'
  const hero = STATUS_VIEW[status] || STATUS_VIEW.UNKNOWN
  const HeroIcon = hero.icon

  return (
    <div className="ops-page">
      <section className={`ops-hero-banner ops-hero-${hero.tone}`}>
        <div className="ops-hero-left">
          <span className="ops-hero-chip">{hero.label}</span>
          <h2>
            <HeroIcon size={20} />
            PROXIMA
          </h2>
          <p>{hero.text}</p>
        </div>
        <div className="ops-hero-right">
          <div>
            Last Sync
            <strong>{snapshot?.last_run_at ? new Date(snapshot.last_run_at).toLocaleTimeString() : 'N/A'}</strong>
          </div>
          <button className="btn btn-primary" onClick={onRunAgents} disabled={running}>
            <Play size={14} />
            {running ? 'Running...' : 'Run Agents'}
          </button>
        </div>
      </section>

      <section className="ops-kpi-row">
        {metrics.map((metric, idx) => (
          <article key={metric.key} className={`ops-kpi-card ops-kpi-${metric.tone}`} style={{ animationDelay: `${idx * (ccConfig.animation_stagger_ms || 90)}ms` }}>
            <div className="ops-kpi-head">
              <p>{metric.label}</p>
              <strong>{metric.value}</strong>
            </div>
            <Sparkline points={snapshot?.sparklines?.[metric.key] || [0, 0]} />
          </article>
        ))}
      </section>

      <section className="ops-panel">
        <div className="ops-section-head">
          <h3>Plant Overview Grid</h3>
          <span>{plants.length} facilities</span>
        </div>
        <div className="ops-plant-grid">
          {plants.map((plant) => (
            <article key={plant.name} className="ops-plant-card">
              <div>
                <h4>{plant.short_name || plant.name}</h4>
                <p>{plant.name}</p>
              </div>
              <OeeGauge value={plant.oee_pct || 0} thresholds={ccConfig} />
              <div>
                <div className="ops-inline-meta">
                  <span>Workforce Coverage</span>
                  <b>{Number(plant.workforce_pct || 0).toFixed(1)}%</b>
                </div>
                <div className="ops-workforce-bar">
                  <span style={{ width: `${Math.max(0, Math.min(100, Number(plant.workforce_pct || 0)))}%` }} />
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      <div className="ops-two-col">
        <section className="ops-panel">
          <div className="ops-section-head">
            <h3>Agent Health Matrix</h3>
            <span>Operational score</span>
          </div>
          <div className="ops-agent-matrix">
            {agentMatrix.map((agent) => (
              <div key={agent.key} className="ops-agent-row">
                <span>{agent.name}</span>
                <span className="ops-agent-score">{agent.score.toFixed(0)}</span>
                <span className={`ops-agent-badge ${agent.badge.cls}`}>{agent.badge.text}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="ops-panel">
          <div className="ops-section-head">
            <h3>Live Activity Feed</h3>
            <span>{feedRows.length} events</span>
          </div>
          <div className="ops-feed-wrap ops-amber-scroll">
            <table className="ops-feed-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Source</th>
                  <th>Event</th>
                </tr>
              </thead>
              <tbody>
                {feedRows.map((row) => (
                  <tr key={row.id} className={`ops-feed-${row.severity}`}>
                    <td>{new Date(row.at).toLocaleTimeString()}</td>
                    <td>{row.source}</td>
                    <td>{row.event}</td>
                  </tr>
                ))}
                {feedRows.length === 0 && (
                  <tr>
                    <td colSpan={3}>No activity events available.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  )
}
