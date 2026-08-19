/* ============================================================================
   Audit — single rich column; split 40/60 once a record is selected.
   window.CSAudit
   ============================================================================ */
(function () {
  "use strict";
  const { useState } = React;
  const I = window.CSIcon;
  function ts(t) { return new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
  function factLine(f) { return Object.keys(f).filter((k) => k !== "__t").map((k) => `${k}: ${f[k]}`).join(" · "); }

  function Detail({ rec }) {
    return (
      <div className="ax-detail">
        <div className="ax-top"><window.CSDecision value={rec.decision} size="lg" /><span className="ax-reason">{rec.reason}</span><span className="ax-us">{rec.durationUs}µs</span></div>
        <div className="ax-hash"><span className="lab">chain</span><code>prev {rec.prevHash}</code> → <code className="cur">this {rec.hash}</code></div>
        <div className="ax-sec"><div className="lab"><I d="lock" s={12} /> facts · working memory</div>{rec.facts.map((f, i) => <div key={i} className="ax-chip"><span className="ds-tag">{f.__t}</span>{factLine(f)}</div>)}</div>
        <div className="ax-sec"><div className="lab"><I d="bench" s={12} /> evaluation trace · {rec.trace.length} rules</div>{rec.trace.map((e) => <div key={e.id} className={`ax-chip ${e.matched ? "" : "muted"}`}><span className="ax-dot" style={e.matched ? { background: window.DEC[e.severity].c } : null} />{e.name}<span className="ax-tr">{e.matched ? (window.DEC[e.severity].label) : "—"} · sal {e.salience}</span></div>)}</div>
        <div className="ax-sec"><div className="lab">Ed25519 signature</div><div className="ax-sig">{rec.sig.replace(/(.{16})/g, "$1\u200b")}</div></div>
      </div>
    );
  }

  function Audit() {
    const { audit, resetAudit } = window.useStudio();
    const [sel, setSel] = useState(null);
    const rec = audit.find((r) => r.seq === sel);
    const split = !!rec;
    return (
      <div className="audit">
        <div className="audit-head">
          <div><h2 className="ds-h2">Audit chain</h2><p className="audit-sub">Append-only, Ed25519-signed records. Each entry hash-links the previous. Click one to inspect.</p></div>
          <div className="audit-head-r"><span className="audit-badge"><I d="lock" s={13} /> verified · {audit.length}</span>{audit.length > 0 && <button className="ds-btn ds-btn--ghost ds-btn--sm" onClick={() => { resetAudit(); setSel(null); }}><I d="reset" s={14} />Clear</button>}</div>
        </div>
        {audit.length === 0 ? (
          <div className="audit-empty"><I d="audit" s={30} w={1.4} /><p className="ds-lead" style={{ marginTop: 12 }}>No evaluations yet. Run something on the Bench or open Live Wire — signed records appear here.</p></div>
        ) : (
          <div className={`audit-body ${split ? "is-split" : ""}`}>
            <div className="audit-list">
              <div className="wb-h"><span>⚿ Chain · {audit.length}</span><span>append-only</span></div>
              <div className="audit-scroll">
                {audit.map((r) => (
                  <button key={r.seq} className={`arow ${split ? "compact" : ""} ${sel === r.seq ? "on" : ""}`} onClick={() => setSel(sel === r.seq ? null : r.seq)}>
                    <span className="arow-sq">#{String(r.seq).padStart(4, "0")}</span>
                    <window.CSDecision value={r.decision} size="sm" />
                    <span className="arow-rs">{r.reason}</span>
                    {!split && <span className="arow-meta">{r.facts.length} facts · {r.fired.length} fired</span>}
                    {!split && <span className="arow-tm">{ts(r.ts)}</span>}
                    <span className="arow-hl">{r.hash}</span>
                    {!split && <span className="arow-us">{r.durationUs}µs</span>}
                  </button>
                ))}
              </div>
            </div>
            {split && <div className="audit-detail-pane"><div className="wb-h"><span>Record #{String(rec.seq).padStart(4, "0")}</span><span>signed · {ts(rec.ts)}</span></div><div className="audit-scroll"><Detail rec={rec} /></div></div>}
          </div>
        )}
      </div>
    );
  }
  window.CSAudit = Audit;
})();
