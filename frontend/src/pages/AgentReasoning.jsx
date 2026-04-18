import { useEffect, useRef, useState, useCallback } from 'react'
import { Brain, Cpu, ShoppingCart, Leaf, DollarSign, Calendar, GitBranch, CheckCircle, Loader2, Clock } from 'lucide-react'
import * as api from '../api/client'
import './AgentReasoning.css'

/* ── Agent metadata ─────────────────────────────────────────────────── */
const AGENTS = [
  {
    id: 'Forecaster',
    label: 'Forecaster',
    subtitle: 'Demand Intelligence',
    Icon: Brain,
    color: 'var(--cyan)',
    glow: 'var(--cyan-glow)',
    border: 'var(--border)',
    col: 1, row: 0,
  },
  {
    id: 'Mechanic',
    label: 'Mechanic',
    subtitle: 'Machine Health',
    Icon: Cpu,
    color: 'var(--amber)',
    glow: 'var(--amber-glow)',
    border: 'var(--border)',
    col: 2, row: 0,
  },
  {
    id: 'Buyer',
    label: 'Buyer',
    subtitle: 'Inventory & Procurement',
    Icon: ShoppingCart,
    color: 'var(--green)',
    glow: 'var(--green-glow)',
    border: 'var(--border)',
    col: 3, row: 0,
  },
  {
    id: 'Environmentalist',
    label: 'Environmentalist',
    subtitle: 'Carbon & Energy',
    Icon: Leaf,
    color: 'var(--green)',
    glow: 'var(--green-glow)',
    border: 'var(--border)',
    col: 1, row: 1,
  },
  {
    id: 'Finance',
    label: 'Finance',
    subtitle: 'Budget Gate',
    Icon: DollarSign,
    color: 'var(--amber)',
    glow: 'var(--amber-glow)',
    border: 'var(--border)',
    col: 2, row: 1,
  },
  {
    id: 'Scheduler',
    label: 'Scheduler',
    subtitle: 'Production Planning',
    Icon: Calendar,
    color: 'var(--purple)',
    glow: 'var(--purple-glow)',
    border: 'var(--border)',
    col: 3, row: 1,
  },
  {
    id: 'Orchestrator',
    label: 'Orchestrator',
    subtitle: 'System Supervisor',
    Icon: GitBranch,
    color: 'var(--red)',
    glow: 'var(--red-glow)',
    border: 'var(--border)',
    col: 2, row: 2,
  },
]

/* ── Agent Node card ─────────────────────────────────────────────────── */
function AgentNode({ agent, state, lastThought }) {
  const { label, subtitle, Icon, color, glow, border } = agent
  const isActive = state === 'thinking'
  const isDone   = state === 'done'
  const isIdle   = state === 'idle' || state === 'unknown'

  return (
    <div
      className={`rp-node ${isActive ? 'rp-node--active' : ''} ${isDone ? 'rp-node--done' : ''}`}
      style={{
        '--node-color':  color,
        '--node-glow':   glow,
        '--node-border': border,
      }}
    >
      {/* Animated ring when thinking */}
      {isActive && <div className="rp-node-ring" />}

      <div className="rp-node-icon-wrap">
        <Icon size={20} style={{ color }} />
        {isActive && <Loader2 size={12} className="rp-spin" style={{ color, marginLeft: 4 }} />}
        {isDone   && <CheckCircle size={12} style={{ color: 'var(--green)', marginLeft: 4 }} />}
        {isIdle   && <Clock size={12} style={{ color: 'var(--text-muted)', marginLeft: 4 }} />}
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

/* ── SVG connector arrows between nodes ─────────────────────────────── */
function Connector({ fromCol, fromRow, toCol, toRow, active }) {
  const CW = 244, CH = 192
  const cx = (col) => col * CW + 110
  const cy = (row) => row * CH + 84

  const x1 = cx(fromCol - 1), y1 = cy(fromRow)
  const x2 = cx(toCol - 1),   y2 = cy(toRow)
  const mx = (x1 + x2) / 2

  return (
    <path
      d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
      fill="none"
      stroke={active ? 'var(--primary)' : 'var(--border)'}
      strokeWidth={active ? 2.5 : 1.5}
      strokeDasharray={active ? '6 4' : '4 4'}
      style={active ? { animation: 'dash-flow 1s linear infinite' } : {}}
      markerEnd="url(#arrow)"
    />
  )
}

/* connections: [fromCol, fromRow, toCol, toRow] */
const CONNECTIONS = [
  [1, 0, 2, 0], // Forecaster → Mechanic
  [2, 0, 3, 0], // Mechanic   → Buyer
  [1, 0, 1, 1], // Forecaster → Environmentalist
  [2, 0, 2, 1], // Mechanic   → Finance
  [3, 0, 3, 1], // Buyer      → Scheduler
  [3, 0, 2, 1], // Buyer      → Finance (clearance request)
  [1, 1, 2, 1], // Environ    → Finance
  [2, 1, 3, 1], // Finance    → Scheduler
  [2, 1, 2, 2], // Finance    → Orchestrator
  [3, 1, 2, 2], // Scheduler  → Orchestrator
]

/* ── Log entry row ───────────────────────────────────────────────────── */
function LogEntry({ entry, isLast }) {
  const agent = AGENTS.find(a => a.id === entry.agent) || { color: 'var(--text-secondary)' }

  // Safe timestamp parsing
  let dateObj = entry.ts
  if (typeof entry.ts === 'number') {
    dateObj = new Date(entry.ts * 1000)
  } else if (typeof entry.ts === 'string') {
    dateObj = new Date(entry.ts)
  } else if (!(entry.ts instanceof Date)) {
    dateObj = new Date()
  }

  const ts = dateObj.toLocaleTimeString('en-GB', { hour12: false })

  return (
    <div className={`rp-log-entry ${isLast ? 'rp-log-entry--last' : ''}`}>
      <span className="rp-log-ts">{ts}</span>
      <span className="rp-log-agent" style={{ color: agent.color }}>
        {entry.agent}
      </span>
      <span className="rp-log-sep">›</span>
      <span className="rp-log-text">
        {entry.text}
        {isLast && entry.type === 'token' && <span className="rp-cursor">▋</span>}
      </span>
    </div>
  )
}

/* ── Main page ───────────────────────────────────────────────────────── */
export default function AgentReasoning() {
  const logRef = useRef(null)

  const [logs, setLogs]               = useState([])
  const [agentStates, setAgentStates] = useState({})
  const [agentThoughts, setAgentThoughts] = useState({})
  const [connected, setConnected]     = useState(false)
  const [isRunning, setIsRunning]     = useState(false)

  // Auto-scroll log to bottom on new entries
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs])

  const fetchState = useCallback(async () => {
    try {
      // Bug #1 fixed: use correct key 'log' not 'items'
      // Added third call: real per-agent active state from /api/agents/active
      const [logData, status, activeData] = await Promise.all([
        api.getAgentLog({ limit: 50 }).catch(() => ({ log: [] })),
        api.getSystemStatus().catch(() => ({ is_running: false, active_agent: null })),
        api.getActiveAgent().catch(() => ({ is_running: false, active_agent: null })),
      ])

      setConnected(true)

      // Bug #1 fix: backend returns { log: [...] } not { items: [...] }
      const rawItems = logData?.log || []

      // rawItems come newest-first from the DB (ORDER BY logged_at DESC)
      // Reverse so the terminal shows oldest at top, newest at bottom
      const newLogs = rawItems.slice().reverse().map(item => ({
        agent: item.agent_name || 'System',
        ts:    item.logged_at,
        text:  item.message,
        type:  'token',
      }))
      setLogs(newLogs)

      // Bug #4 fix: build per-agent "last thought" from the most recent log per agent
      // rawItems is newest-first, so first occurrence per agent = most recent
      const newThoughts = {}
      rawItems.forEach(item => {
        const agentId = item.agent_name || 'System'
        if (!newThoughts[agentId]) {
          newThoughts[agentId] = item.message
        }
      })
      setAgentThoughts(newThoughts)

      // Use the freshest running/active info (prefer activeData if available)
      const running     = activeData?.is_running ?? status?.is_running ?? false
      const activeAgent = activeData?.active_agent ?? status?.active_agent ?? null
      setIsRunning(running)

      // Bug #2+3 fix: true per-agent state from /api/agents/active
      const agentsWithLogs = new Set(rawItems.map(i => i.agent_name))
      const states = {}
      AGENTS.forEach(a => {
        if (activeAgent === a.id) {
          // This agent is literally running right now
          states[a.id] = 'thinking'
        } else if (running) {
          // System is running but this specific agent is not the active one.
          // Agents that already have logs are done; others are waiting (idle).
          states[a.id] = agentsWithLogs.has(a.id) ? 'done' : 'idle'
        } else {
          // System is idle — show done for any agent that has ever logged, else idle
          states[a.id] = agentsWithLogs.has(a.id) ? 'done' : 'idle'
        }
      })
      setAgentStates(states)

    } catch (e) {
      setConnected(false)
    }
  }, [])

  useEffect(() => {
    fetchState()
    const id = setInterval(fetchState, 2000)
    return () => clearInterval(id)
  }, [fetchState])

  const CW = 244, CH = 192
  const svgW = 3 * CW + 60, svgH = 3 * CH + 60

  // Bug #5 fix: honest status label
  const statusLabel = !connected
    ? 'Offline'
    : isRunning
      ? 'Agents Running'
      : 'Live'

  const statusColor = !connected
    ? 'var(--error)'
    : isRunning
      ? 'var(--amber)'
      : 'var(--green)'

  const statusGlow = !connected
    ? 'var(--error-glow)'
    : isRunning
      ? 'var(--amber-glow)'
      : 'var(--green-glow)'

  return (
    <div className="rp-page">

      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="rp-header">
        <div>
          <h1 className="rp-title">⬡ Agent Reasoning</h1>
          <p className="rp-subtitle">Live multi-agent pipeline — true per-agent execution state</p>
        </div>
        <div className="rp-status-pill" style={{ borderColor: statusColor }}>
          <span
            className="rp-status-dot"
            style={{
              background: statusColor,
              boxShadow:  `0 0 8px ${statusGlow}`,
            }}
          />
          {statusLabel}
        </div>
      </div>

      {/* ── Workflow Graph ───────────────────────────────────────────── */}
      <div className="rp-graph-card">
        <div className="rp-graph-label">PIPELINE EXECUTION FLOW</div>

        <div className="rp-graph-wrap">
          {/* SVG connector layer */}
          <svg
            width={svgW}
            height={svgH}
            className="rp-svg"
            style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none' }}
          >
            <defs>
              <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
                <path d="M0,0 L0,6 L8,3 z" fill="var(--text-muted)" />
              </marker>
            </defs>
            {CONNECTIONS.map(([fc, fr, tc, tr], i) => {
              const fromAgent = AGENTS.find(a => a.col === fc && a.row === fr)
              const isActive  = fromAgent && agentStates[fromAgent.id] === 'thinking'
              return (
                <Connector key={i} fromCol={fc} fromRow={fr} toCol={tc} toRow={tr} active={isActive} />
              )
            })}
          </svg>

          {/* Agent node grid */}
          <div className="rp-grid">
            {AGENTS.map(agent => (
              <div
                key={agent.id}
                style={{
                  gridColumn: agent.col,
                  gridRow:    agent.row + 1,
                  zIndex: 2,
                }}
              >
                <AgentNode
                  agent={agent}
                  state={agentStates[agent.id] || 'unknown'}
                  lastThought={agentThoughts[agent.id] || ''}
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Live Log Terminal ────────────────────────────────────────── */}
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
              Waiting for agent activity… The orchestrator runs automatically every 5 minutes,
              or click <strong>Run All Agents</strong> from the Sidebar to trigger immediately.
            </div>
          ) : (
            logs.map((entry, i) => (
              <LogEntry key={i} entry={entry} isLast={i === logs.length - 1} />
            ))
          )}
        </div>
      </div>
    </div>
  )
}
