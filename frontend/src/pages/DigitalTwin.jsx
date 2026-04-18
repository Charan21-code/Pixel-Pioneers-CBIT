import { useState, useEffect, useCallback } from 'react'
import {
  Cpu, Play, Loader2,
} from 'lucide-react'
import {
  BarChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import * as api from '../api/client'
import { useUiConfig } from '../ui-config'
import './DigitalTwin.css'

const TT = {
  background: 'var(--bg-card)',
  border: '1px solid rgba(240,238,232,0.1)',
  borderRadius: 10,
  fontSize: 11,
  boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
}

/* ── Single field slider ────────────────────────────────────────────────── */
function Slider({ label, value, onChange, min, max, step, format }) {
  return (
    <div className="dt-slider-row">
      <div className="dt-slider-top">
        <span className="dt-slider-label">{label}</span>
        <span className="dt-slider-val">{format ? format(value) : value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))} />
    </div>
  )
}

/* ── Main Page ──────────────────────────────────────────────────────────── */
export default function DigitalTwin() {
  const { uiConfig } = useUiConfig()
  const twinConfig    = uiConfig.digital_twin || {}
  const rangeConfig   = twinConfig.ranges || {}
  const defaultParams = twinConfig.default_params || {
    oee_pct: 91, workforce_pct: 95, forecast_qty: 2000,
    energy_price: 0.12, downtime_hrs: 0, optimise_for: 'Time',
    horizon_days: 7, demand_buffer_pct: 0.10,
  }

  const [plants,     setPlants]     = useState([])
  const [selPlant,   setSelPlant]   = useState('')

  // Single scenario state
  const [sParams,    setSParams]    = useState({ ...defaultParams, base_capacity: null })
  const [sResult,    setSResult]    = useState(null)
  const [sLoading,   setSLoading]   = useState(false)
  const [sError,     setSError]     = useState(null)

  const [loadingDefaults, setLoadingDefaults] = useState(false)

  // Load plants
  useEffect(() => {
    api.getPlants().then(d => {
      const pl = d.plants?.map(p => p.name) || []
      setPlants(pl)
      if (pl.length && !selPlant) setSelPlant(pl[0])
    }).catch(() => {})
  }, [])

  // Load defaults when plant changes
  const loadAll = useCallback(async (plant) => {
    if (!plant) return
    setLoadingDefaults(true)
    try {
      const defs = await api.getSimDefaults(plant)
      setSParams(prev => ({ ...prev, ...defs, base_capacity: defs.base_capacity || null }))
    } catch (_) {}
    finally { setLoadingDefaults(false) }
  }, [])

  useEffect(() => { if (selPlant) loadAll(selPlant) }, [selPlant, loadAll])

  // ── Single run ─────────────────────────────────────────────────────────────
  const runSingle = async () => {
    if (!selPlant) return
    setSLoading(true); setSError(null)
    try {
      const r = await api.runSimulation({ plant_id: selPlant, ...sParams, base_capacity: sParams.base_capacity || undefined })
      setSResult(r)
    } catch (e) { setSError(e.message) }
    finally { setSLoading(false) }
  }

  // ── Single chart data ──────────────────────────────────────────────────────
  const sChartData = sResult?.daily_breakdown?.map((units, i) => ({
    day: `D${i+1}`, units,
    cumulative: sResult.cumulative_breakdown?.[i] || 0,
    cost: sResult.daily_cost?.[i] || 0,
    carbon: sResult.daily_carbon?.[i] || 0,
  })) || []

  return (
    <div className="dt-page">

      {/* ── Header ── */}
      <div className="dt-header">
        <div>
          <h1 className="dt-title">⬡ Digital Twin</h1>
          <p className="dt-subtitle">Simulation Engine</p>
        </div>
        <div className="dt-header-right">
          <select className="input" style={{ width: 220, fontSize: 12 }}
            value={selPlant} onChange={e => setSelPlant(e.target.value)}>
            {plants.map(p => <option key={p} value={p}>{p.split('(')[0].trim()}</option>)}
          </select>
          {loadingDefaults && <Loader2 size={14} className="dt-spin" style={{ color: 'var(--text-muted)' }}/>}
        </div>
      </div>

      <div className="dt-two-col">
        <div className="card">
          <div className="card-header">
            <div className="card-title"><Cpu size={14}/> Parameters</div>
          </div>
          <Slider label="OEE (%)" value={sParams.oee_pct} min={rangeConfig.oee_pct?.min??1} max={rangeConfig.oee_pct?.max??100} step={0.5}
            onChange={v => setSParams(p => ({...p, oee_pct:v}))} />
          <Slider label="Workforce (%)" value={sParams.workforce_pct} min={rangeConfig.workforce_pct?.min??1} max={100} step={0.5}
            onChange={v => setSParams(p => ({...p, workforce_pct:v}))} />
          <Slider label="Downtime Day 1 (hrs)" value={sParams.downtime_hrs} min={0} max={24} step={0.5}
            onChange={v => setSParams(p => ({...p, downtime_hrs:v}))} />
          <Slider label="Energy Price ($/kWh)" value={sParams.energy_price} min={0.01} max={0.50} step={0.01}
            format={v => `$${v}`}
            onChange={v => setSParams(p => ({...p, energy_price:v}))} />
          <Slider label="Demand Buffer (%)" value={sParams.demand_buffer_pct} min={0} max={0.30} step={0.01}
            format={v => `${(v*100).toFixed(0)}%`}
            onChange={v => setSParams(p => ({...p, demand_buffer_pct:v}))} />
          <div className="form-row" style={{ marginTop:12 }}>
            <div>
              <label className="form-label">Forecast Qty</label>
              <input type="number" className="input" value={sParams.forecast_qty} min="0"
                onChange={e => setSParams(p => ({...p, forecast_qty:Number(e.target.value)}))} />
            </div>
            <div>
              <label className="form-label">Horizon (days)</label>
              <input type="number" className="input" value={sParams.horizon_days} min={1} max={30}
                onChange={e => setSParams(p => ({...p, horizon_days:Number(e.target.value)}))} />
            </div>
          </div>
          <div style={{ marginBottom:16 }}>
            <label className="form-label">Optimise For</label>
            <div style={{ display:'flex', gap:8 }}>
              {['Time','Cost','Carbon'].map(o => (
                <button key={o} className={`btn btn-sm ${sParams.optimise_for===o?'btn-primary':'btn-ghost'}`}
                  onClick={() => setSParams(p => ({...p, optimise_for:o}))}>
                  {o==='Time'?'⚡':o==='Cost'?'💰':'🌱'} {o}
                </button>
              ))}
            </div>
          </div>
          {sError && <div className="error-box" style={{ marginBottom:10 }}>{sError}</div>}
          <button className="btn btn-primary" style={{ width:'100%' }} onClick={runSingle} disabled={sLoading||!selPlant}>
            {sLoading ? <><Loader2 size={14} className="dt-spin"/>Simulating…</> : <><Play size={14}/>Run Simulation</>}
          </button>
        </div>

        <div>
          {sResult ? (
            <>
              {sResult.warnings?.length > 0 && (
                <div className="warn-box" style={{ marginBottom:12 }}>
                  {sResult.warnings.map((w,i) => <div key={i}>⚠️ {w}</div>)}
                </div>
              )}
              <div className="twin-result-grid">
                {[
                  ['expected_output_units','Units Produced', v => v?.toLocaleString(), null],
                  ['shortfall_units','Shortfall/Surplus', (v,r) => r.shortfall_units>0?`-${r.shortfall_units?.toLocaleString()}`:`+${r.surplus_units?.toLocaleString()}`, r=>r.shortfall_units>0?'var(--red)':'var(--green)'],
                  ['target_qty','Target Qty', v=>v?.toLocaleString(), null],
                  ['completion_day','Completion Day', (v,r)=>`Day ${v>r.parameters_used?.horizon_days?'N/A':v}`, null],
                  ['cost_usd','Total Cost', v=>`$${v?.toLocaleString(undefined,{maximumFractionDigits:0})}`, null],
                  ['carbon_kg','CO₂ Emitted', v=>`${v?.toLocaleString(undefined,{maximumFractionDigits:0})} kg`, 'var(--green)'],
                  ['utilisation_pct','Utilisation', v=>`${v?.toFixed(1)}%`, null],
                ].map(([key,label,fmt,color]) => (
                  <div key={key} className="twin-result-card">
                    <div className="twin-result-value" style={{ color: typeof color === 'function' ? color(sResult) : color, fontSize: key==='completion_day'?16:undefined }}>
                      {fmt(sResult[key], sResult)}
                    </div>
                    <div className="twin-result-label">{label}</div>
                  </div>
                ))}
              </div>
              {sResult.optimise_suggestions?.length>0 && (
                <div className="card">
                  <div className="card-header"><div className="card-title">💡 Optimisation Suggestions</div></div>
                  {sResult.optimise_suggestions.map((s,i) => (
                    <div key={i} className="stat-row"><span style={{ fontSize:12, lineHeight:1.5 }}>{s}</span></div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="empty-state" style={{ height:300 }}>
              <div className="empty-state-icon"><Cpu size={40}/></div>
              <div className="empty-state-title">Digital Twin Ready</div>
              <div className="empty-state-desc">Configure parameters and click Run Simulation.</div>
            </div>
          )}
        </div>
      </div>

      {sResult && sChartData.length > 0 && (
        <div className="chart-container" style={{ marginTop:20 }}>
          <div className="chart-title">📈 Daily Production Output</div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={sChartData} margin={{ top:10, right:20, left:10, bottom:30 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" strokeOpacity={0.8}/>
              <XAxis dataKey="day" tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false}/>
              <YAxis yAxisId="l" tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={70} tickFormatter={v=>v.toLocaleString()}/>
              <YAxis yAxisId="r" orientation="right" tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={70} tickFormatter={v=>v.toLocaleString()}/>
              <Tooltip contentStyle={TT}/>
              <Legend wrapperStyle={{ fontSize:11 }}/>
              <Bar yAxisId="l" dataKey="units" name="Daily Output" fill="var(--primary)" radius={[4,4,0,0]} opacity={0.85}/>
              <Line yAxisId="r" type="monotone" dataKey="cumulative" name="Cumulative" stroke="var(--tertiary)" strokeWidth={2} dot={false}/>
              {sResult.target_qty && <ReferenceLine yAxisId="r" y={sResult.target_qty} stroke="var(--red)" strokeDasharray="4 2" label={{ value:'Target', position:'insideBottomLeft', fill:'var(--red)', fontSize:10 }}/>}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
