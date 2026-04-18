import { useState, useEffect, useCallback } from 'react'
import { Zap, Leaf, AlertTriangle } from 'lucide-react'
import {
  ComposedChart, Area, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import * as api from '../api/client'
import { useUiConfig } from '../ui-config'

const GRID_COLORS = { Peak: 'var(--red)', 'Off-Peak': 'var(--green)', peak: 'var(--red)', off_peak: 'var(--green)' }
const CHART_TOOLTIP_STYLE = {
  background: 'var(--bg-card)',
  border: '1px solid rgba(240, 238, 232, 0.1)',
  borderRadius: 12,
  fontSize: 12,
  boxShadow: '0 10px 24px rgba(0,0,0,0.45)',
}

const parseChartDate = (value) => {
  if (!value) return null

  const parts = String(value).split('-').map(Number)
  if (parts.length === 3 && parts.every(Number.isFinite)) {
    return new Date(parts[0], parts[1] - 1, parts[2])
  }

  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

const formatChartDate = (value, options) => {
  const parsed = parseChartDate(value)
  return parsed
    ? parsed.toLocaleDateString('en-US', options)
    : String(value)
}

const formatCompactValue = (value) =>
  new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value) || 0)

const formatFullValue = (value) =>
  Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })

export default function CarbonEnergy() {
  const { uiConfig } = useUiConfig()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const carbonConfig = uiConfig.carbon || {}

  const load = useCallback(async () => {
    setError(null)
    try { setData(await api.getCarbon()) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="loading-overlay"><div className="spinner" /><span>Loading Carbon & Energy...</span></div>
  if (error) return <div className="error-box">{error}</div>

  const compliant = data?.compliance_flag ?? true
  const compColor = compliant ? 'var(--green)' : 'var(--red)'
  const grid = data?.grid_breakdown || {}
  const pieData = Object.entries(grid).map(([k, v]) => ({ name: k, value: Number(v.toFixed(0)) }))
  const facilities = data?.facility_penalties || []
  const energySeries = data?.energy_time_series || []
  const suggestions = data?.shift_suggestions || []
  const trendWindow = carbonConfig.trend_window_days || 14
  const energyChartSeries = energySeries.map((point, index, series) => {
    const kwh = Number(point?.kwh || 0)
    const windowStart = Math.max(0, index - trendWindow + 1)
    const trendSlice = series.slice(windowStart, index + 1)
    const trend = trendSlice.reduce((sum, item) => sum + Number(item?.kwh || 0), 0) / trendSlice.length

    return {
      ...point,
      kwh,
      trend: Number(trend.toFixed(1)),
    }
  })
  const energyPointCount = energyChartSeries.length
  const energyTickValues = energyPointCount > 1
    ? Array.from({ length: Math.min(carbonConfig.max_energy_ticks || 7, energyPointCount) }, (_, idx) => {
      const lastIndex = energyPointCount - 1
      const pointIndex = Math.round((idx * lastIndex) / Math.max(1, Math.min(carbonConfig.max_energy_ticks || 7, energyPointCount) - 1))
      return energyChartSeries[pointIndex]?.date
    }).filter((value, idx, arr) => value && arr.indexOf(value) === idx)
    : energyChartSeries.map(point => point.date)
  const totalEnergyForAvg = energyChartSeries.reduce((sum, point) => sum + point.kwh, 0)
  const averageEnergy = energyPointCount ? totalEnergyForAvg / energyPointCount : 0
  const latestEnergyPoint = energyPointCount ? energyChartSeries[energyPointCount - 1] : null
  const peakEnergyPoint = energyChartSeries.reduce((peak, point) => (
    !peak || point.kwh > peak.kwh ? point : peak
  ), null)

  return (
    <div>
      {/* Compliance Banner */}
      <div className={compliant ? 'status-banner ok' : 'status-banner blocked'} style={{ marginBottom: 20 }}>
        <Leaf size={18} />
        {compliant
          ? '✅ CARBON COMPLIANT — Peak penalty ratio within acceptable thresholds'
          : '⚠️ NON-COMPLIANT — Peak hour penalty ratio exceeds threshold. Shift scheduling required'}
        <div className="banner-meta">
          <span>Status: <b style={{ color: compColor }}>{data?.compliance_status || (compliant ? 'COMPLIANT' : 'NON-COMPLIANT')}</b></span>
          <span>Savings: <b style={{ color: 'var(--green)' }}>${(data?.estimated_savings_usd || 0).toLocaleString()}</b></span>
        </div>
      </div>

      {/* KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card" style={{ '--accent-color': 'var(--green)' }}>
          <div className="kpi-label">Total Carbon</div>
          <div className="kpi-value" style={{ color: 'var(--green)', fontSize: 22 }}>{(data?.total_carbon_kg || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
          <div className="kpi-delta">kg CO₂ emitted</div>
          <Leaf size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color': 'var(--cyan)' }}>
          <div className="kpi-label">Total Energy</div>
          <div className="kpi-value" style={{ color: 'var(--cyan)', fontSize: 22 }}>{(data?.total_energy_kwh || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
          <div className="kpi-delta">kWh consumed</div>
          <Zap size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color': 'var(--red)' }}>
          <div className="kpi-label">Total Penalty</div>
          <div className="kpi-value" style={{ color: 'var(--red)', fontSize: 22 }}>${(data?.total_penalty_usd || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
          <div className="kpi-delta">USD carbon cost</div>
          <AlertTriangle size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color': 'var(--red)' }}>
          <div className="kpi-label">Peak Penalty</div>
          <div className="kpi-value" style={{ color: 'var(--red)', fontSize: 22 }}>${(data?.peak_penalty_usd || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
          <div className="kpi-delta">{(data?.peak_penalty_pct || 0).toFixed(1)}% of total</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color': 'var(--green)' }}>
          <div className="kpi-label">Off-Peak Penalty</div>
          <div className="kpi-value" style={{ color: 'var(--green)', fontSize: 22 }}>${(data?.off_peak_penalty_usd || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
          <div className="kpi-delta">off-peak hours</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color': 'var(--amber)' }}>
          <div className="kpi-label">Est. Savings</div>
          <div className="kpi-value" style={{ color: 'var(--amber)', fontSize: 22 }}>${(data?.estimated_savings_usd || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
          <div className="kpi-delta">by shifting to off-peak</div>
        </div>
      </div>

      {/* Agent Summary */}
      {data?.summary && <div className="info-box">🌱 <b>EnvironmentalistAgent:</b> {data.summary}</div>}

      <div className="two-col">
        {/* Energy Time Series */}
        <div className="chart-container">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap', marginBottom: 14 }}>
            <div>
              <div className="chart-title" style={{ marginBottom: 2 }}><Zap size={14} /> Daily Energy Consumption (kWh)</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                Daily readings stay visible in the background while the highlighted {trendWindow}-day trend makes the overall pattern easier to read.
              </div>
            </div>
            {energyPointCount > 0 && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <div style={{ padding: '8px 10px', borderRadius: 12, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 4 }}>Average</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{formatCompactValue(averageEnergy)} kWh</div>
                </div>
                <div style={{ padding: '8px 10px', borderRadius: 12, background: 'rgba(255,179,0,0.08)', border: '1px solid rgba(255,179,0,0.16)' }}>
                  <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 4 }}>Peak Day</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--amber)' }}>{formatCompactValue(peakEnergyPoint?.kwh || 0)} kWh</div>
                </div>
                <div style={{ padding: '8px 10px', borderRadius: 12, background: 'rgba(255,184,48,0.08)', border: '1px solid rgba(255,184,48,0.16)' }}>
                  <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: 4 }}>Latest</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--cyan)' }}>{formatCompactValue(latestEnergyPoint?.kwh || 0)} kWh</div>
                </div>
              </div>
            )}
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={energyChartSeries} margin={{ top: 10, right: 16, left: 4, bottom: 18 }}>
              <defs>
                <linearGradient id="nrgGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--primary)" stopOpacity={0.18} />
                  <stop offset="100%" stopColor="var(--primary)" stopOpacity={0.02} />
                </linearGradient>
                <filter id="nrgGlow" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="3" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              <CartesianGrid strokeDasharray="2 4" stroke="var(--chart-grid)" strokeOpacity={0.45} vertical={false} />
              <XAxis
                dataKey="date"
                ticks={energyTickValues}
                tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                tickLine={false}
                axisLine={false}
                minTickGap={24}
                tickMargin={10}
                tickFormatter={value => formatChartDate(value, { month: 'short', year: '2-digit' })}
              />
              <YAxis
                tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                tickLine={false}
                axisLine={false}
                width={54}
                tickCount={5}
                tickFormatter={value => formatCompactValue(value)}
                domain={[
                  (dataMin) => Math.max(0, Math.floor(dataMin * 0.88)),
                  (dataMax) => Math.ceil(dataMax * 1.08),
                ]}
              />
              <Tooltip
                cursor={{ stroke: 'rgba(255,255,255,0.2)', strokeDasharray: '4 4' }}
                contentStyle={CHART_TOOLTIP_STYLE}
                labelFormatter={value => formatChartDate(value, { day: 'numeric', month: 'short', year: 'numeric' })}
                formatter={(value, name) => [
                  `${formatFullValue(value)} kWh`,
                  name === 'trend' ? `${trendWindow}-day trend` : 'Daily usage',
                ]}
              />
              <Area
                type="monotone"
                dataKey="kwh"
                name="kwh"
                stroke="var(--primary-bright)"
                strokeOpacity={0.2}
                strokeWidth={1.5}
                fill="url(#nrgGrad)"
                dot={false}
                activeDot={false}
                animationDuration={600}
              />
              <Line
                type="monotone"
                dataKey="trend"
                name="trend"
                stroke="var(--primary-dim)"
                strokeWidth={3}
                dot={false}
                activeDot={{ r: 5, strokeWidth: 0, fill: 'var(--primary-bright)' }}
                filter="url(#nrgGlow)"
                animationDuration={600}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        {/* Peak vs Off-Peak Pie */}
        <div className="chart-container">
          <div className="chart-title">⚡ Peak vs Off-Peak Energy Split</div>
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <PieChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={55} outerRadius={80} dataKey="value" paddingAngle={3} label={({ name, percent }) => `${(percent * 100).toFixed(0)}%`} labelLine={true} animationDuration={600}>
                  {pieData.map((entry, i) => (
                    <Cell key={i} fill={GRID_COLORS[entry.name] || 'var(--text-muted)'} />
                  ))}
                </Pie>
                <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={v => [v.toLocaleString(), 'kWh']} />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 10 }} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="empty-state"><div className="empty-state-desc">No grid period data available</div></div>
          )}
        </div>
      </div>

      {/* Per-Facility Penalties */}
      {facilities.length > 0 && (
        <div className="chart-container">
          <div className="chart-title">🏭 Carbon Penalty by Facility</div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={facilities} margin={{ top: 10, right: 20, left: 10, bottom: 30 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" strokeOpacity={0.8} />
              <XAxis dataKey="facility" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} tickLine={false} angle={-20} textAnchor="end" height={40} tickFormatter={v => v.split('(')[0].trim()} />
              <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} width={72} tickFormatter={v => `$${v.toLocaleString()}`} />
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={v => [`$${v.toLocaleString()}`, 'Penalty']} />
              <Bar dataKey="total_penalty" name="Carbon Penalty" fill="var(--red)" radius={[4, 4, 0, 0]} opacity={0.8} animationDuration={600} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Shift Suggestions */}
      {suggestions.length > 0 && (
        <div className="card">
          <div className="card-header"><div className="card-title">💡 Shift Scheduling Suggestions</div></div>
          {suggestions.map((s, i) => (
            <div key={i} className="stat-row">
              <span className="stat-row-label">{typeof s === 'string' ? `Suggestion ${i + 1}` : s.facility || `Suggestion ${i + 1}`}</span>
              <span className="stat-row-value" style={{ color: 'var(--cyan)', fontSize: 12 }}>
                {typeof s === 'string' ? s : s.current_shift || s.message || JSON.stringify(s)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
