/* ============================================================================
   Reasoning Bench — creem app view. Reasoning-line layout + fact builder +
   scenario editor + session memory. Reads the studio store. window.CSBench
   ============================================================================ */
(function () {
  "use strict";
  const { useState } = React;
  const F = window.Fathom;
  const I = window.CSIcon;

  function factLabel(f) {
    return Object.keys(f).filter((k) => k !== "__t").map((k) => `${f[k]}`).join(" · ");
  }
  const Scribble = ({ color }) => (
    <svg className="rb-scrib" viewBox="0 0 200 12" preserveAspectRatio="none" style={{ color }}>
      <path d="M2 8C30 2 52 2 80 7s52 4 80-2 36-3 38 2" fill="none" stroke="currentColor" strokeWidth="3.4" strokeLinecap="round" /></svg>
  );

  /* ---- fact builder modal ---- */
  function FactModal({ templates, onAssert, onClose }) {
    const [tn, setTn] = useState(templates[0].name);
    const tpl = templates.find((t) => t.name === tn) || templates[0];
    const [draft, setDraft] = useState(() => F.blankFact(tpl));
    const pick = (n) => { setTn(n); setDraft(F.blankFact(templates.find((t) => t.name === n))); };
    const set = (k, v) => setDraft((d) => ({ ...d, [k]: v }));
    const footer = <><button className="ds-btn ds-btn--ghost" onClick={onClose}>Cancel</button><button className="ds-btn ds-btn--primary" onClick={() => { onAssert(draft); onClose(); }}><I d="plus" s={16} />Assert fact</button></>;
    return (
      <window.CSModal title="Assert a fact" subtitle="Facts must match a template's typed slots." onClose={onClose} footer={footer}>
        <window.CSField label="Template"><window.CSSelect value={tn} options={templates.map((t) => t.name)} onChange={pick} /></window.CSField>
        <p className="cs-doc">{tpl.doc}</p>
        {tpl.slots.map((s) => (
          <window.CSField key={s.name} label={s.name} hint={s.type}>
            {s.type === "boolean" ? <div className="cs-bool"><window.CSToggle on={!!draft[s.name]} onChange={(v) => set(s.name, v)} /><em>{String(!!draft[s.name])}</em></div>
              : (s.values && s.values.length) ? <window.CSSelect value={draft[s.name]} options={s.values} onChange={(v) => set(s.name, v)} />
                : <window.CSInput value={draft[s.name]} onChange={(v) => set(s.name, v)} placeholder={s.doc} mono />}
          </window.CSField>
        ))}
      </window.CSModal>
    );
  }

  /* ---- scenario editor ---- */
  function ScenarioEditor({ initial, templates, onSave, onClose }) {
    const [label, setLabel] = useState(initial.label || "");
    const [blurb, setBlurb] = useState(initial.blurb || "");
    const [facts, setFacts] = useState((initial.facts || []).map((f) => ({ ...f })));
    const [builder, setBuilder] = useState(false);
    const footer = <><button className="ds-btn ds-btn--ghost" onClick={onClose}>Cancel</button><button className="ds-btn ds-btn--primary" disabled={!label.trim() || !facts.length} onClick={() => { onSave({ label: label.trim(), blurb: blurb.trim(), facts }, initial.key); onClose(); }}>{initial.key ? "Save scenario" : "Create scenario"}</button></>;
    return (
      <>
        <window.CSModal title={initial.key ? "Edit scenario" : "New scenario"} subtitle="A named set of facts to load onto the bench." onClose={onClose} footer={footer}>
          <p className="cs-doc">Saved to this browser session only (not persisted). The facts you assert here are evaluated by the real engine when you Run.</p>
          <window.CSField label="Name"><window.CSInput value={label} onChange={setLabel} placeholder="e.g. Clearance breach" /></window.CSField>
          <window.CSField label="Description"><window.CSInput value={blurb} onChange={setBlurb} placeholder="One-line summary" /></window.CSField>
          <div className="cs-sub-h">Facts · {facts.length}</div>
          <div className="rb-facts">
            {facts.map((f, i) => <div key={i} className="rb-fact" data-t={f.__t}><span className="ds-tag">{f.__t}</span><span className="rb-fact-v">{factLabel(f)}</span><button className="rb-fact-x" onClick={() => setFacts(facts.filter((_, j) => j !== i))}><I d="close" s={13} w={2.4} /></button></div>)}
            {!facts.length && <div className="cs-empty">No facts yet.</div>}
          </div>
          <button className="cs-add-row" onClick={() => setBuilder(true)}><I d="plus" s={14} /> Add fact</button>
        </window.CSModal>
        {builder && <FactModal templates={templates} onAssert={(f) => setFacts((fs) => [...fs, f])} onClose={() => setBuilder(false)} />}
      </>
    );
  }

  function Bench() {
    const { rules, templates, memory, evaluate, scenarios, setScenarios } = window.useStudio();
    const firstKey = Object.keys(scenarios)[0];
    const [scn, setScn] = useState(firstKey);
    const [facts, setFacts] = useState(scenarios[firstKey].facts.map((f) => ({ ...f })));
    const [result, setResult] = useState(null);
    const [runN, setRunN] = useState(0);
    const [busy, setBusy] = useState(false);
    const [modal, setModal] = useState(false);
    const [scnEd, setScnEd] = useState(null);

    // Scope the (aggregated) rules + templates to the active scenario's ruleset
    // so the agenda count, governing rule, and fact builder reflect only the
    // policy actually being evaluated.
    const activeRs = scenarios[scn] && scenarios[scn].ruleset;
    const rsRules = rules.filter((r) => r.pack === activeRs);
    const rsTemplates = templates.filter((t) => t.pack === activeRs);
    const tpls = rsTemplates.length ? rsTemplates : templates;

    function load(k) { setScn(k); setFacts(scenarios[k].facts.map((f) => ({ ...f }))); setResult(null); }
    async function run() {
      setBusy(true);
      try {
        const r = await evaluate(scenarios[scn] && scenarios[scn].ruleset, facts.map((f) => ({ ...f })));
        setResult(r); setRunN((n) => n + 1);
      } finally { setBusy(false); }
    }
    function slug(s) { return (s || "scenario").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "scenario"; }
    function saveScn(data, key) { let k = key; if (!k) { const b = slug(data.label); k = b; let i = 2; while (scenarios[k]) k = b + "-" + i++; } const rs = (scenarios[scn] && scenarios[scn].ruleset); setScenarios((p) => ({ ...p, [k]: { label: data.label, blurb: data.blurb, ruleset: (key && p[key] ? p[key].ruleset : rs), facts: data.facts.map((f) => ({ ...f })) } })); load(k); }
    function delScn(k) { const rem = Object.keys(scenarios).filter((x) => x !== k); setScenarios((p) => { const n = { ...p }; delete n[k]; return n; }); if (scn === k && rem.length) load(rem[0]); }

    const focus = result && result.fired[0] ? rsRules.find((r) => r.id === result.fired[0].id) || rsRules[0] : rsRules[0];
    const mem = memory.snapshot();
    const dec = result ? window.DEC[result.decision] : null;

    return (
      <div className="rb-bench">
        <div className="rb-input">
          <div className="rb-sec">
            <div className="rb-sec-head"><span className="ds-eyebrow">Scenario</span><button className="ds-btn ds-btn--ghost ds-btn--sm" onClick={() => setScnEd({ label: "", blurb: "", facts: facts.map((f) => ({ ...f })) })}><I d="plus" s={14} />New</button></div>
            <div className="rb-scn-rail">
              {Object.entries(scenarios).map(([k, s]) => (
                <div key={k} className={`rb-scn ${scn === k ? "is-on" : ""}`} onClick={() => load(k)} role="button" title={s.blurb}>
                  <span>{s.label}</span>
                  <span className="rb-scn-acts" onClick={(e) => e.stopPropagation()}>
                    <button onClick={() => setScnEd({ key: k, label: s.label, blurb: s.blurb, facts: s.facts })}><I d="edit" s={12} /></button>
                    {Object.keys(scenarios).length > 1 && <button onClick={() => delScn(k)}><I d="close" s={12} w={2.4} /></button>}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="rb-sec">
            <div className="rb-sec-head"><span className="ds-eyebrow">Working memory · {facts.length} facts</span><button className="ds-btn ds-btn--ghost ds-btn--sm" onClick={() => setModal(true)}><I d="plus" s={14} />Fact</button></div>
            <div className="rb-facts">
              {facts.map((f, i) => <div key={i} className="rb-fact" data-t={f.__t}><span className="ds-tag">{f.__t}</span><span className="rb-fact-v">{factLabel(f)}</span>{facts.length > 1 && <button className="rb-fact-x" onClick={() => setFacts(facts.filter((_, j) => j !== i))}><I d="close" s={13} w={2.4} /></button>}</div>)}
            </div>
            {mem.length > 0 && <div className="rb-mem"><span className="rb-mem-l">Session memory</span>{mem.map((m) => <span key={m.agent} className="rb-mem-i">{m.agent} · {m.sources.length} sensitive src</span>)}</div>}
          </div>
          {focus && <div className="rb-sec">
            <span className="ds-eyebrow">Governing rule · {focus.name}</span>
            <window.CSYaml src={F.ruleToYaml(focus)} className="rb-yaml" />
          </div>}
        </div>

        <div className="rb-seam"><div key={runN} className={`rb-engine ${result ? "is-done" : ""}`}><I d="cpu" s={22} w={1.7} /></div><div className="rb-seam-line" /></div>

        <div className="rb-output">
          <div className="rb-runbar"><button className="ds-btn ds-btn--primary ds-btn--lg" onClick={run} disabled={!facts.length || busy}><I d="play" s={17} />{busy ? "Evaluating…" : "Run evaluation"}</button><span className="rb-runmeta">{rsRules.filter((r) => r.enabled !== false).length} rules on the agenda</span></div>
          {!result && <div className="rb-empty"><span className="ds-eyebrow">Awaiting input</span><p className="ds-lead">Assert facts and run. The engine pattern-matches every rule against working memory and returns a deterministic decision — with the full reasoning trace.</p></div>}
          {result && (
            <div className="rb-verdict">
              <div className="rb-verdict-line"><span className="rb-word ds-display ds-scribble" style={{ color: dec.c }}>{dec.label}<Scribble color={dec.c} /></span><span className="rb-us"><b>{result.durationUs}</b>µs</span></div>
              <p className="rb-reason">{result.reason}</p>
              <div className="rb-vfoot"><span><b>{result.fired.length}</b> rule{result.fired.length === 1 ? "" : "s"} fired</span><span><b>{result.ruleCount}</b> evaluated</span>{result.auditFired && <span className="rb-signed"><I d="lock" s={13} />signed &amp; logged</span>}</div>
              <div className="rb-trace">
                <span className="ds-eyebrow">Reasoning trace · by salience</span>
                <div className="rb-timeline">
                  {result.trace.map((e) => { const m = window.DEC[e.severity]; return (
                    <div key={e.id} className={`rb-node ${e.matched ? "is-fired" : ""}`}>
                      <span className="rb-node-dot" style={e.matched ? { background: m.c, borderColor: m.c } : null} />
                      <div className="rb-node-body">
                        <div className="rb-node-line"><span className="rb-node-name">{e.name}</span><window.CSPackTag pack={e.pack} /><span className="rb-node-mod">{e.module}</span><span className="rb-node-us">sal {e.salience}</span>{e.matched ? <window.CSDecision value={e.severity} size="sm" /> : <span className="rb-skip">no match</span>}</div>
                        {e.matched && <div className="rb-node-why">{e.reason}</div>}
                      </div>
                    </div>); })}
                </div>
              </div>
            </div>
          )}
        </div>

        {modal && <FactModal templates={tpls} onAssert={(f) => setFacts((fs) => [...fs, f])} onClose={() => setModal(false)} />}
        {scnEd && <ScenarioEditor initial={scnEd} templates={tpls} onSave={saveScn} onClose={() => setScnEd(null)} />}
      </div>
    );
  }
  window.CSBench = Bench;
})();
