import { useState, useEffect } from "react";
import { listTemplates, listRules, listModules } from "./api/fathom";
import type { Template, Rule, Module } from "./api/fathom";

type Panel = "templates" | "rules" | "modules";

export default function App() {
  const [activePanel, setActivePanel] = useState<Panel>("rules");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [modules, setModules] = useState<Module[]>([]);
  const [selectedItem, setSelectedItem] = useState<string | null>(null);
  const [testOutput, setTestOutput] = useState<string>("");

  useEffect(() => {
    listTemplates().then(setTemplates).catch(() => {});
    listRules().then(setRules).catch(() => {});
    listModules().then(setModules).catch(() => {});
  }, []);

  const sidebarItems = (): { name: string; key: string }[] => {
    switch (activePanel) {
      case "templates":
        return templates.map((t) => ({ name: t.name, key: `tpl:${t.name}` }));
      case "rules":
        return rules.map((r) => ({ name: r.name, key: `rule:${r.name}` }));
      case "modules":
        return modules.map((m) => ({ name: m.name, key: `mod:${m.name}` }));
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      {/* Header */}
      <header
        style={{
          padding: "8px 16px",
          borderBottom: "1px solid #ccc",
          display: "flex",
          gap: 16,
          alignItems: "center",
        }}
      >
        <strong>Fathom Editor</strong>
        {(["templates", "rules", "modules"] as Panel[]).map((p) => (
          <button
            key={p}
            onClick={() => setActivePanel(p)}
            style={{ fontWeight: activePanel === p ? "bold" : "normal" }}
          >
            {p}
          </button>
        ))}
      </header>

      {/* Main area: sidebar + editor */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Sidebar - rule tree */}
        <nav
          style={{
            width: 220,
            borderRight: "1px solid #ccc",
            overflowY: "auto",
            padding: 8,
          }}
        >
          <h3 style={{ margin: "0 0 8px" }}>{activePanel}</h3>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {sidebarItems().map((item) => (
              <li
                key={item.key}
                onClick={() => setSelectedItem(item.key)}
                style={{
                  padding: "4px 8px",
                  cursor: "pointer",
                  background:
                    selectedItem === item.key ? "#e0e7ff" : "transparent",
                  borderRadius: 4,
                }}
              >
                {item.name}
              </li>
            ))}
          </ul>
        </nav>

        {/* Editor panel */}
        <main style={{ flex: 1, padding: 16, overflowY: "auto" }}>
          {selectedItem ? (
            <div>
              <h2>{selectedItem}</h2>
              <pre
                style={{
                  background: "#f5f5f5",
                  padding: 12,
                  borderRadius: 4,
                  whiteSpace: "pre-wrap",
                }}
              >
                {JSON.stringify(
                  activePanel === "templates"
                    ? templates.find(
                        (t) => `tpl:${t.name}` === selectedItem
                      )
                    : activePanel === "rules"
                      ? rules.find(
                          (r) => `rule:${r.name}` === selectedItem
                        )
                      : modules.find(
                          (m) => `mod:${m.name}` === selectedItem
                        ),
                  null,
                  2
                )}
              </pre>
            </div>
          ) : (
            <p style={{ color: "#888" }}>
              Select an item from the sidebar to view details.
            </p>
          )}
        </main>
      </div>

      {/* Bottom panel - test runner */}
      <div
        style={{
          borderTop: "1px solid #ccc",
          padding: 8,
          height: 150,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 4,
          }}
        >
          <strong>Test Runner</strong>
          <button onClick={() => setTestOutput("")}>Clear</button>
        </div>
        <pre
          style={{
            flex: 1,
            background: "#1e1e1e",
            color: "#d4d4d4",
            padding: 8,
            borderRadius: 4,
            overflowY: "auto",
            margin: 0,
            fontSize: 12,
          }}
        >
          {testOutput || "Run an evaluation to see results here."}
        </pre>
      </div>
    </div>
  );
}
