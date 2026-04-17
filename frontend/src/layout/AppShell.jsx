import { Outlet } from "react-router-dom";
import Sidebar from "../components/Sidebar";

function AppShell({ navItems, simulatedTime, isOllamaOnline, onStepForward, onResetClock }) {
  return (
    <div className="app-shell">
      <Sidebar
        navItems={navItems}
        simulatedTime={simulatedTime}
        isOllamaOnline={isOllamaOnline}
        onStepForward={onStepForward}
        onResetClock={onResetClock}
      />

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}

export default AppShell;
