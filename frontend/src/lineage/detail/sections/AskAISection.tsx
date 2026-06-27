// frontend/src/lineage/detail/sections/AskAISection.tsx
//
import { FormEvent, useEffect, useRef, useState } from "react";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { ResolverFailureState } from "../ResolverFailureState";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import { askAiForNode } from "./askAiClient";
import { buildAskAIContextPacket } from "./askAiContextPacket";

const DEFAULT_QUESTION = "Explain this node and its risks.";

export function AskAISection({ node }: { node: GraphViewNode }) {
  const resolvedContext = useResolvedNodeOperationContext();
  const packet =
    resolvedContext?.ok === true
      ? buildAskAIContextPacket(resolvedContext.context)
      : null;
  const contextIdentity =
    packet === null
      ? null
      : `${packet.context_fingerprint}:${packet.selection.forest_node_key}`;
  const latestContextIdentityRef = useRef<string | null>(contextIdentity);
  const requestVersionRef = useRef(0);
  latestContextIdentityRef.current = contextIdentity;
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [answer, setAnswer] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    requestVersionRef.current += 1;
    setAnswer(null);
    setError(null);
    setIsSubmitting(false);
  }, [contextIdentity]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const requestIdentity = contextIdentity;
    if (!packet || !requestIdentity || question.trim() === "") return;
    const requestVersion = requestVersionRef.current + 1;
    requestVersionRef.current = requestVersion;

    setIsSubmitting(true);
    setError(null);
    setAnswer(null);
    try {
      const response = await askAiForNode(packet, question);
      if (
        latestContextIdentityRef.current !== requestIdentity ||
        requestVersionRef.current !== requestVersion
      ) {
        return;
      }
      setAnswer(response.text);
    } catch (err) {
      if (
        latestContextIdentityRef.current !== requestIdentity ||
        requestVersionRef.current !== requestVersion
      ) {
        return;
      }
      setError(err instanceof Error ? err.message : "Ask AI failed");
    } finally {
      if (
        latestContextIdentityRef.current === requestIdentity &&
        requestVersionRef.current === requestVersion
      ) {
        setIsSubmitting(false);
      }
    }
  }

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
        <form
          onSubmit={handleSubmit}
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            marginTop: 4,
          }}
        >
          <textarea
            aria-label="Ask AI question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            rows={3}
            style={{
              width: "100%",
              boxSizing: "border-box",
              resize: "vertical",
              borderRadius: 6,
              border: "1px solid var(--separator)",
              background: "var(--bg-card, rgba(255,255,255,0.06))",
              color: "var(--label-primary)",
              font: "inherit",
              fontSize: 12,
              padding: "8px 10px",
            }}
          />
          <button
            type="submit"
            disabled={!packet || isSubmitting || question.trim() === ""}
            data-testid="ask-ai-section-button"
            style={{
              alignSelf: "flex-start",
              padding: "6px 12px",
              borderRadius: 6,
              border: "1px solid var(--separator)",
              background: packet
                ? "var(--accent, rgba(40,120,255,0.18))"
                : "transparent",
              color: packet
                ? "var(--label-primary)"
                : "var(--label-tertiary)",
              cursor: packet && !isSubmitting ? "pointer" : "not-allowed",
              fontSize: 12,
              opacity: !packet || isSubmitting ? 0.7 : 1,
            }}
          >
            Ask AI about this node
          </button>
        </form>
        {error && (
          <div role="alert" style={{ color: "var(--danger, #b00020)" }}>
            {error}
          </div>
        )}
        {answer && (
          <div
            data-testid="ask-ai-answer"
            role="status"
            style={{
              marginTop: 4,
              padding: "6px 12px",
              borderRadius: 6,
              border: "1px solid var(--separator)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              color: "var(--label-primary)",
            }}
          >
            {answer}
          </div>
        )}
      </div>
    </section>
  );
}
