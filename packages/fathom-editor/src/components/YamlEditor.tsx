import { useCallback, useRef, type ChangeEvent } from "react";

export interface YamlEditorProps {
  /** Current YAML content */
  value: string;
  /** Fired on every edit */
  onChange: (value: string) => void;
  /** Optional placeholder text */
  placeholder?: string;
}

/**
 * YAML editor component with line numbers and monospace styling.
 * POC: uses a plain textarea instead of Monaco for zero extra deps.
 */
export default function YamlEditor({
  value,
  onChange,
  placeholder = "# Enter YAML here...",
}: YamlEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const lineCount = value ? value.split("\n").length : 1;

  const handleChange = useCallback(
    (e: ChangeEvent<HTMLTextAreaElement>) => {
      onChange(e.target.value);
    },
    [onChange],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // Tab inserts two spaces instead of moving focus
      if (e.key === "Tab") {
        e.preventDefault();
        const ta = textareaRef.current;
        if (!ta) return;
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        const updated = value.substring(0, start) + "  " + value.substring(end);
        onChange(updated);
        // Restore cursor after React re-render
        requestAnimationFrame(() => {
          ta.selectionStart = ta.selectionEnd = start + 2;
        });
      }
    },
    [value, onChange],
  );

  return (
    <div
      style={{
        display: "flex",
        border: "1px solid #ccc",
        borderRadius: 4,
        overflow: "hidden",
        height: "100%",
        fontFamily: "monospace",
        fontSize: 13,
      }}
    >
      {/* Line numbers gutter */}
      <div
        style={{
          padding: "8px 8px 8px 4px",
          background: "#f0f0f0",
          color: "#888",
          textAlign: "right",
          userSelect: "none",
          lineHeight: "1.5",
          minWidth: 36,
          whiteSpace: "pre",
        }}
        aria-hidden
      >
        {Array.from({ length: lineCount }, (_, i) => `${i + 1}\n`).join("")}
      </div>

      {/* Editor area */}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        spellCheck={false}
        style={{
          flex: 1,
          border: "none",
          outline: "none",
          resize: "none",
          padding: 8,
          fontFamily: "inherit",
          fontSize: "inherit",
          lineHeight: "1.5",
          background: "#fafafa",
          color: "#1e1e1e",
          tabSize: 2,
        }}
      />
    </div>
  );
}
