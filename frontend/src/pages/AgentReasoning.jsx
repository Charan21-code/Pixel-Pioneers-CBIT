import { useEffect, useRef, useState, useCallback } from 'react'
import {
  Brain, Cpu, ShoppingCart, Leaf, DollarSign, Calendar,
  GitBranch, CheckCircle, Loader2, Clock, AlertTriangle,
  ChevronRight, Zap, TrendingUp, X, Bell, RefreshCw
} from 'lucide-react'
import * as api from '../api/client'
import './AgentReasoning.css'

/* ── Agent metadata ─────────────────────────────────────────────────────── */
// Hub-and-spoke layout — Finance is the central hub.
// Positions are expressed as percentages [cx%, cy%] of the SVG canvas.
// Top arc: Forecaster (left), Mechanic (center), Buyer (right)
// Middle: Environmentalist (left), Finance (CENTER), Scheduler (right)
// Bottom: Orchestrator (center below Finance)
// px = horizontal centre as % of container width
// py = vertical   centre as % of container height
// Safe insets: cards are 192px wide × up to 170px tall.
// At container ≈ 860px wide  × 560px tall:
//   left col  centre  ≈ 160px  → right edge = 256px  ✓
//   right col centre  ≈ 700px  → right edge = 796px  ✓
//   top row   centre  ≈  84px  → top  edge  =  -1px  ✓
//   mid row   centre  ≈ 280px  → bottom     = 367px  ✓
//   orch      centre  ≈ 476px  → bottom     = 563px  ✓
const AGENTS = [
  { id: 'Forecaster', label: 'Forecaster', subtitle: 'Demand Intelligence', Icon: Brain, color: 'var(--cyan)', glow: 'var(--cyan-glow)', px: 18.5, py: 15 },
  { id: 'Mechanic', label: 'Mechanic', subtitle: 'Machine Health', Icon: Cpu, color: 'var(--amber)', glow: 'var(--amber-glow)', px: 50, py: 15 },
  { id: 'Buyer', label: 'Buyer', subtitle: 'Procurement', Icon: ShoppingCart, color: 'var(--green)', glow: 'var(--green-glow)', px: 81.5, py: 15 },
  { id: 'Environmentalist', label: 'Environmentalist', subtitle: 'Carbon & Energy', Icon: Leaf, color: 'var(--green)', glow: 'var(--green-glow)', px: 18.5, py: 60 },
  { id: 'Finance', label: 'Finance', subtitle: 'Budget Gate', Icon: DollarSign, color: 'var(--amber)', glow: 'var(--amber-glow)', px: 50, py: 55 },
  { id: 'Scheduler', label: 'Scheduler', subtitle: 'Production Planning', Icon: Calendar, color: 'var(--purple)', glow: 'var(--purple-glow)', px: 81.5, py: 60 },
  { id: 'Orchestrator', label: 'Orchestrator', subtitle: 'System Supervisor', Icon: GitBranch, color: 'var(--red)', glow: 'var(--red-glow)', px: 50, py: 85 },
]

// Connections between agents by id
const CONNECTIONS = [
  ['Forecaster', 'Mechanic'],        // top-row horizontal
  ['Mechanic', 'Buyer'],           // top-row horizontal
  ['Forecaster', 'Environmentalist'],// Forecaster  → Environ
  ['Mechanic', 'Finance'],         // Mechanic    → Finance
  ['Buyer', 'Scheduler'],       // Buyer       → Scheduler
  ['Environmentalist', 'Finance'],         // Environ     → Finance
  ['Buyer', 'Finance'],         // Buyer       → Finance (clearance)
  ['Finance', 'Scheduler'],       // Finance     → Scheduler
  ['Finance', 'Orchestrator'],    // Finance     → Orchestrator
  ['Scheduler', 'Orchestrator'],    // Scheduler   → Orchestrator
]

/* ── Msg type config ─────────────────────────────────────────────────────── */
const MSG_CFG = {
  blocker: { label: 'BLOCKER', color: 'var(--red)', bg: 'rgba(239,68,68,0.08)', icon: AlertTriangle },
  proposal: { label: 'PROPOSAL', color: 'var(--amber)', bg: 'rgba(251,191,36,0.08)', icon: TrendingUp },
  eval: { label: 'EVAL', color: 'var(--cyan)', bg: 'rgba(34,211,238,0.08)', icon: Zap },
  consensus: { label: 'CONSENSUS', color: 'var(--green)', bg: 'rgba(34,197,94,0.08)', icon: CheckCircle },
  escalate: { label: 'ESCALATED', color: 'var(--purple)', bg: 'rgba(168,85,247,0.08)', icon: GitBranch },
}

/* ── Node card dimensions ────────────────────────────────────────────────── */
const NODE_W = 192  // card width  (must match CSS .rp-node width)
const NODE_H = 130  // card height (must match CSS .rp-node min-height)

/* ── Agent Node ──────────────────────────────────────────────────────────── */
function AgentNode({ agent, state, lastThought, hasBlocker }) {
  const { label, subtitle, Icon, color, glow } = agent
  const isActive = state === 'thinking'
  const isDone = state === 'done'

  return (
    <div
      className={`rp-node ${isActive ? 'rp-node--active' : ''} ${isDone ? 'rp-node--done' : ''} ${hasBlocker ? 'rp-node--blocked' : ''}`}
      style={{ '--node-color': color, '--node-glow': glow }}
    >
      {isActive && <div className="rp-node-ring" />}
      {hasBlocker && <div className="rp-node-blocker-badge">⚡ BLOCKED</div>}

      <div className="rp-node-icon-wrap">
        <Icon size={20} style={{ color }} />
        {isActive && <Loader2 size={12} className="rp-spin" style={{ color, marginLeft: 4 }} />}
        {isDone && <CheckCircle size={12} style={{ color: 'var(--green)', marginLeft: 4 }} />}
        {!isActive && !isDone && <Clock size={12} style={{ color: 'var(--text-muted)', marginLeft: 4 }} />}
      </div>

      <div className="rp-node-label">{label}</div>
      <div className="rp-node-sub">{subtitle}</div>

      <div className={`rp-node-badge ${isActive ? 'active' : isDone ? 'done' : 'idle'}`}>
        {isActive ? 'THINKING' : isDone ? 'DONE' : 'IDLE'}
      </div>

      {lastThought && (
        <div className="rp-node-thought">
          {lastThought.slice(0, 80)}{lastThought.length > 80 ? '…' : ''}
          {isActive && <span className="rp-cursor">▋</span>}
        </div>
      )}
    </div>
  )
}

/* ── SVG Connector ───────────────────────────────────────────────────────── */
// x1,y1,x2,y2 are already in SVG px coords (derived from % × container dims)
function Connector({ x1, y1, x2, y2, active, blocked }) {
  const mx = (x1 + x2) / 2

  const stroke = blocked ? 'var(--red)' : active ? 'var(--primary)' : 'var(--border)'
  const width = (active || blocked) ? 2.5 : 1.5
  const dash = (active || blocked) ? '6 4' : '4 4'

  return (
    <path
      d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
      fill="none"
      stroke={stroke}
      strokeWidth={width}
      strokeDasharray={dash}
      style={(active || blocked) ? { animation: 'dash-flow 1s linear infinite' } : {}}
      markerEnd="url(#arrow)"
    />
  )
}

/* ── Coordination Message Card ───────────────────────────────────────────── */
function CoordCard({ msg, onClick }) {
  const cfg = MSG_CFG[msg.msg_type] || MSG_CFG.blocker
  const Icon = cfg.icon
  const payload = typeof msg.payload === 'string'
    ? (() => { try { return JSON.parse(msg.payload) } catch { return {} } })()
    : (msg.payload || {})

  const ts = msg.created_at
    ? new Date(msg.created_at + 'Z').toLocaleTimeString('en-GB', { hour12: false })
    : '--:--:--'

  return (
    <div
      className="rp-coord-card"
      style={{ borderLeftColor: cfg.color, background: cfg.bg, cursor: onClick ? 'pointer' : 'default' }}
      onClick={onClick}
    >
      <div className="rp-coord-card-header">
        <span className="rp-coord-type-badge" style={{ color: cfg.color, borderColor: cfg.color }}>
          <Icon size={10} style={{ marginRight: 4 }} />
          {cfg.label}
        </span>
        <span className="rp-coord-ts">{ts}</span>
        <span className="rp-coord-from">{msg.from_agent}</span>
        {msg.to_agent && !['All', 'HITL'].includes(
          Array.isArray(msg.to_agent) ? msg.to_agent[0] : msg.to_agent
        ) && (
            <>
              <ChevronRight size={10} style={{ color: 'var(--text-muted)' }} />
              <span className="rp-coord-to">
                {Array.isArray(msg.to_agent)
                  ? msg.to_agent.join(', ')
                  : String(msg.to_agent).replace(/[\[\]"]/g, '')}
              </span>
            </>
          )}
      </div>
      <div className="rp-coord-subject">{msg.subject}</div>

      {msg.msg_type === 'blocker' && payload.facility && (
        <div className="rp-coord-meta-row">
          <span className="rp-coord-chip rp-chip-red">📦 {payload.sku || 'Material'}</span>
          <span className="rp-coord-chip">{payload.days_remaining?.toFixed(0) || '?'}d stock</span>
          <span className={`rp-coord-chip ${payload.reorder_urgency === 'HIGH' ? 'rp-chip-red' : 'rp-chip-amber'}`}>
            {payload.reorder_urgency || 'MEDIUM'} urgency
          </span>
        </div>
      )}

      {msg.msg_type === 'proposal' && Array.isArray(payload) && (
        <div className="rp-coord-options">
          {payload.slice(0, 3).map((opt, i) => (
            <div key={i} className="rp-coord-option">
              <span className="rp-coord-option-label">{opt.label}</span>
              <span className={`rp-coord-option-risk risk-${(opt.risk_level || 'MEDIUM').toLowerCase()}`}>{opt.risk_level}</span>
              <span className="rp-coord-option-cost">
                {opt.cost_delta_usd >= 0 ? '+' : ''}${Number(opt.cost_delta_usd || 0).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}

      {msg.msg_type === 'eval' && payload.recommended_option && (
        <div className="rp-coord-eval-result">
          <CheckCircle size={11} style={{ color: 'var(--green)' }} />
          <span>Recommended: <strong>{payload.recommended_option.label}</strong></span>
          <span className="rp-coord-eval-cost">
            +${Number(payload.recommended_option.cost_delta_usd || 0).toLocaleString()}
          </span>
        </div>
      )}
      {msg.msg_type === 'eval' && !payload.recommended_option && payload.reason && (
        <div className="rp-coord-eval-result rp-eval-fail">
          <AlertTriangle size={11} style={{ color: 'var(--amber)' }} />
          <span>{payload.reason}</span>
        </div>
      )}

      {msg.msg_type === 'consensus' && payload.winning_option && (
        <div className="rp-coord-eval-result">
          <CheckCircle size={11} style={{ color: 'var(--green)' }} />
          <span>Applied: <strong>{payload.winning_option.label}</strong></span>
        </div>
      )}

      {msg.msg_type === 'escalate' && (
        <div className="rp-coord-eval-result rp-eval-fail">
          <GitBranch size={11} style={{ color: 'var(--purple)' }} />
          <span>Escalated to HITL — manual review required</span>
        </div>
      )}
    </div>
  )
}

/* ── Log Entry ───────────────────────────────────────────────────────────── */
function LogEntry({ entry, isLast }) {
  const agent = AGENTS.find(a => a.id === entry.agent) || { color: 'var(--text-secondary)' }
  let dateObj = entry.ts
  if (typeof entry.ts === 'number') dateObj = new Date(entry.ts * 1000)
  else if (typeof entry.ts === 'string') dateObj = new Date(entry.ts)
  else if (!(entry.ts instanceof Date)) dateObj = new Date()
  const ts = dateObj.toLocaleTimeString('en-GB', { hour12: false })

  return (
    <div className={`rp-log-entry ${isLast ? 'rp-log-entry--last' : ''}`}>
      <span className="rp-log-ts">{ts}</span>
      <span className="rp-log-agent" style={{ color: agent.color }}>{entry.agent}</span>
      <span className="rp-log-sep">›</span>
      <span className="rp-log-text">
        {entry.text}
        {isLast && entry.type === 'token' && <span className="rp-cursor">▋</span>}
      </span>
    </div>
  )
}

/* ── Main Page ───────────────────────────────────────────────────────────── */
export default function AgentReasoning() {
  const logRef = useRef(null)
  const graphRef = useRef(null)
  const [graphSize, setGraphSize] = useState({ w: 800, h: 520 })

  // Keep track of the rendered container size so the SVG viewBox stays in sync
  useEffect(() => {
    const el = graphRef.current
    if (!el) return
    const obs = new ResizeObserver(entries => {
      for (const entry of entries) {
        setGraphSize({ w: entry.contentRect.width, h: entry.contentRect.height })
      }
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  const [logs, setLogs] = useState([])
  const [agentStates, setAgentStates] = useState({})
  const [agentThoughts, setAgentThoughts] = useState({})
  const [connected, setConnected] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [currentRunId, setCurrentRunId] = useState(null)
  const [coordMsgs, setCoordMsgs] = useState([])
  const [blockerIds, setBlockerIds] = useState(new Set())
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerThread, setDrawerThread] = useState(null)
  const [hitlCounts, setHitlCounts] = useState({ total: 0 })
  const [hitlRerunFlash, setHitlRerunFlash] = useState(false)

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  const fetchState = useCallback(async () => {
    try {
      const [logData, activeData] = await Promise.all([
        api.getAgentLog({ limit: 60 }).catch(() => ({ log: [] })),
        api.getActiveAgent().catch(() => ({ is_running: false, active_agent: null, run_id: null })),
      ])

      setConnected(true)

      const running = activeData?.is_running ?? false
      const activeAgent = activeData?.active_agent ?? null
      const runId = activeData?.run_id ?? null

      setIsRunning(running)

      // Fetch coordination messages using the backend's current run_id
      const coordData = await api.getCoordinationMessages(runId || undefined)
        .catch(() => ({ messages: [] }))

      setCurrentRunId(prev => {
        if (prev !== runId && runId) {
          setAgentStates({})
          setLogs([])
        }
        return runId
      })

      let rawItems = logData?.log || []
      if (runId) {
        const scoped = rawItems.filter(i => i.run_id === runId)
        rawItems = scoped.length > 0 ? scoped : rawItems
      }

      const newLogs = rawItems.slice().reverse().map(item => ({
        agent: item.agent_name || 'System',
        ts: item.logged_at,
        text: item.message,
        type: 'token',
      }))
      setLogs(newLogs)

      const newThoughts = {}
      rawItems.forEach(item => {
        const id = item.agent_name
        if (!newThoughts[id]) newThoughts[id] = item.message
      })
      setAgentThoughts(newThoughts)

      const agentsWithLogs = new Set(rawItems.map(i => i.agent_name))
      const states = {}
      AGENTS.forEach(a => {
        if (activeAgent === a.id) states[a.id] = 'thinking'
        else if (agentsWithLogs.has(a.id)) states[a.id] = 'done'
        else states[a.id] = 'idle'
      })
      setAgentStates(states)

      const msgs = coordData?.messages || []
      setCoordMsgs(msgs)

      const blocked = new Set()
      msgs.forEach(m => {
        if (m.msg_type === 'blocker' && m.status === 'open') {
          try {
            const p = typeof m.payload === 'string' ? JSON.parse(m.payload) : m.payload
            if (p?.facility) blocked.add(p.facility)
          } catch { /* skip */ }
          blocked.add(m.from_agent)
        }
      })
      setBlockerIds(blocked)

    } catch (e) {
      setConnected(false)
    }
  }, [])

  useEffect(() => {
    fetchState()
    const id = setInterval(fetchState, 1500)
    return () => clearInterval(id)
  }, [fetchState])

  // ── HITL count polling (every 4 s, independent of main loop) ──────────────
  useEffect(() => {
    const pollHitl = async () => {
      try {
        const c = await api.getHitlCounts()
        setHitlCounts(prev => {
          // If total just dropped (a human resolved something) show the rerun flash
          if (prev.total > 0 && (c.total ?? 0) < prev.total) {
            setHitlRerunFlash(true)
            setTimeout(() => setHitlRerunFlash(false), 5000)
          }
          return c
        })
      } catch { /* ignore */ }
    }
    pollHitl()
    const id = setInterval(pollHitl, 4000)
    return () => clearInterval(id)
  }, [])

  const openThread = async (msg) => {
    if (msg.msg_type !== 'blocker') return
    try {
      const data = await api.getCoordinationThread(msg.id)
      setDrawerThread(data.thread || [])
      setDrawerOpen(true)
    } catch {
      setDrawerThread([msg])
      setDrawerOpen(true)
    }
  }

  const statusLabel = !connected ? 'Offline' : isRunning ? 'Agents Running' : 'Live'
  const statusColor = !connected ? 'var(--error)' : isRunning ? 'var(--amber)' : 'var(--green)'
  const statusGlow = !connected ? 'var(--error-glow)' : isRunning ? 'var(--amber-glow)' : 'var(--green-glow)'

  const blockers = coordMsgs.filter(m => m.msg_type === 'blocker')
  const proposals = coordMsgs.filter(m => m.msg_type === 'proposal')
  const evals = coordMsgs.filter(m => m.msg_type === 'eval')
  const outcomes = coordMsgs.filter(m => m.msg_type === 'consensus' || m.msg_type === 'escalate')
  const allOrdered = [...blockers, ...proposals, ...evals, ...outcomes]

  const blockerAgentIds = new Set(blockers.filter(m => m.status === 'open').map(m => m.from_agent))

  return (
    <div className="rp-page">

      {/* ── Header ── */}
      <div className="rp-header">
        <div>
          <h1 className="rp-title">⬡ Agent Reasoning</h1>
          <p className="rp-subtitle">Live multi-agent pipeline with cross-department coordination protocol</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {hitlRerunFlash && (
            <span style={{
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: 12, color: 'var(--green)',
              background: 'rgba(34,197,94,0.10)',
              border: '1px solid var(--green)',
              borderRadius: 20, padding: '4px 12px',
              animation: 'fadeIn 0.3s ease',
            }}>
              <RefreshCw size={11} style={{ animation: 'spin 1s linear infinite' }} />
              Agents re-running after HITL resolution…
            </span>
          )}
          <div className="rp-status-pill" style={{ borderColor: statusColor }}>
            <span className="rp-status-dot" style={{ background: statusColor, boxShadow: `0 0 8px ${statusGlow}` }} />
            {statusLabel}
            {coordMsgs.length > 0 && (
              <span className="rp-coord-count-badge">{coordMsgs.length} coord msgs</span>
            )}
          </div>
        </div>
      </div>

      {/* ── HITL Pending Alert Banner ── */}
      {hitlCounts.total > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12,
          background: 'rgba(251,191,36,0.08)',
          border: '1px solid var(--amber)',
          borderRadius: 10,
          padding: '10px 18px',
          marginBottom: 16,
          fontSize: 13,
        }}>
          <Bell size={15} style={{ color: 'var(--amber)', flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <span style={{ color: 'var(--amber)', fontWeight: 700 }}>
              {hitlCounts.total} HITL item{hitlCounts.total !== 1 ? 's' : ''} awaiting human review
            </span>
            <span style={{ color: 'var(--text-muted)', marginLeft: 10 }}>
              {[
                hitlCounts.ops         && `${hitlCounts.ops} ops`,
                hitlCounts.procurement && `${hitlCounts.procurement} procurement`,
                hitlCounts.finance     && `${hitlCounts.finance} finance`,
                hitlCounts.maintenance && `${hitlCounts.maintenance} maintenance`,
                hitlCounts.carbon      && `${hitlCounts.carbon} carbon`,
              ].filter(Boolean).join(' · ')}
            </span>
          </div>
          <span style={{
            fontSize: 11, color: 'var(--amber)', opacity: 0.7,
            fontFamily: 'var(--font-mono)',
          }}>
            → Go to HITL Inbox to resolve
          </span>
        </div>
      )}

      {/* ── Pipeline Graph ── */}
      <div className="rp-graph-card">
        <div className="rp-graph-label">PIPELINE EXECUTION FLOW</div>
        {/* Container fills 100% width; height is fixed via CSS */}
        <div className="rp-graph-wrap" ref={graphRef}>

          {/* SVG connectors — 100%×100% overlay */}
          <svg
            width="100%"
            height="100%"
            style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none', zIndex: 1 }}
            viewBox={`0 0 ${graphSize.w} ${graphSize.h}`}
            preserveAspectRatio="none"
          >
            <defs>
              <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
                <path d="M0,0 L0,6 L8,3 z" fill="var(--text-muted)" />
              </marker>
            </defs>
            {CONNECTIONS.map(([fromId, toId], i) => {
              const fromAgent = AGENTS.find(a => a.id === fromId)
              const toAgent = AGENTS.find(a => a.id === toId)
              if (!fromAgent || !toAgent) return null
              const x1 = (fromAgent.px / 100) * graphSize.w
              const y1 = (fromAgent.py / 100) * graphSize.h
              const x2 = (toAgent.px / 100) * graphSize.w
              const y2 = (toAgent.py / 100) * graphSize.h
              const isActive = agentStates[fromAgent.id] === 'thinking'
              const isBlocked = blockerAgentIds.has(fromAgent.id)
              return (
                <Connector key={i}
                  x1={x1} y1={y1} x2={x2} y2={y2}
                  active={isActive} blocked={isBlocked}
                />
              )
            })}
          </svg>

          {/* Agent nodes — absolutely positioned by % of container */}
          {AGENTS.map(agent => (
            <div
              key={agent.id}
              style={{
                position: 'absolute',
                left: `calc(${agent.px}% - ${NODE_W / 2}px)`,
                top: `calc(${agent.py}% - ${NODE_H / 2}px)`,
                zIndex: 2,
              }}
            >
              <AgentNode
                agent={agent}
                state={agentStates[agent.id] || 'idle'}
                lastThought={agentThoughts[agent.id] || ''}
                hasBlocker={blockerAgentIds.has(agent.id)}
              />
            </div>
          ))}
        </div>
      </div>

      {/* ── Two-column lower section ── */}
      <div className="rp-lower-grid">

        {/* ── Coordination Feed ── */}
        <div className="rp-coord-card-wrap">
          <div className="rp-section-label">
            ⚡ COORDINATION FEED
            {blockers.some(m => m.status === 'open') && (
              <span className="rp-live-badge">ACTIVE NEGOTIATION</span>
            )}
          </div>

          {allOrdered.length === 0 ? (
            <div className="rp-empty-feed">
              {currentRunId
                ? '✅ No coordination conflicts in this run — agents resolved all decisions independently.'
                : 'No coordination messages yet. Agents will post here when they negotiate blockers.'}
            </div>
          ) : (
            <div className="rp-coord-feed">
              {allOrdered.map((msg, i) => (
                <CoordCard
                  key={msg.id || i}
                  msg={msg}
                  onClick={msg.msg_type === 'blocker' ? () => openThread(msg) : undefined}
                />
              ))}
            </div>
          )}
        </div>

        {/* ── Agent Log Terminal ── */}
        <div className="rp-terminal-card">
          <div className="rp-terminal-header">
            <div className="rp-terminal-dots">
              <span style={{ background: '#FF5F57' }} />
              <span style={{ background: '#FFBD2E' }} />
              <span style={{ background: '#28CA41' }} />
            </div>
            <div className="rp-terminal-title">AGENT LOG STREAM</div>
            <div className="rp-terminal-count">{logs.length} entries</div>
          </div>
          <div className="rp-log-body" ref={logRef}>
            {logs.length === 0 ? (
              <div className="rp-log-empty">
                Waiting for agent activity… Click <strong>Run All Agents</strong> from the sidebar.
              </div>
            ) : (
              logs.map((entry, i) => (
                <LogEntry key={i} entry={entry} isLast={i === logs.length - 1} />
              ))
            )}
          </div>
        </div>
      </div>

      {/* ── Thread Drawer ── */}
      {drawerOpen && (
        <div className="rp-drawer-overlay" onClick={() => setDrawerOpen(false)}>
          <div className="rp-drawer" onClick={e => e.stopPropagation()}>
            <div className="rp-drawer-header">
              <span>Negotiation Thread</span>
              <button className="rp-drawer-close" onClick={() => setDrawerOpen(false)}><X size={16} /></button>
            </div>
            <div className="rp-drawer-body">
              {(drawerThread || []).map((msg, i) => (
                <CoordCard key={i} msg={msg} />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
