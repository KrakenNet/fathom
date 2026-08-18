/* ============================================================================
   Fathom mini-engine v2 — declarative, editable rule model.
   Rules are DATA (conditions + reason template), matched by a generic engine,
   so the Studio UI can author them. A couple of stateful rules keep JS tests.
   Exposed on window.Fathom.
   ============================================================================ */
(function () {
  "use strict";

  /* ---- Classification lattice ------------------------------------------- */
  const LATTICE = ["public", "internal", "confidential", "secret", "top-secret"];
  const rank = (c) => LATTICE.indexOf(String(c == null ? "" : c).toLowerCase());
  const dominates = (a, b) => rank(a) >= rank(b);
  const below = (a, b) => rank(a) < rank(b);
  const meetsOrExceeds = (a, b) => rank(a) >= rank(b);

  /* ---- Operators -------------------------------------------------------- */
  const OPS = {
    eq:   { label: "equals",            sym: "==",  arity: 1 },
    neq:  { label: "not equals",        sym: "!=",  arity: 1 },
    in:   { label: "in",                sym: "∈",   arity: "list" },
    nin:  { label: "not in",            sym: "∉",   arity: "list" },
    below:{ label: "below (class)",     sym: "<<",  arity: 1, cls: true },
    exceeds:{label: "above (class)",    sym: ">>",  arity: 1, cls: true },
    mte:  { label: "meets/exceeds",     sym: "⊒",   arity: 1, cls: true },
    gt:   { label: "greater than",      sym: ">",   arity: 1, num: true },
    lt:   { label: "less than",         sym: "<",   arity: 1, num: true },
    gte:  { label: "≥",                 sym: ">=",  arity: 1, num: true },
    lte:  { label: "≤",                 sym: "<=",  arity: 1, num: true },
  };
  function cmp(op, a, b) {
    switch (op) {
      case "eq":  return a === b || String(a) === String(b);
      case "neq": return !(a === b || String(a) === String(b));
      case "in":  return Array.isArray(b) && b.map(String).includes(String(a));
      case "nin": return Array.isArray(b) && !b.map(String).includes(String(a));
      case "below":   return rank(a) < rank(b);
      case "exceeds": return rank(a) > rank(b);
      case "mte":     return rank(a) >= rank(b);
      case "gt":  return Number(a) > Number(b);
      case "lt":  return Number(a) < Number(b);
      case "gte": return Number(a) >= Number(b);
      case "lte": return Number(a) <= Number(b);
      default: return false;
    }
  }

  /* ---- Default Templates ------------------------------------------------ */
  const DEFAULT_TEMPLATES = [
    { name: "agent", pack: "core", builtin: true, doc: "An autonomous agent operating in the fleet.",
      slots: [
        { name: "id", type: "symbol", doc: "Unique agent identifier" },
        { name: "clearance", type: "classification", doc: "Security clearance level", values: LATTICE },
        { name: "purpose", type: "symbol", doc: "Declared operating purpose" },
        { name: "session_id", type: "symbol", doc: "Session this agent belongs to" },
      ] },
    { name: "data_request", pack: "core", builtin: true, doc: "A request by an agent to read or write a data source.",
      slots: [
        { name: "agent_id", type: "symbol", doc: "Requesting agent" },
        { name: "target", type: "symbol", doc: "Data source being requested" },
        { name: "classification", type: "classification", doc: "Sensitivity of target data", values: LATTICE },
        { name: "action", type: "symbol", doc: "read | write | delete", values: ["read", "write", "delete"] },
      ] },
    { name: "tool_call", pack: "owasp", builtin: true, doc: "An agent invoking an external tool or capability.",
      slots: [
        { name: "agent_id", type: "symbol", doc: "Calling agent" },
        { name: "tool", type: "symbol", doc: "Tool / capability name" },
        { name: "scope", type: "symbol", doc: "internal | external", values: ["internal", "external"] },
        { name: "approved", type: "boolean", doc: "Human approval on file" },
      ] },
    { name: "phi_access", pack: "hipaa", builtin: true, doc: "Access to protected health information.",
      slots: [
        { name: "agent_id", type: "symbol", doc: "Accessing agent" },
        { name: "record_type", type: "symbol", doc: "diagnosis | billing | demographics", values: ["diagnosis", "billing", "demographics"] },
        { name: "purpose", type: "symbol", doc: "treatment | payment | operations | research", values: ["treatment", "payment", "operations", "research", "marketing"] },
      ] },
  ];

  /* ---- Default Rules ----------------------------------------------------- */
  /* Declarative rules use `conditions` + `reason` (template string with {var}).
     Built-in stateful rules use a `test(ctx)` fn + `reason(b)` fn. */
  const SEV = { allow: 0, log: 0, escalate: 2, deny: 3 };

  const DEFAULT_RULES = [
    {
      id: "ac-clearance-gate", name: "clearance-gate", module: "access-control", pack: "nist",
      control: "AC-3", salience: 90, severity: "deny", enabled: true,
      summary: "Deny when an agent's clearance is below the data classification it requests.",
      conditions: [
        { template: "agent", match: [
          { slot: "id", op: "bind", var: "a" },
          { slot: "clearance", op: "bind", var: "c" },
        ] },
        { template: "data_request", match: [
          { slot: "agent_id", op: "eq", value: { var: "a" } },
          { slot: "classification", op: "bind", var: "need" },
          { slot: "classification", op: "exceeds", value: { var: "c" } },
          { slot: "target", op: "bind", var: "t" },
        ] },
      ],
      reason: "Agent clearance '{c}' insufficient for '{need}' data ('{t}')",
    },
    {
      id: "owasp-excessive-agency", name: "excessive-agency", module: "agentic-guardrails", pack: "owasp",
      control: "ASI-06", salience: 80, severity: "deny", enabled: true,
      summary: "Deny unapproved external tool calls (OWASP Agentic: Excessive Agency).",
      conditions: [
        { template: "tool_call", match: [
          { slot: "tool", op: "bind", var: "tool" },
          { slot: "scope", op: "eq", value: "external" },
          { slot: "approved", op: "eq", value: false },
        ] },
      ],
      reason: "External tool '{tool}' invoked without human approval",
    },
    {
      id: "hipaa-minimum-necessary", name: "minimum-necessary", module: "phi-controls", pack: "hipaa",
      control: "164.502(b)", salience: 75, severity: "deny", enabled: true,
      summary: "Deny PHI access whose purpose isn't treatment, payment, or operations.",
      conditions: [
        { template: "phi_access", match: [
          { slot: "record_type", op: "bind", var: "rec" },
          { slot: "purpose", op: "bind", var: "purpose" },
          { slot: "purpose", op: "nin", value: ["treatment", "payment", "operations"] },
        ] },
      ],
      reason: "PHI '{rec}' access for purpose '{purpose}' violates minimum-necessary",
    },
    {
      id: "wm-cumulative-pii", name: "cumulative-pii", module: "fleet-memory", pack: "core",
      control: "AU-12", salience: 85, severity: "deny", enabled: true, builtin: true, temporal: true,
      threshold: 3,
      summary: "Working memory: deny once an agent has touched ≥N distinct sensitive sources this session.",
      test(ctx) {
        const N = ctx.rule.threshold || 3;
        for (const a of ctx.byTemplate("agent")) {
          const distinct = ctx.memory.distinctTargets(a.id);
          for (const r of ctx.byTemplate("data_request")) {
            if (r.agent_id === a.id && rank(r.classification) >= rank("confidential")) {
              const projected = new Set([...distinct, r.target]);
              if (projected.size >= N) return { matched: true, bindings: { agent: a.id, count: projected.size } };
            }
          }
        }
        return { matched: false };
      },
      reason: (b) => `Agent '${b.agent}' accessed ${b.count} distinct sensitive sources this session — cumulative exposure limit`,
      yaml: `rule: cumulative-pii
module: fleet-memory
salience: 85
when:
  - agent: { id: ?a }
  - data_request: { agent_id: ?a, target: ?t }
  - test: distinct_count(?a, target) >= 3   # spans prior evaluations
then:
  decision: deny
  reason: "Agent '?a' exceeded cumulative exposure limit"`,
    },
    {
      id: "nist-audit-all", name: "audit-all-access", module: "audit", pack: "nist",
      control: "AU-2", salience: 10, severity: "log", enabled: true, builtin: true,
      summary: "Emit a signed audit record for every data request (always fires).",
      test(ctx) {
        const reqs = ctx.byTemplate("data_request");
        return reqs.length ? { matched: true, bindings: { n: reqs.length } } : { matched: false };
      },
      reason: (b) => `${b.n} data request(s) recorded to append-only audit log`,
      yaml: `rule: audit-all-access
module: audit
salience: 10
when:
  - data_request: {}
then:
  assert:
    audit_record: { signed: true, ts: now() }`,
    },
  ];

  /* ---- YAML generation for declarative rules ---------------------------- */
  function valRepr(v) {
    if (v && typeof v === "object" && "var" in v) return "?" + v.var;
    if (Array.isArray(v)) return "[" + v.join(", ") + "]";
    if (typeof v === "string") return v;
    return String(v);
  }
  function ruleToYaml(rule) {
    if (rule.yaml) return rule.yaml; // built-ins ship literal yaml
    const L = [];
    L.push(`rule: ${rule.name}`);
    if (rule.pack) L.push(`pack: ${rule.pack}`);
    L.push(`module: ${rule.module}`);
    if (rule.control) L.push(`control: ${rule.control}`);
    L.push(`salience: ${rule.salience}`);
    if (rule.summary) L.push(`summary: ${rule.summary}`);
    L.push(`when:`);
    for (const cond of rule.conditions || []) {
      L.push(`  - ${cond.template}:`);
      const tests = [];
      for (const m of cond.match) {
        if (m.op === "bind") L.push(`      ${m.slot}: ?${m.var}`);
        else if (m.op === "eq") L.push(`      ${m.slot}: ${valRepr(m.value)}`);
        else tests.push(`${OPS[m.op] ? m.op : m.op}(${m.slot}, ${valRepr(m.value)})`);
      }
      for (const t of tests) L.push(`  - test: ${t}`);
    }
    L.push(`then:`);
    L.push(`  decision: ${rule.severity}`);
    L.push(`  reason: "${rule.reason}"`);
    return L.join("\n");
  }

  /* ---- YAML -> rule(s) parser (tuned to the format ruleToYaml emits) ----- */
  function stripQuotes(s) {
    s = (s || "").trim();
    if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) return s.slice(1, -1);
    return s;
  }
  function litVal(s) {
    s = (s || "").trim();
    if (s === "true") return true;
    if (s === "false") return false;
    if (s !== "" && /^-?\d+(\.\d+)?$/.test(s)) return Number(s);
    return stripQuotes(s);
  }
  function valAfter(line) { return line.slice(line.indexOf(":") + 1).trim(); }
  function splitTopComma(s) {
    const out = []; let d = 0, cur = "";
    for (const ch of s) {
      if (ch === "[") d++; else if (ch === "]") d--;
      if (ch === "," && d === 0) { out.push(cur); cur = ""; } else cur += ch;
    }
    if (cur.trim()) out.push(cur);
    return out.map((x) => x.trim());
  }
  function parseV(raw) {
    raw = (raw || "").trim();
    if (raw.startsWith("[")) return raw.replace(/^\[/, "").replace(/\]$/, "").split(",").map((x) => stripQuotes(x.trim())).filter(Boolean);
    if (raw.startsWith("?")) return { var: raw.slice(1) };
    return litVal(raw);
  }
  function parseTestExpr(expr) {
    const m = (expr || "").match(/^(\w+)\s*\((.*)\)\s*$/);
    if (!m) return null;
    const args = splitTopComma(m[2]);
    return { slot: args[0], op: m[1], value: parseV(args[1] || "") };
  }
  function parseSlotEntry(slot, rawv, cond) {
    rawv = (rawv || "").trim();
    if (rawv.startsWith("?")) cond.match.push({ slot, op: "bind", var: rawv.slice(1) });
    else cond.match.push({ slot, op: "eq", value: litVal(rawv) });
  }
  function parseOneRule(lines) {
    const r = { id: "rule-" + Math.random().toString(36).slice(2, 8), name: "", module: "custom", pack: "core", control: "", salience: 50, severity: "deny", enabled: true, summary: "", conditions: [], reason: "" };
    let section = null, cond = null;
    for (const raw of lines) {
      if (!raw.trim() || raw.trim().startsWith("#")) continue;
      const indent = raw.length - raw.replace(/^ +/, "").length;
      const t = raw.trim();
      if (indent === 0 && !t.startsWith("-")) {
        const key = t.split(":")[0].trim();
        if (key === "rule") r.name = stripQuotes(valAfter(t));
        else if (key === "pack") r.pack = stripQuotes(valAfter(t));
        else if (key === "module") r.module = stripQuotes(valAfter(t));
        else if (key === "control") r.control = stripQuotes(valAfter(t));
        else if (key === "salience") r.salience = Number(valAfter(t)) || 50;
        else if (key === "summary") r.summary = stripQuotes(valAfter(t));
        else if (key === "when") { section = "when"; cond = null; }
        else if (key === "then") { section = "then"; }
        else if (key === "reason") r.reason = stripQuotes(valAfter(t));
        else if (key === "decision") r.severity = stripQuotes(valAfter(t));
        continue;
      }
      if (section === "when") {
        if (t.startsWith("- test:")) { const e = parseTestExpr(valAfter(t)); if (e && cond) cond.match.push(e); }
        else if (t.startsWith("-")) {
          const body = t.slice(1).trim();
          const ci = body.indexOf(":");
          const tn = (ci >= 0 ? body.slice(0, ci) : body).trim();
          const rest = ci >= 0 ? body.slice(ci + 1).trim() : "";
          cond = { template: tn, match: [] };
          r.conditions.push(cond);
          if (rest.startsWith("{")) {
            const inside = rest.replace(/^\{/, "").replace(/\}$/, "");
            for (const part of splitTopComma(inside)) { const pi = part.indexOf(":"); if (pi > 0) parseSlotEntry(part.slice(0, pi).trim(), part.slice(pi + 1), cond); }
          }
        } else if (cond) { const ci = t.indexOf(":"); if (ci > 0) parseSlotEntry(t.slice(0, ci).trim(), t.slice(ci + 1), cond); }
      } else if (section === "then") {
        if (t.startsWith("decision:")) r.severity = stripQuotes(valAfter(t));
        else if (t.startsWith("reason:")) r.reason = stripQuotes(valAfter(t));
      }
    }
    if (!r.name) return null;
    if (!["allow", "deny", "escalate", "log"].includes(r.severity)) r.severity = "deny";
    if (r.conditions.length === 0) r.conditions = [{ template: "agent", match: [] }];
    return r;
  }
  function parseRulesFromYaml(text) {
    const lines = String(text || "").replace(/\r/g, "").split("\n");
    const blocks = []; let cur = [];
    for (const line of lines) {
      if (line.trim() === "---") { if (cur.length) blocks.push(cur); cur = []; continue; }
      if (/^rule\s*:/.test(line) && cur.some((l) => /^rule\s*:/.test(l))) { blocks.push(cur); cur = [line]; continue; }
      cur.push(line);
    }
    if (cur.length) blocks.push(cur);
    return blocks.map(parseOneRule).filter(Boolean);
  }

  /* ---- Declarative matcher ---------------------------------------------- */
  function applyMatch(items, fact, b) {
    for (const it of items) {
      const fv = fact[it.slot];
      if (it.op === "bind") {
        if (it.var in b) { if (String(b[it.var]) !== String(fv)) return false; }
        else b[it.var] = fv;
        continue;
      }
      const target = (it.value && typeof it.value === "object" && "var" in it.value) ? b[it.value.var] : it.value;
      if (!cmp(it.op, fv, target)) return false;
    }
    return true;
  }
  function matchDeclarative(rule, facts, b, pi) {
    const conds = rule.conditions || [];
    if (pi >= conds.length) return { matched: true, bindings: b };
    const cond = conds[pi];
    for (const fact of facts) {
      if (fact.__t !== cond.template) continue;
      const nb = { ...b };
      if (applyMatch(cond.match, fact, nb)) {
        const res = matchDeclarative(rule, facts, nb, pi + 1);
        if (res.matched) return res;
      }
    }
    return { matched: false };
  }
  function fillTemplate(tpl, b) {
    return String(tpl).replace(/\{(\w+)\}/g, (_, k) => (k in b ? b[k] : "?" + k));
  }

  /* ---- Working memory --------------------------------------------------- */
  function makeMemory() {
    const targetsByAgent = {};
    return {
      targetsByAgent,
      distinctTargets(id) { return targetsByAgent[id] ? new Set(targetsByAgent[id]) : new Set(); },
      record(facts) {
        for (const r of facts.filter((f) => f.__t === "data_request")) {
          if (rank(r.classification) >= rank("confidential"))
            (targetsByAgent[r.agent_id] = targetsByAgent[r.agent_id] || new Set()).add(r.target);
        }
      },
      reset() { for (const k of Object.keys(targetsByAgent)) delete targetsByAgent[k]; },
      snapshot() { return Object.entries(targetsByAgent).map(([k, v]) => ({ agent: k, sources: [...v] })); },
    };
  }

  /* ---- Evaluation ------------------------------------------------------- */
  function evaluate(facts, opts) {
    opts = opts || {};
    const memory = opts.memory || makeMemory();
    const ruleSet = (opts.rules || DEFAULT_RULES).filter((r) => r.enabled !== false);
    const t0 = (performance.now ? performance.now() : Date.now());

    const ctx = { facts, memory, byTemplate: (name) => facts.filter((f) => f.__t === name) };
    const agenda = ruleSet.slice().sort((a, b) => b.salience - a.salience);

    const trace = [];
    const fired = [];
    let decision = "allow";
    let primaryReason = "All policies satisfied — request permitted";

    for (const rule of agenda) {
      let res, reasonText = "";
      try {
        if (typeof rule.test === "function") {
          ctx.rule = rule;
          res = rule.test(ctx);
          if (res.matched) reasonText = typeof rule.reason === "function" ? rule.reason(res.bindings) : fillTemplate(rule.reason, res.bindings);
        } else {
          res = matchDeclarative(rule, facts, {}, 0);
          if (res.matched) reasonText = fillTemplate(rule.reason, res.bindings);
        }
      } catch (e) { res = { matched: false }; }

      const us = 3 + (rule.salience % 7) + (res.matched ? 4 : 1) + ((rule.conditions ? rule.conditions.length : 1) * 2);
      const entry = {
        id: rule.id, name: rule.name, module: rule.module, pack: rule.pack, control: rule.control,
        salience: rule.salience, severity: rule.severity, matched: !!res.matched,
        bindings: res.bindings || null, us,
      };
      if (res.matched) {
        entry.reason = reasonText;
        fired.push(entry);
        if (SEV[rule.severity] > SEV[decision]) {
          if (rule.severity !== "log") { decision = rule.severity; primaryReason = reasonText; }
        }
      }
      trace.push(entry);
    }
    memory.record(facts);

    const durationUs = Math.max(12, Math.round(((performance.now ? performance.now() : Date.now()) - t0) * 1000) + trace.length * 3 || 12);
    const realDecision = decision === "log" ? "allow" : decision;
    return {
      decision: realDecision, reason: primaryReason, durationUs,
      trace, fired: fired.filter((f) => f.severity !== "log"),
      auditFired: fired.find((f) => f.severity === "log") || null,
      factCount: facts.length, ruleCount: agenda.length, memory,
    };
  }

  /* ---- Ingest config + synthetic traffic -------------------------------- */
  const INGEST_DEFAULTS = {
    agents: 8,
    weights: { data_request: 62, tool_call: 20, phi_access: 18 },
    externalProb: 0.66,
    approvalProb: 0.45,
    sensitivity: "mixed",   // low | mixed | high  → biases requested classification
    clearance: "mixed",     // low | mixed | high  → biases agent clearance
    targets: ["hr_records", "metrics_db", "billing", "patient_index", "model_weights", "audit_store", "vault", "telemetry"],
  };
  const AGENT_NAMES = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "theta", "iota", "kappa", "lambda", "mu", "nu"];
  function biasedClass(bias) {
    const r = Math.random();
    if (bias === "high") return LATTICE[Math.min(4, 2 + Math.floor(r * 3))];
    if (bias === "low") return LATTICE[Math.floor(r * 3)];
    return LATTICE[Math.floor(r * 5)];
  }
  function weightedType(w) {
    const total = (w.data_request + w.tool_call + w.phi_access) || 1;
    let r = Math.random() * total;
    if ((r -= w.data_request) < 0) return "data_request";
    if ((r -= w.tool_call) < 0) return "tool_call";
    return "phi_access";
  }
  function genTraffic(cfg) {
    cfg = cfg || INGEST_DEFAULTS;
    const pick = (a) => a[Math.floor(Math.random() * a.length)];
    const agent = `agent-${AGENT_NAMES[Math.floor(Math.random() * Math.max(1, Math.min(cfg.agents, AGENT_NAMES.length)))]}`;
    const clearance = biasedClass(cfg.clearance);
    const facts = [{ __t: "agent", id: agent, clearance, purpose: "ops", session_id: "live" }];
    const type = weightedType(cfg.weights);
    let summary;
    if (type === "data_request") {
      const target = pick(cfg.targets.length ? cfg.targets : INGEST_DEFAULTS.targets);
      const action = pick(["read", "read", "write"]);
      facts.push({ __t: "data_request", agent_id: agent, target, classification: biasedClass(cfg.sensitivity), action });
      summary = `${action} ${target}`;
    } else if (type === "tool_call") {
      const tool = pick(["shell.exec", "http.post", "email.send", "db.query", "fs.write"]);
      const scope = Math.random() < cfg.externalProb ? "external" : "internal";
      const approved = Math.random() < cfg.approvalProb;
      facts.push({ __t: "tool_call", agent_id: agent, tool, scope, approved });
      summary = `${tool} (${scope})`;
    } else {
      const record_type = pick(["diagnosis", "billing", "demographics"]);
      const purpose = pick(["treatment", "payment", "operations", "research", "marketing"]);
      facts.push({ __t: "phi_access", agent_id: agent, record_type, purpose });
      summary = `phi:${record_type}/${purpose}`;
    }
    return { agent, facts, summary };
  }

  /* ---- Seed scenarios --------------------------------------------------- */
  const SCENARIOS = {
    "clearance-breach": { label: "Clearance breach", blurb: "A secret-cleared agent reaches for top-secret data.",
      facts: [
        { __t: "agent", id: "agent-alpha", clearance: "secret", purpose: "threat-analysis", session_id: "sess-001" },
        { __t: "data_request", agent_id: "agent-alpha", target: "hr_records", classification: "top-secret", action: "read" },
      ] },
    "clean-read": { label: "Permitted read", blurb: "Everything checks out — the request is allowed.",
      facts: [
        { __t: "agent", id: "agent-beta", clearance: "confidential", purpose: "reporting", session_id: "sess-002" },
        { __t: "data_request", agent_id: "agent-beta", target: "metrics_db", classification: "internal", action: "read" },
      ] },
    "rogue-tool": { label: "Excessive agency", blurb: "An agent calls an external tool with no approval.",
      facts: [
        { __t: "agent", id: "agent-gamma", clearance: "internal", purpose: "automation", session_id: "sess-003" },
        { __t: "tool_call", agent_id: "agent-gamma", tool: "shell.exec", scope: "external", approved: false },
      ] },
    "phi-research": { label: "Minimum-necessary", blurb: "PHI pulled for 'research' — not a permitted purpose.",
      facts: [
        { __t: "agent", id: "agent-delta", clearance: "confidential", purpose: "ml-training", session_id: "sess-004" },
        { __t: "phi_access", agent_id: "agent-delta", record_type: "diagnosis", purpose: "research" },
      ] },
  };

  // a blank fact for the builder, given a template
  function blankFact(tpl) {
    const f = { __t: tpl.name };
    for (const s of tpl.slots) {
      if (s.type === "boolean") f[s.name] = false;
      else if (s.values && s.values.length) f[s.name] = s.values[0];
      else f[s.name] = "";
    }
    return f;
  }

  window.Fathom = {
    LATTICE, rank, dominates, below, meetsOrExceeds, OPS, cmp,
    DEFAULT_TEMPLATES, DEFAULT_RULES, SCENARIOS, INGEST_DEFAULTS, AGENT_NAMES,
    makeMemory, evaluate, ruleToYaml, parseRulesFromYaml, fillTemplate, genTraffic, blankFact,
    PACKS: {
      core: { name: "Fathom Core" }, nist: { name: "fathom-nist-800-53" },
      owasp: { name: "fathom-owasp-agentic" }, hipaa: { name: "fathom-hipaa" }, cmmc: { name: "fathom-cmmc" },
    },
  };
})();
