// frontend/src/lineage/detail/sections/AskAISection.tsx
//
import { FormEvent, useEffect, useRef, useState } from "react";
import { isAskAIEnabled } from "../../../workbench/featureFlags";
import { useProjectRootOptional } from "../../../workbench/ProjectRootContext";
import {
  appendAiActivity,
  askAiHistoryForNode,
  makeActivityId,
  type AskAiActivityRecord,
} from "../../../aiActivity/aiActivityLog";
import { renderMarkdown } from "../../../report/markdown";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { ResolverFailureState } from "../ResolverFailureState";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import { askAiForNode, fetchLlmConfig, type LlmConfigInfo } from "./askAiClient";
import { buildAskAIContextPacket } from "./askAiContextPacket";

const DEFAULT_QUESTION = "Explain this node and its risks.";

export function AskAISection({ node }: { node: GraphViewNode }) {
  const askAIEnabled = isAskAIEnabled();
  const resolvedContext = useResolvedNodeOperationContext();
  const packet =
    askAIEnabled && resolvedContext?.ok === true
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
  // v1.6.12 (V6): per-node Q&A history — regenerating no longer erases the
  // previous answer; every exchange lands in the typed AI activity log.
  const projectRoot = useProjectRootOptional();
  const nodeKey = packet?.selection.forest_node_key ?? null;
  const [history, setHistory] = useState<AskAiActivityRecord[]>([]);

  useEffect(() => {
    requestVersionRef.current += 1;
    setAnswer(null);
    setError(null);
    setIsSubmitting(false);
    setHistory(
      projectRoot && nodeKey ? askAiHistoryForNode(projectRoot, nodeKey) : [],
    );
  }, [contextIdentity, projectRoot, nodeKey]);

  if (!askAIEnabled) return null;

  function logExchange(record: Omit<AskAiActivityRecord, "id" | "at" | "kind" | "node_key" | "node_label">) {
    if (!projectRoot || !nodeKey) return;
    appendAiActivity(projectRoot, {
      kind: "ask_ai",
      id: makeActivityId(),
      at: new Date().toISOString(),
      node_key: nodeKey,
      node_label: node.title,
      ...record,
    });
    setHistory(askAiHistoryForNode(projectRoot, nodeKey));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await ask(question);
  }

  async function ask(questionText: string) {
    const question = questionText;
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
      logExchange({
        question,
        status: "answered",
        model: response.model,
        context_fingerprint: packet.context_fingerprint,
        answer: response.text,
      });
    } catch (err) {
      if (
        latestContextIdentityRef.current !== requestIdentity ||
        requestVersionRef.current !== requestVersion
      ) {
        return;
      }
      const message = err instanceof Error ? err.message : "Ask AI failed";
      setError(message);
      logExchange({
        question,
        status: "error",
        context_fingerprint: packet.context_fingerprint,
        error: message,
      });
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
        style={{
          marginBottom: 6,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span>Ask AI</span>
        <LlmProviderBadge />
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
        {packet && (node.artifacts ?? []).length > 0 && (
          <div
            data-testid="ask-ai-artifacts"
            style={{ display: "flex", flexDirection: "column", gap: 4 }}
          >
            <span style={{ color: "var(--label-tertiary)", fontSize: 11 }}>
              Attached artifacts (in the AI's context):
            </span>
            {(node.artifacts ?? []).map((artifact) => (
              <div
                key={artifact.name}
                style={{ display: "flex", alignItems: "center", gap: 8 }}
              >
                <code style={{ fontSize: 11 }}>{artifact.name}</code>
                {/* v1.6.12 T4 (A3) — one-click focused explanation. The
                 * artifact's preview already travels in the packet; the
                 * focused question makes the model explain THAT artifact. */}
                <button
                  type="button"
                  data-testid={`ask-ai-explain-${artifact.name}`}
                  disabled={isSubmitting}
                  onClick={() => {
                    const q = `Explain the artifact "${artifact.name}" from this node's context: what does it contain, what does it tell us about the data, and what should I watch out for?`;
                    setQuestion(q);
                    void ask(q);
                  }}
                  style={{
                    padding: "1px 8px",
                    minHeight: 0,
                    borderRadius: 999,
                    border: "1px solid var(--separator)",
                    background: "var(--bg-card-2, rgba(0,0,0,0.05))",
                    color: "var(--label)",
                    fontSize: 10.5,
                    cursor: isSubmitting ? "not-allowed" : "pointer",
                  }}
                >
                  Explain
                </button>
              </div>
            ))}
          </div>
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
              wordBreak: "break-word",
              color: "var(--label-primary)",
            }}
          >
            {renderMarkdown(answer)}
          </div>
        )}
        <AskAiHistory history={history} latestShownInline={answer !== null} />
      </div>
    </section>
  );
}

/** v1.6.12 T5 (A4) — read-only LLM provider badge: which model answers, or a
 *  pointer to the env file when unconfigured. Key changes stay outside the UI. */
function LlmProviderBadge() {
  const [config, setConfig] = useState<LlmConfigInfo | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchLlmConfig()
      .then((info) => {
        if (!cancelled) setConfig(info);
      })
      .catch(() => {
        /* endpoint unreachable — badge simply stays hidden */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  if (!config) return null;
  if (!config.configured) {
    return (
      <span
        data-testid="llm-provider-badge"
        title="Set WORKBENCH_LLM_BASE_URL / _API_KEY / _MODEL in ~/.config/econometrics-workbench/llm.env (see .env.example), then restart the backend."
        style={{ fontSize: 10.5, color: "var(--diff-removed, #b35900)", fontWeight: 500 }}
      >
        LLM not configured
      </span>
    );
  }
  return (
    <span
      data-testid="llm-provider-badge"
      title={`Provider ${config.base_url ?? ""} · key ${config.key_present ? "present" : "missing"} — configured via env file, read-only here`}
      style={{ fontSize: 10.5, color: "var(--label-tertiary)", fontWeight: 400 }}
    >
      {config.model}
    </span>
  );
}

/** Per-node Q&A history (V6). Read-only audit view — newest first; the most
 *  recent exchange is skipped while it is already shown inline above. */
function AskAiHistory({
  history,
  latestShownInline,
}: {
  history: AskAiActivityRecord[];
  latestShownInline: boolean;
}) {
  const entries = latestShownInline ? history.slice(1) : history;
  if (history.length === 0) {
    return (
      <div style={{ color: "var(--label-tertiary)", fontSize: 11 }}>
        Past questions on this node will be kept here.
      </div>
    );
  }
  if (entries.length === 0) return null;
  return (
    <details data-testid="ask-ai-history" style={{ marginTop: 4 }}>
      <summary style={{ cursor: "pointer", fontSize: 11 }}>
        History ({entries.length})
      </summary>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
        {entries.map((record) => (
          <div
            key={record.id}
            data-testid="ask-ai-history-entry"
            style={{
              border: "1px solid var(--separator)",
              borderRadius: 6,
              padding: "6px 10px",
            }}
          >
            <div style={{ color: "var(--label-tertiary)", fontSize: 10.5 }}>
              {new Date(record.at).toLocaleString()}
              {record.model ? ` · ${record.model}` : ""}
              {record.status === "error" ? " · failed" : ""}
            </div>
            <div style={{ fontWeight: 600, margin: "3px 0" }}>{record.question}</div>
            {record.status === "answered" ? (
              <div style={{ color: "var(--label-primary)" }}>
                {renderMarkdown(record.answer ?? "")}
              </div>
            ) : (
              <div style={{ color: "var(--danger, #b00020)" }}>{record.error}</div>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}
