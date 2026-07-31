import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useAgentSurface } from "./AgentSurfaceContext";
import { agentAuditExportUrl } from "./agentApi";
import { AgentComposer } from "./AgentComposer";
import type { AgentMessage } from "./agentTypes";
import { renderMarkdown } from "../../report/markdown";
import "./agent.css";

function roleMarker(role: string): string {
  if (role === "user") return "❯";
  if (role === "assistant") return "·";
  return "⋮";
}

function roleLabel(role: string): string {
  if (role === "user") return "you";
  if (role === "assistant") return "agent";
  return "tool";
}

/** Reader-facing names for declared post-estimation operations. An unknown
 * operation falls back to its id rather than being hidden. */
const AGENT_POST_ESTIMATION_LABELS: Record<string, string> = {
  "model.quadratic_stationary_point": "Quadratic stationary point",
  "model.joint_f_test": "Joint F test",
  "model.white_test": "White test",
};

function formatAgentResultValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "—";
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  if (Array.isArray(value)) return value.map(formatAgentResultValue).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function observableActivity(eventType: string | null): string {
  if (!eventType) return "Preparing the bounded context";
  const normalized = eventType.toLowerCase();
  if (normalized.includes("tool")) return "Checking evidence";
  if (normalized.includes("proposal")) return "Preparing a reviewable proposal";
  if (normalized.includes("message") || normalized.includes("response")) return "Drafting the response";
  return "Processing the current request";
}

function terminalFailureMessage(
  messages: Array<{ role: string; stop_reason?: string | null; error?: string | null }>,
  transportError: string | null,
  hasPendingProposal: boolean,
): string | null {
  const terminal = [...messages]
    .reverse()
    .find((message) => message.role === "assistant" && message.stop_reason === "error");
  const error = terminal?.error ?? transportError;
  if (!error) return null;
  if (error === "max_steps_exceeded" && hasPendingProposal) {
    return "The Agent reached its step limit after creating a proposal that is still awaiting your review. The proposal will not execute automatically; confirm, revise, or decline it below.";
  }
  if (error === "LLMUpstreamError") {
    return "The configured provider did not return a usable response. Check the selected model in Settings, then retry. No proposal or analysis was executed.";
  }
  if (error === "tool_runtime_error") {
    return "The Agent tool runtime stopped unexpectedly. Retry the request; no proposal or analysis was executed.";
  }
  return `The Agent stopped before completing the request (${error}). No proposal or analysis was executed.`;
}

function useElapsedSeconds(startedAt: number | null | undefined, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active || startedAt == null) return undefined;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [active, startedAt]);
  return active && startedAt != null ? Math.max(0, Math.floor((now - startedAt) / 1_000)) : 0;
}

function transcriptIsAtBottom(element: HTMLElement): boolean {
  // Scroll positions are fractional on some displays. A small tolerance keeps
  // the terminal anchored when the reader is visually at its bottom without
  // stealing their position once they intentionally inspect earlier output.
  return element.scrollHeight - element.clientHeight - element.scrollTop <= 24;
}

/** Project a durable tool-result entry into a typed one-line status.
 *
 * Tool entries persist the full ToolResult JSON for audit/replay; the panel
 * shows what happened (tool id, ok/error, proposal-ready) instead of dumping
 * the bounded output payload into the transcript. Unparseable content falls
 * back to the raw string so nothing is silently hidden. */
function toolStatusLine(content: string, toolName?: string | null): string {
  let payload: unknown;
  try {
    payload = JSON.parse(content);
  } catch {
    return content;
  }
  if (typeof payload !== "object" || payload === null) return content;
  const record = payload as {
    tool_id?: unknown;
    ok?: unknown;
    error?: unknown;
    output?: { requires_confirmation?: unknown; proposal?: { proposal_id?: unknown } };
  };
  const toolId =
    typeof record.tool_id === "string"
      ? record.tool_id
      : typeof toolName === "string" && toolName
        ? toolName
        : "tool";
  if (record.ok === false) {
    const error = typeof record.error === "string" ? record.error : "failed";
    return `${toolId} ✗ ${error}`;
  }
  if (record.output?.requires_confirmation === true) {
    const proposalId = record.output.proposal?.proposal_id;
    const ref = typeof proposalId === "string" ? ` ${proposalId}` : "";
    return `${toolId} ✓ proposal ready${ref} — awaiting confirmation`;
  }
  return `${toolId} ✓ ok`;
}

type TranscriptTurn = {
  user: AgentMessage | null;
  reasoning: AgentMessage[];
  responses: AgentMessage[];
};

function transcriptTurns(messages: AgentMessage[]): TranscriptTurn[] {
  const turns: TranscriptTurn[] = [];
  let current: TranscriptTurn | null = null;
  for (const message of messages) {
    if (message.role === "user") {
      current = { user: message, reasoning: [], responses: [] };
      turns.push(current);
      continue;
    }
    if (current === null) {
      current = { user: null, reasoning: [], responses: [] };
      turns.push(current);
    }
    if (message.role === "tool" || message.stop_reason === "tool_calls") {
      current.reasoning.push(message);
    } else {
      current.responses.push(message);
    }
  }
  return turns;
}

function visibleReasoningEntries(messages: AgentMessage[]): AgentMessage[] {
  return messages.filter((message) => message.role !== "assistant" || message.content.trim().length > 0);
}

/** One cast entry as the user typed it, e.g. `wage → string`. */
function castLine(entry: unknown): string | null {
  if (!entry || typeof entry !== "object") return null;
  const cast = entry as { column?: unknown; target_dtype?: unknown };
  if (typeof cast.column !== "string" || typeof cast.target_dtype !== "string") return null;
  return `${cast.column} → ${cast.target_dtype}`;
}

function changeSummary(changes: Record<string, unknown>): string {
  return Object.entries(changes).map(([key, value]) => {
    if (
      key !== "model_options"
      && value
      && typeof value === "object"
      && "old" in value
      && "new" in value
    ) {
      const pair = value as { old?: unknown; new?: unknown };
      return `${key}: ${String(pair.old)} → ${String(pair.new)}`;
    }
    // A data cast's `casts` array reads as human intent, not raw JSON: the batch
    // NL path (data.columns.cast) surfaces here, and a dumped array is unreadable.
    if (key === "casts" && Array.isArray(value)) {
      const lines = value.map(castLine).filter((line): line is string => line !== null);
      if (lines.length === value.length && lines.length > 0) {
        return `Cast ${lines.join(", ")}`;
      }
    }
    if (typeof value === "string") return `${key}: ${value}`;
    return `${key}: ${JSON.stringify(value)}`;
  }).join(" · ");
}

function navigationButtonLabel(ref: {
  kind: string;
  relation: string;
  label: string;
}): string {
  const relation = ref.relation === "source"
    ? "source"
    : ref.relation === "parent"
      ? "parent"
      : ref.relation === "child"
        ? "child"
        : ref.relation === "result"
          ? "result"
          : ref.kind;
  const label = ref.label.replace(/^(source|parent|child|result)\s+/i, "");
  return `Open ${relation} ${label}`;
}

export function AgentPanel({ runId, projectRoot }: { runId: string; projectRoot: string }) {
  const agent = useAgentSurface();
  const [editingProposalId, setEditingProposalId] = useState<string | null>(null);
  const [revisionDraft, setRevisionDraft] = useState("");
  const [revisionError, setRevisionError] = useState<string | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const shouldFollowTranscriptRef = useRef(true);
  const hasMeasuredTranscriptRef = useRef(false);
  const turnActive = agent.isSubmitting || agent.sessionStatus.toLowerCase() === "running";
  const elapsedSeconds = useElapsedSeconds(agent.activeTurnStartedAt, turnActive);
  const terminalFailure = agent.isSubmitting
    ? null
    : terminalFailureMessage(
      agent.messages,
      agent.error,
      agent.proposals.some((proposal) => proposal.status === "pending"),
    );
  const auditSessionId = agent.navigationLinks.find(
    (link) => link.kind === "operation" && typeof link.href.session_id === "string",
  )?.href.session_id;
  const recentToolSteps = agent.messages
    .filter((message) => message.role === "tool")
    .slice(-3)
    .map((message) => toolStatusLine(message.content, message.name));
  const turns = transcriptTurns(agent.messages);
  useLayoutEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript) return;
    if (!hasMeasuredTranscriptRef.current) {
      shouldFollowTranscriptRef.current = transcriptIsAtBottom(transcript);
      hasMeasuredTranscriptRef.current = true;
      return;
    }
    if (shouldFollowTranscriptRef.current) {
      transcript.scrollTop = transcript.scrollHeight;
    }
  }, [agent.liveResponseText, agent.messages]);
  const renderTranscriptMessage = (message: AgentMessage) => {
    const sourceRef = message.navigation?.find(
      (link) => link.kind === "graph_node" && link.available,
    );
    return (
      <div
        key={message.entry_id}
        data-testid={`agent-message-${message.role}`}
        data-role={message.role}
        className="wb-agent-terminal-line"
      >
        <span className="wb-agent-terminal-marker" title={roleLabel(message.role)}>
          {roleMarker(message.role)}
        </span>
        {message.role === "tool" ? (
          <span className="wb-agent-terminal-content">
            {toolStatusLine(message.content, message.name)}
          </span>
        ) : message.role === "assistant" ? (
          <div className="wb-agent-terminal-content wb-agent-terminal-markdown">
            {renderMarkdown(message.content)}
          </div>
        ) : (
          <span className="wb-agent-terminal-content wb-agent-terminal-plain">
            {message.content}
          </span>
        )}
        {message.navigation && message.navigation.length > 0 && (
          <span className="wb-agent-message-links" aria-label="Message navigation links">
            {message.navigation.map((link) => (
              <button
                key={`${link.kind}:${link.id}:${link.relation}`}
                type="button"
                className="wb-agent-message-link"
                aria-label={navigationButtonLabel(link)}
                disabled={!link.available || !agent.openNavigation}
                title={link.available ? link.label : link.reason ?? "Unavailable"}
                onClick={() => {
                  if (link.available) agent.openNavigation?.(link);
                }}
              >
                ↗ {link.label}
              </button>
            ))}
          </span>
        )}
        {sourceRef && (
          <button
            type="button"
            className="wb-agent-message-link"
            aria-label={`Fork from Agent message ${message.entry_id}`}
            disabled={!agent.forkFromMessage}
            onClick={() => void agent.forkFromMessage(message.entry_id, sourceRef)}
          >
            ↳ Fork Agent context
          </button>
        )}
      </div>
    );
  };

  return (
    <section
      data-testid="agent-panel"
      aria-label="Agent panel"
      className="wb-agent-panel"
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontSize: 11,
          fontFamily: "var(--font-mono, ui-monospace, monospace)",
        }}
      >
        <strong style={{ color: "var(--label)" }}>agent</strong>
        <span style={{ color: "var(--label-secondary)" }}>{agent.scopeLabel}</span>
        {turnActive && (
          <span data-testid="agent-turn-progress" style={{ color: "var(--label-tertiary)" }} aria-live="polite">
            {`Working · ${elapsedSeconds}s`}
          </span>
        )}
        <span
          data-testid="agent-event-cursor"
          title={agent.lastEventType ? `last event: ${agent.lastEventType}` : "No Agent events yet"}
          style={{ color: "var(--label-tertiary)" }}
        >
          events #{agent.eventCursor}
        </span>
        {auditSessionId && (
          <a
            href={agentAuditExportUrl(projectRoot, auditSessionId)}
            target="_blank"
            rel="noreferrer"
            style={{ color: "var(--label-secondary)" }}
          >
            Export Agent audit
          </a>
        )}
      </header>
      {turnActive && (
        <div
          data-testid="agent-execution-trace"
          className="wb-agent-execution-trace"
          aria-label="Agent execution progress"
          aria-live="polite"
        >
          <div className="wb-agent-execution-trace__step" data-state="complete">
            <span aria-hidden="true">✓</span>
            <span>Request received</span>
          </div>
          {recentToolSteps.map((step, index) => (
            <div key={`${index}:${step}`} className="wb-agent-execution-trace__step" data-state="complete">
              <span aria-hidden="true">✓</span>
              <span>{step}</span>
            </div>
          ))}
          <div className="wb-agent-execution-trace__step" data-state="active">
            <span aria-hidden="true">●</span>
            <span>{observableActivity(agent.lastEventType)}</span>
          </div>
        </div>
      )}
      {turnActive && (
        <section
          data-testid="agent-live-response"
          className="wb-agent-live-response"
          aria-live="polite"
          aria-label="Live Agent response"
        >
          <span className="wb-agent-live-response__label">Live response</span>
          {agent.liveResponseText ? (
            <div className="wb-agent-terminal-markdown">
              {renderMarkdown(agent.liveResponseText)}
            </div>
          ) : (
            <span className="wb-agent-live-response__pending">
              Waiting for the Agent's public response…
            </span>
          )}
        </section>
      )}
      {terminalFailure && (
        <p
          data-testid="agent-turn-error"
          role="status"
          style={{ margin: "6px 0", color: "var(--danger, #b42318)", fontSize: 12 }}
        >
          {terminalFailure}
        </p>
      )}
      <div
        ref={transcriptRef}
        role="log"
        aria-label={`Agent transcript for ${runId}`}
        className="wb-agent-terminal"
        onScroll={(event) => {
          shouldFollowTranscriptRef.current = transcriptIsAtBottom(event.currentTarget);
        }}
      >
        {agent.messages.length === 0 ? (
          <div data-testid="agent-empty" className="wb-agent-terminal-empty">
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Start a task</div>
            <div>Ask about the selected node, active head, or model output.</div>
          </div>
        ) : turns.map((turn, index) => {
          const reasoning = visibleReasoningEntries(turn.reasoning);
          const turnId = turn.user?.entry_id ?? `orphan-${index}`;
          return (
            <div key={turnId} className="wb-agent-turn">
              {turn.user && renderTranscriptMessage(turn.user)}
              {reasoning.length > 0 && (
                <details data-testid={`agent-reasoning-${turnId}`} className="wb-agent-reasoning">
                  <summary>
                    <span>Reasoning</span>
                    <span>{reasoning.length} steps</span>
                  </summary>
                  <div className="wb-agent-reasoning-content">
                    {reasoning.map(renderTranscriptMessage)}
                  </div>
                </details>
              )}
              {turn.responses.map(renderTranscriptMessage)}
            </div>
          );
        })}
      </div>
      {agent.activeOperation && (
        <div
          data-testid="agent-operation-status"
          role="status"
          aria-live="polite"
          className="wb-agent-terminal-line"
          data-role="tool"
          style={{
            flex: "0 0 auto",
            fontFamily: "var(--font-mono, ui-monospace, monospace)",
            fontSize: 12,
          }}
        >
          <span className="wb-agent-terminal-marker" aria-hidden="true">⋮</span>
          <span>
            {agent.activeOperation.operation_id} → {agent.activeOperation.status}
            {agent.activeOperation.target_run_id
              ? ` · child run ${agent.activeOperation.target_run_id}`
              : ""}
          </span>
        </div>
      )}
      {agent.activeOperation && agent.activeOperation.postEstimationResults.length > 0 && (
        /* The answer to the question that prompted the workflow. Without it a
         * confirmed operation reports only that it finished, and the computed
         * result stays in an artifact the user never opens. */
        <div
          data-testid="agent-operation-post-estimation"
          className="wb-agent-terminal-line"
          data-role="tool"
          style={{ flex: "0 0 auto", fontSize: 12, alignItems: "flex-start" }}
        >
          <span className="wb-agent-terminal-marker" aria-hidden="true">↳</span>
          <div style={{ display: "grid", gap: 6 }}>
            {agent.activeOperation.postEstimationResults.map((entry) => (
              <div key={entry.artifact_id}>
                <div style={{ fontWeight: 600 }}>
                  {AGENT_POST_ESTIMATION_LABELS[entry.operation_id] ?? entry.operation_id}
                  <span style={{ fontWeight: 400, opacity: 0.7 }}>
                    {" "}· step {entry.workflow_step_id}
                  </span>
                </div>
                <div style={{ fontVariantNumeric: "tabular-nums" }}>
                  {Object.entries(entry.result)
                    .filter(([key]) => key !== "schema_version")
                    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${formatAgentResultValue(value)}`)
                    .join(" · ")}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {agent.activeOperation?.stdout && (
        /* What the sandboxed program printed. This is the captured output of a
         * finished run, not a live stream — the operation's stdout is only
         * durable once the record completes, so nothing here should read as
         * "watch it run". */
        <div
          data-testid="agent-operation-stdout"
          className="wb-agent-terminal-line"
          data-role="tool"
          style={{ flex: "0 0 auto", fontSize: 12, alignItems: "flex-start" }}
        >
          <span className="wb-agent-terminal-marker" aria-hidden="true">↳</span>
          <pre
            style={{
              margin: 0,
              maxHeight: 160,
              overflow: "auto",
              whiteSpace: "pre-wrap",
              fontFamily: "var(--font-mono, ui-monospace, monospace)",
              fontSize: 12,
            }}
          >
            {agent.activeOperation.stdout}
          </pre>
        </div>
      )}
      {agent.activeOperation?.diffFocused && agent.activeOperation.diff_ref && (
        <div
          data-testid="agent-operation-diff"
          className="wb-agent-terminal-line"
          data-role="tool"
          style={{ flex: "0 0 auto", fontSize: 12 }}
        >
          <span className="wb-agent-terminal-marker" aria-hidden="true">↳</span>
          <span>
            Diff · {String(agent.activeOperation.diff_ref.kind ?? "operation")}
            {(() => {
              const changed = agent.activeOperation?.diff_ref?.changed_fields
                ?? agent.activeOperation?.diff_ref?.changed;
              if (!Array.isArray(changed)) return "";
              const fields = changed.filter((value): value is string => typeof value === "string");
              return fields.length > 0 ? ` · changed: ${fields.join(", ")}` : "";
            })()}
            {agent.activeOperation.verification.passed === true ? " · verified" : " · verification failed"}
          </span>
        </div>
      )}
      {agent.proposals.length > 0 && (
        <aside
          data-testid="agent-action-rail"
          aria-label="Agent actions"
          className="wb-agent-action-rail"
        >
          {agent.proposals.map((proposal) => {
        const pending = proposal.status === "pending";
        return (
          <article
            key={proposal.proposal_id}
            data-testid={`agent-proposal-${proposal.proposal_id}`}
            className="wb-agent-proposal"
            aria-label={`Agent proposal ${proposal.proposal_id}`}
          >
            <div className="wb-agent-proposal-header">
              <strong>{proposal.operation_id}</strong>
              <span>revision {proposal.revision}</span>
              <span className="wb-agent-proposal-status">{proposal.status}</span>
            </div>
            <div className="wb-agent-proposal-change">{changeSummary(proposal.changes)}</div>
            {proposal.expected_effect.length > 0 && (
              <div className="wb-agent-proposal-detail">Expected: {proposal.expected_effect.join("; ")}</div>
            )}
            {proposal.risks.length > 0 && (
              <div className="wb-agent-proposal-detail">Risk: {proposal.risks.join("; ")}</div>
            )}
            {pending && (
              <>
                <div className="wb-agent-proposal-actions">
                  <button
                    type="button"
                    className="wb-agent-proposal-confirm"
                    aria-label={`Confirm proposal ${proposal.proposal_id}`}
                    disabled={agent.confirmationBusyId !== null}
                    onClick={() => void agent.confirmProposal(proposal.proposal_id)}
                  >
                    {agent.confirmationBusyId === proposal.proposal_id
                      ? "Confirming…"
                      : "Confirm proposal"}
                  </button>
                  <button
                    type="button"
                    className="wb-agent-proposal-decline"
                    aria-label={`Decline proposal ${proposal.proposal_id}`}
                    disabled={agent.confirmationBusyId !== null}
                    onClick={() => void agent.declineProposal(proposal.proposal_id)}
                  >
                    {agent.confirmationBusyId === proposal.proposal_id ? "Working…" : "Decline"}
                  </button>
                  <button
                    type="button"
                    className="wb-agent-proposal-revise"
                    aria-label={`Revise proposal ${proposal.proposal_id}`}
                    disabled={agent.confirmationBusyId !== null}
                    onClick={() => {
                      setEditingProposalId(proposal.proposal_id);
                      setRevisionDraft(JSON.stringify(proposal.changes, null, 2));
                      setRevisionError(null);
                    }}
                  >
                    Revise
                  </button>
                </div>
                {editingProposalId === proposal.proposal_id && (
                  <div className="wb-agent-proposal-editor">
                    <textarea
                      aria-label={`Proposal changes ${proposal.proposal_id}`}
                      value={revisionDraft}
                      onChange={(event) => setRevisionDraft(event.target.value)}
                      rows={4}
                    />
                    {revisionError && <div role="alert">{revisionError}</div>}
                    <div className="wb-agent-proposal-actions">
                      <button
                        type="button"
                        className="wb-agent-proposal-confirm"
                        aria-label={`Save revision ${proposal.proposal_id}`}
                        disabled={agent.confirmationBusyId !== null}
                        onClick={async () => {
                          try {
                            const parsed: unknown = JSON.parse(revisionDraft);
                            if (
                              typeof parsed !== "object" ||
                              parsed === null ||
                              Array.isArray(parsed)
                            ) {
                              throw new Error("Changes must be a JSON object");
                            }
                            const saved = await agent.reviseProposal(
                              proposal.proposal_id,
                              proposal.revision,
                              parsed as Record<string, unknown>,
                            );
                            if (saved) setEditingProposalId(null);
                          } catch (error) {
                            setRevisionError(
                              error instanceof Error ? error.message : "Invalid proposal changes",
                            );
                          }
                        }}
                      >
                        Save revision
                      </button>
                      <button
                        type="button"
                        className="wb-agent-proposal-revise"
                        aria-label={`Cancel revision ${proposal.proposal_id}`}
                        onClick={() => setEditingProposalId(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </article>
        );
          })}
        </aside>
      )}
      <AgentComposer showScope={false} variant="terminal" />
    </section>
  );
}
