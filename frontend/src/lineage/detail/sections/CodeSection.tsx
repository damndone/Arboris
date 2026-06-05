// frontend/src/lineage/detail/sections/CodeSection.tsx
//
// V1.5.2 P5 — read-only Code section. Plan §14.
//
// Renders only when `node.code` is present. V1.5.2 is read-only;
// V1.5.3 turns this into a Monaco-backed editor wired to the partial
// rerun pipeline. The current scaffold uses a plain <pre> so the
// surface is honest about what V1.5.2 ships.

import type { GraphViewNode } from "../../api/graphViewTypes";

export function CodeSection({ node }: { node: GraphViewNode }) {
  const code = node.code;
  if (!code || !code.body) return null;

  return (
    <section
      aria-label="Code"
      data-testid="code-section"
      style={{ marginTop: 18 }}
    >
      <div
        className="ln-section-label"
        style={{ marginBottom: 6, display: "flex", alignItems: "center" }}
      >
        <span>Code</span>
        <span
          style={{
            marginLeft: 8,
            fontSize: 11,
            color: "var(--label-tertiary)",
          }}
        >
          {code.lang} · read-only
        </span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            color: "var(--label-tertiary)",
            fontStyle: "italic",
          }}
        >
          Editor lands V1.5.3
        </span>
      </div>
      <pre
        data-testid="code-section-body"
        style={{
          margin: 0,
          padding: 12,
          background: "var(--bg-code, rgba(0,0,0,0.25))",
          borderRadius: 8,
          fontSize: 12,
          fontFamily: "var(--font-mono, monospace)",
          color: "var(--label)",
          overflowX: "auto",
          lineHeight: 1.5,
        }}
      >
        {code.body}
      </pre>
    </section>
  );
}
