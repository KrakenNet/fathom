/* ============================================================================
   Fathom Policy Studio (creem) — shared store + UI primitives.
   StudioCtx/useStudio, CS* primitives (Icon, Decision, PackTag, Yaml, Modal,
   form fields, Upload), and the engine-backed store. Loaded first.
   ============================================================================ */
(function () {
  "use strict";
  const { useState, useRef, useEffect } = React;
  const F = window.Fathom;

  /* ---- context ---- */
  const StudioCtx = React.createContext(null);
  const useStudio = () => React.useContext(StudioCtx);

  /* ---- icons ---- */
  const P = {
    bench: "M4 7h16M4 12h10M4 17h16", wire: "M3 12c3 0 3-7 6-7s3 14 6 14 3-7 6-7",
    rules: "M5 4h11l3 3v13H5zM15 4v4h4M8 12h8M8 16h5", template: "M4 5h7v6H4zM13 5h7v4h-7zM13 12h7v7h-7zM4 13h7v6H4z",
    audit: "M12 3l7 3v6c0 4-3 7-7 8-4-1-7-4-7-8V6zM9 12l2 2 4-4",
    play: "M8 5v14l11-7z", plus: "M12 5v14M5 12h14", close: "M6 6l12 12M18 6L6 18",
    check: "M5 12l4 4 10-10", deny: "M6 6l12 12M18 6L6 18", escalate: "M12 4l8 16H4zM12 10v4",
    cpu: "M8 8h8v8H8zM9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3",
    bolt: "M13 3L5 13h6l-1 8 8-11h-6z", lock: "M6 11h12v9H6zM9 11V7a3 3 0 0 1 6 0v4",
    edit: "M4 20h4L18 10l-4-4L4 16zM14 6l4 4", trash: "M5 7h14M9 7V5h6v2M7 7l1 13h8l1-13",
    chevron: "M9 6l6 6-6 6", upload: "M12 16V4M7 9l5-5 5 5M5 20h14", pack: "M12 3l8 4v10l-8 4-8-4V7zM4 7l8 4 8-4M12 11v10",
    reset: "M4 12a8 8 0 1 0 2.3-5.6M4 4v4h4", pause: "M8 5v14M16 5v14", arrow: "M5 12h14M13 6l6 6-6 6", sun: "M12 3v2M12 19v2M4.5 4.5l1.4 1.4M18 18l1.5 1.5M3 12h2M19 12h2M4.5 19.5l1.4-1.4M18 6l1.5-1.5M12 8a4 4 0 100 8 4 4 0 000-8z",
  };
  function Icon({ d, s = 18, w = 2 }) {
    return <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={w} strokeLinecap="round" strokeLinejoin="round"><path d={P[d] || P.cpu} /></svg>;
  }

  /* ---- yaml highlight ---- */
  function hl(src) {
    return String(src).split("\n").map((line) => {
      let h = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      h = h.replace(/(#.*)$/g, '<span class="y-com">$1</span>');
      h = h.replace(/^(\s*-?\s*)([A-Za-z_][\w\-\.]*)(:)/g, '$1<span class="y-key">$2</span><span class="y-punc">$3</span>');
      h = h.replace(/(\?[A-Za-z_]\w*)/g, '<span class="y-var">$1</span>');
      h = h.replace(/(&quot;[^&]*?&quot;|&#39;[^&]*?&#39;)/g, '<span class="y-str">$1</span>');
      h = h.replace(/([\s:>])(\d+)\b/g, '$1<span class="y-num">$2</span>');
      h = h.replace(/([\s:>])(deny|allow|escalate|true|false|log)\b/g, '$1<span class="y-bool">$2</span>');
      return h;
    }).join("\n");
  }
  function Yaml({ src, className = "" }) { return <pre className={`ds-yaml ${className}`}><code dangerouslySetInnerHTML={{ __html: hl(src) }} /></pre>; }

  /* ---- decision + pack ---- */
  const DEC = {
    allow: { label: "ALLOW", icon: "check", cls: "ds-allow", c: "var(--ds-allow)" },
    deny: { label: "DENY", icon: "deny", cls: "ds-deny", c: "var(--ds-deny)" },
    escalate: { label: "ESCALATE", icon: "escalate", cls: "ds-escalate", c: "var(--ds-escalate)" },
    log: { label: "LOG", icon: "check", cls: "ds-allow", c: "var(--ds-accent)" },
  };
  function Decision({ value, size }) {
    const m = DEC[value] || DEC.allow;
    const sz = size === "lg" ? "ds-decision--lg" : size === "sm" ? "ds-decision--sm" : "";
    const extra = value === "log" ? { style: { background: "var(--ds-accent-wash)", color: "var(--ds-accent)", borderColor: "var(--ds-accent)" } } : {};
    return <span className={`ds-decision ${m.cls} ${sz}`} {...extra}><Icon d={m.icon} s={size === "lg" ? 18 : 13} w={2.6} />{m.label}</span>;
  }
  const PACK_LABEL = { core: "core", nist: "NIST", owasp: "OWASP", hipaa: "HIPAA", cmmc: "CMMC" };
  function PackTag({ pack }) { return <span className="ds-tag">{PACK_LABEL[pack] || pack}</span>; }

  /* ---- modal ---- */
  function Modal({ title, subtitle, onClose, children, footer, wide }) {
    useEffect(() => { const h = (e) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, [onClose]);
    return (
      <div className="cs-scrim" onMouseDown={onClose}>
        <div className={`cs-modal ${wide ? "is-wide" : ""}`} onMouseDown={(e) => e.stopPropagation()}>
          <div className="cs-modal-head">
            <div><div className="cs-modal-title">{title}</div>{subtitle && <div className="cs-modal-sub">{subtitle}</div>}</div>
            <button className="cs-x" onClick={onClose}><Icon d="close" s={18} /></button>
          </div>
          <div className="cs-modal-body">{children}</div>
          {footer && <div className="cs-modal-foot">{footer}</div>}
        </div>
      </div>
    );
  }

  /* ---- form fields ---- */
  function Field({ label, hint, children, inline }) {
    return <label className={`cs-field ${inline ? "is-inline" : ""}`}>{label && <span className="cs-field-l">{label}{hint && <em>{hint}</em>}</span>}{children}</label>;
  }
  function TextInput({ value, onChange, placeholder, mono }) { return <input className={`ds-input ${mono ? "ds-mono" : ""}`} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />; }
  function NumberInput({ value, onChange, min, max }) { return <input type="number" className="ds-input" value={value} min={min} max={max} onChange={(e) => onChange(Number(e.target.value))} />; }
  function Select({ value, options, onChange }) {
    return <select className="ds-input ds-select" value={value} onChange={(e) => onChange(e.target.value)}>{options.map((o) => { const v = typeof o === "object" ? o.value : o; const l = typeof o === "object" ? o.label : o; return <option key={v} value={v}>{l}</option>; })}</select>;
  }
  function Toggle({ on, onChange }) { return <button className={`ds-toggle ${on ? "is-on" : ""}`} onClick={() => onChange(!on)} />; }
  function Seg({ value, options, onChange }) {
    return <div className="ds-seg">{options.map((o) => { const v = typeof o === "object" ? o.value : o; const l = typeof o === "object" ? o.label : o; return <button key={v} className={value === v ? "is-on" : ""} onClick={() => onChange(v)}>{l}</button>; })}</div>;
  }
  function Slider({ value, min, max, step, onChange, unit }) {
    return <div className="cs-slider"><input type="range" value={value} min={min} max={max} step={step || 1} onChange={(e) => onChange(Number(e.target.value))} /><span>{value}{unit || ""}</span></div>;
  }
  function Upload({ onText, label = "Upload YAML" }) {
    const ref = useRef(null);
    function pick(e) { const f = e.target.files && e.target.files[0]; if (!f) return; const r = new FileReader(); r.onload = () => onText(String(r.result), f.name); r.readAsText(f); e.target.value = ""; }
    return <><button className="ds-btn ds-btn--ghost ds-btn--sm" onClick={() => ref.current.click()}><Icon d="upload" s={15} />{label}</button><input ref={ref} type="file" accept=".yaml,.yml,.txt" style={{ display: "none" }} onChange={pick} /></>;
  }

  /* ---- count-up (timer-based; preview throttles rAF) ---- */
  function useCountUp(target, ms = 500) {
    const [v, setV] = useState(target); const from = useRef(target);
    useEffect(() => {
      if (from.current === target) { setV(target); return; }
      const f = from.current, s = Date.now();
      const h = setInterval(() => { const p = Math.min(1, (Date.now() - s) / ms); setV(f + (target - f) * (1 - Math.pow(1 - p, 3))); if (p >= 1) { from.current = target; clearInterval(h); } }, 33);
      return () => clearInterval(h);
    }, [target, ms]);
    return v;
  }

  /* ---- hash for audit chain ---- */
  function hashHex(str) { let h = 0x811c9dc5; for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 0x01000193); } return (h >>> 0).toString(16).padStart(8, "0"); }

  /* ---- store provider ----
     Loads real scenarios / templates / rules from the studio API and routes
     every evaluation through the real engine. If the API is unreachable it
     falls back to the deterministic in-browser mock engine, flagged
     ``live=false`` so the shell can label the session as offline. */
  function StudioProvider({ children }) {
    const [theme, setTheme] = useState("light");
    const [live, setLive] = useState(true);
    const [ready, setReady] = useState(false);
    const [ruleset, setRulesetState] = useState(null);
    const [templates, setTemplates] = useState([]);
    const [rules, setRules] = useState([]);
    const [packs, setPacks] = useState({});
    const [scenarios, setScenarios] = useState({});
    const [ingest, setIngest] = useState({ rate: 1, include: {} });
    const [audit, setAudit] = useState([]);
    const memoryRef = useRef(F.makeMemory());
    const detailCache = useRef({});
    const seqRef = useRef(0);
    const [, bump] = useState(0);

    useEffect(() => { document.documentElement.setAttribute("data-theme", theme); }, [theme]);

    useEffect(() => {
      let cancelled = false;
      (async () => {
        try {
          const scns = await window.StudioAPI.loadScenarios();
          if (cancelled) return;
          const obj = {}, inc = {}, seenPacks = {};
          for (const s of scns) { obj[s.id] = s; inc[s.id] = true; seenPacks[s.ruleset] = { name: s.ruleset }; }
          // Load every distinct ruleset so the Rules + Templates views browse
          // the full set; each rule/template is tagged with its ruleset (pack).
          const rsIds = Object.keys(seenPacks);
          const details = await Promise.all(rsIds.map((id) =>
            window.StudioAPI.loadRuleset(id).then((d) => { detailCache.current[id] = d; return d; })));
          if (cancelled) return;
          const allRules = [], allTemplates = [];
          for (const d of details) { allRules.push(...d.rules); allTemplates.push(...d.templates); }
          setScenarios(obj); setPacks(seenPacks);
          setIngest((g) => ({ ...g, include: inc }));
          setTemplates(allTemplates); setRules(allRules); setRulesetState(rsIds[0] || null);
          if (!cancelled) setReady(true);
        } catch (e) {
          if (cancelled) return;
          console.warn("Studio API unavailable — using offline mock engine:", e);
          setLive(false);
          setTemplates(F.DEFAULT_TEMPLATES.map((x) => JSON.parse(JSON.stringify(x))));
          setRules(F.DEFAULT_RULES.map((r) => { const c = Object.assign({}, r); if (r.conditions) c.conditions = JSON.parse(JSON.stringify(r.conditions)); return c; }));
          setPacks(Object.assign({}, F.PACKS));
          const sc = JSON.parse(JSON.stringify(F.SCENARIOS));
          setScenarios(sc);
          setIngest({ rate: 1, include: Object.fromEntries(Object.keys(sc).map((k) => [k, true])) });
          setReady(true);
        }
      })();
      return () => { cancelled = true; };
    }, []);

    function pushAudit(rec) { if (rec) setAudit((a) => [rec, ...a].slice(0, 80)); }

    function mockAuditRecord(r, facts) {
      seqRef.current += 1; const seq = seqRef.current;
      const prevHash = audit.length ? audit[0].hash : "00000000";
      const hash = hashHex(prevHash + JSON.stringify({ seq, d: r.decision, r: r.reason, f: facts }));
      const sig = (hashHex("s0" + hash) + hashHex(hash + "s1") + hashHex("s2" + hash) + hashHex(hash + "s3")).toUpperCase();
      return { seq, ts: Date.now(), decision: r.decision, reason: r.reason, durationUs: r.durationUs, prevHash, hash, sig, facts: facts.map((f) => ({ ...f })), trace: r.trace, fired: r.fired };
    }

    // Evaluate against the real engine (or the offline mock). Async; pushes
    // the resulting signed audit record onto the chain. Returns the result.
    async function evaluate(rsId, facts) {
      if (!live) {
        const r = F.evaluate(facts.map((f) => ({ ...f })), { memory: memoryRef.current, rules });
        const rec = mockAuditRecord(r, facts);
        pushAudit(rec);
        return Object.assign({}, r, { audit: rec });
      }
      const res = await window.StudioAPI.evaluate(rsId, facts);
      pushAudit(res.audit);
      return res;
    }

    const store = {
      theme, setTheme, live, ready,
      ruleset, templates, setTemplates, rules, setRules,
      packs, setPacks, addPack: (id, name) => setPacks((p) => ({ ...p, [id]: { name: name || id } })),
      scenarios, setScenarios, ingest, setIngest, audit, evaluate,
      resetAudit: () => { seqRef.current = 0; setAudit([]); },
      memory: memoryRef.current, resetMemory: () => { memoryRef.current = F.makeMemory(); bump((n) => n + 1); },
    };
    return <StudioCtx.Provider value={store}>{children}</StudioCtx.Provider>;
  }

  Object.assign(window, {
    StudioCtx, useStudio, StudioProvider,
    CSIcon: Icon, CSDecision: Decision, CSPackTag: PackTag, CSYaml: Yaml, csHl: hl, DEC,
    CSModal: Modal, CSField: Field, CSInput: TextInput, CSNumber: NumberInput, CSSelect: Select,
    CSToggle: Toggle, CSSeg: Seg, CSSlider: Slider, CSUpload: Upload, useCountUp,
  });
})();
