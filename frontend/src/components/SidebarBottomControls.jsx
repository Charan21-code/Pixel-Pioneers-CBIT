function SidebarBottomControls({ simulatedTime, isOllamaOnline, onStepForward, onResetClock }) {
  const formattedTime = new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    month: "short",
    year: "numeric"
  }).format(simulatedTime);

  return (
    <div className="sidebar-controls glass-panel-soft">
      <div className="control-block">
        <p className="control-label">Global Simulated Clock</p>
        <p className="control-value">{formattedTime}</p>
      </div>

      <div className="control-block">
        <p className="control-label">Ollama Connectivity</p>
        <div className="connectivity-row">
          <span className={isOllamaOnline ? "status-dot status-ok" : "status-dot status-error"} />
          <span className="control-value">{isOllamaOnline ? "Online" : "Offline"}</span>
        </div>
      </div>

      <div className="control-actions">
        <button type="button" className="control-button" onClick={onStepForward}>
          Step +15m
        </button>
        <button type="button" className="control-button control-button-muted" onClick={onResetClock}>
          Reset
        </button>
      </div>
    </div>
  );
}

export default SidebarBottomControls;
