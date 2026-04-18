import { useState, useEffect, useCallback, useMemo } from 'react'
import { AlertTriangle, Activity, ShieldAlert, CheckCircle2, Play } from 'lucide-react'
import * as api from '../api/client'

const STATUS_VIEW = {
  ALL_OK: { label: 'NOMINAL', tone: 'nominal', icon: CheckCircle2, text: 'Global ecosystem is operating inside target tolerances.' },
  NEEDS_HITL: { label: 'WARNING', tone: 'warning', icon: AlertTriangle, text: 'Human review required for priority decisions and overrides.' },
  BLOCKED: { label: 'CRITICAL', tone: 'critical', icon: ShieldAlert, text: 'System is blocked by unresolved critical dependencies.' },
  UNKNOWN: { label: 'INITIALIZING', tone: 'warning', icon: Activity, text: 'Awaiting first completed cycle from orchestration engine.' },
}

const AGENT_NAMES = {
  forecast: 'Forecaster',
  mechanic: 'Mechanic',
  buyer: 'Buyer',
  environ: 'Environmentalist',
  finance: 'Finance',
  scheduler: 'Scheduler',
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

function OeeGauge({ value }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0))
  const radius = 30
  const circumference = 2 * Math.PI * radius
  const strokeDashoffset = circumference * (1 - pct / 100)
  const color = pct >= 90 ? 'var(--green)' : pct >= 80 ? 'var(--amber)' : 'var(--red)'

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

function computeAgentScore(key, payload) {
  if (!payload) return 0
  if (key === 'forecast') {
    if (payload.risk_level === 'high') return 52
    if (payload.risk_level === 'medium') return 74
    return 91
  }
  if (key === 'mechanic') {
    const critical = Number(payload.critical_count || 0)
    const warning = Number(payload.warning_count || 0)
    return Math.max(100 - critical * 25 - warning * 8, 18)
  }
  if (key === 'buyer') {
    const reorders = Number(payload.reorders_triggered || 0)
    return Math.max(94 - reorders * 4, 32)
  }
  if (key === 'environ') {
    return payload.compliance_flag ? 88 : 54
  }
  if (key === 'finance') {
    return Number(payload.health_score || 0)
  }
  if (key === 'scheduler') {
    return Number(payload.avg_utilisation || 0)
  }
  return 0
}

function agentBadge(score) {
  if (score >= 85) return { text: 'Nominal', cls: 'ops-badge-ok' }
  if (score >= 65) return { text: 'Watch', cls: 'ops-badge-warn' }
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [plants, setPlants] = useState([])
  const [feedRows, setFeedRows] = useState([])

  const load = useCallback(async () => {
    setError(null)
    try {
      const [cc, pl, logs] = await Promise.all([
        api.getCommandCenter(),
        api.getPlants(),
        api.getAgentLog({ limit: 18 }).catch(() => []),
      ])

      setSnapshot(cc)
      setPlants(pl?.plants || [])
      setFeedRows(toFeedRows(logs?.items || logs || [], cc?.conflicts || []))
    } catch (e) {
      setError(e.message || 'Failed to load command center')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [load])

  const metrics = useMemo(() => {
    const kpis = snapshot?.kpis || {}
    const hitl = snapshot?.hitl_counts || {}
    return [
      { key: 'otd', label: 'On-Time Delivery', value: `${Number(kpis.on_time_pct || 0).toFixed(1)}%`, numeric: Number(kpis.on_time_pct || 0), tone: 'nominal' },
      { key: 'alerts', label: 'Active Alerts', value: Number(kpis.active_alerts || 0).toLocaleString(), numeric: Number(kpis.active_alerts || 0), tone: Number(kpis.active_alerts || 0) > 0 ? 'critical' : 'nominal' },
      { key: 'health', label: 'System Health', value: `${Number(snapshot?.system_health || 0).toFixed(0)}/100`, numeric: Number(snapshot?.system_health || 0), tone: Number(snapshot?.system_health || 0) >= 70 ? 'nominal' : 'warning' },
      { key: 'inventory', label: 'Min Inventory Days', value: `${Number(kpis.min_inventory_days || 0).toFixed(1)}d`, numeric: Number(kpis.min_inventory_days || 0), tone: Number(kpis.min_inventory_days || 0) < 3 ? 'critical' : 'warning' },
      { key: 'hitl', label: 'Pending HITL', value: Number(hitl.total || 0).toLocaleString(), numeric: Number(hitl.total || 0), tone: Number(hitl.total || 0) > 0 ? 'warning' : 'nominal' },
    ]
  }, [snapshot])

  const agentMatrix = useMemo(() => {
    const agents = snapshot?.agents || {}
    return Object.entries(AGENT_NAMES).map(([key, name]) => {
      const payload = agents[key] || {}
      const score = computeAgentScore(key, payload)
      return {
        key,
        name,
        score,
        badge: agentBadge(score),
      }
    })
  }, [snapshot])

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
            OPS//CORE Global Health
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
          <article key={metric.key} className={`ops-kpi-card ops-kpi-${metric.tone}`} style={{ animationDelay: `${idx * 90}ms` }}>
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
              <OeeGauge value={plant.oee_pct || 0} />
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
