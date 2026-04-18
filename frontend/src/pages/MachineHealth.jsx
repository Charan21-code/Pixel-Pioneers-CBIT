import { useState, useEffect, useCallback } from 'react'
import { Wrench, AlertTriangle, TrendingDown, Activity } from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, RadarChart, Radar, PolarGrid, PolarAngleAxis,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine
} from 'recharts'
import * as api from '../api/client'
import { useUiConfig } from '../ui-config'

const RISK_COLOR = {
  critical: 'var(--red)',
  warning:  'var(--amber)',
  healthy:  'var(--green)',
  low:      'var(--green)',
  medium:   'var(--amber)',
  high:     'var(--red)',
}

const CHART_TOOLTIP_STYLE = {
  background: 'var(--bg-card)',
  border: '1px solid rgba(240, 238, 232, 0.1)',
  borderRadius: 12,
  fontSize: 12,
  boxShadow: '0 10px 24px rgba(0,0,0,0.45)',
}

function FacilityRiskCard({ name, risk, thresholds }) {
  const status = risk.status || 'healthy'
  const color  = RISK_COLOR[status] || 'var(--text-muted)'
  const score  = risk.risk_score || 0
  const riskCriticalMin = thresholds?.risk_progress_critical_min ?? 80
  const riskWarningMin = thresholds?.risk_progress_warning_min ?? 50
  const oeeTargetPct = thresholds?.oee_target_pct ?? 90
  const oeeWarningPct = thresholds?.oee_warning_pct ?? 80
  const ttfCriticalHrs = thresholds?.ttf_critical_hrs ?? 24
  const ttfWarningHrs = thresholds?.ttf_warning_hrs ?? 100

  return (
    <div className="card" style={{ borderTopColor: color, borderTop: `3px solid ${color}` }}>
      <div className="card-header">
        <div>
          <div className="card-title">🏭 {name.split('(')[0].trim()}</div>
          <div className="card-subtitle">{name}</div>
        </div>
        <span className={`badge ${status === 'critical' || status === 'high' ? 'badge-critical' : status === 'warning' || status === 'medium' ? 'badge-warning' : 'badge-ok'}`}>
          {status.toUpperCase()}
        </span>
      </div>

      {/* Risk score progress */}
      <div style={{ marginBottom:14 }}>
        <div style={{ display:'flex', justifyContent:'space-between', fontSize:11, color:'var(--text-muted)', marginBottom:5 }}>
          <span>Risk Score</span>
          <span style={{ fontFamily:'var(--font-mono)', color }}>{score.toFixed(0)}/100</span>
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{
            width:`${score}%`,
            '--fill-color': score >= riskCriticalMin ? 'var(--red)' : score >= riskWarningMin ? 'var(--amber)' : 'var(--green)'
          }} />
        </div>
      </div>

      <div className="stat-row">
        <span className="stat-row-label">OEE</span>
        <span className="stat-row-value" style={{ color: (risk.oee_pct||0) >= oeeTargetPct ? 'var(--green)' : (risk.oee_pct||0) >= oeeWarningPct ? 'var(--amber)' : 'var(--red)' }}>
          {(risk.oee_pct || 0).toFixed(1)}%
        </span>
      </div>
      <div className="stat-row">
        <span className="stat-row-label">TTF</span>
        <span className="stat-row-value" style={{ color: (risk.ttf_hrs||0) < ttfCriticalHrs ? 'var(--red)' : (risk.ttf_hrs||0) < ttfWarningHrs ? 'var(--amber)' : 'var(--green)' }}>
          {risk.ttf_hrs != null ? `${risk.ttf_hrs.toFixed(0)} hrs` : '—'}
        </span>
      </div>
      {risk.temp_c != null && (
        <div className="stat-row">
          <span className="stat-row-label">Temperature</span>
          <span className="stat-row-value">{risk.temp_c.toFixed(1)}°C</span>
        </div>
      )}
      {risk.vibration != null && (
        <div className="stat-row">
          <span className="stat-row-label">Vibration</span>
          <span className="stat-row-value">{risk.vibration.toFixed(2)} mm/s</span>
        </div>
      )}
    </div>
  )
}

export default function MachineHealth() {
  const { uiConfig } = useUiConfig()
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [selPlant, setSelPlant] = useState(null)

  const machineConfig = uiConfig.machine_health || {}

  const load = useCallback(async () => {
    setError(null)
    try {
      const d = await api.getMachines()
      setData(d)
      if (!selPlant && d.facility_risks) setSelPlant(Object.keys(d.facility_risks)[0] || null)
    }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [selPlant])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="loading-overlay"><div className="spinner" /><span>Loading Machine Health & OEE...</span></div>
  if (error)   return <div className="error-box">{error}</div>

  const risks     = data?.facility_risks      || {}
  const critical  = data?.critical_facilities || []
  const warnings  = data?.warning_facilities  || []
  const oeeTs     = data?.oee_time_series     || {}
  const recs      = data?.recommendations     || []
  const plants    = Object.keys(risks)

  // OEE comparison bar
  const oeeBar = plants.map(p => ({
    plant: p.split('(')[0].trim(),
    oee:   (risks[p]?.oee_pct || 0).toFixed(1),
    risk:  risks[p]?.risk_score || 0,
  }))

  // Time series for selected plant — downsample to weekly averages to avoid scatter
  const selOeeTs = (() => {
    const raw = selPlant && oeeTs[selPlant] ? oeeTs[selPlant] : []
    if (raw.length <= 60) return raw  // already sparse enough
    // Group by ISO week (year-week) and average
    const weeks = {}
    raw.forEach(pt => {
      const d = new Date(pt.date)
      const jan1 = new Date(d.getFullYear(), 0, 1)
      const weekNum = Math.ceil(((d - jan1) / 86400000 + jan1.getDay() + 1) / 7)
      const key = `${d.getFullYear()}-W${String(weekNum).padStart(2,'0')}`
      if (!weeks[key]) weeks[key] = { date: pt.date, sum: 0, count: 0 }
      weeks[key].sum += pt.oee
      weeks[key].count += 1
    })
    return Object.values(weeks).map(w => ({ date: w.date, oee: parseFloat((w.sum / w.count).toFixed(2)) }))
  })()

  return (
    <div>
      {/* Alerts */}
      {critical.length > 0 && (
        <div className="error-box">
          🔴 <b>CRITICAL FACILITIES:</b> {critical.join(', ')} — Immediate maintenance required!
        </div>
      )}
      {warnings.length > 0 && !critical.length && (
        <div className="warn-box">
          ⚠️ <b>WARNING FACILITIES:</b> {warnings.join(', ')} — Schedule inspection soon.
        </div>
      )}

      {/* KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card" style={{ '--accent-color': critical.length > 0 ? 'var(--red)' : 'var(--green)' }}>
          <div className="kpi-label">Critical Facilities</div>
          <div className="kpi-value" style={{ color: critical.length > 0 ? 'var(--red)' : 'var(--green)' }}>{critical.length}</div>
          <div className="kpi-delta">require immediate action</div>
          <AlertTriangle size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color': warnings.length > 0 ? 'var(--amber)' : 'var(--green)' }}>
          <div className="kpi-label">Warning Facilities</div>
          <div className="kpi-value" style={{ color: warnings.length > 0 ? 'var(--amber)' : 'var(--green)' }}>{warnings.length}</div>
          <div className="kpi-delta">schedule inspection</div>
          <Wrench size={22} className="kpi-icon" />
        </div>
        {plants.length > 0 && (() => {
          const avgOee = plants.reduce((s, p) => s + (risks[p]?.oee_pct || 0), 0) / plants.length
          return (
            <div className="kpi-card" style={{ '--accent-color': avgOee >= (machineConfig.oee_target_pct ?? 90) ? 'var(--green)' : avgOee >= (machineConfig.oee_warning_pct ?? 80) ? 'var(--amber)' : 'var(--red)' }}>
              <div className="kpi-label">Average OEE</div>
              <div className="kpi-value">{avgOee.toFixed(1)}%</div>
              <div className="kpi-delta">fleet-wide average</div>
              <Activity size={22} className="kpi-icon" />
            </div>
          )
        })()}
        <div className="kpi-card" style={{ '--accent-color':'var(--cyan)' }}>
          <div className="kpi-label">Facilities Monitored</div>
          <div className="kpi-value">{plants.length}</div>
          <div className="kpi-delta">under active telemetry</div>
        </div>
      </div>

      {/* Agent Summary */}
      {data?.summary && <div className="info-box">🔧 <b>MechanicAgent:</b> {data.summary}</div>}

      {/* OEE Bar Chart */}
      {oeeBar.length > 0 && (
        <div className="chart-container">
        <div className="chart-title">📊 OEE & Risk Score by Facility</div>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={oeeBar} margin={{ top:10, right:20, left:10, bottom:30 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" strokeOpacity={0.8} />
              <XAxis dataKey="plant" tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} angle={-20} textAnchor="end" height={40} />
              <YAxis tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={48} unit="%" domain={[0,105]} />
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ fontSize:11, paddingTop:8 }} />
              <ReferenceLine y={machineConfig.oee_target_pct ?? 90} stroke="var(--green)" strokeDasharray="4 2" label={{ value:`Target ${machineConfig.oee_target_pct ?? 90}%`, fill:'var(--green)', fontSize:10, position:'insideTopRight' }} />
              <ReferenceLine y={machineConfig.oee_warning_pct ?? 80} stroke="var(--amber)" strokeDasharray="4 2" label={{ value:`Warning ${machineConfig.oee_warning_pct ?? 80}%`, fill:'var(--amber)', fontSize:10, position:'insideTopRight' }} />
              <Bar dataKey="oee"  name="OEE %"       fill="var(--cyan)"   radius={[4,4,0,0]} animationDuration={600} />
              <Bar dataKey="risk" name="Risk Score"   fill="var(--red)"    radius={[4,4,0,0]} opacity={0.7} animationDuration={600} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="two-col">
        {/* OEE Time Series */}
        <div className="chart-container" style={{ marginBottom:0 }}>
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:12 }}>
            <div className="chart-title" style={{ margin:0 }}>📈 OEE Trend</div>
            <select className="input" style={{ width:180, fontSize:12 }} value={selPlant||''} onChange={e=>setSelPlant(e.target.value)}>
              {plants.map(p => <option key={p} value={p}>{p.split('(')[0].trim()}</option>)}
            </select>
          </div>
          {selOeeTs.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={selOeeTs} margin={{ top:10, right:20, left:10, bottom:30 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" strokeOpacity={0.5} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize:10, fill:'var(--text-muted)', fontFamily:'monospace' }}
                  tickLine={false}
                  interval={Math.max(0, Math.floor(selOeeTs.length / 10) - 1)}
                  angle={-30}
                  textAnchor="end"
                  height={45}
                />
                <YAxis
                  tick={{ fontSize:10, fill:'var(--text-muted)' }}
                  tickLine={false}
                  axisLine={false}
                  width={48}
                  unit="%"
                  domain={[machineConfig.trend_y_axis_min ?? 60, machineConfig.trend_y_axis_max ?? 105]}
                  ticks={[
                    machineConfig.trend_y_axis_min ?? 60,
                    70,
                    75,
                    machineConfig.oee_warning_pct ?? 80,
                    85,
                    machineConfig.oee_target_pct ?? 90,
                    95,
                    100,
                    machineConfig.trend_y_axis_max ?? 105,
                  ]}
                />
                <Tooltip
                  contentStyle={CHART_TOOLTIP_STYLE}
                  formatter={v=>[`${parseFloat(v).toFixed(1)}%`,'OEE (weekly avg)']}
                  labelStyle={{ color:'var(--text-muted)', marginBottom:4 }}
                />
                <ReferenceLine y={machineConfig.oee_target_pct ?? 90} stroke="var(--green)" strokeDasharray="5 3" strokeOpacity={0.8}
                  label={{ value:`Target ${machineConfig.oee_target_pct ?? 90}%`, fill:'var(--green)', fontSize:9, position:'insideTopRight' }} />
                <ReferenceLine y={machineConfig.oee_warning_pct ?? 80} stroke="var(--amber)" strokeDasharray="5 3" strokeOpacity={0.8}
                  label={{ value:`Warning ${machineConfig.oee_warning_pct ?? 80}%`, fill:'var(--amber)', fontSize:9, position:'insideTopRight' }} />
                <Line
                  type="monotone"
                  dataKey="oee"
                  stroke="var(--cyan)"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r:4, strokeWidth:0 }}
                  animationDuration={600}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : <div className="empty-state" style={{ padding:'24px' }}><div className="empty-state-desc">No OEE time series data.</div></div>}
        </div>

        {/* Recommendations */}
        <div className="card" style={{ marginBottom:0 }}>
          <div className="card-header"><div className="card-title">💡 Mechanic Recommendations</div></div>
          {recs.length > 0 ? (
            recs.slice(0, machineConfig.recommendations_display ?? 6).map((r, i) => (
              <div key={i} className="stat-row">
                <span className="stat-row-label" style={{ fontSize:12 }}>
                  {typeof r === 'string' ? r : r.message || JSON.stringify(r)}
                </span>
              </div>
            ))
          ) : <div className="empty-state" style={{ padding:'24px' }}><div className="empty-state-desc">No recommendations yet.</div></div>}
        </div>
      </div>

      {/* Facility Risk Cards */}
      <div className="section-title" style={{ marginTop:20 }}>🔧 Facility Telemetry Detail</div>
      <div className="three-col">
        {plants.map(p => <FacilityRiskCard key={p} name={p} risk={risks[p]} thresholds={machineConfig} />)}
      </div>
    </div>
  )
}
