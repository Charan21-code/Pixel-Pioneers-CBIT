import { useMemo, useState } from "react";

const DEPARTMENTS = [
  { id: "finance", label: "Finance" },
  { id: "buyer", label: "Buyer" },
  { id: "mechanic", label: "Mechanic" },
  { id: "planning", label: "Planning" },
  { id: "sustainability", label: "Sustainability" }
];

const INITIAL_TICKETS = [
  {
    id: "FIN-114",
    department: "finance",
    title: "Approve emergency overtime budget",
    detail: "Plant-3 asks for temporary overtime budget extension to prevent order spillover.",
    requester: "Operations Lead",
    due: "02:00 AM",
    priority: "High",
    status: "pending"
  },
  {
    id: "BUY-079",
    department: "buyer",
    title: "Authorize alternate supplier lot",
    detail: "Fallback vendor can deliver steel coil within 8 hours at +3.5% premium.",
    requester: "Inventory Agent",
    due: "01:30 AM",
    priority: "High",
    status: "pending"
  },
  {
    id: "MEC-042",
    department: "mechanic",
    title: "Approve accelerated bearing replacement",
    detail: "Machine Health predicts critical TTF breach in less than 24 hours.",
    requester: "Mechanic Agent",
    due: "03:15 AM",
    priority: "Critical",
    status: "pending"
  },
  {
    id: "PLN-233",
    department: "planning",
    title: "Confirm shift reassignment for Plant-5",
    detail: "Rebalance suggested to recover projected throughput deficit by 4.2%.",
    requester: "Orchestrator",
    due: "04:00 AM",
    priority: "Medium",
    status: "pending"
  },
  {
    id: "SUS-058",
    department: "sustainability",
    title: "Approve off-peak compressor schedule",
    detail: "Proposed timing reduces forecasted carbon intensity during high-tariff window.",
    requester: "Carbon Agent",
    due: "05:00 AM",
    priority: "Medium",
    status: "pending"
  }
];

function HitlInboxPage() {
  const [activeDepartment, setActiveDepartment] = useState(DEPARTMENTS[0].id);
  const [tickets, setTickets] = useState(INITIAL_TICKETS);

  const pendingByDepartment = useMemo(() => {
    return DEPARTMENTS.reduce((accumulator, department) => {
      accumulator[department.id] = tickets.filter(
        (ticket) => ticket.department === department.id && ticket.status === "pending"
      ).length;
      return accumulator;
    }, {});
  }, [tickets]);

  const visibleTickets = useMemo(() => {
    return tickets.filter((ticket) => ticket.department === activeDepartment && ticket.status === "pending");
  }, [tickets, activeDepartment]);

  const processTicket = (ticketId, decision) => {
    setTickets((current) =>
      current.map((ticket) => {
        if (ticket.id !== ticketId) {
          return ticket;
        }
        return { ...ticket, status: decision };
      })
    );
  };

  return (
    <section className="phase-five-shell">
      <header className="glass-panel phase-three-header">
        <p className="page-kicker">Phase 5</p>
        <h2>HITL Inbox</h2>
        <p>Department queues route critical approvals into review tickets with explicit decision controls.</p>
      </header>

      <article className="glass-panel hitl-shell">
        <div className="hitl-tabs">
          {DEPARTMENTS.map((department) => {
            const pendingCount = pendingByDepartment[department.id] ?? 0;
            return (
              <button
                key={department.id}
                type="button"
                onClick={() => setActiveDepartment(department.id)}
                className={activeDepartment === department.id ? "hitl-tab hitl-tab-active" : "hitl-tab"}
              >
                {department.label}
                <span>{pendingCount}</span>
              </button>
            );
          })}
        </div>

        {visibleTickets.length === 0 ? (
          <div className="zero-inbox">
            <div className="zero-inbox-orb" />
            <h3>Zero Inbox</h3>
            <p>No pending review tickets in this queue.</p>
          </div>
        ) : (
          <div className="ticket-list">
            {visibleTickets.map((ticket) => (
              <article key={ticket.id} className="review-ticket">
                <div className="ticket-head">
                  <h3>{ticket.title}</h3>
                  <span className="ticket-priority">{ticket.priority}</span>
                </div>
                <p>{ticket.detail}</p>
                <div className="ticket-meta">
                  <span>ID: {ticket.id}</span>
                  <span>Requester: {ticket.requester}</span>
                  <span>Due: {ticket.due}</span>
                </div>
                <div className="ticket-actions">
                  <button type="button" className="ticket-button ticket-button-reject" onClick={() => processTicket(ticket.id, "rejected")}>
                    Reject
                  </button>
                  <button type="button" className="ticket-button ticket-button-approve" onClick={() => processTicket(ticket.id, "approved")}>
                    Approve
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </article>
    </section>
  );
}

export default HitlInboxPage;
