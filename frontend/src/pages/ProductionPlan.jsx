import { useState, useEffect, useCallback } from 'react'
import { BarChart2, CheckCircle, AlertTriangle, Clock } from 'lucide-react'
import {
  BarChart, Bar, LineChart, Line,
  AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine
} from 'recharts'
import * as api from '../api/client'

// Aggregate dense daily time-series into weekly averages to avoid the
// "scattered spike" look caused by hundreds of raw data points.
function toWeeklyAvg(rows) {
  if (!rows || rows.length === 0) return []
  const buckets = {}
  rows.forEach(({ date, qty }) => {
    const d = new Date(date)
    if (isNaN(d)) return
    // ISO week key: year + week-of-year
    const dayOfYear = Math.floor((d - new Date(d.getFullYear(), 0, 0)) / 86400000)
    const weekNum   = Math.ceil((dayOfYear + d.getDay()) / 7)
    const key       = `${d.getFullYear()}-W${String(weekNum).padStart(2,'0')}`
    if (!buckets[key]) buckets[key] = { week: key, total: 0, count: 0 }
    buckets[key].total += (qty || 0)
    buckets[key].count += 1
  })
  return Object.values(buckets)
    .sort((a, b) => a.week.localeCompare(b.week))
    .map(b => ({ week: b.week, qty: Math.round(b.total / b.count) }))
}

const COLORS = ['#00E5FF','#FFB300','#00E676','#7C3AED','#FF1744','#FF6D00']

export default function ProductionPlan() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [selPlant, setSelPlant] = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const d = await api.getProduction()
      setData(d)
      if (!selPlant && d.scheduler) setSelPlant(Object.keys(d.scheduler)[0] || null)
    }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [selPlant])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="loading-overlay"><div className="spinner" /><span>Loading Production Plan...</span></div>
  if (error)   return <div className="error-box">{error}</div>

  const scheduler  = data?.scheduler       || {}
  const plans      = Object.entries(scheduler)
  const prodTs     = data?.production_ts   || {}
  const status     = data?.final_status    || 'UNKNOWN'
  const conflicts  = data?.conflicts       || []

  const allPlants = Object.keys(scheduler)
  const selected  = selPlant && scheduler[selPlant] ? scheduler[selPlant] : null

  // Summary stats
  const totalThroughput = plans.reduce((s, [, p]) => s + (p.expected_throughput || 0), 0)
  const avgUtil = plans.length > 0
    ? plans.reduce((s, [, p]) => s + (p.utilisation_pct || 0), 0) / plans.length
    : 0

  // Build utilization bar data
  const utilData = plans.map(([plant, plan]) => ({
    plant: plant.split('(')[0].trim(),
    utilisation: plan.utilisation_pct || 0,
    throughput:  plan.expected_throughput || 0,
  }))

  // Time series for selected plant
  const selTs    = selPlant && prodTs[selPlant] ? prodTs[selPlant] : []
  const weeklyTs  = toWeeklyAvg(selTs)

  return (
    <div>
      {/* KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card" style={{ '--accent-color':'var(--cyan)' }}>
          <div className="kpi-label">Total Throughput</div>
          <div className="kpi-value" style={{ fontSize:22 }}>{totalThroughput.toLocaleString()}</div>
          <div className="kpi-delta">units planned across all plants</div>
          <BarChart2 size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color': avgUtil >= 90 ? 'var(--green)' : avgUtil >= 70 ? 'var(--amber)' : 'var(--red)' }}>
          <div className="kpi-label">Avg Utilisation</div>
          <div className="kpi-value">{avgUtil.toFixed(1)}%</div>
          <div className="kpi-delta">across {plans.length} plants</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color': conflicts.length > 0 ? 'var(--red)' : 'var(--green)' }}>
          <div className="kpi-label">Active Conflicts</div>
          <div className="kpi-value" style={{ color: conflicts.length > 0 ? 'var(--red)' : 'var(--green)' }}>{conflicts.length}</div>
          <div className="kpi-delta">cross-agent conflicts</div>
          <AlertTriangle size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color': status === 'ALL_OK' ? 'var(--green)' : status === 'NEEDS_HITL' ? 'var(--amber)' : 'var(--red)' }}>
          <div className="kpi-label">Plan Status</div>
          <div className="kpi-value" style={{
            color: status === 'ALL_OK' ? 'var(--green)' : status === 'NEEDS_HITL' ? 'var(--amber)' : 'var(--red)',
            fontSize: 16, textTransform:'uppercase'
          }}>
            {status.replace(/_/g,' ')}
          </div>
          <div className="kpi-delta">system final status</div>
        </div>
      </div>

      {/* Utilisation Bar Chart */}
      <div className="chart-container">
        <div className="chart-title">📊 Plant Utilisation & Throughput</div>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={utilData} margin={{ top:10, right:20, left:10, bottom:30 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#253347" strokeOpacity={0.8} />
            <XAxis dataKey="plant" tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} angle={-20} textAnchor="end" height={40} />
            <YAxis yAxisId="left" tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={48} unit="%" />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={80} tickFormatter={v=>v.toLocaleString()} />
            <Tooltip contentStyle={{ background:'#111827', border:'1px solid #253347', borderRadius:8, fontSize:12, boxShadow:'0 8px 24px rgba(0,0,0,0.5)' }} />
            <Legend wrapperStyle={{ fontSize:11, paddingTop:8 }} />
            <ReferenceLine yAxisId="left" y={90} stroke="var(--green)" strokeDasharray="4 2" label={{ value:'Target 90%', fill:'var(--green)', fontSize:10, position:'insideTopRight' }} />
            <Bar yAxisId="left"  dataKey="utilisation" name="Utilisation %" fill="var(--cyan)"   radius={[4,4,0,0]} animationDuration={600} />
            <Bar yAxisId="right" dataKey="throughput"  name="Throughput"   fill="var(--purple)" radius={[4,4,0,0]} animationDuration={600} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="two-col">
        {/* Plant Selector + Shift Plan */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">🗓️ Shift Plan Detail</div>
            <select className="input" style={{ width:200, fontSize:12 }} value={selPlant || ''} onChange={e => setSelPlant(e.target.value)}>
              {allPlants.map(p => <option key={p} value={p}>{p.split('(')[0].trim()}</option>)}
            </select>
          </div>
          {selected ? (
            <>
              <div className="stat-row">
                <span className="stat-row-label">Expected Throughput</span>
                <span className="stat-row-value">{selected.expected_throughput?.toLocaleString()} units</span>
              </div>
              <div className="stat-row">
                <span className="stat-row-label">Utilisation</span>
                <span className="stat-row-value">{selected.utilisation_pct?.toFixed(1)}%</span>
              </div>
              <div className="stat-row">
                <span className="stat-row-label">Available Facilities</span>
                <span className="stat-row-value">{selected.available_facilities?.length || 0}</span>
              </div>
              <div className="stat-row">
                <span className="stat-row-label">Excluded Facilities</span>
                <span className="stat-row-value" style={{ color:'var(--red)' }}>{selected.excluded_facilities?.length || 0}</span>
              </div>
              {selected.summary && (
                <div style={{ fontSize:12, color:'var(--text-secondary)', marginTop:10, fontStyle:'italic' }}>
                  {selected.summary}
                </div>
              )}
              {/* Shift plan table */}
              {selected.shift_plan?.length > 0 && (
                <div style={{ marginTop:14, overflowX:'auto' }}>
                  <table className="data-table">
                    <thead><tr><th>Facility</th><th>Shift</th><th>Assigned Qty</th><th>OEE</th></tr></thead>
                    <tbody>
                      {selected.shift_plan.slice(0, 8).map((s, i) => (
                        <tr key={i}>
                          <td>{String(s.facility||'—').split('(')[0].trim()}</td>
                          <td className="mono">{s.shift || '—'}</td>
                          <td className="mono">{Number(s.assigned_qty || 0).toLocaleString()}</td>
                          <td className="mono">{Number(s.oee_pct || 0).toFixed(1)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : (
            <div className="empty-state" style={{ padding:'24px' }}>
              <div className="empty-state-desc">Select a plant to view its shift plan.</div>
            </div>
          )}
        </div>

        {/* Production Time Series for Selected Plant */}
        <div>
          {weeklyTs.length > 0 && (
            <div className="chart-container" style={{ marginBottom:16 }}>
              <div className="chart-title">📈 Weekly Avg Output — {selPlant?.split('(')[0].trim()}</div>
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={weeklyTs} margin={{ top:10, right:20, left:10, bottom:40 }}>
                  <defs>
                    <linearGradient id="tsGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="var(--cyan)" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="var(--cyan)" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#253347" strokeOpacity={0.8} />
                  <XAxis
                    dataKey="week"
                    tick={{ fontSize:9, fill:'var(--text-muted)', fontFamily:'monospace' }}
                    tickLine={false}
                    interval={Math.max(0, Math.floor(weeklyTs.length / 12) - 1)}
                    angle={-35}
                    textAnchor="end"
                    height={50}
                  />
                  <YAxis
                    tick={{ fontSize:10, fill:'var(--text-muted)' }}
                    tickLine={false}
                    axisLine={false}
                    width={72}
                    tickFormatter={v => v.toLocaleString()}
                  />
                  <Tooltip
                    contentStyle={{ background:'#111827', border:'1px solid #253347', borderRadius:8, fontSize:12, boxShadow:'0 8px 24px rgba(0,0,0,0.5)' }}
                    formatter={v => [v.toLocaleString(), 'Avg Units/day']}
                    labelFormatter={l => `Week: ${l}`}
                  />
                  <Area
                    type="monotoneX"
                    dataKey="qty"
                    stroke="var(--cyan)"
                    strokeWidth={2}
                    fill="url(#tsGrad)"
                    dot={false}
                    activeDot={{ r:4, fill:'var(--cyan)', strokeWidth:0 }}
                    animationDuration={600}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Plan status Per Plant */}
          <div className="card">
            <div className="card-header"><div className="card-title">🏭 Plant Plan Summary</div></div>
            <table className="data-table">
              <thead><tr><th>Plant</th><th>Util %</th><th>Throughput</th><th>Status</th></tr></thead>
              <tbody>
                {plans.map(([plant, plan]) => {
                  const util = plan.utilisation_pct || 0
                  const utilColor = util >= 90 ? 'var(--green)' : util >= 70 ? 'var(--amber)' : 'var(--red)'
                  return (
                    <tr key={plant} onClick={() => setSelPlant(plant)} style={{ cursor:'pointer' }}>
                      <td>{plant.split('(')[0].trim()}</td>
                      <td className="mono" style={{ color: utilColor }}>{util.toFixed(1)}%</td>
                      <td className="mono">{(plan.expected_throughput || 0).toLocaleString()}</td>
                      <td>
                        <span style={{ fontSize:11, color: plan.shift_plan?.length > 0 ? 'var(--green)' : 'var(--text-muted)' }}>
                          {plan.shift_plan?.length > 0 ? '✅ Ready' : '⏳ Pending'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
