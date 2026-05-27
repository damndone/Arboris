// frontend/src/lineage/detail/sections/AskAISection.tsx
//
// V1.5.2 P5 — AskAISection placeholder. Plan §13.
//
// Always renders (the AI slot is the V1.5.2 visible promise that AI
// is coming). V1.5.2 makes ZERO LLM calls. The button is disabled
// with a tooltip explaining the V1.5.3 backend dependency. When
// /llm/chat lands, this becomes a streaming chat surface scoped to
// the node's context.

import type { GraphViewNode } from "../../api/graphViewTypes";

export function AskAISection({ node }: { node: GraphViewNode }) {
  return (
    <section
      aria-label="Ask AI"
      data-testid="ask-ai-section"
      style={{ marginTop: 18 }}
    >
      <div
        className="ln-section-label"
        style={{ marginBottom: 6, display: "flex", alignItems: "center" }}
      >
        <span>Ask AI</span>
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 6,
          padding: 10,
          background: "var(--bg-card-2, rgba(255,255,255,0.04))",
          borderRadius: 8,
          fontSize: 12,
          color: "var(--label-secondary)",
        }}
      >
        <span>
          AI will use this node's context (kind: <code>{node.kind}</code>,
          stage: <code>{node.stage}</code>) as its scope.
        </span>
        <button
          type="button"
          disabled
          data-testid="ask-ai-section-button"
          title="LLM backend lands in V1.5.3"
          style={{
            alignSelf: "flex-start",
            marginTop: 4,
            padding: "6px 12px",
            borderRadius: 6,
            border: "1px solid var(--separator)",
            background: "transparent",
            color: "var(--label-tertiary)",
            cursor: "not-allowed",
            fontSize: 12,
            opacity: 0.7,
          }}
        >
          Ask AI about this node — V1.5.3
        </button>
      </div>
    </section>
  );
}
