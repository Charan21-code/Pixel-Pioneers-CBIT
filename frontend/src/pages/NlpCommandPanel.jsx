import { useState, useEffect, useCallback, useRef } from 'react'
import { Send, MessageSquare, Zap, RefreshCw } from 'lucide-react'
import * as api from '../api/client'

const SUGGESTED = [
  'What is the current system health?',
  'How many pending HITL approvals are there?',
  'Which facility has the lowest inventory?',
  'What is the 7-day demand forecast?',
  'Are there any critical machine alerts?',
  'What is the current carbon compliance status?',
  'What is the finance gate decision?',
  'Show me the schedule utilisation across all plants.',
  'Approve all pending procurement items',
  'What are the active conflicts in the system?',
]

const INTENT_COLORS = {
  query: 'var(--cyan)',
  approve: 'var(--green)',
  reject: 'var(--red)',
  escalate: 'var(--amber)',
  simulate: 'var(--purple)',
  reconfigure: 'var(--amber)',
}

function Message({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`chat-msg ${isUser ? 'user' : 'assistant'}`}>
      <div className={`chat-avatar ${isUser ? 'user' : 'assist'}`}>
        {isUser ? '👤' : '🤖'}
      </div>
      <div>
        <div className={`chat-bubble ${isUser ? 'user' : 'assist'}`}>
          {msg.content}
        </div>
        {msg.meta && (
          <div className="chat-meta" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', paddingLeft: 4 }}>
            {msg.meta.intent && (
              <span style={{ color: INTENT_COLORS[msg.meta.intent] || 'var(--text-muted)' }}>
                Intent: {msg.meta.intent}
              </span>
            )}
            {msg.meta.agent && <span>Agent: {msg.meta.agent}</span>}
            {msg.meta.confidence_pct && (
              <span>Confidence: {msg.meta.confidence_pct}%</span>
            )}
            {msg.meta.action_result?.action_taken && (
              <span style={{ color: 'var(--green)' }}>✅ {msg.meta.action_result.action_taken}</span>
            )}
            <span>{new Date(msg.ts).toLocaleTimeString()}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default function NlpCommandPanel() {
  const [messages, setMessages] = useState([{
    role: 'assistant',
    content: '🤖 OPS//CORE Tactical AI online. Ask me anything about the production system, or give me a command to approve/reject HITL items, escalate issues, or run simulations.',
    ts: Date.now(),
  }])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [plants, setPlants] = useState([])
  const [selPlant, setSelPlant] = useState('')
  const [ollamaOnline, setOllamaOnline] = useState(null)  // null=checking, true=online, false=offline
  const endRef = useRef(null)

  useEffect(() => {
    api.getPlants().then(d => setPlants(d.plants?.map(p => p.name) || [])).catch(() => { })
  }, [])

  // Ping Ollama availability via backend health
  useEffect(() => {
    const checkOllama = async () => {
      try {
        const res = await fetch('http://192.168.137.97:11434/api/tags', { signal: AbortSignal.timeout(3000) })
        setOllamaOnline(res.ok)
      } catch {
        setOllamaOnline(false)
      }
    }
    checkOllama()
    const id = setInterval(checkOllama, 30000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = useCallback(async (query) => {
    if (!query.trim()) return
    const userMsg = { role: 'user', content: query, ts: Date.now() }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await api.nlpQuery({ query, selected_plant: selPlant || undefined })
      const assistMsg = {
        role: 'assistant',
        content: res.response || 'No response generated.',
        ts: Date.now(),
        meta: {
          intent: res.intent,
          agent: res.agent,
          confidence_pct: res.confidence_pct,
          params: res.params,
          action_result: res.action_result,
        },
      }
      setMessages(prev => [...prev, assistMsg])
    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `⚠️ Error: ${e.message}`,
        ts: Date.now(),
      }])
    } finally {
      setLoading(false)
    }
  }, [selPlant])

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) }
  }

  return (
    <div>
      {/* Header controls */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <label className="form-label">Context Plant (optional)</label>
          <select className="input" value={selPlant} onChange={e => setSelPlant(e.target.value)}>
            <option value="">All Plants</option>
            {plants.map(p => <option key={p} value={p}>{p.split('(')[0].trim()}</option>)}
          </select>
        </div>
        <div style={{ marginTop: 20 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setMessages([{
            role: 'assistant', content: '🤖 Conversation cleared. How can I help?', ts: Date.now()
          }])}>
            <RefreshCw size={13} /> Clear
          </button>
        </div>
      </div>

      {/* Info */}
      <div className="info-box" style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ flex: 1 }}>
          <b>💡 Supported commands:</b> Ask questions about any agent, approve/reject HITL items, escalate issues, or query system status.
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, whiteSpace: 'nowrap' }}>
          {ollamaOnline === null && <span style={{ color: 'var(--text-muted)' }}>🔄 Checking LLM...</span>}
          {ollamaOnline === true && <span style={{ color: 'var(--green)', fontWeight: 600 }}>🟢 Ollama LLM Online — rich AI responses active</span>}
          {ollamaOnline === false && <span style={{ color: 'var(--amber)', fontWeight: 600 }}>🟡 Ollama offline — using smart heuristic responses</span>}
        </div>
      </div>

      {/* Suggested Queries */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Quick Commands
        </div>
        <div className="tag-list">
          {SUGGESTED.map((s, i) => (
            <button
              key={i}
              className="tag"
              style={{ cursor: 'pointer', transition: 'all 0.15s' }}
              onClick={() => send(s)}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Chat window */}
      <div className="chat-container">
        <div className="chat-messages">
          {messages.map((msg, i) => <Message key={i} msg={msg} />)}
          {loading && (
            <div className="chat-msg assistant">
              <div className="chat-avatar assist">🤖</div>
              <div className="chat-bubble assist" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
                Processing command...
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        <div className="chat-input-row">
          <input
            className="input"
            style={{ flex: 1, fontSize: 13 }}
            placeholder="Ask a question or give a command... (Enter to send)"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            disabled={loading}
          />
          <button
            className="btn btn-primary"
            onClick={() => send(input)}
            disabled={loading || !input.trim()}
          >
            <Send size={14} /> Send
          </button>
        </div>
      </div>

      {/* Command Reference */}
      <div className="two-col" style={{ marginTop: 20 }}>
        <div className="card">
          <div className="card-header"><div className="card-title">📖 Command Reference</div></div>
          {[
            ['Query', 'var(--cyan)', 'What is the system health? / Show demand forecast'],
            ['Approve', 'var(--green)', 'Approve item #3 / Approve pending procurement'],
            ['Reject', 'var(--red)', 'Reject item #5 because over budget'],
            ['Escalate', 'var(--amber)', 'Escalate machine alert at Plant A to HITL'],
            ['Simulate', 'var(--purple)', 'What if Plant B has 6 hours downtime?'],
            ['Reconfigure', 'var(--amber)', 'Set workforce to 80% at Foxconn'],
          ].map(([intent, color, example]) => (
            <div key={intent} className="stat-row">
              <span>
                <span style={{ color, fontWeight: 600, fontSize: 12, fontFamily: 'var(--font-mono)' }}>[{intent}]</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>{example}</span>
              </span>
            </div>
          ))}
        </div>

        <div className="card">
          <div className="card-header"><div className="card-title">🎯 Intent Detection</div></div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.8 }}>
            <p>The system uses a <b>heuristic intent parser</b> that understands:</p>
            <ul style={{ marginTop: 8, paddingLeft: 16 }}>
              <li>Plant/facility references (partial names ok)</li>
              <li>Numeric quantities and percentages</li>
              <li>HITL item IDs (e.g. "item #3")</li>
              <li>Action keywords (approve, reject, escalate)</li>
              <li>Domain keywords (finance, carbon, maintenance...)</li>
            </ul>
            <p style={{ marginTop: 8 }}>When Ollama is active, responses use LLM reasoning for richer answers.</p>
          </div>
        </div>
      </div>
    </div>
  )
}
