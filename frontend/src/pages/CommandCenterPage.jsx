const COMMAND_CENTER_DATA = {
  finalStatus: "blocked",
  statusMessage: "2 plants need intervention before next shift lock-in.",
  metrics: [
    { label: "Live Plants", value: "5", delta: "+1 vs last hour", tone: "good" },
    { label: "Orders At Risk", value: "3", delta: "-2 since mitigation", tone: "alert" },
    { label: "Avg OEE", value: "84.7%", delta: "+1.8% today", tone: "good" },
    { label: "Material Coverage", value: "2.4 days", delta: "Low for Plant-3", tone: "warn" }
  ],
  plants: [
    {
      id: "Plant-1",
      status: "good",
      machineHealth: "Healthy",
      inventoryHealth: "Stable",
      blocker: "No blocker"
    },
    {
      id: "Plant-2",
      status: "warn",
      machineHealth: "Vibration drift",
      inventoryHealth: "Watchlist",
      blocker: "Bearing inspection due"
    },
    {
      id: "Plant-3",
      status: "critical",
      machineHealth: "TTF threshold",
      inventoryHealth: "Steel coils low",
      blocker: "Urgent replenishment needed"
    },
    {
      id: "Plant-4",
      status: "good",
      machineHealth: "Healthy",
      inventoryHealth: "Stable",
      blocker: "No blocker"
    },
    {
      id: "Plant-5",
      status: "warn",
      machineHealth: "OEE trending down",
      inventoryHealth: "Tight",
      blocker: "Shift rebalance suggested"
    }
  ],
  operations: [
    { agent: "Orchestrator", action: "Escalated Plant-3 intake delay", minutesAgo: 2, impact: "high" },
    { agent: "InventoryAgent", action: "Re-prioritized steel lot #A42", minutesAgo: 9, impact: "medium" },
    { agent: "MechanicAgent", action: "Scheduled Plant-2 bearing check", minutesAgo: 15, impact: "medium" },
    { agent: "BuyerAgent", action: "Sent supplier expedite request", minutesAgo: 22, impact: "low" },
    { agent: "FinanceAgent", action: "Cleared overtime budget envelope", minutesAgo: 31, impact: "low" }
  ]
};

function metricToneClass(tone) {
  if (tone === "good") {
    return "metric-delta metric-delta-good";
  }
  if (tone === "warn") {
    return "metric-delta metric-delta-warn";
  }
  return "metric-delta metric-delta-alert";
}

function plantStatusClass(status) {
  if (status === "good") {
    return "plant-status-chip plant-status-good";
  }
  if (status === "warn") {
    return "plant-status-chip plant-status-warn";
  }
  return "plant-status-chip plant-status-critical";
}

function plantDotClass(status) {
  if (status === "good") {
    return "status-dot plant-dot-good";
  }
  if (status === "warn") {
    return "status-dot plant-dot-warn";
  }
  return "status-dot plant-dot-critical";
}

function bannerClass(finalStatus) {
  return finalStatus === "all_clear" ? "status-banner status-banner-ok" : "status-banner status-banner-blocked";
}

function impactClass(impact) {
  if (impact === "high") {
    return "impact-chip impact-chip-high";
  }
  if (impact === "medium") {
    return "impact-chip impact-chip-medium";
  }
  return "impact-chip impact-chip-low";
}

function CommandCenterPage() {
  return (
    <section className="command-center-shell">
      <header className={bannerClass(COMMAND_CENTER_DATA.finalStatus)}>
        <p className="status-banner-label">Orchestrator Final Status</p>
        <h2>{COMMAND_CENTER_DATA.finalStatus === "all_clear" ? "All Clear" : "Blocked"}</h2>
        <p>{COMMAND_CENTER_DATA.statusMessage}</p>
      </header>

      <section className="metric-grid">
        {COMMAND_CENTER_DATA.metrics.map((metric) => (
          <article key={metric.label} className="glass-panel metric-card">
            <p className="metric-label">{metric.label}</p>
            <p className="metric-value">{metric.value}</p>
            <p className={metricToneClass(metric.tone)}>{metric.delta}</p>
          </article>
        ))}
      </section>

      <section className="plant-grid">
        {COMMAND_CENTER_DATA.plants.map((plant) => (
          <article key={plant.id} className="glass-panel plant-card">
            <div className="plant-card-top">
              <h3>{plant.id}</h3>
              <span className={plantStatusClass(plant.status)}>
                <span className={plantDotClass(plant.status)} />
                {plant.status.toUpperCase()}
              </span>
            </div>
            <dl className="plant-details">
              <div>
                <dt>Machine</dt>
                <dd>{plant.machineHealth}</dd>
              </div>
              <div>
                <dt>Inventory</dt>
                <dd>{plant.inventoryHealth}</dd>
              </div>
              <div>
                <dt>Blocker</dt>
                <dd>{plant.blocker}</dd>
              </div>
            </dl>
          </article>
        ))}
      </section>

      <section className="glass-panel operations-feed">
        <div className="operations-header">
          <h3>Agent Operations Feed</h3>
          <p>Most recent actions are highlighted stronger to guide attention.</p>
        </div>

        <div className="operations-table-wrap">
          <table className="operations-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Action</th>
                <th>Impact</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {COMMAND_CENTER_DATA.operations.map((operation, index) => (
                <tr key={`${operation.agent}-${operation.minutesAgo}`} style={{ opacity: Math.max(1 - index * 0.14, 0.42) }}>
                  <td>{operation.agent}</td>
                  <td>{operation.action}</td>
                  <td>
                    <span className={impactClass(operation.impact)}>{operation.impact}</span>
                  </td>
                  <td>{operation.minutesAgo}m ago</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}

export default CommandCenterPage;
