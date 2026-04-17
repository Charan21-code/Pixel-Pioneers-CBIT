import Plot from "react-plotly.js";

const HOURS = ["-6h", "-5h", "-4h", "-3h", "-2h", "-1h", "Now"];

const TELEMETRY_SERIES = [
  {
    key: "ttf",
    title: "TTF",
    subtitle: "Time-to-Failure (hrs)",
    unit: "hrs",
    values: [52, 48, 43, 36, 30, 25, 21],
    yRange: [0, 60],
    zones: [
      { y0: 40, y1: 60, tone: "safe" },
      { y0: 24, y1: 40, tone: "warn" },
      { y0: 0, y1: 24, tone: "danger" }
    ]
  },
  {
    key: "oee",
    title: "OEE",
    subtitle: "Overall Equipment Effectiveness",
    unit: "%",
    values: [89, 88, 86, 84, 83, 82, 80],
    yRange: [60, 95],
    zones: [
      { y0: 85, y1: 95, tone: "safe" },
      { y0: 75, y1: 85, tone: "warn" },
      { y0: 60, y1: 75, tone: "danger" }
    ]
  },
  {
    key: "temp",
    title: "Temp",
    subtitle: "Bearing Temperature",
    unit: "C",
    values: [62, 64, 65, 69, 72, 76, 81],
    yRange: [50, 90],
    zones: [
      { y0: 50, y1: 72, tone: "safe" },
      { y0: 72, y1: 78, tone: "warn" },
      { y0: 78, y1: 90, tone: "danger" }
    ]
  },
  {
    key: "vib",
    title: "Vib",
    subtitle: "Vibration RMS",
    unit: "mm/s",
    values: [2.1, 2.3, 2.4, 2.8, 3.2, 3.6, 4.1],
    yRange: [1, 5],
    zones: [
      { y0: 1, y1: 3, tone: "safe" },
      { y0: 3, y1: 3.8, tone: "warn" },
      { y0: 3.8, y1: 5, tone: "danger" }
    ]
  }
];

function zoneColor(tone) {
  if (tone === "safe") {
    return "rgba(16, 185, 129, 0.15)";
  }
  if (tone === "warn") {
    return "rgba(245, 158, 11, 0.16)";
  }
  return "rgba(239, 68, 68, 0.16)";
}

function lineColor(metricKey) {
  if (metricKey === "ttf") {
    return "#22d3ee";
  }
  if (metricKey === "oee") {
    return "#34d399";
  }
  if (metricKey === "temp") {
    return "#f59e0b";
  }
  return "#c084fc";
}

function buildTelemetryLayout(metric) {
  return {
    template: "plotly_dark",
    autosize: true,
    height: 250,
    margin: { l: 46, r: 20, t: 10, b: 32 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(2, 6, 23, 0.3)",
    xaxis: {
      showgrid: false,
      tickfont: { color: "#cbd5e1", size: 10 }
    },
    yaxis: {
      range: metric.yRange,
      gridcolor: "rgba(148, 163, 184, 0.15)",
      tickfont: { color: "#cbd5e1", size: 10 }
    },
    shapes: metric.zones.map((zone) => ({
      type: "rect",
      xref: "paper",
      x0: 0,
      x1: 1,
      yref: "y",
      y0: zone.y0,
      y1: zone.y1,
      fillcolor: zoneColor(zone.tone),
      line: { width: 0 },
      layer: "below"
    }))
  };
}

function MachineHealthPage() {
  const ttfMetric = TELEMETRY_SERIES.find((metric) => metric.key === "ttf");
  const ttfLatest = ttfMetric.values[ttfMetric.values.length - 1];
  const showCriticalAlert = ttfLatest < 24;

  return (
    <section className="phase-three-shell">
      <header className="glass-panel phase-three-header">
        <p className="page-kicker">Phase 3</p>
        <h2>Machine Health</h2>
        <p>Small-multiple telemetry charts expose reliability drift and dangerous operating windows.</p>
      </header>

      {showCriticalAlert ? (
        <article className="machine-alert-card">
          <p className="machine-alert-label">Critical Alert</p>
          <h3>TTF under 24 hours</h3>
          <p>
            Immediate mechanic dispatch recommended. Current projected failure window is <strong>{ttfLatest} hrs</strong>.
          </p>
        </article>
      ) : null}

      <section className="telemetry-grid">
        {TELEMETRY_SERIES.map((metric) => {
          const latestValue = metric.values[metric.values.length - 1];

          return (
            <article key={metric.key} className="glass-panel telemetry-card">
              <div className="telemetry-card-head">
                <div>
                  <h3>{metric.title}</h3>
                  <p>{metric.subtitle}</p>
                </div>
                <span className="telemetry-latest">
                  {latestValue}
                  {metric.unit}
                </span>
              </div>

              <Plot
                className="plot-surface"
                data={[
                  {
                    x: HOURS,
                    y: metric.values,
                    type: "scatter",
                    mode: "lines+markers",
                    line: { shape: "spline", width: 3, color: lineColor(metric.key) },
                    marker: { color: lineColor(metric.key), size: 5 },
                    hovertemplate: `%{x}<br>%{y}${metric.unit}<extra></extra>`
                  }
                ]}
                layout={buildTelemetryLayout(metric)}
                config={{ responsive: true, displaylogo: false }}
                useResizeHandler
              />
            </article>
          );
        })}
      </section>
    </section>
  );
}

export default MachineHealthPage;
