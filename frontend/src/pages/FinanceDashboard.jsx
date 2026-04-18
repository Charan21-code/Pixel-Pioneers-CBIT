import { useState, useEffect, useCallback } from 'react'
import { DollarSign, TrendingUp, AlertTriangle, Shield } from 'lucide-react'
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine
} from 'recharts'
import * as api from '../api/client'
import { useUiConfig } from '../ui-config'

const CHART_TOOLTIP_STYLE = {
  background: 'var(--bg-card)',
  border: '1px solid rgba(240, 238, 232, 0.1)',
  borderRadius: 12,
  fontSize: 12,
  boxShadow: '0 10px 24px rgba(0,0,0,0.45)',
}

export default function FinanceDashboard() {
  const { uiConfig } = useUiConfig()
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try { setData(await api.getFinance()) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="loading-overlay"><div className="spinner" /><span>Loading Finance Dashboard...</span></div>
  if (error)   return <div className="error-box">{error}</div>

  const financeConfig = uiConfig.finance || {}

  const health     = data?.health_score  || 0
  const gate       = data?.gate_decision || 'UNKNOWN'
  const risk       = data?.risk_score    || 0
  const budget     = data?.budget_status || {}
  const alerts     = data?.alerts        || []
  const penalties  = data?.penalty_series || []
  const costs      = data?.cost_series    || []
  const monthly    = data?.monthly_spend  || []
  const summary    = data?.summary || ''
  const suggestions = data?.suggestions || []

  const approvedGateValues = financeConfig.approved_gate_values || ['APPROVED', 'AUTO_APPROVE']
  const blockedGateValues = financeConfig.blocked_gate_values || ['BLOCKED', 'HITL_REQUIRED']

  const healthColor = health >= (financeConfig.health_nominal_min ?? 70)
    ? 'var(--green)'
    : health >= (financeConfig.health_warning_min ?? 40)
      ? 'var(--amber)'
      : 'var(--red)'
  const gateColor = approvedGateValues.includes(gate)
    ? 'var(--green)'
    : blockedGateValues.includes(gate)
      ? 'var(--red)'
      : 'var(--amber)'

  const budgetUsed    = budget.pct_used || 0
  const budgetSpent   = budget.spent_usd || 0
  const budgetTotal   = budget.monthly_budget ?? financeConfig.monthly_budget ?? 0
  const budgetColor   = budgetUsed >= (financeConfig.budget_critical_pct ?? 95)
    ? 'var(--red)'
    : budgetUsed >= (financeConfig.budget_warning_pct ?? 80)
      ? 'var(--amber)'
      : 'var(--green)'
  const riskColor = risk >= (financeConfig.risk_critical_min ?? 70)
    ? 'var(--red)'
    : risk >= (financeConfig.risk_warning_min ?? 40)
      ? 'var(--amber)'
      : 'var(--green)'

  return (
    <div>
      {/* Gate Banner */}
      <div className={`status-banner ${approvedGateValues.includes(gate) ? 'ok' : blockedGateValues.includes(gate) ? 'blocked' : 'hitl'}`}>
        <Shield size={18} />
        Finance Gate: <b>{gate}</b>
        <div className="banner-meta">
          <span>Health: <b style={{ color: healthColor, fontFamily:'var(--font-mono)' }}>{health.toFixed(0)}/100</b></span>
          <span>Risk: <b style={{ color: riskColor, fontFamily:'var(--font-mono)' }}>{risk.toFixed(0)}/100</b></span>
        </div>
      </div>

      {/* Alerts */}
      {alerts.length > 0 && (
        <div className="warn-box">
          {alerts.slice(0, financeConfig.alerts_display ?? 3).map((a,i) => <div key={i}>⚠️ {typeof a === 'string' ? a : a.message || JSON.stringify(a)}</div>)}
        </div>
      )}

      {summary && (
        <div className="info-box" style={{ marginBottom:20 }}>
          💰 <b>FinanceAgent:</b> {summary}
        </div>
      )}

      {/* KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card" style={{ '--accent-color': healthColor }}>
          <div className="kpi-label">Finance Health</div>
          <div className="kpi-value" style={{ color: healthColor }}>{health.toFixed(0)}</div>
          <div className="kpi-delta">out of 100</div>
          <Shield size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color': gateColor }}>
          <div className="kpi-label">Gate Decision</div>
          <div className="kpi-value" style={{ color: gateColor, fontSize:14, textTransform:'uppercase' }}>
            {gate.replace(/_/g,' ')}
          </div>
          <div className="kpi-delta">procurement gate status</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color': budgetColor }}>
          <div className="kpi-label">Budget Used</div>
          <div className="kpi-value" style={{ color: budgetColor }}>{budgetUsed.toFixed(1)}%</div>
          <div className="kpi-delta">${budgetSpent.toLocaleString(undefined,{maximumFractionDigits:0})} of ${budgetTotal.toLocaleString()}</div>
          <DollarSign size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color': riskColor }}>
          <div className="kpi-label">Financial Risk</div>
          <div className="kpi-value" style={{ color: riskColor }}>{risk.toFixed(0)}</div>
          <div className="kpi-delta">composite risk score</div>
          <AlertTriangle size={22} className="kpi-icon" />
        </div>
      </div>

      {/* Budget progress */}
      <div className="card">
        <div className="card-header"><div className="card-title">💰 Monthly Budget Utilisation</div></div>
        <div style={{ marginBottom:10, fontSize:13, color:'var(--text-secondary)' }}>
          ${budgetSpent.toLocaleString(undefined,{maximumFractionDigits:0})} spent of ${budgetTotal.toLocaleString()} monthly budget
        </div>
        <div className="progress-bar" style={{ height:12 }}>
          <div className="progress-fill" style={{ width:`${Math.min(100,budgetUsed)}%`, '--fill-color': budgetColor }} />
        </div>
        <div style={{ display:'flex', justifyContent:'space-between', fontSize:11, marginTop:6, color:'var(--text-muted)' }}>
          <span>$0</span>
          <span style={{ color: budgetColor, fontWeight:600 }}>{budgetUsed.toFixed(1)}% used</span>
          <span>${budgetTotal.toLocaleString()}</span>
        </div>
      </div>

      <div className="two-col">
        {/* Carbon Penalty Series */}
        {penalties.length > 0 && (
          <div className="chart-container" style={{ marginBottom:0 }}>
            <div className="chart-title"><AlertTriangle size={14} /> Daily Carbon Penalty ($)</div>
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={penalties} margin={{ top:10, right:20, left:10, bottom:30 }}>
                <defs>
                  <linearGradient id="penGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="var(--red)" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="var(--red)" stopOpacity={0}    />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" strokeOpacity={0.8} />
                <XAxis dataKey="date" tick={{ fontSize:10, fill:'var(--text-muted)', fontFamily:'monospace' }} tickLine={false} interval="preserveStartEnd" angle={-30} textAnchor="end" height={45} />
                <YAxis tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={80} tickFormatter={v=>`$${v.toLocaleString()}`} />
                <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={v=>[`$${v.toLocaleString()}`,'Penalty']} />
                <Area type="basis" dataKey="penalty" stroke="var(--red)" strokeWidth={2} fill="url(#penGrad)" dot={{ r:2, fill:'var(--red)', strokeWidth:0 }} activeDot={{ r:5, fill:'var(--red)' }} animationDuration={600} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Supplier Cost Series */}
        {costs.length > 0 && (
          <div className="chart-container" style={{ marginBottom:0 }}>
            <div className="chart-title"><DollarSign size={14} /> Daily Supplier Cost ($)</div>
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={costs} margin={{ top:10, right:20, left:10, bottom:30 }}>
                <defs>
                  <linearGradient id="costGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="var(--primary)" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="var(--primary)" stopOpacity={0}    />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" strokeOpacity={0.8} />
                <XAxis dataKey="date" tick={{ fontSize:10, fill:'var(--text-muted)', fontFamily:'monospace' }} tickLine={false} interval="preserveStartEnd" angle={-30} textAnchor="end" height={45} />
                <YAxis tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={80} tickFormatter={v=>`$${v.toLocaleString()}`} />
                <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={v=>[`$${v.toLocaleString()}`,'Cost']} />
                <Area type="basis" dataKey="cost" stroke="var(--amber)" strokeWidth={2} fill="url(#costGrad)" dot={{ r:2, fill:'var(--primary)', strokeWidth:0 }} activeDot={{ r:5, fill:'var(--primary)' }} animationDuration={600} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Budget Details */}
      <div className="two-col">
        <div className="card">
          <div className="card-header"><div className="card-title">📋 Budget Breakdown</div></div>
          {Object.entries(budget).filter(([k]) => k !== 'pct_used').map(([k, v]) => (
            <div key={k} className="stat-row">
              <span className="stat-row-label">{k.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}</span>
              <span className="stat-row-value">
                {typeof v === 'number' ? (k.includes('pct') ? `${v.toFixed(1)}%` : `$${v.toLocaleString(undefined,{maximumFractionDigits:0})}`) : String(v)}
              </span>
            </div>
          ))}
        </div>

        <div className="card">
          <div className="card-header"><div className="card-title">💳 Recent Monthly Spend</div></div>
          {monthly.length > 0 ? (
            <table className="data-table">
              <thead><tr><th>Date</th><th>Amount</th><th>Description</th></tr></thead>
              <tbody>
                {monthly.slice(0, financeConfig.monthly_spend_display ?? 6).map((s, i) => (
                  <tr key={i}>
                    <td className="mono">{s.logged_at ? new Date(s.logged_at).toLocaleDateString() : '—'}</td>
                    <td className="mono" style={{ color:'var(--amber)' }}>${Number(s.amount_usd||0).toLocaleString(undefined,{maximumFractionDigits:0})}</td>
                    <td style={{ fontSize:11, color:'var(--text-muted)' }}>{s.description || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty-state" style={{ padding:'24px' }}>
              <div className="empty-state-desc">No spend records logged yet.</div>
            </div>
          )}
        </div>
      </div>

      {suggestions.length > 0 && (
        <div className="card">
          <div className="card-header"><div className="card-title">💡 Finance Suggestions</div></div>
          {suggestions.map((s, i) => (
            <div key={i} className="stat-row">
              <span className="stat-row-label" style={{ fontSize:12, lineHeight:1.5 }}>
                {typeof s === 'string' ? s : JSON.stringify(s)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
