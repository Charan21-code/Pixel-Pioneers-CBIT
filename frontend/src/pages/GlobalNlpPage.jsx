import { useEffect, useRef, useState } from "react";

const INITIAL_MESSAGES = [
  {
    role: "agent",
    content:
      "Global NLP channel online. You can issue planning constraints, production targets, or escalation actions in plain language."
  }
];

const INTENT_RULES = [
  { keywords: ["overtime", "increase"], summary: "Overtime ceiling raised by +1h for the next cycle." },
  { keywords: ["overtime", "reduce"], summary: "Overtime ceiling reduced by -1h for cost control." },
  { keywords: ["plant-3", "priority"], summary: "Plant-3 dispatch priority moved to top queue." },
  { keywords: ["buffer", "inventory"], summary: "Safety stock buffer updated for high-risk materials." },
  { keywords: ["maintenance", "expedite"], summary: "Maintenance SLA escalated to urgent lane." }
];

function inferIntentSummary(message) {
  const lower = message.toLowerCase();
  const matchedRule = INTENT_RULES.find((rule) => rule.keywords.every((word) => lower.includes(word)));

  if (matchedRule) {
    return matchedRule.summary;
  }

  return "Constraint update acknowledged and orchestrator context has been refreshed.";
}

function GlobalNlpPage() {
  const [messages, setMessages] = useState(INITIAL_MESSAGES);
  const [inputValue, setInputValue] = useState("");
  const [toasts, setToasts] = useState([]);
  const toastTimers = useRef([]);

  useEffect(() => {
    return () => {
      toastTimers.current.forEach((timerId) => window.clearTimeout(timerId));
    };
  }, []);

  const pushToast = (text) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, text }]);

    const timerId = window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
      toastTimers.current = toastTimers.current.filter((value) => value !== timerId);
    }, 2600);

    toastTimers.current.push(timerId);
  };

  const sendMessage = () => {
    const message = inputValue.trim();
    if (!message) {
      return;
    }

    const intentSummary = inferIntentSummary(message);
    const agentReply = `Intent execution queued. ${intentSummary}`;

    setMessages((current) => [...current, { role: "user", content: message }, { role: "agent", content: agentReply }]);
    setInputValue("");
    pushToast(`Intent executed: ${intentSummary}`);
  };

  return (
    <section className="phase-five-shell">
      <header className="glass-panel phase-three-header">
        <p className="page-kicker">Phase 5</p>
        <h2>Global NLP Interface</h2>
        <p>Issue natural-language commands and monitor live execution confirmations with visible feedback.</p>
      </header>

      <article className="glass-panel nlp-chat-shell">
        <div className="nlp-chat-head">
          <h3>Execution Chat</h3>
          <p>User messages align right, agent responses align left.</p>
        </div>

        <div className="nlp-chat-log">
          {messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              className={message.role === "user" ? "nlp-bubble nlp-bubble-user" : "nlp-bubble nlp-bubble-agent"}
            >
              {message.content}
            </div>
          ))}
        </div>

        <div className="nlp-composer">
          <input
            type="text"
            value={inputValue}
            onChange={(event) => setInputValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                sendMessage();
              }
            }}
            placeholder="Type an instruction, for example: increase overtime by 1 hour for plant-3"
          />
          <button type="button" onClick={sendMessage}>
            Execute
          </button>
        </div>
      </article>

      <div className="toast-stack">
        {toasts.map((toast) => (
          <div key={toast.id} className="intent-toast">
            {toast.text}
          </div>
        ))}
      </div>
    </section>
  );
}

export default GlobalNlpPage;
