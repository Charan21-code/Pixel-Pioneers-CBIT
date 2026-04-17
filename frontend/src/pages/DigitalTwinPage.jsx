import { useMemo, useState } from "react";
import Plot from "react-plotly.js";

const SIMULATION_POINTS = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"];

function generateSimulationSeries({ demandShiftPct, overtimeHours, maintenanceBufferPct, scrapRatePct }) {
  const baseline = [910, 940, 965, 1000, 1035, 1020, 1060, 1085];

  const proposed = baseline.map((point) => {
    const demandFactor = 1 + demandShiftPct / 100;
    const overtimeFactor = 1 + overtimeHours * 0.012;
    const maintenanceFactor = 1 - maintenanceBufferPct * 0.005;
    const scrapFactor = 1 - scrapRatePct * 0.008;
    return Math.round(point * demandFactor * overtimeFactor * maintenanceFactor * scrapFactor);
  });

  return { baseline, proposed };
}

function DigitalTwinPage() {
  const [controls, setControls] = useState({
    demandShiftPct: 8,
    overtimeHours: 3,
    maintenanceBufferPct: 12,
    scrapRatePct: 4
  });
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState([
    {
      role: "assistant",
      content: "Mini-Ollama panel ready. Ask what-if questions and I will summarize parameter impact."
    }
  ]);

  const simulation = useMemo(() => generateSimulationSeries(controls), [controls]);

  const baselineTotal = simulation.baseline.reduce((sum, value) => sum + value, 0);
  const proposedTotal = simulation.proposed.reduce((sum, value) => sum + value, 0);
  const absoluteVariance = proposedTotal - baselineTotal;
  const variancePct = ((absoluteVariance / baselineTotal) * 100).toFixed(1);

  const updateControl = (key, value) => {
    setControls((previous) => ({ ...previous, [key]: Number(value) }));
  };

  const sendChat = () => {
    const message = chatInput.trim();
    if (!message) {
      return;
    }

    const assistantReply = `Projected output variance is ${variancePct}% with current sliders. Highest sensitivity is tied to demand shift and overtime hours.`;

    setChatMessages((currentMessages) => [
      ...currentMessages,
      { role: "user", content: message },
      { role: "assistant", content: assistantReply }
    ]);
    setChatInput("");
  };

  return (
    <section className="phase-four-shell">
      <header className="glass-panel phase-three-header">
        <p className="page-kicker">Phase 4</p>
        <h2>Digital Twin Simulation</h2>
        <p>Adjust scenario levers and inspect outcome variance before committing the next plan revision.</p>
      </header>

      <section className="digital-twin-layout">
        <aside className="glass-panel twin-controls">
          <h3>Scenario Inputs</h3>

          <label className="slider-field">
            <span>Demand Shift (%)</span>
            <input
              type="range"
              min="-15"
              max="20"
              value={controls.demandShiftPct}
              onChange={(event) => updateControl("demandShiftPct", event.target.value)}
            />
            <strong>{controls.demandShiftPct}%</strong>
          </label>

          <label className="slider-field">
            <span>Overtime (hours)</span>
            <input
              type="range"
              min="0"
              max="8"
              value={controls.overtimeHours}
              onChange={(event) => updateControl("overtimeHours", event.target.value)}
            />
            <strong>{controls.overtimeHours}h</strong>
          </label>

          <label className="slider-field">
            <span>Maintenance Buffer (%)</span>
            <input
              type="range"
              min="0"
              max="30"
              value={controls.maintenanceBufferPct}
              onChange={(event) => updateControl("maintenanceBufferPct", event.target.value)}
            />
            <strong>{controls.maintenanceBufferPct}%</strong>
          </label>

          <label className="slider-field">
            <span>Scrap Rate (%)</span>
            <input
              type="range"
              min="1"
              max="10"
              value={controls.scrapRatePct}
              onChange={(event) => updateControl("scrapRatePct", event.target.value)}
            />
            <strong>{controls.scrapRatePct}%</strong>
          </label>
        </aside>

        <article className="glass-panel twin-results">
          <div className="twin-results-head">
            <h3>Outcome Projection</h3>
            <p>Area chart compares baseline vs scenario output trajectory.</p>
          </div>

          <Plot
            className="plot-surface"
            data={[
              {
                x: SIMULATION_POINTS,
                y: simulation.baseline,
                type: "scatter",
                mode: "lines",
                fill: "tozeroy",
                name: "Baseline",
                line: { shape: "spline", width: 2, color: "rgba(148, 163, 184, 0.9)" },
                fillcolor: "rgba(148, 163, 184, 0.18)"
              },
              {
                x: SIMULATION_POINTS,
                y: simulation.proposed,
                type: "scatter",
                mode: "lines",
                fill: "tozeroy",
                name: "Scenario",
                line: { shape: "spline", width: 3, color: "#06b6d4" },
                fillcolor: "rgba(6, 182, 212, 0.22)"
              }
            ]}
            layout={{
              template: "plotly_dark",
              autosize: true,
              height: 320,
              margin: { l: 55, r: 20, t: 12, b: 40 },
              paper_bgcolor: "rgba(0,0,0,0)",
              plot_bgcolor: "rgba(2, 6, 23, 0.35)",
              legend: { orientation: "h", yanchor: "bottom", y: 1.01, x: 0 },
              xaxis: { gridcolor: "rgba(148,163,184,0.14)" },
              yaxis: { title: "Units", gridcolor: "rgba(148,163,184,0.16)" }
            }}
            config={{ responsive: true, displaylogo: false }}
            useResizeHandler
          />

          <section className="variance-metrics">
            <article className="variance-card">
              <p>Total Baseline</p>
              <strong>{baselineTotal}</strong>
            </article>
            <article className="variance-card">
              <p>Total Scenario</p>
              <strong>{proposedTotal}</strong>
            </article>
            <article className="variance-card variance-card-accent">
              <p>Variance</p>
              <strong>
                {absoluteVariance >= 0 ? "+" : ""}
                {absoluteVariance} ({variancePct}%)
              </strong>
            </article>
          </section>

          <section className="mini-chat">
            <h4>Mini-Ollama What-If</h4>
            <div className="mini-chat-log">
              {chatMessages.map((message, index) => (
                <div
                  key={`${message.role}-${index}`}
                  className={message.role === "user" ? "mini-chat-bubble mini-chat-user" : "mini-chat-bubble mini-chat-agent"}
                >
                  {message.content}
                </div>
              ))}
            </div>
            <div className="mini-chat-input-row">
              <input
                type="text"
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                placeholder="Ask: what if overtime is cut by 2 hours?"
              />
              <button type="button" onClick={sendChat}>
                Send
              </button>
            </div>
          </section>
        </article>
      </section>
    </section>
  );
}

export default DigitalTwinPage;
