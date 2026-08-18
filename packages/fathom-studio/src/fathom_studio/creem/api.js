/* ============================================================================
   Studio API client + adapters.
   Bridges the creem SPA to the real Fathom engine behind /studio/api/*.
   Converts the backend's real payloads into the shapes the views already
   consume, so a "Run" is a genuine engine evaluation — never fabricated.
   Exposed on window.StudioAPI. Loaded after engine.js, before the JSX views.
   ============================================================================ */
(function () {
  "use strict";

  const BASE = "/studio/api";

  async function getJSON(path) {
    const r = await fetch(BASE + path, { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`${path} → ${r.status}`);
    return r.json();
  }
  async function postJSON(path, body) {
    const r = await fetch(BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      let detail = r.status;
      try { detail = (await r.json()).detail || detail; } catch (e) { /* ignore */ }
      throw new Error(`${path} → ${detail}`);
    }
    return r.json();
  }

  /* ---- shape adapters: real engine → SPA view shapes ---- */
  // A real rule_trace entry is "module::rule"; strip the module prefix.
  function bareRuleName(s) { const i = String(s).indexOf("::"); return i >= 0 ? s.slice(i + 2) : s; }
  // The studio palette only colours allow/deny/escalate/log; coerce others.
  function coerceSeverity(decision) {
    const d = String(decision || "").toLowerCase();
    return ["allow", "deny", "escalate", "log"].includes(d) ? d : "escalate";
  }

  // {template, data} → SPA fact {__t, ...data}
  function factToSpa(f) { return Object.assign({ __t: f.template }, f.data || {}); }

  function adaptTemplate(t, ruleset) {
    return {
      name: t.name, pack: ruleset, builtin: true, doc: t.description || "",
      slots: (t.slots || []).map((s) => ({
        name: s.name, type: s.type, doc: "",
        values: s.allowed_values || [], required: !!s.required,
      })),
    };
  }

  // Render the rule's real `when` patterns (slot conditions intact). Falls back
  // to bare template names only when the backend sent no structured patterns.
  function ruleYaml(r, ruleset) {
    const L = [`rule: ${r.name}`, `ruleset: ${ruleset}`, `salience: ${r.salience}`];
    if (r.description) L.push(`summary: ${r.description}`);
    L.push("when:");
    const when = (r.when && r.when.length)
      ? r.when
      : (r.templates && r.templates.length ? r.templates : ["fact"]).map((t) => ({ template: t, conditions: [] }));
    for (const p of when) {
      L.push(`  - ${p.template}:${p.alias ? "  # " + p.alias : ""}`);
      const conds = p.conditions || [];
      for (const c of conds) {
        if (c.slot && (c.expression || c.bind)) L.push(`      ${c.slot}: ${c.expression || c.bind}`);
        if (c.test) L.push(`      test: ${c.test}`);
      }
      if (!conds.length) L.push(`      # matches any ${p.template}`);
    }
    L.push("then:");
    L.push(`  decision: ${r.decision}`);
    if (r.reason) L.push(`  reason: "${r.reason}"`);
    return L.join("\n");
  }

  function adaptRule(r, ruleset) {
    return {
      id: ruleset + "::" + r.name, name: r.name, module: ruleset, pack: ruleset,
      control: "", salience: r.salience, severity: coerceSeverity(r.decision),
      decisionRaw: r.decision, enabled: true, builtin: true,
      summary: r.description || r.reason || "", reason: r.reason || "",
      templates: r.templates || [], yaml: ruleYaml(r, ruleset),
    };
  }

  function adaptScenario(s) {
    return {
      id: s.id, label: s.title, blurb: s.description, ruleset: s.ruleset,
      facts: (s.facts || []).map(factToSpa),
    };
  }

  // Build the SPA result object the Bench/Audit views expect from a real
  // /evaluate response. Per-rule timings are NOT fabricated (the engine only
  // reports a total duration); the trace shows each rule's salience instead.
  function adaptResult(res, factsSpa, ruleset) {
    const fired = new Set((res.rule_trace || []).map(bareRuleName));
    const adaptedRules = (res.rules || []).map((r) => adaptRule(r, ruleset))
      .sort((a, b) => b.salience - a.salience);
    const trace = adaptedRules.map((r) => Object.assign({}, r, {
      matched: fired.has(r.name),
      reason: fired.has(r.name) ? r.reason : undefined,
    }));
    const firedNodes = trace.filter((n) => n.matched && n.severity !== "log");
    const rec = res.audit ? adaptAuditRecord(res.audit, trace, factsSpa, res) : null;
    return {
      decision: res.decision || "allow",
      reason: res.reason || "All policies satisfied — request permitted",
      durationUs: res.duration_us,
      moduleTrace: res.module_trace || [],
      trace, fired: firedNodes,
      auditFired: { signed: true },
      factCount: factsSpa.length, ruleCount: adaptedRules.length,
      audit: rec,
    };
  }

  function adaptAuditRecord(a, trace, factsSpa, res) {
    return {
      seq: a.seq, ts: Date.parse(a.ts) || Date.now(),
      decision: a.decision || "allow", reason: a.reason || "",
      durationUs: a.duration_us != null ? a.duration_us : (res ? res.duration_us : 0),
      prevHash: a.prev_hash, hash: a.hash,
      sig: a.signature || "(attestation extra not installed)",
      facts: factsSpa, trace,
      fired: trace.filter((n) => n.matched && n.severity !== "log"),
      ruleset: a.ruleset,
    };
  }

  window.StudioAPI = {
    bareRuleName, coerceSeverity, factToSpa,
    adaptTemplate, adaptRule, adaptScenario, adaptResult,
    async loadScenarios() { return (await getJSON("/scenarios")).items.map(adaptScenario); },
    async loadRuleset(id) {
      const d = await getJSON("/ruleset/" + encodeURIComponent(id));
      return {
        ruleset: id,
        templates: (d.templates || []).map((t) => adaptTemplate(t, id)),
        rules: (d.rules || []).map((r) => adaptRule(r, id)),
        modules: d.modules || [],
      };
    },
    // factsSpa: SPA facts ({__t,...}); returns the adapted result.
    async evaluate(ruleset, factsSpa) {
      const facts = factsSpa.map((f) => {
        const data = {}; for (const k of Object.keys(f)) if (k !== "__t") data[k] = f[k];
        return { template: f.__t, data };
      });
      const res = await postJSON("/evaluate", { ruleset, facts });
      return adaptResult(res, factsSpa.map((f) => Object.assign({}, f)), ruleset);
    },
    async verify(signature) { return postJSON("/audit/verify", { signature }); },
  };
})();
