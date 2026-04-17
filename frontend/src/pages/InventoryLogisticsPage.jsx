const INVENTORY_ITEMS = [
  { material: "Steel Coil A42", plant: "Plant-3", remainingDays: 2.8, leadTimeDays: 4.0, stockLevel: 26 },
  { material: "Resin Batch R12", plant: "Plant-2", remainingDays: 6.4, leadTimeDays: 3.5, stockLevel: 58 },
  { material: "Bearing Kit BK9", plant: "Plant-5", remainingDays: 3.1, leadTimeDays: 3.2, stockLevel: 34 },
  { material: "Control Board CB7", plant: "Plant-1", remainingDays: 8.2, leadTimeDays: 5.0, stockLevel: 63 },
  { material: "Coolant Mix C1", plant: "Plant-4", remainingDays: 4.7, leadTimeDays: 2.5, stockLevel: 49 }
];

const MAX_DAY_SCALE = 10;

function statusForItem(item) {
  if (item.remainingDays <= item.leadTimeDays) {
    return "critical";
  }
  if (item.remainingDays <= item.leadTimeDays + 1.5) {
    return "warning";
  }
  return "healthy";
}

function statusLabel(status) {
  if (status === "critical") {
    return "Lead Time Breach";
  }
  if (status === "warning") {
    return "Buffer Tight";
  }
  return "Healthy Buffer";
}

function barToneClass(status) {
  if (status === "critical") {
    return "inventory-bar-remaining inventory-bar-critical";
  }
  if (status === "warning") {
    return "inventory-bar-remaining inventory-bar-warning";
  }
  return "inventory-bar-remaining inventory-bar-healthy";
}

function statusChipClass(status) {
  if (status === "critical") {
    return "inventory-status inventory-status-critical";
  }
  if (status === "warning") {
    return "inventory-status inventory-status-warning";
  }
  return "inventory-status inventory-status-healthy";
}

function InventoryLogisticsPage() {
  return (
    <section className="phase-three-shell">
      <header className="glass-panel phase-three-header">
        <p className="page-kicker">Phase 3</p>
        <h2>Inventory Logistics</h2>
        <p>Remaining stock runway is mapped against lead time thresholds to surface logistics collisions quickly.</p>
      </header>

      <section className="inventory-list">
        {INVENTORY_ITEMS.map((item) => {
          const status = statusForItem(item);
          const remainingPercent = Math.min((item.remainingDays / MAX_DAY_SCALE) * 100, 100);
          const leadPercent = Math.min((item.leadTimeDays / MAX_DAY_SCALE) * 100, 100);
          const depletedPercent = Math.max(100 - remainingPercent, 0);

          return (
            <article key={`${item.material}-${item.plant}`} className="glass-panel inventory-row">
              <div className="inventory-head">
                <div>
                  <h3>{item.material}</h3>
                  <p>
                    {item.plant} | {item.stockLevel}% stock level
                  </p>
                </div>
                <span className={statusChipClass(status)}>{statusLabel(status)}</span>
              </div>

              <div className="inventory-bar-wrap">
                <div className="inventory-bar-stack">
                  <div className={barToneClass(status)} style={{ width: `${remainingPercent}%` }} />
                  <div className="inventory-bar-depleted" style={{ width: `${depletedPercent}%` }} />
                  <div className="inventory-lead-marker" style={{ left: `${leadPercent}%` }}>
                    <span>Lead Time</span>
                  </div>
                </div>
              </div>

              <div className="inventory-meta">
                <p>Remaining: {item.remainingDays.toFixed(1)} days</p>
                <p>Lead Time: {item.leadTimeDays.toFixed(1)} days</p>
              </div>
            </article>
          );
        })}
      </section>
    </section>
  );
}

export default InventoryLogisticsPage;
