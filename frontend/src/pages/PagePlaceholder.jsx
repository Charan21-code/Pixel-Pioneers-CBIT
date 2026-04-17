function PagePlaceholder({ title, subtitle }) {
  return (
    <section className="page-shell">
      <div className="page-hero glass-panel">
        <p className="page-kicker">Phase 1</p>
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>

      <div className="page-grid">
        <article className="glass-panel page-card">
          <h3>Design System Active</h3>
          <p>Dark slate gradients, status colors, blur containers, and typography tokens are now global.</p>
        </article>
        <article className="glass-panel page-card">
          <h3>Navigation Shell Active</h3>
          <p>Every page now renders inside the same persistent command-center sidebar shell.</p>
        </article>
      </div>
    </section>
  );
}

export default PagePlaceholder;
