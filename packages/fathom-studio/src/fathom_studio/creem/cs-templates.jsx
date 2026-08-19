/* ============================================================================
   Templates — compact grid; click a card opens its re-centerable focus graph.
   window.CSTemplates
   ============================================================================ */
(function () {
  "use strict";
  const { useState } = React;
  const F = window.Fathom;
  const I = window.CSIcon;
  const TYPE_TONE = { symbol: "lav", classification: "peach", boolean: "grass", number: "lav" };

  function refsOf(t, templates) { return (t.slots || []).filter((s) => s.name.endsWith("_id") && templates.some((x) => x.name === s.name.slice(0, -3))).map((s) => ({ slot: s.name, target: s.name.slice(0, -3) })); }
  function refByOf(name, templates) { return templates.filter((t) => (t.slots || []).some((s) => s.name === name + "_id")); }

  function FocusGraph({ t, templates, onPick, onEdit }) {
    const refs = refsOf(t, templates);
    const refBy = refByOf(t.name, templates);
    return (
      <div className="fgx">
        <span className="fgx-hdr l">references →</span>
        <span className="fgx-hdr r">← referenced by</span>
        <div className="fgx-side left">
          {refs.length === 0 && <span className="fgx-none">root fact</span>}
          {refs.map((r) => <div key={r.target} className="fgx-card lref" onClick={() => onPick(r.target)}><h5>{r.target}</h5><span className="rf">{t.name}.{r.slot} → {r.target}.id</span></div>)}
        </div>
        <div className="fgx-rail l"><div className="bus" /></div>
        <div className="fgx-center">
          <div className="fgx-focus">
            <h4><window.CSPackTag pack={t.pack} /> {t.name}<button className="fgx-edit" onClick={() => onEdit(t)}><I d="edit" s={13} /></button></h4>
            {t.slots.map((s) => { const isRef = refs.some((r) => r.slot === s.name); return <div key={s.name} className={`fgx-slot ${isRef || s.name === "id" ? "k" : ""}`}><span className="kk">{s.name}{s.name === "id" ? " ●" : ""}</span><span className="ty">{isRef ? "→ " + s.name.slice(0, -3) + ".id" : (s.values && s.values.length ? s.values.join(" · ") : s.type)}</span></div>; })}
          </div>
        </div>
        <div className="fgx-rail r"><div className="bus" /></div>
        <div className="fgx-side right">
          {refBy.length === 0 && <span className="fgx-none">not referenced</span>}
          {refBy.map((x) => <div key={x.name} className="fgx-card rref" onClick={() => onPick(x.name)}><h5>{x.name}</h5><span className="rf">{x.name}.{t.name}_id → {t.name}.id</span></div>)}
        </div>
      </div>
    );
  }

  // Templates carry a pack (ruleset); names are only unique within a pack, so
  // key + relate within the same pack to keep the graph per-ruleset.
  const keyOf = (t) => t.pack + "::" + t.name;
  const samePack = (templates, t) => templates.filter((x) => x.pack === t.pack);

  function Templates() {
    const { templates, setTemplates } = window.useStudio();
    const [focus, setFocus] = useState(null);
    const [editing, setEditing] = useState(null);
    const focusT = focus ? templates.find((x) => keyOf(x) === focus) : null;
    // Drive the lattice footer from the real ordered allowed_values of a
    // classification/clearance slot, not a hardcoded mock constant.
    const latticeSlot = templates.flatMap((t) => t.slots || []).find((s) => (s.name === "classification" || s.name === "clearance") && s.values && s.values.length);
    const lattice = latticeSlot ? latticeSlot.values : F.LATTICE;
    const latticeName = latticeSlot ? latticeSlot.name : "classification";
    function saveTpl(u) { setTemplates((ts) => { const i = ts.findIndex((x) => x.pack === u.pack && x.name === u.name); return i === -1 ? [...ts, u] : ts.map((x, j) => j === i ? u : x); }); }
    function delTpl(t) { setTemplates((ts) => ts.filter((x) => !(x.pack === t.pack && x.name === t.name))); }

    const focusFooter = focus && <><button className="ds-btn ds-btn--ghost" onClick={() => setFocus(null)}>Close</button></>;
    return (
      <div className="tpl">
        <div className="audit-head">
          <div><h2 className="ds-h2">Templates</h2><p className="audit-sub">Typed fact schemas. Click a template to see how it relates to the others.</p></div>
          <button className="ds-btn ds-btn--primary ds-btn--sm" onClick={() => setEditing("new")}><I d="plus" s={14} />New template</button>
        </div>
        <div className="tpl-grid">
          {templates.map((t) => { const pk = samePack(templates, t); const rc = refsOf(t, pk).length, bc = refByOf(t.name, pk).length; return (
            <div key={keyOf(t)} className="tpl-card" onClick={() => setFocus(keyOf(t))}>
              <div className="tpl-card-h"><span className="tpl-name">{t.name}</span><window.CSPackTag pack={t.pack} /><button className="tpl-edit" onClick={(e) => { e.stopPropagation(); setEditing(t); }}><I d="edit" s={13} /></button></div>
              <p className="tpl-doc">{t.doc}</p>
              <div className="tpl-slots">{t.slots.map((s) => <div key={s.name} className="tpl-slot"><span className="sn">{s.name}</span><span className={`st tt-${TYPE_TONE[s.type] || "lav"}`} title={(s.values && s.values.length) ? s.values.join(", ") : s.type}>{s.type}</span></div>)}</div>
              <div className="tpl-rel">{rc} ref{rc === 1 ? "" : "s"} · ref'd ×{bc}{!t.builtin && <span className="tpl-del" onClick={(e) => { e.stopPropagation(); delTpl(t); }}><I d="trash" s={13} /></span>}</div>
            </div>
          ); })}
          <div className="tpl-card new" onClick={() => setEditing("new")}><I d="plus" s={18} /><span>New template</span></div>
        </div>
        <div className="tpl-lattice"><span className="lbl">{latticeName} lattice</span>{lattice.map((l, i) => <React.Fragment key={l}><span className="latn">{l}</span>{i < lattice.length - 1 && <span className="lat-arrow">›</span>}</React.Fragment>)}</div>

        {focusT && <window.CSModal title={focusT.name + " · relationships"} subtitle="Click a neighbour to re-center; click a slot's edit to change the schema." onClose={() => setFocus(null)} footer={focusFooter} wide><FocusGraph t={focusT} templates={samePack(templates, focusT)} onPick={(name) => setFocus(focusT.pack + "::" + name)} onEdit={(t) => { setFocus(null); setEditing(t); }} /></window.CSModal>}
        {editing && <window.CSTemplateEditor template={editing === "new" ? null : editing} onSave={saveTpl} onClose={() => setEditing(null)} />}
      </div>
    );
  }
  window.CSTemplates = Templates;
})();
