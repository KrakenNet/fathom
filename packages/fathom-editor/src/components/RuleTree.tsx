import { useState, useEffect, useMemo } from "react";
import { listRules, listModules } from "../api/fathom";
import type { Rule, Module } from "../api/fathom";

interface RuleTreeProps {
  onSelectRule?: (rule: Rule) => void;
}

interface TreeNode {
  label: string;
  type: "module" | "rule";
  rule?: Rule;
  children?: TreeNode[];
}

export default function RuleTree({ onSelectRule }: RuleTreeProps) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [modules, setModules] = useState<Module[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    listRules().then(setRules).catch(() => {});
    listModules().then(setModules).catch(() => {});
  }, []);

  const tree = useMemo((): TreeNode[] => {
    const lowerSearch = search.toLowerCase();

    // Group rules by module
    const byModule: Record<string, Rule[]> = {};
    for (const rule of rules) {
      const mod = rule.module ?? "MAIN";
      if (!byModule[mod]) byModule[mod] = [];
      byModule[mod].push(rule);
    }

    // Build tree nodes from modules
    const nodes: TreeNode[] = modules.map((m) => {
      const moduleRules = byModule[m.name] ?? [];
      const children: TreeNode[] = moduleRules
        .filter(
          (r) =>
            !lowerSearch ||
            r.name.toLowerCase().includes(lowerSearch) ||
            m.name.toLowerCase().includes(lowerSearch)
        )
        .map((r) => ({ label: r.name, type: "rule" as const, rule: r }));

      return {
        label: m.name,
        type: "module" as const,
        children,
      };
    });

    // Add rules not in any known module under "MAIN"
    const knownModules = new Set(modules.map((m) => m.name));
    const orphanRules = rules.filter(
      (r) => !knownModules.has(r.module ?? "MAIN") || !r.module
    );
    if (orphanRules.length > 0) {
      const existing = nodes.find((n) => n.label === "MAIN");
      const filtered = orphanRules.filter(
        (r) =>
          !lowerSearch ||
          r.name.toLowerCase().includes(lowerSearch) ||
          "main".includes(lowerSearch)
      );
      if (existing) {
        const existingNames = new Set(
          (existing.children ?? []).map((c) => c.label)
        );
        for (const r of filtered) {
          if (!existingNames.has(r.name)) {
            existing.children = existing.children ?? [];
            existing.children.push({
              label: r.name,
              type: "rule",
              rule: r,
            });
          }
        }
      } else if (filtered.length > 0) {
        nodes.unshift({
          label: "MAIN",
          type: "module",
          children: filtered.map((r) => ({
            label: r.name,
            type: "rule" as const,
            rule: r,
          })),
        });
      }
    }

    // Filter out empty modules when searching
    if (lowerSearch) {
      return nodes.filter(
        (n) => (n.children?.length ?? 0) > 0 || n.label.toLowerCase().includes(lowerSearch)
      );
    }

    return nodes;
  }, [rules, modules, search]);

  const toggleExpand = (label: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  const handleRuleClick = (rule: Rule) => {
    setSelected(rule.name);
    onSelectRule?.(rule);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Search input */}
      <input
        type="text"
        placeholder="Search rules..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{
          padding: "6px 8px",
          marginBottom: 8,
          border: "1px solid #ccc",
          borderRadius: 4,
          fontSize: 13,
        }}
      />

      {/* Tree */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {tree.length === 0 && (
          <p style={{ color: "#888", fontSize: 13, padding: "4px 0" }}>
            No rules found.
          </p>
        )}
        {tree.map((node) => (
          <div key={node.label}>
            {/* Module header */}
            <div
              onClick={() => toggleExpand(node.label)}
              style={{
                padding: "4px 4px",
                cursor: "pointer",
                fontWeight: 600,
                fontSize: 13,
                display: "flex",
                alignItems: "center",
                gap: 4,
                userSelect: "none",
              }}
            >
              <span style={{ fontSize: 10, width: 12, textAlign: "center" }}>
                {expanded.has(node.label) ? "\u25BC" : "\u25B6"}
              </span>
              {node.label}
              <span style={{ color: "#888", fontWeight: 400, fontSize: 11 }}>
                ({node.children?.length ?? 0})
              </span>
            </div>

            {/* Rule children */}
            {expanded.has(node.label) &&
              node.children?.map((child) => (
                <div
                  key={child.label}
                  onClick={() => child.rule && handleRuleClick(child.rule)}
                  style={{
                    padding: "3px 8px 3px 24px",
                    cursor: "pointer",
                    fontSize: 13,
                    background:
                      selected === child.label ? "#e0e7ff" : "transparent",
                    borderRadius: 3,
                  }}
                >
                  {child.label}
                </div>
              ))}
          </div>
        ))}
      </div>
    </div>
  );
}
