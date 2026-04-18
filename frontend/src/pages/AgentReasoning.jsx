import { useEffect, useRef, useState, useCallback } from 'react'
import {
  Brain, Cpu, ShoppingCart, Leaf, DollarSign, Calendar,
  GitBranch, CheckCircle, Loader2, Clock, AlertTriangle,
  ChevronRight, Zap, TrendingUp, X
} from 'lucide-react'
import * as api from '../api/client'
import './AgentReasoning.css'

/* ── Agent metadata ─────────────────────────────────────────────────────── */
// Layout: 3 cols × 3 rows
//   Row 0: Forecaster (col1) | Mechanic (col2) | Buyer (col3)
//   Row 1: Environ   (col1) | Finance  (col2) | Scheduler (col3)
//   Row 2: (empty)           | Orchestrator (col2) | (empty)
const AGENTS = [
  { id: 'Forecaster',       label: 'Forecaster',       subtitle: 'Demand Intelligence',    Icon: Brain,        color: 'var(--cyan)',   glow: 'var(--cyan-glow)',   col: 1, row: 0 },
  { id: 'Mechanic',         label: 'Mechanic',          subtitle: 'Machine Health',         Icon: Cpu,          color: 'var(--amber)',  glow: 'var(--amber-glow)',  col: 2, row: 0 },
  { id: 'Buyer',            label: 'Buyer',             subtitle: 'Procurement',            Icon: ShoppingCart, color: 'var(--green)',  glow: 'var(--green-glow)',  col: 3, row: 0 },
  { id: 'Environmentalist', label: 'Environmentalist',  subtitle: 'Carbon & Energy',        Icon: Leaf,         color: 'var(--green)',  glow: 'var(--green-glow)',  col: 1, row: 1 },
  { id: 'Finance',          label: 'Finance',           subtitle: 'Budget Gate',            Icon: DollarSign,   color: 'var(--amber)',  glow: 'var(--amber-glow)',  col: 2, row: 1 },
  { id: 'Scheduler',        label: 'Scheduler',         subtitle: 'Production Planning',    Icon: Calendar,     color: 'var(--purple)', glow: 'var(--purple-glow)', col: 3, row: 1 },
  { id: 'Orchestrator',     label: 'Orchestrator',      subtitle: 'System Supervisor',      Icon: GitBranch,    color: 'var(--red)',    glow: 'var(--red-glow)',    col: 2, row: 2 },
]

// Connections: [fromCol, fromRow, toCol, toRow]
// Row-0 horizontal flow
// Row-0 → Row-1 verticals
// Row-1 → Orchestrator
const CONNECTIONS = [
  [1, 0, 2, 0], // Forecaster  → Mechanic
  [2, 0, 3, 0], // Mechanic    → Buyer
  [1, 0, 1, 1], // Forecaster  → Environmentalist
  [2, 0, 2, 1], // Mechanic    → Finance
  [3, 0, 3, 1], // Buyer       → Scheduler
  [1, 1, 2, 1], // Environ     → Finance
  [3, 0, 2, 1], // Buyer       → Finance (clearance)
  [2, 1, 3, 1], // Finance     → Scheduler
  [2, 1, 2, 2], // Finance     → Orchestrator
  [3, 1, 2, 2], // Scheduler   → Orchestrator
]

/* ── Msg type config ─────────────────────────────────────────────────────── */
const MSG_CFG = {
  blocker:   { label: 'BLOCKER',   color: 'var(--red)',    bg: 'rgba(239,68,68,0.08)',   icon: AlertTriangle },
  proposal:  { label: 'PROPOSAL',  color: 'var(--amber)',  bg: 'rgba(251,191,36,0.08)',  icon: TrendingUp },
  eval:      { label: 'EVAL',      color: 'var(--cyan)',   bg: 'rgba(34,211,238,0.08)',  icon: Zap },
  consensus: { label: 'CONSENSUS', color: 'var(--green)',  bg: 'rgba(34,197,94,0.08)',   icon: CheckCircle },
  escalate:  { label: 'ESCALATED', color: 'var(--purple)', bg: 'rgba(168,85,247,0.08)', icon: GitBranch },
}

/* ── Grid + SVG constants ────────────────────────────────────────────────── */
// Each node cell is CW × CH pixels inside the SVG coordinate system
const CW = 224   // horizontal cell width
const CH = 180   // vertical cell height
const NODE_W = 192  // card width  (must match CSS .rp-node width)
const NODE_H = 130  // card height (must match CSS .rp-node height)
// Node centre within its SVG cell
const cx = col => (col - 1) * CW + NODE_W / 2
const cy = row => row         * CH + NODE_H / 2
// SVG canvas size  (3 cols × 3 rows, small padding)
const SVG_W = 3 * CW + 40
const SVG_H = 3 * CH + 40

/* ── Agent Node ──────────────────────────────────────────────────────────── */
function AgentNode({ agent, state, lastThought, hasBlocker }) {
  const { label, subtitle, Icon, color, glow } = agent
  const isActive = state === 'thinking'
  const isDone   = state === 'done'

  return (
    <div
      className={`rp-node ${isActive ? 'rp-node--active' : ''} ${isDone ? 'rp-node--done' : ''} ${hasBlocker ? 'rp-node--blocked' : ''}`}
      style={{ '--node-color': color, '--node-glow': glow }}
    >
      {isActive && <div className="rp-node-ring" />}
      {hasBlocker && <div className="rp-node-blocker-badge">⚡ BLOCKED</div>}

      <div className="rp-node-icon-wrap">
        <Icon size={20} style={{ color }} />
        {isActive  && <Loader2 size={12} className="rp-spin" style={{ color, marginLeft: 4 }} />}
        {isDone    && <CheckCircle size={12} style={{ color: 'var(--green)', marginLeft: 4 }} />}
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
function Connector({ fromCol, fromRow, toCol, toRow, active, blocked }) {
  const x1 = cx(fromCol), y1 = cy(fromRow)
  const x2 = cx(toCol),   y2 = cy(toRow)
  const mx = (x1 + x2) / 2

  const stroke = blocked ? 'var(--red)' : active ? 'var(--primary)' : 'var(--border)'
  const width  = (active || blocked) ? 2.5 : 1.5
  const dash   = (active || blocked) ? '6 4' : '4 4'

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
        {msg.to_agent && !['All','HITL'].includes(msg.to_agent) && (
          <>
            <ChevronRight size={10} style={{ color: 'var(--text-muted)' }} />
            <span className="rp-coord-to">{typeof msg.to_agent === 'string' ? msg.to_agent.replace(/[\[\]"]/g, '') : msg.to_agent}</span>
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

  const [logs,          setLogs]          = useState([])
  const [agentStates,   setAgentStates]   = useState({})
  const [agentThoughts, setAgentThoughts] = useState({})
  const [connected,     setConnected]     = useState(false)
  const [isRunning,     setIsRunning]     = useState(false)
  const [currentRunId,  setCurrentRunId]  = useState(null)
  const [coordMsgs,     setCoordMsgs]     = useState([])
  const [blockerIds,    setBlockerIds]    = useState(new Set())
  const [drawerOpen,    setDrawerOpen]    = useState(false)
  const [drawerThread,  setDrawerThread]  = useState(null)

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  const fetchState = useCallback(async () => {
    try {
      const [logData, activeData, coordData] = await Promise.all([
        api.getAgentLog({ limit: 60 }).catch(() => ({ log: [] })),
        api.getActiveAgent().catch(() => ({ is_running: false, active_agent: null, run_id: null })),
        api.getCoordinationMessages().catch(() => ({ messages: [] })),
      ])

      setConnected(true)

      const running     = activeData?.is_running ?? false
      const activeAgent = activeData?.active_agent ?? null
      const runId       = activeData?.run_id ?? null

      setIsRunning(running)

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
        ts:    item.logged_at,
        text:  item.message,
        type:  'token',
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
        if (activeAgent === a.id)        states[a.id] = 'thinking'
        else if (agentsWithLogs.has(a.id)) states[a.id] = 'done'
        else                               states[a.id] = 'idle'
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
  const statusGlow  = !connected ? 'var(--error-glow)' : isRunning ? 'var(--amber-glow)' : 'var(--green-glow)'

  const blockers  = coordMsgs.filter(m => m.msg_type === 'blocker')
  const proposals = coordMsgs.filter(m => m.msg_type === 'proposal')
  const evals     = coordMsgs.filter(m => m.msg_type === 'eval')
  const outcomes  = coordMsgs.filter(m => m.msg_type === 'consensus' || m.msg_type === 'escalate')
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
        <div className="rp-status-pill" style={{ borderColor: statusColor }}>
          <span className="rp-status-dot" style={{ background: statusColor, boxShadow: `0 0 8px ${statusGlow}` }} />
          {statusLabel}
          {coordMsgs.length > 0 && (
            <span className="rp-coord-count-badge">{coordMsgs.length} coord msgs</span>
          )}
        </div>
      </div>

      {/* ── Pipeline Graph ── */}
      <div className="rp-graph-card">
        <div className="rp-graph-label">PIPELINE EXECUTION FLOW</div>
        <div className="rp-graph-wrap" style={{ position: 'relative', width: SVG_W, minHeight: SVG_H }}>

          {/* SVG connectors */}
          <svg
            width={SVG_W}
            height={SVG_H}
            style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none', zIndex: 1 }}
          >
            <defs>
              <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
                <path d="M0,0 L0,6 L8,3 z" fill="var(--text-muted)" />
              </marker>
            </defs>
            {CONNECTIONS.map(([fc, fr, tc, tr], i) => {
              const fromAgent = AGENTS.find(a => a.col === fc && a.row === fr)
              const isActive  = fromAgent && agentStates[fromAgent.id] === 'thinking'
              const isBlocked = fromAgent && blockerAgentIds.has(fromAgent.id)
              return (
                <Connector key={i}
                  fromCol={fc} fromRow={fr}
                  toCol={tc}   toRow={tr}
                  active={isActive} blocked={isBlocked}
                />
              )
            })}
          </svg>

          {/* Agent nodes — absolutely positioned within the SVG coordinate space */}
          {AGENTS.map(agent => (
            <div
              key={agent.id}
              style={{
                position: 'absolute',
                left: cx(agent.col) - NODE_W / 2,
                top:  cy(agent.row) - NODE_H / 2,
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
              No coordination messages yet. Run agents to trigger negotiation protocol.
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
              <button className="rp-drawer-close" onClick={() => setDrawerOpen(false)}><X size={16}/></button>
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
