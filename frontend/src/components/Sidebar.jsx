import { NavLink } from "react-router-dom";
import SidebarBottomControls from "./SidebarBottomControls";

function Sidebar({ navItems, simulatedTime, isOllamaOnline, onStepForward, onResetClock }) {
  return (
    <aside className="sidebar glass-panel">
      <header className="sidebar-header">
        <p className="sidebar-kicker">Agentic Production Planning</p>
        <h1 className="sidebar-title">Operations Hub</h1>
      </header>

      <nav className="sidebar-nav">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) => (isActive ? "nav-link nav-link-active" : "nav-link")}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <SidebarBottomControls
        simulatedTime={simulatedTime}
        isOllamaOnline={isOllamaOnline}
        onStepForward={onStepForward}
        onResetClock={onResetClock}
      />
    </aside>
  );
}

export default Sidebar;
