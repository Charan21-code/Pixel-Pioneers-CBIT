import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react'
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine
} from 'recharts'
import * as api from '../api/client'

const FACILITIES_COLORS = ['#00E5FF','#FFB300','#00E676','#7C3AED','#FF1744','#FF6D00']

export default function DemandIntelligence() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try { setData(await api.getDemand()) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="loading-overlay"><div className="spinner" /><span>Loading Demand Intelligence...</span></div>
  if (error)   return <div className="error-box">{error}</div>

  const ts       = data?.time_series   || []
  const forecast = data?.forecast_qty  || 0
  const slope    = data?.trend_slope   || 0
  const r2       = data?.r_squared     || 0
  const anomaly  = data?.anomaly_count || 0
  const risk     = data?.risk_level    || 'low'
  const sched    = data?.schedule_status || {}

  const riskColor = risk === 'high' ? 'var(--red)' : risk === 'medium' ? 'var(--amber)' : 'var(--green)'

  return (
    <div>
      {/* KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card" style={{ '--accent-color':'var(--cyan)' }}>
          <div className="kpi-label">7-Day Forecast</div>
          <div className="kpi-value">{forecast.toLocaleString()}</div>
          <div className="kpi-delta">units demand projected</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color': slope >= 0 ? 'var(--green)' : 'var(--red)' }}>
          <div className="kpi-label">Trend Slope</div>
          <div className="kpi-value" style={{ color: slope >= 0 ? 'var(--green)' : 'var(--red)', fontSize:22 }}>
            {slope >= 0 ? <TrendingUp size={20} style={{ display:'inline' }} /> : <TrendingDown size={20} style={{ display:'inline' }} />}
            {' '}{slope >= 0 ? '+' : ''}{slope.toFixed(2)} u/day
          </div>
          <div className="kpi-delta">R² = {r2.toFixed(3)}</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color': anomaly > 0 ? 'var(--red)' : 'var(--green)' }}>
          <div className="kpi-label">Anomalies Detected</div>
          <div className="kpi-value" style={{ color: anomaly > 0 ? 'var(--red)' : 'var(--green)' }}>{anomaly}</div>
          <div className="kpi-delta">demand spike events</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color': riskColor }}>
          <div className="kpi-label">Risk Level</div>
          <div className="kpi-value" style={{ color: riskColor, textTransform:'uppercase', fontSize:20 }}>{risk}</div>
          <div className="kpi-delta">{data?.recommended_action?.slice(0, 60) || '—'}</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--green)' }}>
          <div className="kpi-label">On-Time Events</div>
          <div className="kpi-value" style={{ color:'var(--green)' }}>
            {sched.total > 0 ? ((sched.on_time / sched.total) * 100).toFixed(1) : '—'}%
          </div>
          <div className="kpi-delta">{sched.on_time?.toLocaleString()} of {sched.total?.toLocaleString()}</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--red)' }}>
          <div className="kpi-label">Delayed Events</div>
          <div className="kpi-value" style={{ color:'var(--red)' }}>{sched.delayed?.toLocaleString() || 0}</div>
          <div className="kpi-delta">require intervention</div>
        </div>
      </div>

      {/* Agent Summary */}
      {data?.summary && (
        <div className="info-box" style={{ marginBottom:20 }}>
          📈 <b>Forecaster Agent:</b> {data.summary}
        </div>
      )}

      {/* Demand Time Series */}
      <div className="chart-container">
        <div className="chart-title"><TrendingUp size={15} /> Daily Demand Volume — All Facilities</div>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={ts} margin={{ top:10, right:20, left:10, bottom:30 }}>
            <defs>
              <linearGradient id="demGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#00E5FF" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#00E5FF" stopOpacity={0}   />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#253347" strokeOpacity={0.8} />
            <XAxis dataKey="date" tick={{ fontSize:10, fill:'var(--text-muted)', fontFamily:'monospace' }} tickLine={false} interval="preserveStartEnd" angle={-30} textAnchor="end" height={45} />
            <YAxis tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={72} tickFormatter={v => v.toLocaleString()} />
            <Tooltip
              contentStyle={{ background:'#111827', border:'1px solid #253347', borderRadius:8, fontSize:12, boxShadow:'0 8px 24px rgba(0,0,0,0.5)' }}
              labelStyle={{ color:'var(--text-secondary)' }}
              formatter={v => [v.toLocaleString(), 'Units']}
            />
            <Area type="monotone" dataKey="qty" stroke="#00E5FF" strokeWidth={2} fill="url(#demGrad)" dot={false} animationDuration={600} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Per-Facility Breakdown */}
      {data?.plant_series && Object.keys(data.plant_series).length > 0 && (() => {
        // Merge all facilities into one unified timeline array
        const facilities = Object.keys(data.plant_series)
        const dateMap = {}
        facilities.forEach(fac => {
          const key = fac.split('(')[0].trim()
          ;[...data.plant_series[fac]]
            .sort((a, b) => new Date(a.date) - new Date(b.date))
            .forEach(({ date, qty }) => {
              if (!dateMap[date]) dateMap[date] = { date }
              dateMap[date][key] = qty
            })
        })
        const merged = Object.values(dateMap).sort((a, b) => new Date(a.date) - new Date(b.date))
        const facKeys = facilities.map(f => f.split('(')[0].trim())
        // Show ~10 ticks on X axis
        const tickInterval = Math.max(1, Math.floor(merged.length / 10))

        return (
          <div className="chart-container">
            <div className="chart-title">📊 Per-Facility Weekly Demand</div>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={merged} margin={{ top:10, right:20, left:10, bottom:40 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#253347" strokeOpacity={0.8} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize:10, fill:'var(--text-muted)' }}
                  tickLine={false}
                  interval={tickInterval}
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
                  formatter={(v, name) => [v?.toLocaleString(), name]}
                />
                <Legend wrapperStyle={{ fontSize:11, paddingTop:8 }} />
                {facKeys.map((key, i) => (
                  <Line
                    key={key}
                    dataKey={key}
                    name={key}
                    stroke={FACILITIES_COLORS[i % FACILITIES_COLORS.length]}
                    strokeWidth={1.5}
                    dot={false}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )
      })()}

      {/* Schedule Status */}
      <div className="two-col">
        <div className="card">
          <div className="card-header"><div className="card-title">📊 Schedule Status Breakdown</div></div>
          <div className="stat-row">
            <span className="stat-row-label">On-Time Events</span>
            <span className="stat-row-value" style={{ color:'var(--green)' }}>{sched.on_time?.toLocaleString()}</span>
          </div>
          <div className="stat-row">
            <span className="stat-row-label">Delayed Events</span>
            <span className="stat-row-value" style={{ color:'var(--red)' }}>{sched.delayed?.toLocaleString()}</span>
          </div>
          <div className="stat-row">
            <span className="stat-row-label">Total Records</span>
            <span className="stat-row-value">{sched.total?.toLocaleString()}</span>
          </div>
          <div className="stat-row">
            <span className="stat-row-label">On-Time Rate</span>
            <span className="stat-row-value">
              {sched.total > 0 ? ((sched.on_time / sched.total)*100).toFixed(1) : '—'}%
            </span>
          </div>
        </div>

        <div className="card">
          <div className="card-header"><div className="card-title">🎯 Forecaster Diagnostics</div></div>
          <div className="stat-row">
            <span className="stat-row-label">7-Day Forecast Qty</span>
            <span className="stat-row-value">{forecast.toLocaleString()} units</span>
          </div>
          <div className="stat-row">
            <span className="stat-row-label">Trend</span>
            <span className="stat-row-value" style={{ color: slope >= 0 ? 'var(--green)' : 'var(--red)' }}>
              {slope >= 0 ? '+' : ''}{slope.toFixed(2)} units/day
            </span>
          </div>
          <div className="stat-row">
            <span className="stat-row-label">Model R²</span>
            <span className="stat-row-value">{r2.toFixed(4)}</span>
          </div>
          <div className="stat-row">
            <span className="stat-row-label">Horizon Days</span>
            <span className="stat-row-value">{data?.horizon_days || 7}</span>
          </div>
          <div className="stat-row">
            <span className="stat-row-label">Risk Level</span>
            <span className="stat-row-value" style={{ color: riskColor, textTransform:'uppercase' }}>{risk}</span>
          </div>
          <div className="stat-row">
            <span className="stat-row-label">Anomalies</span>
            <span className="stat-row-value" style={{ color: anomaly > 0 ? 'var(--red)' : 'var(--green)' }}>{anomaly}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
