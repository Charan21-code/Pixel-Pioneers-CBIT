import { useState, useEffect, useCallback } from 'react'
import { Cpu, Play, RefreshCw, AlertTriangle, TrendingDown, Zap } from 'lucide-react'
import {
  BarChart, Bar, LineChart, Line, AreaChart, Area,
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

export default function DigitalTwin() {
  const { uiConfig } = useUiConfig()
  const twinConfig = uiConfig.digital_twin || {}
  const rangeConfig = twinConfig.ranges || {}
  const optimiseOptions = twinConfig.optimise_options || ['Time', 'Cost', 'Carbon']
  const defaultParams = twinConfig.default_params || {
    oee_pct: 91,
    workforce_pct: 95,
    forecast_qty: 2000,
    energy_price: 0.12,
    downtime_hrs: 0,
    optimise_for: 'Time',
    horizon_days: 7,
    demand_buffer_pct: 0.10,
  }
  const [plants,    setPlants]    = useState([])
  const [selPlant,  setSelPlant]  = useState('')
  const [params,    setParams]    = useState({
    ...defaultParams,
    base_capacity:     null,
  })
  const [result,    setResult]    = useState(null)
  const [loading,   setLoading]   = useState(false)
  const [loadingDefaults, setLoadingDefaults] = useState(false)
  const [error,     setError]     = useState(null)

  // Load plants
  useEffect(() => {
    api.getPlants().then(d => {
      const pl = d.plants?.map(p=>p.name) || []
      setPlants(pl)
      if (pl.length > 0 && !selPlant) setSelPlant(pl[0])
    }).catch(()=>{})
  }, [])

  // Load defaults when plant changes
  const loadDefaults = useCallback(async (plant) => {
    if (!plant) return
    setLoadingDefaults(true)
    try {
      const defs = await api.getSimDefaults(plant)
      setParams(prev => ({ ...prev, ...defs, base_capacity: defs.base_capacity || null }))
    } catch (_) {}
    finally { setLoadingDefaults(false) }
  }, [])

  useEffect(() => { if (selPlant) loadDefaults(selPlant) }, [selPlant, loadDefaults])

  const handleRun = async () => {
    if (!selPlant) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.runSimulation({
        plant_id: selPlant,
        ...params,
        base_capacity: params.base_capacity || undefined,
      })
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const set = (key, val) => setParams(prev => ({ ...prev, [key]: val }))

  // Build chart data from result
  const chartData = result?.daily_breakdown?.map((units, i) => ({
    day:        `Day ${i+1}`,
    units,
    cumulative: result.cumulative_breakdown?.[i] || 0,
    cost:       result.daily_cost?.[i] || 0,
    carbon:     result.daily_carbon?.[i] || 0,
  })) || []

  const targetLine = result?.target_qty

  return (
    <div>
      <div className="two-col">
        {/* Controls */}
        <div>
          <div className="card">
            <div className="card-header">
              <div className="card-title"><Cpu size={15} /> Simulation Parameters</div>
              <div style={{ display:'flex', gap:8 }}>
                {loadingDefaults && <div className="spinner" style={{ width:16,height:16 }} />}
                <select
                  className="input"
                  style={{ width:200, fontSize:12 }}
                  value={selPlant}
                  onChange={e => setSelPlant(e.target.value)}
                >
                  {plants.map(p => <option key={p} value={p}>{p.split('(')[0].trim()}</option>)}
                </select>
              </div>
            </div>

            <div className="slider-container">
              <div className="slider-header">
                <span className="slider-label">OEE (%)</span>
                <span className="slider-value">{params.oee_pct}%</span>
              </div>
              <input type="range" min={rangeConfig.oee_pct?.min ?? 1} max={rangeConfig.oee_pct?.max ?? 100} step={rangeConfig.oee_pct?.step ?? 0.5} value={params.oee_pct}
                onChange={e => set('oee_pct', Number(e.target.value))} />
            </div>

            <div className="slider-container">
              <div className="slider-header">
                <span className="slider-label">Workforce (%)</span>
                <span className="slider-value">{params.workforce_pct}%</span>
              </div>
              <input type="range" min={rangeConfig.workforce_pct?.min ?? 1} max={rangeConfig.workforce_pct?.max ?? 100} step={rangeConfig.workforce_pct?.step ?? 0.5} value={params.workforce_pct}
                onChange={e => set('workforce_pct', Number(e.target.value))} />
            </div>

            <div className="slider-container">
              <div className="slider-header">
                <span className="slider-label">Downtime Day 1 (hrs)</span>
                <span className="slider-value">{params.downtime_hrs} hrs</span>
              </div>
              <input type="range" min={rangeConfig.downtime_hrs?.min ?? 0} max={rangeConfig.downtime_hrs?.max ?? 24} step={rangeConfig.downtime_hrs?.step ?? 0.5} value={params.downtime_hrs}
                onChange={e => set('downtime_hrs', Number(e.target.value))} />
            </div>

            <div className="slider-container">
              <div className="slider-header">
                <span className="slider-label">Energy Price ($/kWh)</span>
                <span className="slider-value">${params.energy_price}</span>
              </div>
              <input type="range" min={rangeConfig.energy_price?.min ?? 0.01} max={rangeConfig.energy_price?.max ?? 0.50} step={rangeConfig.energy_price?.step ?? 0.01} value={params.energy_price}
                onChange={e => set('energy_price', Number(e.target.value))} />
            </div>

            <div className="slider-container">
              <div className="slider-header">
                <span className="slider-label">Demand Buffer (%)</span>
                <span className="slider-value">{(params.demand_buffer_pct * 100).toFixed(0)}%</span>
              </div>
              <input type="range" min={rangeConfig.demand_buffer_pct?.min ?? 0} max={rangeConfig.demand_buffer_pct?.max ?? 0.30} step={rangeConfig.demand_buffer_pct?.step ?? 0.01} value={params.demand_buffer_pct}
                onChange={e => set('demand_buffer_pct', Number(e.target.value))} />
            </div>

            <div className="form-row" style={{ marginTop:12 }}>
              <div>
                <label className="form-label">Forecast Qty (units)</label>
                <input type="number" className="input" value={params.forecast_qty} min="0"
                  onChange={e => set('forecast_qty', Number(e.target.value))} />
              </div>
              <div>
                <label className="form-label">Horizon (days)</label>
                <input type="number" className="input" value={params.horizon_days} min={rangeConfig.horizon_days?.min ?? 1} max={rangeConfig.horizon_days?.max ?? 30} step={rangeConfig.horizon_days?.step ?? 1}
                  onChange={e => set('horizon_days', Number(e.target.value))} />
              </div>
            </div>

            <div style={{ marginBottom:16 }}>
              <label className="form-label">Optimise For</label>
              <div style={{ display:'flex', gap:8 }}>
                {optimiseOptions.map(opt => (
                  <button
                    key={opt}
                    className={`btn btn-sm ${params.optimise_for === opt ? 'btn-primary' : 'btn-ghost'}`}
                    onClick={() => set('optimise_for', opt)}
                  >
                    {opt === 'Time' ? '⚡' : opt === 'Cost' ? '💰' : '🌱'} {opt}
                  </button>
                ))}
              </div>
            </div>

            {error && <div className="error-box" style={{ marginBottom:12 }}>{error}</div>}

            <button className="btn btn-primary" style={{ width:'100%' }} onClick={handleRun} disabled={loading || !selPlant}>
              {loading ? <><div className="spinner" style={{ width:14,height:14,borderWidth:2 }} /> Simulating...</> : <><Play size={14} /> Run Simulation</>}
            </button>
          </div>
        </div>

        {/* Results */}
        <div>
          {result ? (
            <>
              {/* Warnings */}
              {result.warnings?.length > 0 && (
                <div className="warn-box">
                  {result.warnings.map((w,i) => <div key={i}>⚠️ {w}</div>)}
                </div>
              )}

              {/* KPI Result Cards */}
              <div className="twin-result-grid">
                <div className="twin-result-card">
                  <div className="twin-result-value">{result.expected_output_units?.toLocaleString()}</div>
                  <div className="twin-result-label">Units Produced</div>
                </div>
                <div className="twin-result-card">
                  <div className="twin-result-value" style={{ color: result.shortfall_units > 0 ? 'var(--red)' : 'var(--green)' }}>
                    {result.shortfall_units > 0 ? `-${result.shortfall_units?.toLocaleString()}` : `+${result.surplus_units?.toLocaleString()}`}
                  </div>
                  <div className="twin-result-label">{result.shortfall_units > 0 ? 'Shortfall' : 'Surplus'}</div>
                </div>
                <div className="twin-result-card">
                  <div className="twin-result-value">{result.target_qty?.toLocaleString()}</div>
                  <div className="twin-result-label">Target Qty</div>
                </div>
                <div className="twin-result-card">
                  <div className="twin-result-value" style={{ fontSize:16 }}>
                    Day {result.completion_day > result.parameters_used?.horizon_days ? 'N/A' : result.completion_day}
                  </div>
                  <div className="twin-result-label">Completion Day</div>
                </div>
                <div className="twin-result-card">
                  <div className="twin-result-value" style={{ fontSize:16 }}>${result.cost_usd?.toLocaleString(undefined,{maximumFractionDigits:0})}</div>
                  <div className="twin-result-label">Total Cost</div>
                </div>
                <div className="twin-result-card">
                  <div className="twin-result-value" style={{ fontSize:16, color:'var(--green)' }}>
                    {result.carbon_kg?.toLocaleString(undefined,{maximumFractionDigits:0})} kg
                  </div>
                  <div className="twin-result-label">CO₂ Emitted</div>
                </div>
                <div className="twin-result-card">
                  <div className="twin-result-value">{result.workforce_needed}</div>
                  <div className="twin-result-label">Workers Needed</div>
                </div>
                <div className="twin-result-card">
                  <div className="twin-result-value" style={{ color:'var(--cyan)', fontSize:14 }}>
                    {result.parameters_used?.optimise_for}
                  </div>
                  <div className="twin-result-label">Optimised For</div>
                </div>
              </div>

              {/* Suggestions */}
              {result.optimise_suggestions?.length > 0 && (
                <div className="card">
                  <div className="card-header"><div className="card-title">💡 Optimisation Suggestions</div></div>
                  {result.optimise_suggestions.map((s, i) => (
                    <div key={i} className="stat-row">
                      <span className="stat-row-label" style={{ fontSize:12, lineHeight:1.5 }}>{s}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="empty-state" style={{ height:300 }}>
              <div className="empty-state-icon"><Cpu size={40} /></div>
              <div className="empty-state-title">Digital Twin Ready</div>
              <div className="empty-state-desc">Configure parameters and click <b>Run Simulation</b> to generate a {params.horizon_days}-day production forecast for the selected plant.</div>
            </div>
          )}
        </div>
      </div>
      {/* Charts */}
      {result && chartData.length > 0 && (
        <>
          <div className="chart-container">
            <div className="chart-title">📈 Daily & Cumulative Production Output</div>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={chartData} margin={{ top:10, right:20, left:10, bottom:30 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" strokeOpacity={0.8} />
                <XAxis dataKey="day" tick={{ fontSize:10, fill:'var(--text-muted)', fontFamily:'monospace' }} tickLine={false} angle={-30} textAnchor="end" height={45} interval="preserveStartEnd" />
                <YAxis yAxisId="left" tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={80} tickFormatter={v=>v.toLocaleString()} />
                <YAxis yAxisId="right" orientation="right" tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={80} tickFormatter={v=>v.toLocaleString()} />
                <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                <Legend wrapperStyle={{ fontSize:11, paddingTop:8 }} />
                <Bar yAxisId="left" dataKey="units" name="Daily Output" fill="var(--cyan)" radius={[4,4,0,0]} opacity={0.8} animationDuration={600} />
                <Line yAxisId="right" type="monotone" dataKey="cumulative" name="Cumulative Output" stroke="var(--purple)" strokeWidth={2} dot={false} animationDuration={600} />
                {targetLine && <ReferenceLine yAxisId="right" y={targetLine} stroke="var(--amber)" strokeDasharray="4 2" label={{ value:'Total Demand Target', position:'insideBottomLeft', fill:'var(--amber)', fontSize:11 }} />}
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="two-col">
            <div className="chart-container" style={{ marginBottom:0 }}>
              <div className="chart-title"><Zap size={14} /> Daily Cost ($)</div>
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={chartData} margin={{ top:10, right:20, left:10, bottom:30 }}>
                  <defs>
                  <linearGradient id="costGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--tertiary)" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="var(--tertiary)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" strokeOpacity={0.8} />
                  <XAxis dataKey="day" tick={{ fontSize:10, fill:'var(--text-muted)', fontFamily:'monospace' }} tickLine={false} angle={-30} textAnchor="end" height={45} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={80} tickFormatter={v=>`$${(v/1000).toFixed(0)}k`} />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={v=>[`$${v.toLocaleString()}`,'Cost']} />
                  <Area type="monotone" dataKey="cost" stroke="var(--green)" strokeWidth={2} fill="url(#costGrad)" dot={false} animationDuration={600} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            <div className="chart-container" style={{ marginBottom:0 }}>
              <div className="chart-title">🌱 Daily CO₂ Emissions (kg)</div>
              <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={chartData} margin={{ top:10, right:20, left:10, bottom:30 }}>
                <defs>
                  <linearGradient id="co2Grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--tertiary)" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="var(--tertiary)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" strokeOpacity={0.8} />
                <XAxis dataKey="day" tick={{ fontSize:10, fill:'var(--text-muted)', fontFamily:'monospace' }} tickLine={false} angle={-30} textAnchor="end" height={45} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize:10, fill:'var(--text-muted)' }} tickLine={false} axisLine={false} width={80} tickFormatter={v=>`${(v/1000).toFixed(0)}k`} />
                <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={v=>[`${v.toLocaleString()}kg`,'Carbon']} />
                <Area type="monotone" dataKey="carbon" stroke="var(--green)" strokeWidth={2} fill="url(#co2Grad)" dot={false} animationDuration={600} />
              </AreaChart>
            </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
