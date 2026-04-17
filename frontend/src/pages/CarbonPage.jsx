const HOURS = Array.from({ length: 24 }, (_, index) => index.toString().padStart(2, "0"));

const ENERGY_DENSITY = [
  {
    zone: "Plant-1",
    values: [18, 14, 12, 11, 10, 12, 22, 38, 46, 51, 56, 58, 62, 65, 60, 53, 47, 44, 50, 59, 63, 52, 34, 24]
  },
  {
    zone: "Plant-3",
    values: [21, 19, 16, 15, 13, 16, 28, 44, 55, 63, 72, 78, 81, 84, 79, 70, 62, 58, 66, 74, 77, 64, 43, 29]
  },
  {
    zone: "Plant-5",
    values: [17, 15, 13, 12, 11, 13, 24, 39, 48, 54, 61, 66, 69, 72, 68, 60, 51, 47, 56, 63, 66, 54, 36, 22]
  }
];

const SAVING_SUGGESTIONS = [
  { title: "Shift non-critical curing load from 12:00-14:00 to 16:00-18:00", tags: ["Peak Cut", "Medium Effort", "3.2% Savings"] },
  { title: "Batch compressor starts using staggered 20-minute windows", tags: ["Demand Smoothing", "Low Effort", "2.1% Savings"] },
  { title: "Switch Plant-3 standby profile to low-idle during forecast dips", tags: ["Idle Optimization", "Medium Effort", "1.7% Savings"] },
  { title: "Move nightly wash cycle one hour earlier to avoid tariff edge", tags: ["Tariff Avoidance", "Low Effort", "1.1% Savings"] }
];

function heatCellClass(value) {
  if (value >= 78) {
    return "heat-cell heat-cell-high";
  }
  if (value >= 58) {
    return "heat-cell heat-cell-warn";
  }
  return "heat-cell heat-cell-base";
}

function CarbonPage() {
  return (
    <section className="phase-four-shell">
      <header className="glass-panel phase-three-header">
        <p className="page-kicker">Phase 4</p>
        <h2>Carbon Insights</h2>
        <p>Hour-of-day energy density reveals peak windows and highlights where emissions can be reduced fastest.</p>
      </header>

      <article className="glass-panel carbon-heatmap-card">
        <div className="carbon-heatmap-head">
          <h3>Hour-of-Day Density Heatmap</h3>
          <p>Higher intensity marks heavier energy draw and carbon load periods.</p>
        </div>

        <div className="carbon-hour-labels">
          <span />
          {HOURS.map((hour) => (
            <span key={hour}>{hour}</span>
          ))}
        </div>

        <div className="carbon-heatmap-grid">
          {ENERGY_DENSITY.map((row) => (
            <div key={row.zone} className="heat-row">
              <p>{row.zone}</p>
              <div className="heat-row-cells">
                {row.values.map((value, index) => (
                  <span key={`${row.zone}-${index}`} className={heatCellClass(value)} title={`${row.zone} @ ${HOURS[index]}: ${value}`} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </article>

      <article className="glass-panel suggestions-card">
        <div className="carbon-heatmap-head">
          <h3>Actionable Cost-Saving Suggestions</h3>
          <p>Recommendations are presented as ready-to-queue actions.</p>
        </div>

        <div className="suggestion-list">
          {SAVING_SUGGESTIONS.map((suggestion) => (
            <div key={suggestion.title} className="suggestion-item">
              <p>{suggestion.title}</p>
              <div className="suggestion-tags">
                {suggestion.tags.map((tag) => (
                  <span key={`${suggestion.title}-${tag}`} className="pill-tag">
                    {tag}
                  </span>
                ))}
                <button type="button" className="pill-action">
                  Queue Action
                </button>
              </div>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}

export default CarbonPage;
