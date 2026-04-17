import { useMemo, useState } from "react";

const INITIAL_PLANT_PLANS = [
  {
    id: "Plant-1",
    location: "North Hub",
    plannedUnits: 1240,
    maxCapacity: 1320,
    readiness: { finance: true, buyer: true, mechanic: true },
    shifts: [
      { shift: "A", line: "Line-1", targetUnits: 210, assignedUnits: 205 },
      { shift: "B", line: "Line-1", targetUnits: 210, assignedUnits: 208 },
      { shift: "C", line: "Line-2", targetUnits: 190, assignedUnits: 184 }
    ]
  },
  {
    id: "Plant-2",
    location: "West Hub",
    plannedUnits: 1110,
    maxCapacity: 1260,
    readiness: { finance: true, buyer: true, mechanic: false },
    shifts: [
      { shift: "A", line: "Line-3", targetUnits: 180, assignedUnits: 170 },
      { shift: "B", line: "Line-3", targetUnits: 180, assignedUnits: 172 },
      { shift: "C", line: "Line-4", targetUnits: 170, assignedUnits: 160 }
    ]
  },
  {
    id: "Plant-3",
    location: "Central Hub",
    plannedUnits: 980,
    maxCapacity: 1200,
    readiness: { finance: true, buyer: false, mechanic: false },
    shifts: [
      { shift: "A", line: "Line-5", targetUnits: 160, assignedUnits: 145 },
      { shift: "B", line: "Line-5", targetUnits: 165, assignedUnits: 142 },
      { shift: "C", line: "Line-6", targetUnits: 150, assignedUnits: 136 }
    ]
  }
];

function gateClass(isReady) {
  return isReady ? "readiness-gate readiness-gate-pass" : "readiness-gate readiness-gate-fail";
}

function gateLabel(isReady) {
  return isReady ? "CLEAR" : "PENDING";
}

function summaryTone(readiness) {
  const openCount = Object.values(readiness).filter((value) => !value).length;
  if (openCount === 0) {
    return "plant-level-chip plant-level-good";
  }
  if (openCount === 1) {
    return "plant-level-chip plant-level-warn";
  }
  return "plant-level-chip plant-level-critical";
}

function ProductionPlanPage() {
  const [plans, setPlans] = useState(INITIAL_PLANT_PLANS);
  const [selectedPlantId, setSelectedPlantId] = useState(INITIAL_PLANT_PLANS[0].id);

  const selectedPlant = useMemo(
    () => plans.find((plant) => plant.id === selectedPlantId) || plans[0],
    [plans, selectedPlantId]
  );

  const updateAssignedUnits = (plantId, rowIndex, nextValue) => {
    const parsedValue = Number(nextValue);
    const safeValue = Number.isFinite(parsedValue) ? Math.max(0, parsedValue) : 0;

    setPlans((currentPlans) =>
      currentPlans.map((plant) => {
        if (plant.id !== plantId) {
          return plant;
        }

        const nextShifts = plant.shifts.map((shift, shiftIndex) => {
          if (shiftIndex !== rowIndex) {
            return shift;
          }

          return { ...shift, assignedUnits: safeValue };
        });

        return { ...plant, shifts: nextShifts };
      })
    );
  };

  return (
    <section className="phase-four-shell">
      <header className="glass-panel phase-three-header">
        <p className="page-kicker">Phase 4</p>
        <h2>Production Plan</h2>
        <p>Plant-level planning can be expanded for detailed, editable shift assignments.</p>
      </header>

      <section className="plant-level-grid">
        {plans.map((plant) => {
          const gatePendingCount = Object.values(plant.readiness).filter((value) => !value).length;
          const utilization = Math.round((plant.plannedUnits / plant.maxCapacity) * 100);
          const isSelected = plant.id === selectedPlantId;

          return (
            <button
              key={plant.id}
              type="button"
              className={isSelected ? "glass-panel plant-level-card plant-level-card-active" : "glass-panel plant-level-card"}
              onClick={() => setSelectedPlantId(plant.id)}
            >
              <div className="plant-level-head">
                <h3>{plant.id}</h3>
                <span className={summaryTone(plant.readiness)}>
                  {gatePendingCount === 0 ? "READY" : `${gatePendingCount} BLOCKED`}
                </span>
              </div>
              <p>{plant.location}</p>
              <div className="plant-level-meta">
                <span>Planned: {plant.plannedUnits}</span>
                <span>Utilization: {utilization}%</span>
              </div>
            </button>
          );
        })}
      </section>

      <article className="glass-panel production-details">
        <div className="production-details-head">
          <h3>{selectedPlant.id} Execution Detail</h3>
          <p>Readiness gates and shift schedule can be reviewed before dispatch.</p>
        </div>

        <section className="readiness-grid">
          <div className={gateClass(selectedPlant.readiness.finance)}>
            <p className="readiness-title">FINANCE</p>
            <p className="readiness-state">{gateLabel(selectedPlant.readiness.finance)}</p>
          </div>
          <div className={gateClass(selectedPlant.readiness.buyer)}>
            <p className="readiness-title">BUYER</p>
            <p className="readiness-state">{gateLabel(selectedPlant.readiness.buyer)}</p>
          </div>
          <div className={gateClass(selectedPlant.readiness.mechanic)}>
            <p className="readiness-title">MECHANIC</p>
            <p className="readiness-state">{gateLabel(selectedPlant.readiness.mechanic)}</p>
          </div>
        </section>

        <div className="schedule-table-wrap">
          <table className="schedule-table">
            <thead>
              <tr>
                <th>Shift</th>
                <th>Line</th>
                <th>Target Units</th>
                <th>Assigned Units</th>
              </tr>
            </thead>
            <tbody>
              {selectedPlant.shifts.map((shift, index) => (
                <tr key={`${shift.shift}-${shift.line}`}>
                  <td>{shift.shift}</td>
                  <td>{shift.line}</td>
                  <td>{shift.targetUnits}</td>
                  <td className="assigned-column">
                    <input
                      type="number"
                      min="0"
                      value={shift.assignedUnits}
                      className="assigned-input"
                      onChange={(event) => updateAssignedUnits(selectedPlant.id, index, event.target.value)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
}

export default ProductionPlanPage;
