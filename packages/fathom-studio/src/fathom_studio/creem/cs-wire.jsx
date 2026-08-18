/* ============================================================================
   Live Wire (C-2) — stage + decision stream, deny-rate-by-source strip beneath.
   Traffic is SYNTHETIC: it samples the real scenarios and evaluates each one
   against the real engine, so every packet is a genuine decision that feeds the
   real audit chain. window.CSWire
   ============================================================================ */
(function () {
  "use strict";
  const { useState, useRef, useEffect, useCallback } = React;
  const I = window.CSIcon;
  const LANE = { deny: 22, escalate: 50, allow: 78 };
  const laneFor = (d) => (LANE[d] != null ? LANE[d] : LANE.allow);

  function IngestConfig({ scenarios, ingest, setIngest, onClose }) {
    const [inc, setInc] = useState(() => Object.assign({}, ingest.include));
    const keys = Object.keys(scenarios);
    const toggle = (k) => setInc((x) => ({ ...x, [k]: !x[k] }));
    const footer = (
      <>
        <button className="ds-btn ds-btn--ghost" onClick={() => setInc(Object.fromEntries(keys.map((k) => [k, true])))}>All</button>
        <button className="ds-btn ds-btn--primary" onClick={() => { setIngest((g) => ({ ...g, include: inc })); onClose(); }}>Apply</button>
      </>
    );
    return (
      <window.CSModal title="Configure ingest" subtitle="Synthetic traffic samples the scenarios below — each packet is a real evaluation." onClose={onClose} footer={footer}>
        <div className="cs-sub-h">Scenario mix · {keys.filter((k) => inc[k]).length}/{keys.length}</div>
        <div className="rb-facts">
          {keys.map((k) => (
            <div key={k} className="rb-fact" data-t={scenarios[k].facts[0] && scenarios[k].facts[0].__t}>
              <window.CSToggle on={!!inc[k]} onChange={() => toggle(k)} />
              <span className="rb-fact-v">{scenarios[k].label}</span>
              <span className="ds-tag" style={{ marginLeft: "auto" }}>{scenarios[k].ruleset || "mock"}</span>
            </div>
          ))}
        </div>
      </window.CSModal>
    );
  }

  function Stat({ label, value }) { const v = window.useCountUp(value, 450); return <span className="lw-read"><b>{Math.round(v).toLocaleString()}</b> {label}</span>; }

  function Wire() {
    const { scenarios, ingest, setIngest, evaluate } = window.useStudio();
    const [running, setRunning] = useState(true);
    const [speed, setSpeed] = useState(1);
    const [packets, setPackets] = useState([]);
    const [events, setEvents] = useState([]);
    const [stats, setStats] = useState({ total: 0, allow: 0, deny: 0, escalate: 0 });
    const [bySource, setBySource] = useState({});
    const [cfg, setCfg] = useState(false);
    const idRef = useRef(0);
    const inflight = useRef(false);
    const live = useRef({});
    live.current = { scenarios, ingest, evaluate };

    const emit = useCallback(async () => {
      if (inflight.current) return;
      const { scenarios, ingest, evaluate } = live.current;
      const keys = Object.keys(scenarios).filter((k) => ingest.include[k]);
      const pool = keys.length ? keys : Object.keys(scenarios);
      if (!pool.length) return;
      const key = pool[Math.floor(Math.random() * pool.length)];
      const scn = scenarios[key];
      inflight.current = true;
      let r;
      try { r = await evaluate(scn.ruleset, scn.facts.map((f) => ({ ...f }))); }
      catch (e) { inflight.current = false; return; }
      inflight.current = false;
      const id = ++idRef.current;
      const src = scn.ruleset || key;
      setBySource((s) => { const p = s[src] || { n: 0, d: 0 }; return { ...s, [src]: { n: p.n + 1, d: p.d + (r.decision === "deny" ? 1 : 0) } }; });
      setPackets((p) => [...p.slice(-22), { id, decision: r.decision, lane: laneFor(r.decision), dur: 2.4 / speed }]);
      setStats((s) => ({ total: s.total + 1, allow: s.allow + (r.decision === "allow" ? 1 : 0), deny: s.deny + (r.decision === "deny" ? 1 : 0), escalate: s.escalate + (r.decision === "escalate" ? 1 : 0) }));
      setEvents((e) => [{ id, decision: r.decision, agent: key.replace(/^0\d-/, ""), summary: scn.label, us: r.durationUs }, ...e].slice(0, 9));
      setTimeout(() => setPackets((p) => p.filter((x) => x.id !== id)), 2600);
    }, [speed]);

    useEffect(() => { if (!running) return; const h = setInterval(() => { emit(); }, 950 / speed); return () => clearInterval(h); }, [running, speed, emit]);

    const total = stats.total || 1;
    const denyPct = Math.round((stats.deny / total) * 100), escPct = Math.round((stats.escalate / total) * 100), allowPct = Math.max(0, 100 - denyPct - escPct);
    const sources = Object.entries(bySource).map(([k, v]) => ({ k, pct: Math.round((v.d / v.n) * 100), n: v.n })).sort((a, b) => b.pct - a.pct).slice(0, 6);
    function reset() { setPackets([]); setEvents([]); setStats({ total: 0, allow: 0, deny: 0, escalate: 0 }); setBySource({}); }
    const poolSize = Object.keys(scenarios).filter((k) => ingest.include[k]).length || Object.keys(scenarios).length;

    return (
      <div className="lw">
        <div className="lw-bar">
          <button className={`ds-btn ds-btn--${running ? "soft" : "primary"} ds-btn--sm`} onClick={() => setRunning((r) => !r)}><I d={running ? "pause" : "play"} s={14} />{running ? "Pause" : "Resume"}</button>
          <window.CSSeg value={speed} options={[{ value: 0.5, label: "0.5×" }, { value: 1, label: "1×" }, { value: 2, label: "2×" }, { value: 4, label: "4×" }]} onChange={setSpeed} />
          <button className="ds-btn ds-btn--ghost ds-btn--sm" onClick={() => setCfg(true)}><I d="layers" s={14} />Configure</button>
          <button className="ds-btn ds-btn--ghost ds-btn--sm" onClick={reset}><I d="reset" s={14} />Reset</button>
          <span className="lw-spacer" />
          <Stat label="evaluated" value={stats.total} />
          <div className="lw-gauge"><span className="d" style={{ width: denyPct + "%" }} /><span className="e" style={{ width: escPct + "%" }} /><span className="a" style={{ width: allowPct + "%" }} /></div>
          <span className="lw-read"><b>{denyPct}%</b> deny</span>
        </div>

        <div className="lw-mid">
          <div className="lw-stage">
            <div className="lw-in"><span className="lw-cap">synthetic</span><div className="lw-pulse" /><span className="lw-cap2">{poolSize} scenarios</span></div>
            <div className="lw-track">
              {[22, 50, 78].map((t, i) => <React.Fragment key={i}><div className="lw-glide" style={{ top: t + "%" }} /><span className="lw-gl" style={{ top: t + "%" }}>{["deny", "esc", "allow"][i]}</span></React.Fragment>)}
              <div className="lw-core"><I d="cpu" s={20} w={1.7} /><span>fathom</span></div>
              {packets.map((p) => <div key={p.id} className={`lw-pkt fx-${p.decision}`} style={{ "--lane": p.lane + "%", animationDuration: p.dur + "s" }} />)}
            </div>
            <div className="lw-out">
              <div className="lw-bin"><span className="dot" style={{ background: "var(--ds-deny)" }} /><b>{stats.deny}</b><span>dn</span></div>
              <div className="lw-bin"><span className="dot" style={{ background: "var(--ds-escalate)" }} /><b>{stats.escalate}</b><span>esc</span></div>
              <div className="lw-bin"><span className="dot" style={{ background: "var(--ds-allow)" }} /><b>{stats.allow}</b><span>al</span></div>
            </div>
          </div>
          <div className="lw-feed">
            <div className="lw-feed-h"><span>Decision stream</span><span>real evals</span></div>
            <div className="lw-feed-list">
              {!events.length && <div className="cs-empty" style={{ padding: 14 }}>Waiting for traffic…</div>}
              {events.map((e) => <div key={e.id} className="lw-frow"><window.CSDecision value={e.decision} size="sm" /><span className="lw-ag">{e.agent}</span><span className="lw-su">{e.summary}</span><span className="lw-us">{e.us}µs</span></div>)}
            </div>
          </div>
        </div>

        <div className="lw-sources">
          <span className="lw-src-h">deny by ruleset</span>
          {sources.length === 0 && <span className="cs-empty">accumulating…</span>}
          {sources.map((s) => <span key={s.k} className="lw-schip"><span className="nm">{s.k}</span><span className="b"><i style={{ width: s.pct + "%", background: s.pct >= 50 ? "var(--ds-deny)" : s.pct >= 30 ? "var(--ds-escalate)" : "var(--ds-accent)" }} /></span><span className="v">{s.pct}%</span></span>)}
        </div>

        {cfg && <IngestConfig scenarios={scenarios} ingest={ingest} setIngest={setIngest} onClose={() => setCfg(false)} />}
      </div>
    );
  }
  window.CSWire = Wire;
})();
