/**
 * ERPIntegration.jsx — ERP Integration Layer Dashboard
 *
 * 5 sections:
 *   1. Connection Banner  — adapter badge, health, write mode, HITL-gated switch
 *   2. READ Panel         — live inventory + machine status from ERP adapter
 *   3. WRITE Panel        — production orders and POs pushed to ERP
 *   4. LISTEN Panel       — live ERP event feed from poll_events()
 *   5. EXPLAIN Panel      — searchable audit log with detail drawer
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getErpStatus, getErpAudit, getErpEvents,
  switchErpAdapter, pushErpOrder,
  getErpInventory, getErpMachines,
} from '../api/client'
import { getPlants } from '../api/client'
import './ERPIntegration.css'

// ── Helpers ───────────────────────────────────────────────────────────────────

const ADAPTER_LABELS = {
  sap_mock:  'SAP S/4HANA',
  odoo_mock: 'Odoo 17',
  csv:       'CSV / Local',
  none:      'Disconnected',
}

const fmt = (iso) => {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { return iso }
}

const fmtDate = (iso) => {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`
  } catch { return iso }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function AdapterBadge({ type }) {
  const key = type || 'none'
  return (
    <span className={`erp-adapter-badge ${key}`}>
      {ADAPTER_LABELS[key] || key.toUpperCase()}
    </span>
  )
}

function HealthDot({ status }) {
  const cls = status === 'connected' ? 'connected' : status === 'pending_approval' ? 'pending' : 'error'
  return <span className={`erp-health-dot ${cls}`} />
}

function StatusBadge({ status }) {
  const s = (status || 'unknown').toLowerCase()
  return <span className={`erp-status-badge ${s}`}>{status || '—'}</span>
}

function EventBadge({ type }) {
  const known = ['NEW_SALES_ORDER','GOODS_RECEIPT','PO_CONFIRMATION','MACHINE_ALERT']
  const cls = known.includes(type) ? type : 'default'
  return <span className={`erp-event-badge ${cls}`}>{type}</span>
}

// ── Detail Drawer ─────────────────────────────────────────────────────────────

function AuditDrawer({ entry, onClose }) {
  const navigate = useNavigate()
  if (!entry) return null

  const beforeStr = typeof entry.payload_before === 'string'
    ? entry.payload_before
    : JSON.stringify(entry.payload_before, null, 2)

  const afterStr = typeof entry.payload_after === 'string'
    ? entry.payload_after
    : JSON.stringify(entry.payload_after, null, 2)

  return (
    <>
      <div className="erp-drawer-overlay" onClick={onClose} />
      <div className="erp-drawer" role="dialog" aria-label="Audit detail">
        <div className="erp-drawer-header">
          <span className="erp-drawer-title">🔍 AUDIT ENTRY #{entry.id}</span>
          <StatusBadge status={entry.status} />
          <button className="erp-drawer-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="erp-drawer-body">
          {/* Meta */}
          <div>
            <div className="erp-drawer-section-title">Action</div>
            <div className="erp-drawer-rationale">
              <strong style={{ color: 'var(--green)', fontFamily: 'var(--font-mono)' }}>
                {entry.action_type}
              </strong>
              {entry.document_id && (
                <span style={{ marginLeft: 10, color: 'var(--signal)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                  → {entry.document_id}
                </span>
              )}
            </div>
          </div>

          {/* Rationale */}
          {entry.rationale && (
            <div>
              <div className="erp-drawer-section-title">Agent Rationale</div>
              <div className="erp-drawer-rationale">{entry.rationale}</div>
            </div>
          )}

          {/* Meta grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {[
              ['ERP Type',   entry.erp_type],
              ['Agent',      entry.agent_name],
              ['Timestamp',  fmtDate(entry.timestamp)],
              ['Run ID',     entry.run_id ? entry.run_id.slice(0, 8) + '…' : '—'],
            ].map(([label, val]) => (
              <div key={label} className="erp-data-card" style={{ padding: '8px 10px' }}>
                <div className="erp-data-card-label">{label}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text)' }}>{val || '—'}</div>
              </div>
            ))}
          </div>

          {/* Payload before */}
          <div>
            <div className="erp-drawer-section-title">Payload — Before</div>
            <pre className="erp-json-block">{beforeStr || 'null'}</pre>
          </div>

          {/* Payload after */}
          <div>
            <div className="erp-drawer-section-title">Payload — After (ERP Response)</div>
            <pre className="erp-json-block">{afterStr || 'null'}</pre>
          </div>

          {/* Idempotency */}
          {entry.idempotency_key && (
            <div>
              <div className="erp-drawer-section-title">Idempotency Key</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)', padding: '4px 0' }}>
                {entry.idempotency_key}
              </div>
            </div>
          )}

          {/* Deep-link to Agent Reasoning */}
          {entry.run_id && (
            <button
              className="erp-drawer-link"
              onClick={() => { navigate(`/agent-reasoning?run_id=${entry.run_id}&highlight=${entry.agent_name || ''}`); onClose(); }}
            >
              ⬡ View Agent Reasoning →
            </button>
          )}
        </div>
      </div>
    </>
  )
}

// ── READ Panel ─────────────────────────────────────────────────────────────────

function ReadPanel({ plants, erpType }) {
  const [invByPlant,  setInvByPlant]  = useState({})
  const [mechByPlant, setMechByPlant] = useState({})
  const [loading,     setLoading]     = useState(false)

  const load = useCallback(async () => {
    if (!plants.length) return
    setLoading(true)
    const invResults  = {}
    const mechResults = {}
    await Promise.allSettled(
      plants.slice(0, 6).map(async (p) => {
        try {
          const inv  = await getErpInventory(p)
          const mech = await getErpMachines(p)
          invResults[p]  = inv.inventory?.[0]  || null
          mechResults[p] = mech.machines?.[0]  || null
        } catch { /* ignore */ }
      })
    )
    setInvByPlant(invResults)
    setMechByPlant(mechResults)
    setLoading(false)
  }, [plants, erpType]) // eslint-disable-line

  useEffect(() => { load() }, [load])

  return (
    <div className="erp-panel read">
      <div className="erp-panel-header">
        <span className="erp-panel-icon">📥</span>
        <span className="erp-panel-title read">READ</span>
        <span className="erp-panel-sub">Live pull from {ADAPTER_LABELS[erpType] || erpType}</span>
        {loading && <div className="erp-spinner" />}
      </div>
      <div className="erp-panel-body">
        {plants.slice(0, 6).map((p) => {
          const inv  = invByPlant[p]
          const mech = mechByPlant[p]
          const short = p.split('(')[0].trim()
          return (
            <div key={p} className="erp-plant-row">
              <div className="erp-plant-name">{short}</div>
              <div className="erp-plant-stats">
                {inv && (
                  <>
                    <span className="erp-stat-chip">
                      📦 {(inv.qty || inv.LABST || 0).toLocaleString()} units
                    </span>
                    <span className="erp-stat-chip">
                      ⚠ Threshold {(inv.threshold || inv.MINBE || 20000).toLocaleString()}
                    </span>
                  </>
                )}
                {mech && (
                  <>
                    <span className="erp-stat-chip">
                      ⬡ OEE {(mech.oee_pct || 0).toFixed(1)}%
                    </span>
                    <span className="erp-stat-chip">
                      🌡 {(mech.temp_c || 0).toFixed(0)}°C
                    </span>
                    <span className="erp-stat-chip">
                      TTF {(mech.ttf_hrs || 0).toFixed(0)}h
                    </span>
                  </>
                )}
                {!inv && !mech && (
                  <span className="erp-stat-chip">Pulling…</span>
                )}
              </div>
            </div>
          )
        })}
        {!plants.length && (
          <div className="erp-empty">
            <span className="erp-empty-icon">📭</span>
            No plants loaded. Run agents first.
          </div>
        )}
      </div>
    </div>
  )
}

// ── WRITE Panel ────────────────────────────────────────────────────────────────

function WritePanel({ auditRows, onExplain, plants }) {
  const [plantSel,   setPlantSel]   = useState('')
  const [qty,        setQty]        = useState(500)
  const [pushing,    setPushing]    = useState(false)
  const [pushResult, setPushResult] = useState(null)

  const writeRows = (auditRows || []).filter(r =>
    ['WRITE_PROD_ORDER', 'WRITE_PO', 'MANUAL_PUSH'].includes(r.action_type)
  ).slice(0, 20)

  const handlePush = async () => {
    const plant = plantSel || plants[0] || 'Plant 1'
    setPushing(true)
    setPushResult(null)
    try {
      const res = await pushErpOrder({ plant, qty: parseInt(qty, 10) })
      setPushResult({ ok: true, doc_id: res.doc_id || res.AUFNR || res.name })
    } catch (e) {
      setPushResult({ ok: false, msg: e.message })
    } finally {
      setPushing(false)
    }
  }

  return (
    <div className="erp-panel write" style={{ display: 'flex', flexDirection: 'column' }}>
      <div className="erp-panel-header">
        <span className="erp-panel-icon">📤</span>
        <span className="erp-panel-title write">WRITE</span>
        <span className="erp-panel-sub">{writeRows.length} orders pushed</span>
      </div>
      <div className="erp-panel-body" style={{ flex: 1 }}>
        {writeRows.length === 0 && (
          <div className="erp-empty">
            <span className="erp-empty-icon">📭</span>
            No write actions yet. Run agents or push an order below.
          </div>
        )}
        {writeRows.map((r) => (
          <div key={r.id} className="erp-order-row">
            <span className="erp-doc-id">{r.document_id || '—'}</span>
            <span className="erp-order-meta">{r.agent_name} · {fmtDate(r.timestamp)}</span>
            <span className={`erp-idem-chip ${r.status === 'duplicate' ? 'dup' : ''}`}>
              {r.status === 'duplicate' ? 'DUP ✓' : '✓ IDEM'}
            </span>
            <StatusBadge status={r.status} />
            <button className="erp-explain-btn" onClick={() => onExplain(r)}>
              Explain ▸
            </button>
          </div>
        ))}
        {pushResult && (
          <div className="erp-order-row" style={{ borderColor: pushResult.ok ? 'var(--green)' : 'var(--red)' }}>
            {pushResult.ok
              ? <><span className="erp-doc-id">{pushResult.doc_id}</span><StatusBadge status="CREATED" /></>
              : <span style={{ color: 'var(--red)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{pushResult.msg}</span>
            }
          </div>
        )}
      </div>
      {/* Manual push bar */}
      <div className="erp-push-bar">
        <select
          className="erp-push-input"
          value={plantSel}
          onChange={e => setPlantSel(e.target.value)}
          style={{ maxWidth: 160 }}
        >
          <option value="">Select plant…</option>
          {plants.map(p => (
            <option key={p} value={p}>{p.split('(')[0].trim()}</option>
          ))}
        </select>
        <input
          className="erp-push-input"
          type="number"
          min={1}
          max={9999}
          value={qty}
          onChange={e => setQty(e.target.value)}
          placeholder="Qty"
          style={{ maxWidth: 80 }}
        />
        <button className="erp-push-btn" disabled={pushing} onClick={handlePush} id="erp-push-order-btn">
          {pushing ? '…' : '⬆ Push'}
        </button>
      </div>
    </div>
  )
}

// ── LISTEN Panel ───────────────────────────────────────────────────────────────

function ListenPanel({ events }) {
  return (
    <div className="erp-panel listen">
      <div className="erp-panel-header">
        <span className="erp-panel-icon">📡</span>
        <span className="erp-panel-title listen">LISTEN</span>
        <span className="erp-panel-sub">{events.length} events received</span>
      </div>
      <div className="erp-panel-body">
        {events.length === 0 && (
          <div className="erp-empty">
            <span className="erp-empty-icon">📡</span>
            Waiting for ERP events…
          </div>
        )}
        {events.map((ev) => (
          <div key={ev.id || ev.event_id} className="erp-event-row">
            <EventBadge type={ev.event_type} />
            <div className="erp-event-info">
              <div className="erp-event-plant">{ev.plant || 'Global'}</div>
              <div className="erp-event-meta">{fmtDate(ev.received_at)}</div>
            </div>
            {ev.triggered_agent && (
              <span className="erp-agent-chip">→ {ev.triggered_agent}</span>
            )}
            {ev.replan_triggered ? (
              <span className="erp-status-badge success" style={{ fontSize: 9 }}>REPLAN</span>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── EXPLAIN Panel ──────────────────────────────────────────────────────────────

function ExplainPanel({ auditRows, onExplain }) {
  const [query, setQuery] = useState('')

  const filtered = (auditRows || []).filter(r => {
    if (!query) return true
    const q = query.toLowerCase()
    return (
      (r.action_type || '').toLowerCase().includes(q) ||
      (r.document_id || '').toLowerCase().includes(q) ||
      (r.agent_name  || '').toLowerCase().includes(q) ||
      (r.rationale   || '').toLowerCase().includes(q)
    )
  })

  return (
    <div className="erp-panel explain">
      <div className="erp-panel-header">
        <span className="erp-panel-icon">🔍</span>
        <span className="erp-panel-title explain">EXPLAIN</span>
        <span className="erp-panel-sub">{filtered.length} audit entries</span>
      </div>
      <div className="erp-panel-body">
        <input
          className="erp-audit-search"
          placeholder="Search action, doc ID, agent…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          id="erp-audit-search"
        />
        {filtered.length === 0 && (
          <div className="erp-empty">
            <span className="erp-empty-icon">🗂</span>
            No audit entries match your search.
          </div>
        )}
        {filtered.slice(0, 25).map((r) => (
          <div key={r.id} className="erp-audit-row" onClick={() => onExplain(r)} role="button" tabIndex={0}
               onKeyDown={e => e.key === 'Enter' && onExplain(r)}>
            <span className="erp-audit-ts">{fmtDate(r.timestamp)}</span>
            <span className="erp-audit-action">{r.action_type}</span>
            <span className="erp-audit-doc">{r.document_id || r.erp_type || '—'}</span>
            <StatusBadge status={r.status} />
            <span className="erp-audit-agent">{r.agent_name || '—'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function ERPIntegration() {
  const [erpStatus,   setErpStatus]   = useState(null)
  const [auditRows,   setAuditRows]   = useState([])
  const [events,      setEvents]      = useState([])
  const [plants,      setPlants]      = useState([])
  const [drawerEntry, setDrawerEntry] = useState(null)
  const [switchTarget, setSwitchTarget] = useState('sap_mock')
  const [switching,   setSwitching]   = useState(false)
  const [switchMsg,   setSwitchMsg]   = useState(null)
  const pollRef = useRef(null)

  // ── Data fetching ─────────────────────────────────────────────────────────

  const loadAll = useCallback(async () => {
    try {
      const [s, a, e, p] = await Promise.allSettled([
        getErpStatus(),
        getErpAudit({ limit: 50 }),
        getErpEvents({ limit: 50 }),
        getPlants(),
      ])
      if (s.status === 'fulfilled') setErpStatus(s.value)
      if (a.status === 'fulfilled') setAuditRows(a.value?.rows || [])
      if (e.status === 'fulfilled') setEvents(e.value?.events || [])
      if (p.status === 'fulfilled') setPlants((p.value?.plants || []).map(pl => pl.name))
    } catch { /* silently ignore */ }
  }, [])

  useEffect(() => {
    loadAll()
    pollRef.current = setInterval(loadAll, 15000)
    return () => clearInterval(pollRef.current)
  }, [loadAll])

  // ── Adapter switch (HITL-gated) ───────────────────────────────────────────

  const handleSwitch = async () => {
    setSwitching(true)
    setSwitchMsg(null)
    try {
      const res = await switchErpAdapter({ adapter: switchTarget })
      if (res.status === 'pending_approval') {
        setSwitchMsg({
          type: 'hitl',
          text: `Switch queued as HITL item #${res.hitl_id}. Go to HITL Inbox to approve.`,
          hitlId: res.hitl_id,
        })
      } else if (res.status === 'no_change') {
        setSwitchMsg({ type: 'info', text: 'Already using this adapter.' })
      } else {
        setSwitchMsg({ type: 'ok', text: `Adapter switched to ${switchTarget}.` })
      }
      await loadAll()
    } catch (e) {
      setSwitchMsg({ type: 'err', text: e.message })
    } finally {
      setSwitching(false)
    }
  }

  // ── Derived state ─────────────────────────────────────────────────────────

  const erpType    = erpStatus?.erp_type || 'none'
  const health     = erpStatus?.status   || 'unknown'
  const writeOn    = erpStatus?.write_enabled
  const pending    = erpStatus?.pending_switch
  const pendingId  = erpStatus?.pending_hitl_id

  const navigate = useNavigate()

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="erp-page">

      {/* ── 1. Connection Banner ───────────────────────────────────────── */}
      <div className="erp-banner">
        <div className="erp-banner-left">
          <HealthDot status={health} />
          <div>
            <div className="erp-banner-title">ACTIVE ERP CONNECTION</div>
            <AdapterBadge type={erpType} />
          </div>
          <span className={`erp-write-badge ${writeOn ? 'on' : 'off'}`}>
            {writeOn ? 'Write ON' : 'Write OFF'}
          </span>
          {pending && (
            <span className="erp-hitl-notice">
              ⏳ Switch → {ADAPTER_LABELS[pending] || pending} pending HITL #{pendingId}
            </span>
          )}
        </div>

        <div className="erp-banner-right">
          {erpStatus?.latency_ms != null && (
            <span className="erp-banner-meta">{erpStatus.latency_ms}ms latency</span>
          )}
          <span className="erp-banner-meta">Poll {erpStatus?.poll_interval_secs || 30}s</span>

          <select
            className="erp-switch-select"
            value={switchTarget}
            onChange={e => { setSwitchTarget(e.target.value); setSwitchMsg(null) }}
            disabled={switching || !!pending}
            id="erp-adapter-select"
          >
            <option value="sap_mock">SAP S/4HANA Mock</option>
            <option value="odoo_mock">Odoo 17 Mock</option>
            <option value="csv">CSV / Local</option>
          </select>

          <button
            className="erp-switch-btn"
            disabled={switching || !!pending || switchTarget === erpType}
            onClick={handleSwitch}
            id="erp-switch-btn"
          >
            {switching ? '…' : 'Request Switch'}
          </button>
        </div>

        {/* Switch message */}
        {switchMsg && (
          <div style={{ width: '100%', marginTop: 4 }}>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: switchMsg.type === 'hitl' ? 'var(--amber)'
                   : switchMsg.type === 'err'  ? 'var(--red)'
                   : 'var(--green)',
            }}>
              {switchMsg.text}
              {switchMsg.type === 'hitl' && (
                <button
                  onClick={() => navigate('/hitl')}
                  style={{ marginLeft: 8, background: 'none', border: 'none', color: 'var(--primary)',
                           fontFamily: 'var(--font-mono)', fontSize: 11, cursor: 'pointer', textDecoration: 'underline' }}
                >
                  Go to HITL Inbox →
                </button>
              )}
            </span>
          </div>
        )}
      </div>

      {/* ── 2–5. 4-panel grid ──────────────────────────────────────────── */}
      <div className="erp-grid">
        <ReadPanel    plants={plants} erpType={erpType} />
        <WritePanel   auditRows={auditRows} onExplain={setDrawerEntry} plants={plants} />
        <ListenPanel  events={events} />
        <ExplainPanel auditRows={auditRows} onExplain={setDrawerEntry} />
      </div>

      {/* ── Detail drawer ──────────────────────────────────────────────── */}
      {drawerEntry && (
        <AuditDrawer entry={drawerEntry} onClose={() => setDrawerEntry(null)} />
      )}
    </div>
  )
}
