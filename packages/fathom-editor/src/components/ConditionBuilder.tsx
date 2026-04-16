import { useState, useEffect } from "react";
import { listTemplates } from "../api/fathom";
import type { Template } from "../api/fathom";

export interface ConditionRow {
  id: string;
  template: string;
  slot: string;
  operator: string;
  value: string;
}

interface ConditionBuilderProps {
  conditions?: ConditionRow[];
  onChange?: (conditions: ConditionRow[]) => void;
}

const OPERATORS = ["eq", "neq", "gt", "lt", "gte", "lte"];

let nextId = 1;
function genId(): string {
  return `cond-${nextId++}`;
}

export default function ConditionBuilder({
  conditions: initialConditions,
  onChange,
}: ConditionBuilderProps) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [rows, setRows] = useState<ConditionRow[]>(
    initialConditions ?? []
  );

  useEffect(() => {
    listTemplates().then(setTemplates).catch(() => {});
  }, []);

  const update = (newRows: ConditionRow[]) => {
    setRows(newRows);
    onChange?.(newRows);
  };

  const addRow = () => {
    const tplName = templates.length > 0 ? templates[0].name : "";
    const slots = tplName
      ? Object.keys(templates.find((t) => t.name === tplName)?.slots ?? {})
      : [];
    update([
      ...rows,
      {
        id: genId(),
        template: tplName,
        slot: slots[0] ?? "",
        operator: "eq",
        value: "",
      },
    ]);
  };

  const removeRow = (id: string) => {
    update(rows.filter((r) => r.id !== id));
  };

  const updateRow = (id: string, field: keyof ConditionRow, value: string) => {
    update(
      rows.map((r) => {
        if (r.id !== id) return r;
        const updated = { ...r, [field]: value };
        // Reset slot when template changes
        if (field === "template") {
          const tpl = templates.find((t) => t.name === value);
          const slots = Object.keys(tpl?.slots ?? {});
          updated.slot = slots[0] ?? "";
        }
        return updated;
      })
    );
  };

  const moveRow = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= rows.length) return;
    const newRows = [...rows];
    [newRows[index], newRows[target]] = [newRows[target], newRows[index]];
    update(newRows);
  };

  const getSlotsForTemplate = (tplName: string): string[] => {
    const tpl = templates.find((t) => t.name === tplName);
    return tpl ? Object.keys(tpl.slots) : [];
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <strong style={{ fontSize: 14 }}>Conditions</strong>
        <button
          onClick={addRow}
          style={{
            padding: "4px 10px",
            fontSize: 12,
            cursor: "pointer",
            border: "1px solid #ccc",
            borderRadius: 4,
            background: "#f8f8f8",
          }}
        >
          + Add Condition
        </button>
      </div>

      {rows.length === 0 && (
        <p style={{ color: "#888", fontSize: 13 }}>
          No conditions defined. Click &quot;+ Add Condition&quot; to start.
        </p>
      )}

      {rows.map((row, index) => (
        <div
          key={row.id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginBottom: 6,
            padding: "6px 8px",
            border: "1px solid #e0e0e0",
            borderRadius: 4,
            background: "#fafafa",
            fontSize: 13,
          }}
        >
          {/* Reorder buttons */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 1,
              marginRight: 4,
            }}
          >
            <button
              onClick={() => moveRow(index, -1)}
              disabled={index === 0}
              style={{
                fontSize: 10,
                padding: "0 4px",
                cursor: index === 0 ? "default" : "pointer",
                border: "none",
                background: "transparent",
              }}
              title="Move up"
            >
              {"\u25B2"}
            </button>
            <button
              onClick={() => moveRow(index, 1)}
              disabled={index === rows.length - 1}
              style={{
                fontSize: 10,
                padding: "0 4px",
                cursor: index === rows.length - 1 ? "default" : "pointer",
                border: "none",
                background: "transparent",
              }}
              title="Move down"
            >
              {"\u25BC"}
            </button>
          </div>

          {/* Template selector */}
          <select
            value={row.template}
            onChange={(e) => updateRow(row.id, "template", e.target.value)}
            style={{ padding: "3px 4px", fontSize: 12 }}
          >
            <option value="">-- template --</option>
            {templates.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </select>

          {/* Slot selector */}
          <select
            value={row.slot}
            onChange={(e) => updateRow(row.id, "slot", e.target.value)}
            style={{ padding: "3px 4px", fontSize: 12 }}
          >
            <option value="">-- slot --</option>
            {getSlotsForTemplate(row.template).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>

          {/* Operator selector */}
          <select
            value={row.operator}
            onChange={(e) => updateRow(row.id, "operator", e.target.value)}
            style={{ padding: "3px 4px", fontSize: 12, width: 60 }}
          >
            {OPERATORS.map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>

          {/* Value input */}
          <input
            type="text"
            value={row.value}
            onChange={(e) => updateRow(row.id, "value", e.target.value)}
            placeholder="value"
            style={{
              padding: "3px 6px",
              fontSize: 12,
              flex: 1,
              border: "1px solid #ccc",
              borderRadius: 3,
            }}
          />

          {/* Remove button */}
          <button
            onClick={() => removeRow(row.id)}
            style={{
              padding: "2px 6px",
              fontSize: 12,
              cursor: "pointer",
              border: "none",
              background: "transparent",
              color: "#c00",
            }}
            title="Remove condition"
          >
            {"\u2715"}
          </button>
        </div>
      ))}
    </div>
  );
}
