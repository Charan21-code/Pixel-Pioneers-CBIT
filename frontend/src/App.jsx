import { useState, useEffect, useCallback } from 'react'
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom'
import {
  Factory, TrendingUp, Package, BarChart2, Wrench,
  DollarSign, Zap, Cpu, MessageSquare, GitBranch,
  RefreshCw, Activity, AlertTriangle
} from 'lucide-react'

import * as api from './api/client'
import CommandCenter        from './pages/CommandCenter'
import DemandIntelligence   from './pages/DemandIntelligence'
import HitlInbox            from './pages/HitlInbox'
import CarbonEnergy         from './pages/CarbonEnergy'
import InventoryLogistics   from './pages/InventoryLogistics'
import ProductionPlan       from './pages/ProductionPlan'
import MachineHealth        from './pages/MachineHealth'
import FinanceDashboard     from './pages/FinanceDashboard'
import NlpCommandPanel      from './pages/NlpCommandPanel'
import DigitalTwin          from './pages/DigitalTwin'

const NAV = [
  { path: '/',           label: 'Command Center',      Icon: Factory,       section: 'OVERVIEW' },
  { path: '/demand',     label: 'Demand Intelligence', Icon: TrendingUp,    section: 'ANALYTICS' },
  { path: '/inventory',  label: 'Inventory & Logistics', Icon: Package,     section: 'ANALYTICS' },
  { path: '/production', label: 'Production Plan',     Icon: BarChart2,     section: 'ANALYTICS' },
  { path: '/machines',   label: 'Machine Health & OEE', Icon: Wrench,       section: 'ANALYTICS' },
  { path: '/finance',    label: 'Finance Dashboard',   Icon: DollarSign,    section: 'ANALYTICS' },
  { path: '/carbon',     label: 'Carbon & Energy',     Icon: Zap,           section: 'ANALYTICS' },
  { path: '/twin',       label: 'Digital Twin',        Icon: Cpu,           section: 'SIMULATION' },
  { path: '/nlp',        label: 'NLP Command Panel',   Icon: MessageSquare, section: 'CONTROL' },
  { path: '/hitl',       label: 'HITL Inbox',          Icon: GitBranch,     section: 'CONTROL' },
]

function StatusDot({ status }) {
  const cls = status === 'ALL_OK' ? 'ok' : status === 'NEEDS_HITL' ? 'hitl' : status === 'BLOCKED' ? 'blocked' : 'unknown'
  return <span className={`status-dot ${cls}`} />
}

function Sidebar({ status, hitlCount, onRun, running }) {
  const location = useLocation()

  // Group nav items by section
  const sections = {}
  NAV.forEach(item => {
    if (!sections[item.section]) sections[item.section] = []
    sections[item.section].push(item)
  })

  return (
    <div className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-title">OPS//CORE</div>
        <div className="sidebar-brand-sub">Tactical Command v2.0</div>
      </div>

      <nav className="sidebar-nav">
        {Object.entries(sections).map(([section, items]) => (
          <div key={section}>
            <div className="sidebar-section-label">{section}</div>
            {items.map(({ path, label, Icon }) => {
              const isHitl = path === '/hitl'
              const isActive = path === '/'
                ? location.pathname === '/'
                : location.pathname.startsWith(path)
              return (
                <NavLink
                  key={path}
                  to={path}
                  className={`sidebar-link ${isActive ? 'active' : ''}`}
                  end={path === '/'}
                >
                  <Icon size={15} />
                  {label}
                  {isHitl && hitlCount > 0 && (
                    <span className="sidebar-badge">{hitlCount}</span>
                  )}
                </NavLink>
              )
            })}
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:10, fontSize:12 }}>
          <StatusDot status={status} />
          <span style={{ color:'var(--text-secondary)' }}>
            {status === 'ALL_OK' ? 'All Systems Go' : status === 'NEEDS_HITL' ? 'Needs Review' : status === 'BLOCKED' ? 'Blocked' : 'No Data'}
          </span>
        </div>
        <button
          className={`run-btn ${running ? 'running' : ''}`}
          onClick={onRun}
          disabled={running}
        >
          {running ? <><RefreshCw size={14} style={{ animation:'spin 0.7s linear infinite' }} /> Running...</> : <><Activity size={14} /> Run All Agents</>}
        </button>
      </div>
    </div>
  )
}

function Topbar({ title, status, health, lastRun }) {
  return (
    <div className="topbar">
      <div className="topbar-left">
        <span className="topbar-title">{title}</span>
      </div>
      <div className="topbar-right" style={{ fontSize:12, color:'var(--text-secondary)', gap:16, display:'flex', alignItems:'center' }}>
        {lastRun && <span>Updated: {new Date(lastRun).toLocaleTimeString()}</span>}
        {health != null && (
          <span style={{ color: health >= 70 ? 'var(--green)' : health >= 40 ? 'var(--amber)' : 'var(--red)', fontFamily:'var(--font-mono)', fontWeight:600 }}>
            ⬡ {health.toFixed(0)}/100
          </span>
        )}
        <AlertTriangle size={14} />
      </div>
    </div>
  )
}

const PAGE_TITLES = {
  '/':           'Command Center',
  '/demand':     'Demand Intelligence',
  '/inventory':  'Inventory & Logistics',
  '/production': 'Production Master Plan',
  '/machines':   'Machine Health & OEE',
  '/finance':    'Finance Dashboard',
  '/carbon':     'Carbon & Energy',
  '/twin':       'Digital Twin Simulation',
  '/nlp':        'NLP Command Panel',
  '/hitl':       'HITL Inbox',
}

const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms))

function AppInner() {
  const location = useLocation()
  const [systemStatus, setSystemStatus] = useState({ final_status: 'UNKNOWN', system_health: 0, last_run_at: null })
  const [hitlCount,    setHitlCount]    = useState(0)
  const [running,      setRunning]      = useState(false)

  const fetchStatus = useCallback(async () => {
    let statusData = null
    try {
      const s = await api.getSystemStatus()
      setSystemStatus(s)
      setRunning(s.is_running || false)
      statusData = s
    } catch (_) {}
    try {
      const c = await api.getHitlCounts()
      setHitlCount(c.total || 0)
    } catch (_) {}
    return statusData
  }, [])

  useEffect(() => {
    fetchStatus()
    const id = setInterval(fetchStatus, 15000)
    return () => clearInterval(id)
  }, [fetchStatus])

  const handleRun = async () => {
    if (running) return
    setRunning(true)
    try {
      await api.triggerOrchestrator()
    } catch (e) {
      if (!String(e?.message || '').toLowerCase().includes('already running')) {
        console.error('Orchestrator trigger failed:', e)
      }
    }

    try {
      for (let i = 0; i < 45; i++) {
        const status = await fetchStatus()
        if (i > 0 && status && !status.is_running) break
        await wait(1000)
      }
    } catch (e) {
      console.error('Status polling failed:', e)
    } finally {
      await fetchStatus()
    }
  }

  const title = PAGE_TITLES[location.pathname] || 'OPS//CORE'

  return (
    <div className="layout">
      <Sidebar
        status={systemStatus.final_status}
        hitlCount={hitlCount}
        onRun={handleRun}
        running={running}
      />
      <div className="main-content">
        <Topbar
          title={title}
          status={systemStatus.final_status}
          health={systemStatus.system_health}
          lastRun={systemStatus.last_run_at}
        />
        <div className="page-body">
          <Routes>
            <Route path="/"           element={<CommandCenter      onRunAgents={handleRun} running={running} />} />
            <Route path="/demand"     element={<DemandIntelligence />} />
            <Route path="/inventory"  element={<InventoryLogistics />} />
            <Route path="/production" element={<ProductionPlan     />} />
            <Route path="/machines"   element={<MachineHealth      />} />
            <Route path="/finance"    element={<FinanceDashboard   />} />
            <Route path="/carbon"     element={<CarbonEnergy       />} />
            <Route path="/twin"       element={<DigitalTwin        />} />
            <Route path="/nlp"        element={<NlpCommandPanel    />} />
            <Route path="/hitl"       element={<HitlInbox onCountChange={setHitlCount} />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppInner />
    </BrowserRouter>
  )
}
