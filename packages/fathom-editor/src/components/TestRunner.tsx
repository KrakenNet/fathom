import { useState, useCallback, type FormEvent } from "react";
import { evaluate, type EvaluateResponse } from "../api/fathom";

interface SlotEntry {
  key: string;
  value: string;
}

/**
 * Test execution panel: assert facts, run evaluation, display results.
 */
export default function TestRunner() {
  // Fact assertion form state
  const [templateName, setTemplateName] = useState("");
  const [slots, setSlots] = useState<SlotEntry[]>([{ key: "", value: "" }]);
  const [facts, setFacts] = useState<Record<string, unknown>[]>([]);

  // Evaluation state
  const [results, setResults] = useState<EvaluateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  // --- Slot management ---

  const updateSlot = useCallback(
    (index: number, field: "key" | "value", val: string) => {
      setSlots((prev) => {
        const next = [...prev];
        next[index] = { ...next[index], [field]: val };
        return next;
      });
    },
    [],
  );

  const addSlot = useCallback(() => {
    setSlots((prev) => [...prev, { key: "", value: "" }]);
  }, []);

  const removeSlot = useCallback((index: number) => {
    setSlots((prev) => prev.filter((_, i) => i !== index));
  }, []);

  // --- Fact assertion ---

  const handleAssert = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      if (!templateName.trim()) return;

      const fact: Record<string, unknown> = { _template: templateName.trim() };
      for (const slot of slots) {
        if (slot.key.trim()) {
          // Try to parse as number or boolean, else keep as string
          const raw = slot.value.trim();
          if (raw === "true") fact[slot.key.trim()] = true;
          else if (raw === "false") fact[slot.key.trim()] = false;
          else if (raw !== "" && !isNaN(Number(raw)))
            fact[slot.key.trim()] = Number(raw);
          else fact[slot.key.trim()] = raw;
        }
      }

      setFacts((prev) => [...prev, fact]);
      // Reset form
      setTemplateName("");
      setSlots([{ key: "", value: "" }]);
    },
    [templateName, slots],
  );

  // --- Evaluation ---

  const handleEvaluate = useCallback(async () => {
    if (facts.length === 0) return;
    setRunning(true);
    setError(null);
    try {
      const resp = await evaluate({ facts });
      setResults(resp);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Evaluation failed";
      setError(msg);
      setResults(null);
    } finally {
      setRunning(false);
    }
  }, [facts]);

  const handleClear = useCallback(() => {
    setFacts([]);
    setResults(null);
    setError(null);
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Fact Assertion Form */}
      <form
        onSubmit={handleAssert}
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
          padding: 8,
          background: "#f9f9f9",
          borderRadius: 4,
          border: "1px solid #ddd",
        }}
      >
        <strong style={{ fontSize: 13 }}>Assert Fact</strong>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <label style={{ fontSize: 12, minWidth: 60 }}>Template:</label>
          <input
            type="text"
            value={templateName}
            onChange={(e) => setTemplateName(e.target.value)}
            placeholder="e.g. access-request"
            style={{
              flex: 1,
              padding: "2px 6px",
              fontFamily: "monospace",
              fontSize: 12,
              border: "1px solid #ccc",
              borderRadius: 3,
            }}
          />
        </div>

        {/* Slot key-value rows */}
        {slots.map((slot, i) => (
          <div
            key={i}
            style={{ display: "flex", gap: 4, alignItems: "center" }}
          >
            <input
              type="text"
              value={slot.key}
              onChange={(e) => updateSlot(i, "key", e.target.value)}
              placeholder="slot name"
              style={{
                flex: 1,
                padding: "2px 6px",
                fontFamily: "monospace",
                fontSize: 12,
                border: "1px solid #ccc",
                borderRadius: 3,
              }}
            />
            <span style={{ fontSize: 12 }}>=</span>
            <input
              type="text"
              value={slot.value}
              onChange={(e) => updateSlot(i, "value", e.target.value)}
              placeholder="value"
              style={{
                flex: 1,
                padding: "2px 6px",
                fontFamily: "monospace",
                fontSize: 12,
                border: "1px solid #ccc",
                borderRadius: 3,
              }}
            />
            {slots.length > 1 && (
              <button
                type="button"
                onClick={() => removeSlot(i)}
                style={{ fontSize: 11, padding: "1px 4px" }}
              >
                x
              </button>
            )}
          </div>
        ))}

        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" onClick={addSlot} style={{ fontSize: 12 }}>
            + Slot
          </button>
          <button type="submit" style={{ fontSize: 12 }}>
            Assert
          </button>
        </div>
      </form>

      {/* Asserted Facts */}
      {facts.length > 0 && (
        <div style={{ fontSize: 12 }}>
          <strong>Asserted Facts ({facts.length}):</strong>
          <ul
            style={{
              margin: "4px 0",
              paddingLeft: 16,
              fontFamily: "monospace",
              fontSize: 11,
            }}
          >
            {facts.map((f, i) => (
              <li key={i}>{JSON.stringify(f)}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={handleEvaluate}
          disabled={facts.length === 0 || running}
          style={{
            padding: "4px 12px",
            fontSize: 13,
            fontWeight: "bold",
            background: "#2563eb",
            color: "#fff",
            border: "none",
            borderRadius: 4,
            cursor: facts.length === 0 || running ? "not-allowed" : "pointer",
            opacity: facts.length === 0 || running ? 0.5 : 1,
          }}
        >
          {running ? "Evaluating..." : "Evaluate"}
        </button>
        <button onClick={handleClear} style={{ fontSize: 12 }}>
          Clear
        </button>
      </div>

      {/* Results display */}
      {error && (
        <pre
          style={{
            padding: 8,
            background: "#fef2f2",
            color: "#b91c1c",
            borderRadius: 4,
            fontSize: 12,
            margin: 0,
            whiteSpace: "pre-wrap",
          }}
        >
          Error: {error}
        </pre>
      )}

      {results && (
        <div style={{ fontSize: 12 }}>
          <strong>Results:</strong>
          <pre
            style={{
              padding: 8,
              background: "#f0fdf4",
              borderRadius: 4,
              fontSize: 11,
              fontFamily: "monospace",
              margin: "4px 0",
              whiteSpace: "pre-wrap",
              maxHeight: 200,
              overflowY: "auto",
            }}
          >
            {JSON.stringify(results.results, null, 2)}
          </pre>

          {results.audit_log.length > 0 && (
            <>
              <strong>Audit Trail:</strong>
              <pre
                style={{
                  padding: 8,
                  background: "#fffbeb",
                  borderRadius: 4,
                  fontSize: 11,
                  fontFamily: "monospace",
                  margin: "4px 0",
                  whiteSpace: "pre-wrap",
                  maxHeight: 200,
                  overflowY: "auto",
                }}
              >
                {JSON.stringify(results.audit_log, null, 2)}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
