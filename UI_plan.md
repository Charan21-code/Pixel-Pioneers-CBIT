# UI Implementation Plan: Agentic Production Planning System (React)

## Overview
This plan outlines the staged rollout of the User Interface as a React application. Building on the core logic defined in the master plan, this UI plan ensures steady delivery of a premium, "Glassmorphism Dark Mode" experience that feels like a modern command center rather than a standard dashboard.

## Phase 1: Foundational Aesthetics & Layout
**Objective:** Establish the global design system (colors, typography, container styles) and the permanent lateral navigation.
- **Global Theme & CSS Setup:** Define a centralized theme layer in React (for example `src/styles/theme.css` plus app-level providers).
  - Apply custom Dark Slate backgrounds (`#0f172a` to `#1e293b`).
  - Set primary accents (Neon Cyan `#06b6d4`) and standardized status colors (Emerald, Amber, Crimson).
  - Introduce `backdrop-filter: blur(10px)` utility classes for glassmorphic containers.
  - Use a modern font stack (e.g., *Inter* or *Outfit*) via app-level stylesheet/font loader.
  - Standardize spacing, border radius, shadows, and focus states as reusable tokens/components.
- **App Shell & Navigation:** Build the main structural layout with React Router.
  - Create a persistent left sidebar with route links for each page.
  - Implement fixed elements at the bottom of the sidebar: Global Simulated Clock, Ollama Connectivity Dot, and Step-forward/Reset controls.
  - Keep shell state in shared React state (Context/Zustand/Redux as needed) so all pages read/write consistent app state.

## Phase 2: High-Level Overview (Command Center)
**Objective:** Deliver Page 1 as the primary entry point, functioning as an instant health monitor.
- **Status Banner:** Build a pulsating, full-width header block using conditional CSS classes based on the Orchestrator's `final_status` (for example glowing green border for all-clear, pulsing red border for blocked).
- **Top Metrics:** Build custom metric cards (React components) for expansive, high-visibility KPIs.
- **Plant Grid (Responsive Cards):** Route away from plain tables. Create a 5-column desktop grid (responsive on smaller screens). Inside each, render glassmorphic cards with strong visual status indicators to summarize machine and inventory health and guide the user toward problem areas.
- **Agent Operations Feed:** Display recent system operations at the bottom using a styled React table/list view with row styling that fades by recency.

## Phase 3: Core Analytical Views (Intake & Diagnostics)
**Objective:** Build the pages that visualize raw agent data securely and clearly.
- **Demand Intelligence (Page 2):** Implement dual-axis line charts using `react-plotly.js` with a dark theme and smoothed spline curves. Isolate ForecasterAgent text into a highlighted "Agent Insights" block with a distinct left border.
- **Inventory Logistics (Page 3):** Design horizontally stacked progress bars mapping remaining stock against lead time. Add rule-based warnings: if remaining days overlap lead-time threshold, switch bar state aggressively to red.
- **Machine Health (Page 5):** Use a small-multiples grid layout for telemetry charts (TTF, OEE, Temp, Vib). Add colored threshold bands/overlays in charts to visualize danger zones. Conditionally render a critical red alert card that dominates the page when `TTF < 24 hrs`.

## Phase 4: Control & Simulation (Production Plan & Digital Twin)
**Objective:** Allow user modification, detailed plant-specific planning, and predictive simulation.
- **Production Plan (Page 4):**
  - Construct a toggleable hierarchical layout (accordion/tree pattern). Level A summarizes plants; selecting a plant expands Level B details.
  - Render pre-flight "Readiness Gates" with prominent icons summarizing Finance, Buyer, and Mechanic clearance.
  - Use an editable React table (for example TanStack Table with controlled cell editors) for the live shift schedule, with strong contrast on editable "Assigned Units" cells.
- **Digital Twin Simulation (Page 7):**
  - Implement an asymmetric layout (`grid-template-columns: 1fr 2fr`). Left panel hosts input sliders (pre-filled from shared state); right panel displays outcome area charts and variance metrics.
  - Embed a Mini-Ollama chat input area at the bottom of the simulation module for localized "what-if" interrogations.
- **Finance & Carbon (Pages 6 & 8):** Build budget utilization gauges and carbon analytics visuals (including Hour-of-Day density heatmaps). Render LLM cost-saving suggestions as interactive pill-tag lists/cards.

## Phase 5: The Interaction Loop (NLP & Human-in-the-Loop)
**Objective:** Deliver the execution and approval interfaces where users manage constraints.
- **Global NLP Interface (Page 9):** Establish a full-height chat window. Clearly separate User vs Agent visual states (right-aligned colored bubbles vs left-aligned dark slate bubbles). Wire intent executions to visible toast notifications confirming background variable updates.
- **HITL Inbox (Page 10):** Set up 5 structured tabs denoting department queues. Style requested actions as isolated "Review Tickets." Enforce prominent Green (Approve) and Red (Reject) actions in a fixed, rational location inside each ticket. Construct a polished "Zero Inbox" empty state when no reviews are pending.

## Implementation Notes (React-Specific)
- Prefer TypeScript components for predictable data contracts across pages.
- Create reusable UI primitives (`GlassCard`, `StatusChip`, `MetricTile`, `SectionHeader`, `AlertBanner`) to keep styling and behavior consistent.
- Centralize API/data hooks (`useDashboardData`, `useSimulationState`, `useInbox`) so pages remain presentation-focused.
- Ensure desktop + mobile responsiveness from the start (breakpoints for 5-column grids, sidebar collapse, chart resizing, and table overflow handling).
