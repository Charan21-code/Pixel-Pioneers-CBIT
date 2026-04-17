import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, AlertTriangle, CheckCircle, Clock, Activity, Zap, Package, Users } from 'lucide-react'
import {
  AreaChart, Area, ResponsiveContainer, Tooltip, XAxis, YAxis
} from 'recharts'
import * as api from '../api/client'

const STATUS_CLASS = { ALL_OK: 'ok', NEEDS_HITL: 'hitl', BLOCKED: 'blocked', UNKNOWN: 'unknown' }
const STATUS_LABEL = {
  ALL_OK:     '🟢 ALL SYSTEMS GO — All agents operating within approved parameters',
  NEEDS_HITL: '🟡 ATTENTION NEEDED — Issues require human review',
  BLOCKED:    '🔴 PRODUCTION BLOCKED — Critical conflicts. HITL review required',
  UNKNOWN:    '⚪ Awaiting first agent run — click Run All Agents',
}

const AGENT_ACCENT = {
  forecast:  'var(--cyan)',
  mechanic:  'var(--amber)',
  buyer:     'var(--purple)',
  environ:   'var(--green)',
  finance:   'var(--red)',
  scheduler: 'var(--text-secondary)',
}

function AgentCard({ name, icon, accentKey, summary, metric, status }) {
  const accent = AGENT_ACCENT[accentKey] || 'var(--cyan)'
  return (
    <div className="agent-card" style={{ '--accent-color': accent }}>
      <div className="agent-name">{icon} {name}</div>
      <div className="agent-summary">{summary || 'Not yet run.'}</div>
      <div className="agent-metric">{metric}</div>
    </div>
  )
}

function ConflictItem({ conflict }) {
  const isCritical = conflict.severity === 'CRITICAL'
  return (
    <div className="conflict-item" style={{
      '--border-color': isCritical ? 'var(--red)' : 'var(--amber)',
      '--bg-glow': isCritical ? 'var(--red-glow)' : 'var(--amber-glow)',
    }}>
      <div className="conflict-header">
        <span className={`badge badge-${isCritical ? 'critical' : 'warning'}`}>
          {conflict.severity}
        </span>
        <span style={{ fontSize:12, color:'var(--text-secondary)' }}>
          {conflict.type?.replace(/_/g,' ').replace(/\b\w/g, c=>c.toUpperCase())}
        </span>
        <span style={{ fontSize:11, color:'var(--text-muted)', marginLeft:'auto' }}>
          {conflict.involved_agents?.join(' ↔ ')}
        </span>
      </div>
      <div className="conflict-desc">{conflict.description}</div>
      <div className="conflict-action">→ {conflict.action}</div>
    </div>
  )
}

function PlantCard({ plant }) {
  const topColor =
    plant.risk_status === 'critical' ? 'var(--red)' :
    plant.risk_status === 'warning'  ? 'var(--amber)' :
    'var(--green)'

  const invEmoji =
    plant.inv_status === 'healthy' ? '✅' :
    plant.inv_status === 'low'     ? '⚠️' : '🔴'

  return (
    <div className="plant-card" style={{ '--top-color': topColor }}>
      <div className="plant-name">{plant.short_name}</div>
      <div className="plant-full-name">{plant.name}</div>
      <div className="plant-stats">
        <div className="plant-stat">
          <span>OEE</span>
          <span className="plant-stat-val" style={{ color: plant.oee_pct >= 90 ? 'var(--green)' : plant.oee_pct >= 80 ? 'var(--amber)' : 'var(--red)' }}>
            {plant.oee_pct?.toFixed(1)}%
          </span>
        </div>
        <div className="plant-stat">
          <span>Risk</span>
          <span className="plant-stat-val" style={{ color: topColor }}>
            {plant.risk_status?.toUpperCase()} ({plant.risk_score?.toFixed(0)})
          </span>
        </div>
        <div className="plant-stat">
          <span>Inventory</span>
          <span className="plant-stat-val">{invEmoji} {plant.inv_days?.toFixed(1)}d</span>
        </div>
        <div className="plant-stat">
          <span>Workforce</span>
          <span className="plant-stat-val">{plant.workforce_pct?.toFixed(1)}%</span>
        </div>
        <div className="plant-stat">
          <span>Throughput</span>
          <span className="plant-stat-val">{plant.throughput?.toLocaleString()}</span>
        </div>
      </div>
    </div>
  )
}

export default function CommandCenter({ onRunAgents, running }) {
  const [data,    setData]    = useState(null)
  const [plants,  setPlants]  = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const [cc, pl] = await Promise.all([api.getCommandCenter(), api.getPlants()])
      setData(cc)
      setPlants(pl.plants || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [load])

  if (loading) return <div className="loading-overlay"><div className="spinner" /><span>Loading Command Center...</span></div>

  if (error) return (
    <div className="error-box" style={{ marginTop:0 }}>
      ⚠️ {error} — Backend may not be running. Start with <code>cd backend && uvicorn main:app --reload</code>
    </div>
  )

  const status  = data?.final_status || 'UNKNOWN'
  const health  = data?.system_health || 0
  const kpis    = data?.kpis || {}
  const agents  = data?.agents || {}
  const conflicts = data?.conflicts || []
  const hitl    = data?.hitl_counts || {}

  const healthColor = health >= 70 ? 'var(--green)' : health >= 40 ? 'var(--amber)' : 'var(--red)'

  return (
    <div>
      {/* Status Banner */}
      <div className={`status-banner ${STATUS_CLASS[status] || 'unknown'}`}>
        <span style={{ flex:1 }}>{STATUS_LABEL[status] || STATUS_LABEL.UNKNOWN}</span>
        <div className="banner-meta">
          <span>Health: <b style={{ color: healthColor, fontFamily:'var(--font-mono)' }}>{health.toFixed(0)}/100</b></span>
          {data?.last_run_at && <span>{new Date(data.last_run_at).toLocaleTimeString()}</span>}
          <button className="btn btn-ghost btn-sm" onClick={load}><RefreshCw size={12} /></button>
        </div>
      </div>

      {/* KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card" style={{ '--accent-color':'var(--green)' }}>
          <div className="kpi-label">On-Time Delivery</div>
          <div className="kpi-value" style={{ color:'var(--green)' }}>{kpis.on_time_pct?.toFixed(1) ?? '—'}%</div>
          <div className="kpi-delta">vs 90% target</div>
          <CheckCircle size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--red)' }}>
          <div className="kpi-label">Active Alerts</div>
          <div className="kpi-value" style={{ color: kpis.active_alerts > 0 ? 'var(--red)' : 'var(--green)' }}>{kpis.active_alerts ?? '—'}</div>
          <div className="kpi-delta">{kpis.active_alerts === 0 ? 'All clear' : 'Needs attention'}</div>
          <AlertTriangle size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--amber)' }}>
          <div className="kpi-label">Carbon Penalty</div>
          <div className="kpi-value" style={{ color:'var(--amber)', fontSize:20 }}>${kpis.total_carbon_usd?.toLocaleString(undefined,{maximumFractionDigits:0}) ?? '—'}</div>
          <div className="kpi-delta">cumulative</div>
          <Zap size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--cyan)' }}>
          <div className="kpi-label">Min Inventory</div>
          <div className="kpi-value" style={{ color:'var(--cyan)' }}>{kpis.min_inventory_days?.toFixed(1) ?? '—'}d</div>
          <div className="kpi-delta">days remaining (worst plant)</div>
          <Package size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--purple)' }}>
          <div className="kpi-label">Workforce</div>
          <div className="kpi-value" style={{ color:'var(--purple)' }}>{kpis.workforce_pct?.toFixed(1) ?? '—'}%</div>
          <div className="kpi-delta">coverage</div>
          <Users size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--red)' }}>
          <div className="kpi-label">HITL Pending</div>
          <div className="kpi-value" style={{ color: hitl.total > 0 ? 'var(--red)' : 'var(--green)' }}>{hitl.total ?? 0}</div>
          <div className="kpi-delta" style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
            {hitl.ops > 0 && <span>ops:{hitl.ops}</span>}
            {hitl.procurement > 0 && <span>proc:{hitl.procurement}</span>}
            {hitl.finance > 0 && <span>fin:{hitl.finance}</span>}
            {hitl.maintenance > 0 && <span>maint:{hitl.maintenance}</span>}
          </div>
          <Activity size={22} className="kpi-icon" />
        </div>
      </div>

      {/* Plant Cards */}
      <div className="section-title">🌐 Plant Status Overview</div>
      {plants.length > 0 ? (
        <div className="plant-grid">
          {plants.map(p => <PlantCard key={p.name} plant={p} />)}
        </div>
      ) : (
        <div className="empty-state">
          <div className="empty-state-icon">🏭</div>
          <div className="empty-state-title">No plant data yet</div>
          <div className="empty-state-desc">Click <b>Run All Agents</b> in the sidebar to load live data.</div>
        </div>
      )}

      {/* Agent Summary */}
      <div className="section-title">🤖 Agent Health Summary</div>
      <div className="agent-grid">
        <AgentCard name="Forecaster"      icon="📈" accentKey="forecast"  summary={agents.forecast?.summary}  metric={`Forecast: ${agents.forecast?.forecast_qty?.toLocaleString() || 0} units | Risk: ${agents.forecast?.risk_level || '—'}`} />
        <AgentCard name="Mechanic"        icon="🔧" accentKey="mechanic"  summary={agents.mechanic?.summary}  metric={`${agents.mechanic?.critical_count || 0} critical, ${agents.mechanic?.warning_count || 0} warning facility(ies)`} />
        <AgentCard name="Buyer"           icon="📦" accentKey="buyer"     summary={`${agents.buyer?.reorders_triggered || 0} reorder(s) triggered`} metric={`$${(agents.buyer?.total_spend_usd || 0).toLocaleString(undefined,{maximumFractionDigits:0})} requested`} />
        <AgentCard name="Environmentalist" icon="🌱" accentKey="environ"  summary={agents.environ?.summary}  metric={`Peak penalty: ${agents.environ?.peak_penalty_pct?.toFixed(1) || 0}% | ${agents.environ?.compliance_flag ? '✅ Compliant' : '⚠️ Non-Compliant'}`} />
        <AgentCard name="Finance"         icon="💰" accentKey="finance"   summary={`Health: ${agents.finance?.health_score?.toFixed(1) || '—'}/100 | Gate: ${agents.finance?.gate_decision || '—'}`} metric={`$${(agents.finance?.spent_usd || 0).toLocaleString(undefined,{maximumFractionDigits:0})} spent`} />
        <AgentCard name="Scheduler"       icon="🗓️" accentKey="scheduler" summary={`${agents.scheduler?.plant_count || 0} plant plans generated`} metric={`System: ${agents.scheduler?.final_status || '—'}`} />
      </div>

      {/* Conflicts */}
      <div className="section-title">⚡ Active Conflicts ({conflicts.length})</div>
      {conflicts.length > 0 ? (
        <div className="conflict-list">
          {conflicts.map((c, i) => <ConflictItem key={i} conflict={c} />)}
        </div>
      ) : (
        <div className="info-box">
          ✅ No cross-agent conflicts detected. All agents are operating within approved parameters.
        </div>
      )}
    </div>
  )
}
