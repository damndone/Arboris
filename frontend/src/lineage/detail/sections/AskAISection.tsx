// frontend/src/lineage/detail/sections/AskAISection.tsx
//
import type { GraphViewNode } from "../../api/graphViewTypes";
import { ResolverFailureState } from "../ResolverFailureState";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import { buildAskAIContextPacket } from "./askAiContextPacket";

export function AskAISection({ node }: { node: GraphViewNode }) {
  const resolvedContext = useResolvedNodeOperationContext();
  const packet =
    resolvedContext?.ok === true
      ? buildAskAIContextPacket(resolvedContext.context)
      : null;

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
        {resolvedContext?.ok === false ? (
          <ResolverFailureState result={resolvedContext} />
        ) : (
          <>
            <span>
              AI will use this node's context (kind: <code>{node.kind}</code>,
              stage: <code>{node.stage}</code>) as its scope.
            </span>
            {packet && (
              <details>
                <summary>Context preview</summary>
                <pre
                  data-testid="ask-ai-context-preview"
                  style={{
                    margin: "8px 0 0",
                    maxHeight: 280,
                    overflow: "auto",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {JSON.stringify(packet, null, 2)}
                </pre>
              </details>
            )}
          </>
        )}
        <button
          type="button"
          disabled
          data-testid="ask-ai-section-button"
          title="Ask AI client lands in Task 6"
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
          Ask AI about this node
        </button>
      </div>
    </section>
  );
}
