import { useState, useEffect, useCallback } from 'react'
import { Package, AlertTriangle, TrendingDown } from 'lucide-react'
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import * as api from '../api/client'

const STATUS_COLOR = {
  healthy:   'var(--green)',
  low:       'var(--amber)',
  critical:  'var(--red)',
  emergency: 'var(--red)',
}

const STATUS_BADGE = {
  healthy:   'badge-ok',
  low:       'badge-warning',
  critical:  'badge-critical',
  emergency: 'badge-critical',
}

function InventoryCard({ plant, inv }) {
  const color  = STATUS_COLOR[inv.status] || 'var(--text-muted)'
  const pct    = inv.inventory_threshold > 0
    ? Math.min(100, (inv.current_stock / inv.inventory_threshold) * 100)
    : 0
  const fillColor = pct > 80 ? 'var(--green)' : pct > 40 ? 'var(--amber)' : 'var(--red)'

  return (
    <div className="card" style={{ borderTopColor: color, borderTop: `3px solid ${color}` }}>
      <div className="card-header">
        <div>
          <div className="card-title">🏭 {plant.split('(')[0].trim()}</div>
          <div className="card-subtitle">{plant}</div>
        </div>
        <span className={`badge ${STATUS_BADGE[inv.status] || 'badge-info'}`}>{inv.status?.toUpperCase()}</span>
      </div>

      {/* Stock progress */}
      <div style={{ marginBottom:14 }}>
        <div style={{ display:'flex', justifyContent:'space-between', fontSize:11, color:'var(--text-muted)', marginBottom:5 }}>
          <span>Current Stock vs Threshold</span>
          <span style={{ fontFamily:'var(--font-mono)', color:'var(--text-primary)' }}>{pct.toFixed(0)}%</span>
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width:`${pct}%`, '--fill-color': fillColor }} />
        </div>
      </div>

      <div className="stat-row">
        <span className="stat-row-label">Current Stock</span>
        <span className="stat-row-value">{inv.current_stock?.toLocaleString()} units</span>
      </div>
      <div className="stat-row">
        <span className="stat-row-label">Safety Level</span>
        <span className="stat-row-value">{inv.safety_level?.toLocaleString()} units</span>
      </div>
      <div className="stat-row">
        <span className="stat-row-label">Daily Usage</span>
        <span className="stat-row-value">{inv.daily_use?.toLocaleString()} units/day</span>
      </div>
      <div className="stat-row">
        <span className="stat-row-label">Days Remaining</span>
        <span className="stat-row-value" style={{ color }}>
          {inv.days_remaining?.toFixed(1)} days
        </span>
      </div>
      <div className="stat-row">
        <span className="stat-row-label">Lead Time</span>
        <span className="stat-row-value">{inv.lead_days} days</span>
      </div>
      <div className="stat-row">
        <span className="stat-row-label">Reorder Qty</span>
        <span className="stat-row-value">{inv.reorder_qty?.toLocaleString()} units</span>
      </div>
      <div className="stat-row">
        <span className="stat-row-label">Est. Reorder Cost</span>
        <span className="stat-row-value" style={{ color:'var(--amber)' }}>
          ${inv.cost_usd?.toLocaleString(undefined,{maximumFractionDigits:0})}
        </span>
      </div>
    </div>
  )
}

export default function InventoryLogistics() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try { setData(await api.getInventory()) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="loading-overlay"><div className="spinner" /><span>Loading Inventory & Logistics...</span></div>
  if (error)   return <div className="error-box">{error}</div>

  const inv      = data?.buyer_inventory || {}
  const reorders = data?.reorders        || []
  const rawQuotes = data?.quote_time_series || []
  const plants   = Object.keys(inv)

  // Downsample daily quotes → weekly averages to eliminate chart noise
  const quotes = (() => {
    if (rawQuotes.length === 0) return []
    const buckets = {}
    rawQuotes.forEach(({ date, quote }) => {
      // All dates within the same ISO week collapse to the Monday of that week
      const d = new Date(date)
      const dow = d.getDay() // 0=Sun..6=Sat
      const monday = new Date(d)
      monday.setDate(d.getDate() - ((dow + 6) % 7)) // shift to Monday
      const key = monday.toISOString().slice(0, 10)
      if (!buckets[key]) buckets[key] = { sum: 0, count: 0 }
      buckets[key].sum   += quote
      buckets[key].count += 1
    })
    return Object.entries(buckets)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, { sum, count }]) => ({ date, quote: sum / count }))
  })()
  const allStatuses = plants.map(p => inv[p].status)
  const critCount   = allStatuses.filter(s => s === 'critical' || s === 'emergency').length

  // Build bar chart data
  const barData = plants.map(p => ({
    plant: p.split('(')[0].trim(),
    stock: inv[p].current_stock,
    threshold: inv[p].inventory_threshold,
    days: inv[p].days_remaining,
  }))

  return (
    <div>
      {/* KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card" style={{ '--accent-color':'var(--cyan)' }}>
          <div className="kpi-label">Facilities Checked</div>
          <div className="kpi-value">{data?.facilities_checked || plants.length}</div>
          <div className="kpi-delta">total plants monitored</div>
          <Package size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color': critCount > 0 ? 'var(--red)' : 'var(--green)' }}>
          <div className="kpi-label">Critical/Emergency</div>
          <div className="kpi-value" style={{ color: critCount > 0 ? 'var(--red)' : 'var(--green)' }}>{critCount}</div>
          <div className="kpi-delta">plants below safety level</div>
          <AlertTriangle size={22} className="kpi-icon" />
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--amber)' }}>
          <div className="kpi-label">Reorders Triggered</div>
          <div className="kpi-value" style={{ color:'var(--amber)' }}>{data?.reorders_triggered || reorders.length}</div>
          <div className="kpi-delta">purchase orders raised</div>
        </div>
        <div className="kpi-card" style={{ '--accent-color':'var(--purple)' }}>
          <div className="kpi-label">Total PO Spend</div>
          <div className="kpi-value" style={{ color:'var(--purple)', fontSize:20 }}>
            ${(data?.total_spend_requested || 0).toLocaleString(undefined,{maximumFractionDigits:0})}
          </div>
          <div className="kpi-delta">requested this cycle</div>
        </div>
      </div>

      {/* Inventory by plant bar chart */}
      {barData.length > 0 && (
        <div className="chart-container">
          <div className="chart-title">📊 Inventory Stock vs Threshold by Plant</div>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={barData} margin={{ top:10, right:20, left:10, bottom:30 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#253347" strokeOpacity={0.8} />
              <XAxis dataKey="plant" tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} angle={-20} textAnchor="end" height={40} />
              <YAxis tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={80} tickFormatter={v => v.toLocaleString()} />
              <Tooltip contentStyle={{ background:'#111827', border:'1px solid #253347', borderRadius:8, fontSize:12, boxShadow:'0 8px 24px rgba(0,0,0,0.5)' }} formatter={v=>[v.toLocaleString(),'units']} />
              <Legend wrapperStyle={{ fontSize:11, paddingTop:8 }} />
              <Bar dataKey="stock" name="Current Stock" fill="var(--cyan)" radius={[4,4,0,0]} animationDuration={600} />
              <Bar dataKey="threshold" name="Safety Threshold" fill="#2A3A52" stroke="#3A4E6A" strokeWidth={1} radius={[4,4,0,0]} animationDuration={600} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="two-col">
        {/* Supplier Quotes */}
        {quotes.length > 0 && (
          <div className="chart-container" style={{ marginBottom:0 }}>
            <div className="chart-title">💰 Live Supplier Quote Trend (USD/unit)</div>
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={quotes} margin={{ top:10, right:20, left:10, bottom:30 }}>
                <defs>
                  <linearGradient id="quoteGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#7C3AED" stopOpacity={0.45} />
                    <stop offset="95%" stopColor="#7C3AED" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#253347" strokeOpacity={0.6} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize:9, fill:'var(--text-muted)', fontFamily:'monospace' }}
                  tickLine={false}
                  interval={Math.max(0, Math.floor(quotes.length / 8) - 1)}
                  angle={-30}
                  textAnchor="end"
                  height={45}
                />
                <YAxis
                  tick={{ fontSize:10, fill:'var(--text-muted)' }}
                  tickLine={false}
                  axisLine={false}
                  width={60}
                  tickFormatter={v => `$${v.toFixed(2)}`}
                />
                <Tooltip
                  contentStyle={{ background:'#111827', border:'1px solid #253347', borderRadius:8, fontSize:12, boxShadow:'0 8px 24px rgba(0,0,0,0.5)' }}
                  formatter={v => [`$${v.toFixed(4)}`, 'Avg Quote (USD/unit)']}
                  labelFormatter={label => `Week of ${label}`}
                />
                <Area
                  type="monotoneX"
                  dataKey="quote"
                  stroke="#7C3AED"
                  strokeWidth={2.5}
                  fill="url(#quoteGrad)"
                  dot={false}
                  activeDot={{ r: 4, fill: '#7C3AED', strokeWidth: 0 }}
                  animationDuration={800}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Reorder Table */}
        <div className="card" style={{ marginBottom:0 }}>
          <div className="card-header">
            <div className="card-title">🛒 Active Reorder Events ({reorders.length})</div>
          </div>
          {reorders.length > 0 ? (
            <div style={{ overflowX:'auto' }}>
              <table className="data-table">
                <thead><tr>
                  <th>Facility</th><th>Qty</th><th>Cost</th><th>Decision</th>
                </tr></thead>
                <tbody>
                  {reorders.slice(0,10).map((r, i) => {
                    const dec = r.clearance_decision || 'pending'
                    const decColor = dec === 'auto_approve' ? 'var(--green)' : dec === 'hitl_escalate' ? 'var(--red)' : 'var(--amber)'
                    return (
                      <tr key={i}>
                        <td>{String(r.facility || '—').split('(')[0].trim()}</td>
                        <td className="mono">{Number(r.reorder_qty || 0).toLocaleString()}</td>
                        <td className="mono">${Number(r.cost_usd || 0).toLocaleString(undefined,{maximumFractionDigits:0})}</td>
                        <td><span style={{ fontSize:11, color: decColor, fontWeight:600 }}>{dec.replace(/_/g,' ').toUpperCase()}</span></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state" style={{ padding:'24px' }}>
              <div className="empty-state-desc">No reorders triggered yet.</div>
            </div>
          )}
        </div>
      </div>

      {/* Per-Plant Inventory Cards */}
      <div className="section-title" style={{ marginTop:20 }}>📦 Per-Plant Inventory Detail</div>
      <div className="three-col">
        {plants.map(p => <InventoryCard key={p} plant={p} inv={inv[p]} />)}
      </div>
    </div>
  )
}
