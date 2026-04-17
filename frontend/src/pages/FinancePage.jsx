import Plot from "react-plotly.js";

const BUDGET_GAUGES = [
  { title: "OPEX Utilization", value: 74, threshold: 82 },
  { title: "CAPEX Utilization", value: 61, threshold: 75 },
  { title: "Logistics Spend", value: 79, threshold: 85 }
];

function FinancePage() {
  return (
    <section className="phase-four-shell">
      <header className="glass-panel phase-three-header">
        <p className="page-kicker">Phase 4</p>
        <h2>Finance</h2>
        <p>Budget utilization gauges highlight spend pressure before production commitments are finalized.</p>
      </header>

      <section className="gauge-grid">
        {BUDGET_GAUGES.map((gauge) => (
          <article key={gauge.title} className="glass-panel gauge-card">
            <h3>{gauge.title}</h3>
            <Plot
              className="plot-surface"
              data={[
                {
                  type: "indicator",
                  mode: "gauge+number",
                  value: gauge.value,
                  number: { suffix: "%" },
                  gauge: {
                    axis: { range: [0, 100], tickcolor: "#cbd5e1" },
                    bar: { color: "#06b6d4" },
                    bgcolor: "rgba(15,23,42,0.45)",
                    borderwidth: 0,
                    steps: [
                      { range: [0, 60], color: "rgba(16,185,129,0.26)" },
                      { range: [60, 80], color: "rgba(245,158,11,0.26)" },
                      { range: [80, 100], color: "rgba(239,68,68,0.26)" }
                    ],
                    threshold: {
                      line: { color: "#f43f5e", width: 3 },
                      thickness: 0.8,
                      value: gauge.threshold
                    }
                  }
                }
              ]}
              layout={{
                template: "plotly_dark",
                autosize: true,
                height: 270,
                margin: { l: 25, r: 25, t: 10, b: 10 },
                paper_bgcolor: "rgba(0,0,0,0)",
                font: { color: "#e2e8f0", family: "Outfit, Segoe UI, sans-serif" }
              }}
              config={{ responsive: true, displaylogo: false }}
              useResizeHandler
            />
          </article>
        ))}
      </section>
    </section>
  );
}

export default FinancePage;
