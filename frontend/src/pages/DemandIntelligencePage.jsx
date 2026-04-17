import Plot from "react-plotly.js";

const DEMAND_SERIES = {
  periods: ["W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8"],
  forecastUnits: [820, 860, 910, 980, 1040, 1010, 1095, 1140],
  marketSignal: [62, 66, 68, 72, 77, 74, 80, 84]
};

function DemandIntelligencePage() {
  return (
    <section className="phase-three-shell">
      <header className="glass-panel phase-three-header">
        <p className="page-kicker">Phase 3</p>
        <h2>Demand Intelligence</h2>
        <p>Forecast trend and market pressure are visualized together for fast intake diagnostics.</p>
      </header>

      <article className="glass-panel analytics-card">
        <div className="analytics-card-head">
          <h3>Dual-Axis Demand Projection</h3>
          <p>Left axis: forecast units | Right axis: market signal</p>
        </div>
        <Plot
          className="plot-surface"
          data={[
            {
              x: DEMAND_SERIES.periods,
              y: DEMAND_SERIES.forecastUnits,
              name: "Forecast Units",
              yaxis: "y",
              type: "scatter",
              mode: "lines+markers",
              line: { shape: "spline", width: 3, color: "#06b6d4" },
              marker: { color: "#22d3ee", size: 6 }
            },
            {
              x: DEMAND_SERIES.periods,
              y: DEMAND_SERIES.marketSignal,
              name: "Market Signal",
              yaxis: "y2",
              type: "scatter",
              mode: "lines+markers",
              line: { shape: "spline", width: 3, color: "#f59e0b" },
              marker: { color: "#fbbf24", size: 6 }
            }
          ]}
          layout={{
            template: "plotly_dark",
            autosize: true,
            height: 360,
            margin: { l: 55, r: 55, t: 20, b: 45 },
            paper_bgcolor: "rgba(0,0,0,0)",
            plot_bgcolor: "rgba(2, 6, 23, 0.36)",
            legend: {
              orientation: "h",
              yanchor: "bottom",
              y: 1.02,
              xanchor: "left",
              x: 0
            },
            xaxis: {
              gridcolor: "rgba(148, 163, 184, 0.16)",
              tickfont: { color: "#cbd5e1" }
            },
            yaxis: {
              title: "Units",
              gridcolor: "rgba(148, 163, 184, 0.16)",
              tickfont: { color: "#67e8f9" },
              titlefont: { color: "#67e8f9" }
            },
            yaxis2: {
              title: "Signal",
              overlaying: "y",
              side: "right",
              tickfont: { color: "#fcd34d" },
              titlefont: { color: "#fcd34d" }
            }
          }}
          config={{ responsive: true, displaylogo: false }}
          useResizeHandler
        />
      </article>

      <article className="glass-panel agent-insights">
        <p className="agent-insights-label">Forecaster Agent Insights</p>
        <p>
          Demand acceleration around <strong>W5-W8</strong> is driven by recurring express orders from two key buyers.
          Intake risk is moderate unless Plant-3 downtime extends beyond the next 12 hours.
        </p>
      </article>
    </section>
  );
}

export default DemandIntelligencePage;
