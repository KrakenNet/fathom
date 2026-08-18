/* ============================================================================
   Editors — Rule editor (declarative builder), Template editor, Pack editor.
   Uses CS primitives. window.CSRuleEditor / CSTemplateEditor / CSPackEditor
   ============================================================================ */
(function () {
  "use strict";
  const { useState } = React;
  const F = window.Fathom;
  const I = window.CSIcon;
  const TYPE_OPTS = ["symbol", "classification", "boolean", "number"];

  function reprValue(v) { if (v == null) return ""; if (typeof v === "object" && "var" in v) return "?" + v.var; if (Array.isArray(v)) return v.join(", "); return String(v); }
  function parseValue(str, op) { str = (str || "").trim(); if (str.startsWith("?")) return { var: str.slice(1) }; if (op === "in" || op === "nin") return str.split(",").map((s) => s.trim()).filter(Boolean); if (str === "true") return true; if (str === "false") return false; if (["gt", "lt", "gte", "lte"].includes(op) && str !== "" && !isNaN(Number(str))) return Number(str); return str; }

  function RuleEditor({ rule, templates, onSave, onClose }) {
    const { packs } = window.useStudio();
    const PACK_OPTS = Object.keys(packs);
    const blank = { id: "rule-" + Math.random().toString(36).slice(2, 8), name: "new-rule", module: "custom", pack: "core", control: "", salience: 50, severity: "deny", enabled: true, summary: "", conditions: [{ template: templates[0].name, match: [] }], reason: "" };
    const [r, setR] = useState(() => rule ? JSON.parse(JSON.stringify({ ...rule, conditions: rule.conditions || [{ template: templates[0].name, match: [] }] })) : blank);
    const set = (k, v) => setR((x) => ({ ...x, [k]: v }));
    function loadYaml(text) { const p = F.parseRulesFromYaml(text); if (p[0]) setR((prev) => ({ ...prev, ...p[0], id: prev.id })); }
    function setCond(ci, patch) { setR((x) => ({ ...x, conditions: x.conditions.map((c, i) => i === ci ? { ...c, ...patch } : c) })); }
    function setMatch(ci, mi, patch) { setCond(ci, { match: r.conditions[ci].match.map((m, i) => i === mi ? { ...m, ...patch } : m) }); }
    function addMatch(ci) { const tpl = templates.find((t) => t.name === r.conditions[ci].template) || templates[0]; const slot = tpl.slots[0] ? tpl.slots[0].name : ""; setCond(ci, { match: [...r.conditions[ci].match, { slot, op: "bind", var: slot }] }); }
    const preview = F.ruleToYaml({ ...r, yaml: null });
    const footer = <><button className="ds-btn ds-btn--ghost" onClick={onClose}>Cancel</button><button className="ds-btn ds-btn--primary" onClick={() => { onSave(r); onClose(); }}><I d="check" s={16} />{rule ? "Save rule" : "Create rule"}</button></>;
    return (
      <window.CSModal title={rule ? "Edit rule" : "New rule"} subtitle="Conditions match against working memory; the first satisfying binding fires." onClose={onClose} footer={footer} wide>
        <p className="cs-doc">Draft — session only. Editing here does not change the on-disk ruleset, so the Bench and Live Wire keep evaluating the original rules.</p>
        <div className="re-grid">
          <div className="re-form">
            <div className="re-toolbar"><span>Build by hand, or import a ruleset</span><window.CSUpload onText={loadYaml} /></div>
            <div className="re-row3">
              <window.CSField label="Name"><window.CSInput value={r.name} onChange={(v) => set("name", v)} mono /></window.CSField>
              <window.CSField label="Salience"><window.CSNumber value={r.salience} min={0} max={100} onChange={(v) => set("salience", v)} /></window.CSField>
            </div>
            <div className="re-row3">
              <window.CSField label="Module"><window.CSInput value={r.module} onChange={(v) => set("module", v)} mono /></window.CSField>
              <window.CSField label="Pack"><window.CSSelect value={r.pack} options={PACK_OPTS} onChange={(v) => set("pack", v)} /></window.CSField>
              <window.CSField label="Control"><window.CSInput value={r.control} onChange={(v) => set("control", v)} mono /></window.CSField>
            </div>
            <window.CSField label="Decision"><window.CSSeg value={r.severity} options={[{ value: "deny", label: "Deny" }, { value: "escalate", label: "Escalate" }, { value: "allow", label: "Allow" }, { value: "log", label: "Log" }]} onChange={(v) => set("severity", v)} /></window.CSField>
            <window.CSField label="Summary"><window.CSInput value={r.summary} onChange={(v) => set("summary", v)} placeholder="What this rule enforces" /></window.CSField>
            <div className="re-cl">When <span>all conditions match</span></div>
            {r.conditions.map((cond, ci) => { const tpl = templates.find((t) => t.name === cond.template) || templates[0]; return (
              <div key={ci} className="re-cond">
                <div className="re-cond-h">
                  <window.CSSelect value={cond.template} options={templates.map((t) => t.name)} onChange={(v) => setCond(ci, { template: v, match: [] })} />
                  <button className="re-mini" onClick={() => addMatch(ci)}><I d="plus" s={14} /></button>
                  {r.conditions.length > 1 && <button className="re-mini del" onClick={() => setR((x) => ({ ...x, conditions: x.conditions.filter((_, i) => i !== ci) }))}><I d="close" s={14} /></button>}
                </div>
                {cond.match.map((m, mi) => (
                  <div key={mi} className="re-match">
                    <window.CSSelect value={m.slot} options={tpl.slots.map((s) => s.name)} onChange={(v) => setMatch(ci, mi, { slot: v })} />
                    <window.CSSelect value={m.op} options={[{ value: "bind", label: "bind →" }, ...Object.keys(F.OPS).map((o) => ({ value: o, label: F.OPS[o].label }))]} onChange={(v) => setMatch(ci, mi, { op: v })} />
                    {m.op === "bind" ? <input className="ds-input ds-mono" value={m.var || ""} placeholder="var" onChange={(e) => setMatch(ci, mi, { var: e.target.value.replace(/^\?/, "") })} /> : <input className="ds-input ds-mono" value={reprValue(m.value)} placeholder="value or ?var" onChange={(e) => setMatch(ci, mi, { value: parseValue(e.target.value, m.op) })} />}
                    <button className="re-mini del" onClick={() => setMatch(ci, mi, null) || setCond(ci, { match: cond.match.filter((_, i) => i !== mi) })}><I d="close" s={13} /></button>
                  </div>
                ))}
                {cond.match.length === 0 && <div className="re-empty">matches any {cond.template}</div>}
              </div>
            ); })}
            <button className="cs-add-row" onClick={() => setR((x) => ({ ...x, conditions: [...x.conditions, { template: templates[0].name, match: [] }] }))}><I d="plus" s={14} /> Add condition</button>
            <window.CSField label="Reason" hint="{var} interpolated"><window.CSInput value={r.reason} onChange={(v) => set("reason", v)} placeholder="Agent '{a}' denied because…" /></window.CSField>
          </div>
          <div className="re-preview"><div className="re-preview-c">compiled.yaml</div><window.CSYaml src={preview} /></div>
        </div>
      </window.CSModal>
    );
  }

  function TemplateEditor({ template, onSave, onClose }) {
    const { packs } = window.useStudio();
    const PACK_OPTS = Object.keys(packs);
    const blank = { name: "new_template", pack: "core", doc: "", slots: [{ name: "id", type: "symbol", doc: "" }] };
    const [t, setT] = useState(() => template ? JSON.parse(JSON.stringify(template)) : blank);
    const set = (k, v) => setT((x) => ({ ...x, [k]: v }));
    const setSlot = (i, patch) => setT((x) => ({ ...x, slots: x.slots.map((s, j) => j === i ? { ...s, ...patch } : s) }));
    const footer = <><button className="ds-btn ds-btn--ghost" onClick={onClose}>Cancel</button><button className="ds-btn ds-btn--primary" onClick={() => { const clean = { ...t, slots: t.slots.map((s) => ({ ...s, values: (s.type === "symbol" || s.type === "classification") && s.valuesRaw ? s.valuesRaw.split(",").map((x) => x.trim()).filter(Boolean) : s.values })) }; onSave(clean); onClose(); }}><I d="check" s={16} />{template ? "Save template" : "Create template"}</button></>;
    return (
      <window.CSModal title={template ? "Edit template" : "New template"} subtitle="A typed fact schema. Slots define the shape of facts." onClose={onClose} footer={footer}>
        <p className="cs-doc">Draft — session only. The on-disk ruleset schema is unchanged; the engine evaluates against the original templates.</p>
        <div className="re-row3">
          <window.CSField label="Name"><window.CSInput value={t.name} onChange={(v) => set("name", v.replace(/\s+/g, "_"))} mono /></window.CSField>
          <window.CSField label="Pack"><window.CSSelect value={t.pack} options={PACK_OPTS} onChange={(v) => set("pack", v)} /></window.CSField>
        </div>
        <window.CSField label="Description"><window.CSInput value={t.doc} onChange={(v) => set("doc", v)} placeholder="What this fact represents" /></window.CSField>
        <div className="re-cl">Slots</div>
        {t.slots.map((s, i) => (
          <div key={i} className="te-slot">
            <input className="ds-input ds-mono" value={s.name} placeholder="slot" onChange={(e) => setSlot(i, { name: e.target.value.replace(/\s+/g, "_") })} />
            <window.CSSelect value={s.type} options={TYPE_OPTS} onChange={(v) => setSlot(i, { type: v })} />
            <input className="ds-input" value={s.doc || ""} placeholder="description" onChange={(e) => setSlot(i, { doc: e.target.value })} />
            {(s.type === "symbol" || s.type === "classification") && <input className="ds-input ds-mono" value={s.valuesRaw != null ? s.valuesRaw : (s.values ? s.values.join(", ") : "")} placeholder="allowed values" onChange={(e) => setSlot(i, { valuesRaw: e.target.value })} />}
            {t.slots.length > 1 && <button className="re-mini del" onClick={() => setT((x) => ({ ...x, slots: x.slots.filter((_, j) => j !== i) }))}><I d="close" s={14} /></button>}
          </div>
        ))}
        <button className="cs-add-row" onClick={() => setT((x) => ({ ...x, slots: [...x.slots, { name: "slot", type: "symbol", doc: "" }] }))}><I d="plus" s={14} /> Add slot</button>
      </window.CSModal>
    );
  }

  function PackEditor({ onCreate, onClose }) {
    const [name, setName] = useState("");
    const [loaded, setLoaded] = useState(null);
    const id = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    const footer = <><button className="ds-btn ds-btn--ghost" onClick={onClose}>Cancel</button><button className="ds-btn ds-btn--primary" disabled={!id} onClick={() => { onCreate(id, name.trim(), loaded ? loaded.rules : []); onClose(); }}><I d="check" s={16} />Create pack</button></>;
    return (
      <window.CSModal title="New rule pack" subtitle="Group rules under a named pack. Optionally seed from YAML." onClose={onClose} footer={footer}>
        <window.CSField label="Pack name" hint={id || "id"}><window.CSInput value={name} onChange={setName} placeholder="e.g. SOC 2 Type II" /></window.CSField>
        <div className="pe-up"><div><div className="cs-sub-h">Seed from YAML · optional</div><p className="cs-doc" style={{ border: 0, padding: 0, background: "none" }}>Upload a ruleset (one or more <code>rule:</code> blocks, separated by <code>---</code>).</p></div><window.CSUpload onText={(text, fn) => setLoaded({ rules: F.parseRulesFromYaml(text), fn })} label="Upload ruleset" /></div>
        {loaded && <div className="pe-loaded"><I d="check" s={15} w={2.4} /><span><b>{loaded.rules.length}</b> rule{loaded.rules.length === 1 ? "" : "s"} parsed from {loaded.fn}</span></div>}
      </window.CSModal>
    );
  }

  Object.assign(window, { CSRuleEditor: RuleEditor, CSTemplateEditor: TemplateEditor, CSPackEditor: PackEditor });
})();
