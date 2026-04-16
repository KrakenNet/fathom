import { useState, useEffect } from "react";
import { listTemplates } from "../api/fathom";
import type { Template } from "../api/fathom";

interface TemplateBrowserProps {
  onInsert?: (templateName: string, slotName?: string) => void;
}

export default function TemplateBrowser({ onInsert }: TemplateBrowserProps) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");

  useEffect(() => {
    listTemplates().then(setTemplates).catch(() => {});
  }, []);

  const filtered = search
    ? templates.filter(
        (t) =>
          t.name.toLowerCase().includes(search.toLowerCase()) ||
          Object.keys(t.slots).some((s) =>
            s.toLowerCase().includes(search.toLowerCase())
          )
      )
    : templates;

  const toggleExpand = (name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Search */}
      <input
        type="text"
        placeholder="Search templates..."
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

      {/* Template list */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {filtered.length === 0 && (
          <p style={{ color: "#888", fontSize: 13, padding: "4px 0" }}>
            No templates found.
          </p>
        )}
        {filtered.map((tpl) => (
          <div
            key={tpl.name}
            style={{
              marginBottom: 4,
              border: "1px solid #e0e0e0",
              borderRadius: 4,
              overflow: "hidden",
            }}
          >
            {/* Template header */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                padding: "6px 8px",
                background: "#f8f8f8",
                cursor: "pointer",
                fontSize: 13,
                userSelect: "none",
              }}
            >
              <div
                onClick={() => toggleExpand(tpl.name)}
                style={{ flex: 1, display: "flex", alignItems: "center", gap: 6 }}
              >
                <span style={{ fontSize: 10 }}>
                  {expanded.has(tpl.name) ? "\u25BC" : "\u25B6"}
                </span>
                <strong>{tpl.name}</strong>
                <span style={{ color: "#888", fontSize: 11 }}>
                  ({Object.keys(tpl.slots).length} slots)
                </span>
                {tpl.module && (
                  <span
                    style={{
                      fontSize: 10,
                      background: "#e0e7ff",
                      padding: "1px 5px",
                      borderRadius: 3,
                      color: "#3b5bdb",
                    }}
                  >
                    {tpl.module}
                  </span>
                )}
              </div>
              <button
                onClick={() => onInsert?.(tpl.name)}
                style={{
                  padding: "2px 8px",
                  fontSize: 11,
                  cursor: "pointer",
                  border: "1px solid #ccc",
                  borderRadius: 3,
                  background: "white",
                }}
                title="Insert template reference"
              >
                Insert
              </button>
            </div>

            {/* Slot details */}
            {expanded.has(tpl.name) && (
              <div style={{ padding: "4px 8px 8px 28px" }}>
                {Object.entries(tpl.slots).length === 0 ? (
                  <p style={{ color: "#888", fontSize: 12, margin: 0 }}>
                    No slots defined.
                  </p>
                ) : (
                  <table
                    style={{
                      fontSize: 12,
                      borderCollapse: "collapse",
                      width: "100%",
                    }}
                  >
                    <thead>
                      <tr style={{ borderBottom: "1px solid #e0e0e0" }}>
                        <th style={{ textAlign: "left", padding: "2px 8px 2px 0" }}>
                          Slot
                        </th>
                        <th style={{ textAlign: "left", padding: "2px 8px" }}>
                          Type
                        </th>
                        <th style={{ textAlign: "right", padding: "2px 0" }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(tpl.slots).map(([slotName, slotType]) => (
                        <tr
                          key={slotName}
                          style={{ borderBottom: "1px solid #f0f0f0" }}
                        >
                          <td
                            style={{
                              padding: "3px 8px 3px 0",
                              fontFamily: "monospace",
                            }}
                          >
                            {slotName}
                          </td>
                          <td
                            style={{
                              padding: "3px 8px",
                              color: "#666",
                            }}
                          >
                            {slotType}
                          </td>
                          <td style={{ padding: "3px 0", textAlign: "right" }}>
                            <button
                              onClick={() => onInsert?.(tpl.name, slotName)}
                              style={{
                                fontSize: 10,
                                padding: "1px 6px",
                                cursor: "pointer",
                                border: "1px solid #ddd",
                                borderRadius: 3,
                                background: "white",
                                color: "#555",
                              }}
                              title={`Insert ${tpl.name}.${slotName}`}
                            >
                              +
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {tpl.ttl_seconds != null && (
                  <div
                    style={{
                      marginTop: 4,
                      fontSize: 11,
                      color: "#888",
                    }}
                  >
                    TTL: {tpl.ttl_seconds}s
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
