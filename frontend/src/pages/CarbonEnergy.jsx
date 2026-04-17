import { useState, useEffect, useCallback } from 'react'
import { Zap, Leaf, AlertTriangle } from 'lucide-react'
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import * as api from '../api/client'

const GRID_COLORS = { Peak: '#FF1744', 'Off-Peak': '#00E676', peak: '#FF1744', off_peak: '#00E676' }

export default function CarbonEnergy() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try { setData(await api.getCarbon()) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="loading-overlay"><div className="spinner" /><span>Loading Carbon & Energy...</span></div>
  if (error)   return <div className="error-box">{error}</div>

  const compliant   = data?.compliance_flag ?? true
  const compColor   = compliant ? 'var(--green)' : 'var(--red)'
  const grid        = data?.grid_breakdown || {}
  const pieData     = Object.entries(grid).map(([k,v]) => ({ name: k, value: Number(v.toFixed(0)) }))
  const facilities  = data?.facility_penalties || []
  const energySeries = data?.energy_time_series || []
  const suggestions = data?.shift_suggestions || []

  return (
    <div>
      {/* Compliance Banner */}
      <div className={compliant ? 'status-banner ok' : 'status-banner blocked'} style={{ marginBottom:20 }}>
        <Leaf size={18} />
        {compliant
          ? '✅ CARBON COMPLIANT — Peak penalty ratio within acceptable thresholds'
          : '⚠️ NON-COMPLIANT — Peak hour penalty ratio exceeds threshold. Shift scheduling required'}
        <div className="banner-meta">
          <span>Status: <b style={{ color: compColor }}>{data?.compliance_status || (compliant ? 'COMPLIANT' : 'NON-COMPLIANT')}</b></span>
          <span>Savings: <b style={{ color:'var(--green)' }}>${(data?.estimated_savings_usd || 0).toLocaleString()}</b></span>
        </div>
      </div>

      {/* KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card" style={{ '--accent-color':'var(--green)' }}>
          <div className="kpi-label">Total Carbon</div>
          <div className="kpi-value" style={{ color:'var(--green)', fontSize:22 }}>{(data?.total_carbon_kg || 0).toLocaleString(undefined,{maximumFractionDigits:0})}</div>
          <div className="kpi-delta">kg CO₂ emitted</div>
          <Leaf size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--cyan)' }}>
          <div className="kpi-label">Total Energy</div>
          <div className="kpi-value" style={{ color:'var(--cyan)', fontSize:22 }}>{(data?.total_energy_kwh || 0).toLocaleString(undefined,{maximumFractionDigits:0})}</div>
          <div className="kpi-delta">kWh consumed</div>
          <Zap size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--red)' }}>
          <div className="kpi-label">Total Penalty</div>
          <div className="kpi-value" style={{ color:'var(--red)', fontSize:22 }}>${(data?.total_penalty_usd || 0).toLocaleString(undefined,{maximumFractionDigits:0})}</div>
          <div className="kpi-delta">USD carbon cost</div>
          <AlertTriangle size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--red)' }}>
          <div className="kpi-label">Peak Penalty</div>
          <div className="kpi-value" style={{ color:'var(--red)', fontSize:22 }}>${(data?.peak_penalty_usd || 0).toLocaleString(undefined,{maximumFractionDigits:0})}</div>
          <div className="kpi-delta">{(data?.peak_penalty_pct || 0).toFixed(1)}% of total</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--green)' }}>
          <div className="kpi-label">Off-Peak Penalty</div>
          <div className="kpi-value" style={{ color:'var(--green)', fontSize:22 }}>${(data?.off_peak_penalty_usd || 0).toLocaleString(undefined,{maximumFractionDigits:0})}</div>
          <div className="kpi-delta">off-peak hours</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--amber)' }}>
          <div className="kpi-label">Est. Savings</div>
          <div className="kpi-value" style={{ color:'var(--amber)', fontSize:22 }}>${(data?.estimated_savings_usd || 0).toLocaleString(undefined,{maximumFractionDigits:0})}</div>
          <div className="kpi-delta">by shifting to off-peak</div>
        </div>
      </div>

      {/* Agent Summary */}
      {data?.summary && <div className="info-box">🌱 <b>EnvironmentalistAgent:</b> {data.summary}</div>}

      <div className="two-col">
        {/* Energy Time Series */}
        <div className="chart-container">
          <div className="chart-title"><Zap size={14} /> Daily Energy Consumption (kWh)</div>
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={ts} margin={{ top:10, right:20, left:10, bottom:30 }}>
                <defs>
                  <linearGradient id="nrgGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#FFB300" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#FFB300" stopOpacity={0}    />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#253347" strokeOpacity={0.8} />
                <XAxis dataKey="date" tick={{ fontSize:10, fill:'var(--text-muted)', fontFamily:'monospace' }} tickLine={false} interval="preserveStartEnd" angle={-30} textAnchor="end" height={45} />
                <YAxis tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={72} tickFormatter={v => v.toLocaleString()} />
                <Tooltip contentStyle={{ background:'#111827', border:'1px solid #253347', borderRadius:8, fontSize:12, boxShadow:'0 8px 24px rgba(0,0,0,0.5)' }} formatter={v=>[v.toLocaleString(),'kWh']} />
                <Area type="monotone" dataKey="kwh" stroke="var(--amber)" strokeWidth={2} fill="url(#nrgGrad)" dot={false} animationDuration={600} />
              </AreaChart>
            </ResponsiveContainer>
        </div>

        {/* Peak vs Off-Peak Pie */}
        <div className="chart-container">
          <div className="chart-title">⚡ Peak vs Off-Peak Energy Split</div>
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie data={pieData} cx="50%" cy="45%" innerRadius={50} outerRadius={90} dataKey="value" paddingAngle={3} label={({ name, percent }) => `${(percent*100).toFixed(0)}%`} labelLine={true} animationDuration={600}>
                {pieData.map((entry,i) => (
                  <Cell key={i} fill={GRID_COLORS[entry.name] || '#888'} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background:'#111827', border:'1px solid #253347', borderRadius:8, fontSize:12, boxShadow:'0 8px 24px rgba(0,0,0,0.5)' }} formatter={v=>[v.toLocaleString(),'kWh']} />
              <Legend wrapperStyle={{ fontSize:11, paddingTop:8 }} />
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
              <BarChart data={facilities} margin={{ top:10, right:20, left:10, bottom:30 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#253347" strokeOpacity={0.8} />
                <XAxis dataKey="facility" tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} angle={-20} textAnchor="end" height={40} tickFormatter={v=>v.split('(')[0].trim()} />
                <YAxis tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={72} tickFormatter={v=>`$${v.toLocaleString()}`} />
                <Tooltip contentStyle={{ background:'#111827', border:'1px solid #253347', borderRadius:8, fontSize:12, boxShadow:'0 8px 24px rgba(0,0,0,0.5)' }} formatter={v=>[`$${v.toLocaleString()}`,'Penalty']} />
                <Bar dataKey="total_penalty" name="Carbon Penalty" fill="var(--red)" radius={[4,4,0,0]} opacity={0.8} animationDuration={600} />
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
              <span className="stat-row-label">{s.facility || `Suggestion ${i+1}`}</span>
              <span className="stat-row-value" style={{ color:'var(--cyan)', fontSize:12 }}>
                {s.current_shift || s.message || JSON.stringify(s)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
