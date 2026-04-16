import { useState, useEffect, useRef } from "react";
import { compile } from "../api/fathom";

export interface ClipsPreviewProps {
  /** YAML source to compile */
  yaml: string;
  /** Debounce delay in ms (default 500) */
  debounceMs?: number;
}

/**
 * Read-only CLIPS code preview panel.
 * Calls POST /v1/compile on YAML changes (debounced) and displays output.
 */
export default function ClipsPreview({
  yaml,
  debounceMs = 500,
}: ClipsPreviewProps) {
  const [clipsCode, setClipsCode] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Clear previous timer
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }

    // Skip empty input
    if (!yaml.trim()) {
      setClipsCode("");
      setError(null);
      return;
    }

    timerRef.current = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await compile({ yaml_content: yaml });
        setClipsCode(result.clips_code);
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : "Compilation failed";
        setError(msg);
        setClipsCode("");
      } finally {
        setLoading(false);
      }
    }, debounceMs);

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [yaml, debounceMs]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        border: "1px solid #ccc",
        borderRadius: 4,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "4px 8px",
          background: "#2d2d2d",
          color: "#ccc",
          fontSize: 12,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span>CLIPS Preview</span>
        {loading && (
          <span style={{ color: "#f0c040", fontSize: 11 }}>Compiling...</span>
        )}
      </div>

      {/* Content */}
      <pre
        style={{
          flex: 1,
          margin: 0,
          padding: 8,
          background: "#1e1e1e",
          color: error ? "#f44" : "#d4d4d4",
          fontFamily: "monospace",
          fontSize: 13,
          lineHeight: "1.5",
          overflowY: "auto",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {error
          ? `Error: ${error}`
          : clipsCode || "Enter YAML to see compiled CLIPS output."}
      </pre>
    </div>
  );
}
