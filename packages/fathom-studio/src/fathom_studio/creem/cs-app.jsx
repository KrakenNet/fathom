/* ============================================================================
   Fathom Policy Studio (creem) — app shell. Topbar nav + theme + view routing.
   Loaded last; mounts. Views attach to window.CS* (guarded so missing ones
   show a placeholder during the staged rollout).
   ============================================================================ */
(function () {
  "use strict";
  const { useState } = React;
  const I = window.CSIcon;

  const NAV = [
    { id: "bench", label: "Reasoning Bench", icon: "bench", comp: "CSBench" },
    { id: "wire", label: "Live Wire", icon: "wire", comp: "CSWire" },
    { id: "rules", label: "Rules", icon: "rules", comp: "CSRules" },
    { id: "templates", label: "Templates", icon: "template", comp: "CSTemplates" },
    { id: "audit", label: "Audit", icon: "audit", comp: "CSAudit" },
  ];

  function Logo() {
    return <svg width="22" height="22" viewBox="0 0 32 32" fill="none"><rect width="32" height="32" rx="9" fill="var(--ds-accent)" /><path d="M8 20c3 0 3-9 4.5-9S15 22 17 22s2.5-7 4.5-7" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>;
  }
  function Placeholder({ label }) {
    return <div className="cs-placeholder"><span className="ds-eyebrow">{label}</span><p className="ds-lead">This view is coming in the rollout.</p></div>;
  }

  function Shell() {
    const { theme, setTheme, ready, live } = window.useStudio();
    const [view, setView] = useState("bench");
    const cur = NAV.find((n) => n.id === view);
    const Comp = window[cur.comp];
    return (
      <div className="cs-shell">
        <header className="cs-top">
          <div className="cs-brand"><Logo /><b>Fathom</b><span className="cs-brand-sub">Policy Studio</span></div>
          <nav className="cs-nav">{NAV.map((n) => <button key={n.id} className={`cs-nav-item ${view === n.id ? "is-on" : ""}`} onClick={() => setView(n.id)}><I d={n.icon} s={16} stroke={1.9} />{n.label}</button>)}</nav>
          <div className="cs-top-r">
            <span className="cs-env" title={live ? "Connected to the Fathom engine" : "Studio API unreachable — offline mock engine"}><span className="cs-env-dot" style={live ? null : { background: "var(--ds-escalate)" }} /> {live ? "live · real engine" : "offline · mock"}</span>
            <button className="cs-theme" onClick={() => setTheme(theme === "light" ? "dark" : "light")} title="Toggle theme"><I d={theme === "light" ? "bolt" : "sun"} s={16} /></button>
          </div>
        </header>
        <main className="cs-stage"><div className="cs-stage-in">{!ready ? <div className="cs-placeholder"><span className="ds-eyebrow">Connecting to engine</span><p className="ds-lead">Loading rulesets and scenarios…</p></div> : (Comp ? <Comp /> : <Placeholder label={cur.label} />)}</div></main>
      </div>
    );
  }

  function App() { return <window.StudioProvider><Shell /></window.StudioProvider>; }
  ReactDOM.createRoot(document.getElementById("root")).render(<App />);
})();
