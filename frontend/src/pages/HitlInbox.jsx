import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, CheckCircle, XCircle, Clock, AlertTriangle, Filter } from 'lucide-react'
import * as api from '../api/client'

const TYPE_COLORS = {
  ops:         'var(--cyan)',
  procurement: 'var(--purple)',
  finance:     'var(--amber)',
  maintenance: 'var(--red)',
  carbon:      'var(--green)',
}

const TYPE_LABELS = {
  ops:         '⚙️ Operations',
  procurement: '📦 Procurement',
  finance:     '💰 Finance',
  maintenance: '🔧 Maintenance',
  carbon:      '🌱 Carbon',
}

function HitlCard({ item, onApprove, onReject }) {
  const [comment, setComment] = useState('')
  const [loading, setLoading] = useState(false)
  const color = TYPE_COLORS[item.item_type] || 'var(--text-muted)'
  const payload = item.payload || {}

  const handle = async (action) => {
    setLoading(true)
    try {
      await action(item.id, { comment, resolved_by: 'Dashboard Operator' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="hitl-card" style={{ borderLeftColor: color }}>
      <div className="hitl-header">
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span className="hitl-type-badge" style={{ background: color+'22', color, borderColor: color, border:'1px solid' }}>
            {TYPE_LABELS[item.item_type] || item.item_type}
          </span>
          <span style={{ fontSize:11, color:'var(--text-muted)', fontFamily:'var(--font-mono)' }}>
            #{item.id}
          </span>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ fontSize:11, color:'var(--text-muted)' }}>
            <Clock size={10} style={{ display:'inline', marginRight:3 }} />
            {item.created_at ? new Date(item.created_at).toLocaleString() : '—'}
          </span>
          <span className="badge badge-info">{item.source}</span>
        </div>
      </div>

      <div className="hitl-payload">
        {Object.entries(payload).map(([k, v]) => (
          <div key={k}>
            <span style={{ color:'var(--text-muted)' }}>{k}: </span>
            <span style={{ color:'var(--text-primary)' }}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
          </div>
        ))}
      </div>

      <div style={{ display:'flex', gap:8, marginBottom:8 }}>
        <input
          className="input"
          style={{ fontSize:12 }}
          placeholder="Add review comment (optional)..."
          value={comment}
          onChange={e => setComment(e.target.value)}
        />
      </div>

      <div className="hitl-actions">
        <button
          className="btn btn-success btn-sm"
          disabled={loading}
          onClick={() => handle(onApprove)}
        >
          <CheckCircle size={13} /> Approve
        </button>
        <button
          className="btn btn-danger btn-sm"
          disabled={loading}
          onClick={() => handle(onReject)}
        >
          <XCircle size={13} /> Reject
        </button>
      </div>
    </div>
  )
}

function HistoryCard({ item }) {
  const color   = TYPE_COLORS[item.item_type] || 'var(--text-muted)'
  const isApproved = item.status === 'approved'
  return (
    <div className="hitl-card" style={{ borderLeftColor: isApproved ? 'var(--green)' : 'var(--red)', opacity:0.8 }}>
      <div className="hitl-header">
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span className={`badge badge-${isApproved ? 'ok' : 'critical'}`}>
            {isApproved ? '✅ APPROVED' : '❌ REJECTED'}
          </span>
          <span className="hitl-type-badge" style={{ background: color+'22', color, border:`1px solid ${color}` }}>
            {TYPE_LABELS[item.item_type] || item.item_type}
          </span>
          <span style={{ fontSize:11, color:'var(--text-muted)', fontFamily:'var(--font-mono)' }}>#{item.id}</span>
        </div>
        <span style={{ fontSize:11, color:'var(--text-muted)' }}>
          by {item.resolved_by || '—'} · {item.resolved_at ? new Date(item.resolved_at).toLocaleString() : '—'}
        </span>
      </div>
      {item.comment && (
        <div style={{ fontSize:12, color:'var(--text-secondary)', fontStyle:'italic' }}>"{item.comment}"</div>
      )}
    </div>
  )
}

export default function HitlInbox({ onCountChange }) {
  const [pending,  setPending]  = useState([])
  const [history,  setHistory]  = useState([])
  const [counts,   setCounts]   = useState({})
  const [filter,   setFilter]   = useState('')
  const [tab,      setTab]      = useState('pending')
  const [loading,  setLoading]  = useState(true)

  const load = useCallback(async () => {
    try {
      const [p, h, c] = await Promise.all([
        api.getHitlPending(filter || undefined),
        api.getHitlHistory({ limit:50, item_type: filter || undefined }),
        api.getHitlCounts(),
      ])
      setPending(p.items || [])
      setHistory(h.items || [])
      setCounts(c)
      onCountChange?.(c.total || 0)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [filter, onCountChange])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const id = setInterval(load, 20000)
    return () => clearInterval(id)
  }, [load])

  const handleApprove = async (id, body) => {
    await api.approveHitl(id, body)
    await load()
  }

  const handleReject = async (id, body) => {
    await api.rejectHitl(id, body)
    await load()
  }

  if (loading) return <div className="loading-overlay"><div className="spinner" /><span>Loading HITL Inbox...</span></div>

  const TAB_STYLE = (t) => ({
    padding: '7px 16px',
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
    background: 'none',
    border: 'none',
    borderBottom: tab === t ? '2px solid var(--cyan)' : '2px solid transparent',
    color: tab === t ? 'var(--cyan)' : 'var(--text-muted)',
  })

  return (
    <div>
      {/* Count badges */}
      <div className="kpi-grid" style={{ gridTemplateColumns:'repeat(6, 1fr)', marginBottom:20 }}>
        {[['total','All','var(--cyan)'],['ops','Ops','var(--cyan)'],['procurement','Proc','var(--purple)'],['finance','Fin','var(--amber)'],['maintenance','Maint','var(--red)'],['carbon','Carbon','var(--green)']].map(([k,label,col]) => (
          <div
            key={k}
            className="kpi-card"
            style={{ '--accent-color':col, cursor:'pointer', outline: filter === (k==='total'?'':k) ? `2px solid ${col}` : 'none' }}
            onClick={() => setFilter(k === 'total' ? '' : k)}
          >
            <div className="kpi-label">{label}</div>
            <div className="kpi-value" style={{ color: col, fontSize:24 }}>{counts[k] ?? 0}</div>
          </div>
        ))}
      </div>

      {/* Tab Bar */}
      <div style={{ display:'flex', gap:0, borderBottom:'1px solid var(--border)', marginBottom:16 }}>
        <button style={TAB_STYLE('pending')} onClick={() => setTab('pending')}>
          Pending ({pending.length})
        </button>
        <button style={TAB_STYLE('history')} onClick={() => setTab('history')}>
          Resolved History
        </button>
        <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:8, paddingBottom:8 }}>
          <select className="input" style={{ width:140, fontSize:12 }} value={filter} onChange={e=>setFilter(e.target.value)}>
            <option value="">All Types</option>
            <option value="ops">Operations</option>
            <option value="procurement">Procurement</option>
            <option value="finance">Finance</option>
            <option value="maintenance">Maintenance</option>
            <option value="carbon">Carbon</option>
          </select>
          <button className="btn btn-ghost btn-sm" onClick={load}><RefreshCw size={13} /></button>
        </div>
      </div>

      {tab === 'pending' && (
        pending.length > 0
          ? pending.map(item => (
              <HitlCard
                key={item.id}
                item={item}
                onApprove={handleApprove}
                onReject={handleReject}
              />
            ))
          : <div className="empty-state">
              <div className="empty-state-icon">📭</div>
              <div className="empty-state-title">No pending items</div>
              <div className="empty-state-desc">All decisions have been resolved or no agents have escalated yet.</div>
            </div>
      )}

      {tab === 'history' && (
        history.length > 0
          ? history.map(item => <HistoryCard key={item.id} item={item} />)
          : <div className="empty-state">
              <div className="empty-state-icon">📜</div>
              <div className="empty-state-title">No resolved items yet</div>
            </div>
      )}
    </div>
  )
}
