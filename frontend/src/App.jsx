import { Navigate, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";
import AppShell from "./layout/AppShell";
import PagePlaceholder from "./pages/PagePlaceholder";
import CommandCenterPage from "./pages/CommandCenterPage";
import DemandIntelligencePage from "./pages/DemandIntelligencePage";
import InventoryLogisticsPage from "./pages/InventoryLogisticsPage";
import MachineHealthPage from "./pages/MachineHealthPage";
import ProductionPlanPage from "./pages/ProductionPlanPage";
import FinancePage from "./pages/FinancePage";
import DigitalTwinPage from "./pages/DigitalTwinPage";
import CarbonPage from "./pages/CarbonPage";
import GlobalNlpPage from "./pages/GlobalNlpPage";
import HitlInboxPage from "./pages/HitlInboxPage";

const PAGE_ROUTES = [
  { path: "/command-center", label: "Command Center", title: "Page 1: Command Center" },
  { path: "/demand-intelligence", label: "Demand Intelligence", title: "Page 2: Demand Intelligence" },
  { path: "/inventory-logistics", label: "Inventory Logistics", title: "Page 3: Inventory Logistics" },
  { path: "/production-plan", label: "Production Plan", title: "Page 4: Production Plan" },
  { path: "/machine-health", label: "Machine Health", title: "Page 5: Machine Health" },
  { path: "/finance", label: "Finance", title: "Page 6: Finance" },
  { path: "/digital-twin", label: "Digital Twin", title: "Page 7: Digital Twin Simulation" },
  { path: "/carbon", label: "Carbon", title: "Page 8: Carbon Insights" },
  { path: "/global-nlp", label: "Global NLP", title: "Page 9: Global NLP Interface" },
  { path: "/hitl-inbox", label: "HITL Inbox", title: "Page 10: HITL Inbox" }
];

function App() {
  const [simulatedTime, setSimulatedTime] = useState(() => new Date());
  const [isOllamaOnline] = useState(true);

  useEffect(() => {
    const tick = window.setInterval(() => {
      setSimulatedTime((previousTime) => new Date(previousTime.getTime() + 1000));
    }, 1000);

    return () => window.clearInterval(tick);
  }, []);

  const stepForward = () => {
    setSimulatedTime((previousTime) => new Date(previousTime.getTime() + 15 * 60 * 1000));
  };

  const resetClock = () => {
    setSimulatedTime(new Date());
  };

  const resolvePageElement = (path, title) => {
    if (path === "/command-center") {
      return <CommandCenterPage />;
    }
    if (path === "/demand-intelligence") {
      return <DemandIntelligencePage />;
    }
    if (path === "/inventory-logistics") {
      return <InventoryLogisticsPage />;
    }
    if (path === "/machine-health") {
      return <MachineHealthPage />;
    }
    if (path === "/production-plan") {
      return <ProductionPlanPage />;
    }
    if (path === "/finance") {
      return <FinancePage />;
    }
    if (path === "/digital-twin") {
      return <DigitalTwinPage />;
    }
    if (path === "/carbon") {
      return <CarbonPage />;
    }
    if (path === "/global-nlp") {
      return <GlobalNlpPage />;
    }
    if (path === "/hitl-inbox") {
      return <HitlInboxPage />;
    }

    return <PagePlaceholder title={title} subtitle="Phase-1 foundation layout is active." />;
  };

  return (
    <Routes>
      <Route
        element={
          <AppShell
            navItems={PAGE_ROUTES}
            simulatedTime={simulatedTime}
            isOllamaOnline={isOllamaOnline}
            onStepForward={stepForward}
            onResetClock={resetClock}
          />
        }
      >
        <Route index element={<Navigate replace to="/command-center" />} />
        {PAGE_ROUTES.map((page) => (
          <Route key={page.path} path={page.path} element={resolvePageElement(page.path, page.title)} />
        ))}
      </Route>
    </Routes>
  );
}

export default App;
