/* ============================================================================
   Rules — three-pane workbench (pack rail · rule list · live source/detail).
   window.CSRules
   ============================================================================ */
(function () {
  "use strict";
  const { useState } = React;
  const F = window.Fathom;
  const I = window.CSIcon;

  function Rules() {
    const { rules, setRules, templates, packs, addPack } = window.useStudio();
    const [pack, setPack] = useState("all");
    const [sel, setSel] = useState(rules[0] ? rules[0].id : null);
    const [editing, setEditing] = useState(null);
    const [packEd, setPackEd] = useState(false);
    const packKeys = ["all", ...Object.keys(packs)];
    const list = rules.filter((r) => pack === "all" || r.pack === pack);
    const rule = rules.find((r) => r.id === sel) || list[0];

    function saveRule(u) { setRules((rs) => { const i = rs.findIndex((x) => x.id === u.id); return i === -1 ? [...rs, u] : rs.map((x) => x.id === u.id ? { ...x, ...u } : x); }); setSel(u.id); }
    function toggle(id) { setRules((rs) => rs.map((r) => r.id === id ? { ...r, enabled: r.enabled === false ? true : false } : r)); }
    function del(id) { setRules((rs) => rs.filter((r) => r.id !== id)); setSel(null); }
    function createPack(id, name, seed) { addPack(id, name); if (seed && seed.length) setRules((rs) => [...rs, ...seed.map((r) => ({ ...r, pack: id }))]); setPack(id); }

    return (
      <div className="wb">
        <div className="wb-nav">
          <div className="ds-eyebrow" style={{ display: "flex", marginBottom: 8 }}>Packs</div>
          {packKeys.map((p) => <button key={p} className={`wb-pack ${pack === p ? "on" : ""}`} onClick={() => setPack(p)}>{p === "all" ? "All" : ((packs[p] && packs[p].name) ? packs[p].name.replace(/^fathom-/, "") : p)}<span className="ct">{p === "all" ? rules.length : rules.filter((r) => r.pack === p).length}</span></button>)}
          <button className="wb-pack dashed" onClick={() => setPackEd(true)}><I d="pack" s={13} /> New pack</button>
          <button className="ds-btn ds-btn--primary ds-btn--sm" style={{ marginTop: "auto", justifyContent: "center" }} onClick={() => setEditing("new")}><I d="plus" s={14} />New rule</button>
        </div>

        <div className="wb-panel">
          <div className="wb-h"><span>{list.length} rules</span><span>salience ↓</span></div>
          <div className="wb-scroll">
            {list.slice().sort((a, b) => b.salience - a.salience).map((r) => (
              <div key={r.id} className={`wb-row ${sel === r.id ? "on" : ""} ${r.enabled === false ? "off" : ""}`} onClick={() => setSel(r.id)}>
                <span className="wb-dot" style={{ background: r.severity === "log" ? "var(--ds-accent)" : window.DEC[r.severity].c }} />
                <div className="wb-row-main"><span className="wb-name">{r.name}</span><span className="wb-sum">{r.summary}</span></div>
                <div className="wb-row-r" onClick={(e) => e.stopPropagation()}><window.CSPackTag pack={r.pack} /><span className="wb-sal">{r.salience}</span><window.CSToggle on={r.enabled !== false} onChange={() => toggle(r.id)} /></div>
              </div>
            ))}
            {!list.length && <div className="cs-empty" style={{ padding: 20 }}>No rules in this pack yet.</div>}
          </div>
        </div>

        {rule && (
          <div className="wb-panel">
            <div className="wb-h"><span>{rule.name} · source</span><span className="wb-h-acts">{!rule.builtin && <button onClick={() => setEditing(rule)}><I d="edit" s={14} /></button>}{!rule.builtin && <button onClick={() => del(rule.id)}><I d="trash" s={14} /></button>}</span></div>
            <div className="wb-scroll wb-detail">
              <div className="wb-detail-top"><window.CSDecision value={rule.severity} /><span className="wb-mod">module · {rule.module}</span>{rule.builtin && <span className="wb-builtin">built-in</span>}</div>
              <p className="wb-rsum">{rule.summary}</p>
              <window.CSYaml src={F.ruleToYaml(rule)} />
            </div>
          </div>
        )}

        {editing && <window.CSRuleEditor rule={editing === "new" ? null : editing} templates={templates} onSave={saveRule} onClose={() => setEditing(null)} />}
        {packEd && <window.CSPackEditor onCreate={createPack} onClose={() => setPackEd(false)} />}
      </div>
    );
  }
  window.CSRules = Rules;
})();
