import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { buildTurns, duration, messageTime } from "./transcript/turns";
import { MessageActions } from "./transcript/MessageActions";
import { useAgentSurface } from "./AgentSurfaceContext";
import { agentAuditExportUrl } from "./agentApi";
import { AgentComposer } from "./AgentComposer";
import type { AgentMessage } from "./agentTypes";
import { AgentRowsTable, shownRows } from "./AgentRowsTable";
import { renderMarkdown } from "../../report/markdown";
import "./agent.css";
import { formatPValue } from "../../format/numbers";
import { ProposalFields } from "./ProposalFields";

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
  if (normalized === "provider_retry") return "The provider connection dropped; retrying";
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
  // Only the latest reply decides: a turn that failed earlier and was then
  // asked again and answered is over.
  const latest = [...messages].reverse().find((message) => message.role === "assistant");
  const terminal = latest?.stop_reason === "error" ? latest : undefined;
  const error = terminal?.error ?? transportError;
  if (!error) return null;
  if (error === "max_steps_exceeded" && hasPendingProposal) {
    return "The Agent reached its step limit after creating a proposal that is still awaiting your review. The proposal will not execute automatically; confirm, revise, or decline it below.";
  }
  if (error === "LLMUpstreamError" || error.startsWith("LLMUpstreamError:")) {
    return "The configured provider did not return a usable response. Check the selected model in Settings, then retry. Nothing in your data or models was changed.";
  }
  if (error === "tool_runtime_error") {
    return "The Agent tool runtime stopped unexpectedly. Retry the request; nothing in your data or models was changed.";
  }
  return `The Agent stopped before completing the request (${error}). Nothing in your data or models was changed.`;
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
export function toolStatusLine(content: string, toolName?: string | null): string {
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
    output?: {
      requires_confirmation?: unknown;
      proposal?: { proposal_id?: unknown };
      confirmation_reason?: unknown;
      executed?: unknown;
      inferential_tests_run_this_session?: unknown;
      operation?: { status?: unknown };
    };
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
  const calculations = (record.output as { results?: unknown } | undefined)?.results;
  if (toolId === "calculate" && Array.isArray(calculations)) {
    // Arithmetic done in code, so the answer can quote it (numeric check).
    const lines = calculations.map((item) => {
      const entry = item as { label?: unknown; expression?: unknown; value?: unknown; error?: unknown };
      const name = typeof entry.label === "string" && entry.label ? `${entry.label}: ` : "";
      return typeof entry.value === "string"
        ? `${name}${String(entry.expression)} = ${entry.value}`
        : `${name}${String(entry.expression)} ✗ ${String(entry.error)}`;
    });
    return `calculate ✓ ${lines.join("; ")}`;
  }
  if (record.output?.executed === true) {
    // Read-only workflows run without a click; say so, and how many tests
    // this session has run -- the count the report discloses.
    const tests = record.output.inferential_tests_run_this_session;
    const count = typeof tests === "number" ? ` · ${tests} test${tests === 1 ? "" : "s"} run this session` : "";
    const status = record.output.operation?.status;
    return status === "completed"
      ? `${toolId} ✓ read-only analysis ran without confirmation (recorded)${count}`
      : `${toolId} ✗ read-only analysis ${typeof status === "string" ? status : "failed"}`;
  }
  if (record.output?.executed === false) {
    return `${toolId} ✗ read-only analysis could not run`;
  }
  if (record.output?.requires_confirmation === true) {
    const proposalId = record.output.proposal?.proposal_id;
    const ref = typeof proposalId === "string" ? ` ${proposalId}` : "";
    const reason = record.output.confirmation_reason;
    return `${toolId} ✓ proposal ready${ref} — awaiting confirmation${typeof reason === "string" ? ` (${reason})` : ""}`;
  }
  return `${toolId} ✓ ok`;
}

/** "Worked through 3 steps · rewrote the answer once" */
export function workSummary(steps: number, drafts: number): string {
  const parts = [];
  if (steps > 0) parts.push(`Worked through ${steps} ${steps === 1 ? "step" : "steps"}`);
  if (drafts > 0) parts.push(`${steps > 0 ? "rewrote" : "Rewrote"} the answer ${drafts === 1 ? "once" : `${drafts} times`} after checking its numbers`);
  return parts.join(" · ");
}

function withdrawnNumbers(message: AgentMessage): string {
  const check = message.numeric_check;
  const unverified = check && "unverified" in check ? check.unverified : [];
  const numbers = unverified.map((item) => item.text).filter(Boolean);
  return numbers.length > 0 ? numbers.join(", ") : "some numbers";
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

export function AgentPanel({
  runId,
  projectRoot,
  composer,
  compactHeader = false,
}: {
  runId: string;
  projectRoot: string;
  /** v1.9.0: a host may supply its own composer (the workspace Agent column). */
  composer?: ReactNode;
  /** The workspace shows the focus in its composer; it keeps only the audit link here. */
  compactHeader?: boolean;
}) {
  const agent = useAgentSurface();
  const [revisionIssues, setRevisionIssues] = useState<string[]>([]);
  const [editingProposalId, setEditingProposalId] = useState<string | null>(null);
  const [revisionDraft, setRevisionDraft] = useState<Record<string, unknown>>({});
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
  const turns = buildTurns(agent.messages);
  const pinned = new Set((agent.chapters ?? []).map((chapter) => chapter.entry_id));
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
        data-entry-id={message.entry_id}
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
            {message.stop_reason === "revised" && (
              <p data-testid="agent-withdrawn-draft" className="wb-agent-withdrawn-draft">
                Earlier draft, withdrawn by the number check: {withdrawnNumbers(message)} matched no result, so the Agent rewrote the answer below.
              </p>
            )}
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
        {message.role !== "tool" && message.stop_reason !== "revised" && message.stop_reason !== "tool_calls" && (
          <MessageActions
            message={message}
            pinned={pinned.has(message.entry_id)}
            busy={turnActive}
            onRewind={agent.rewindTo}
            onFork={agent.forkConversation}
            onPin={agent.pinChapter}
            onUnpin={agent.unpinChapter}
          />
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
      {(!compactHeader || auditSessionId) && <header
        className={compactHeader ? "wb-agent-panel__header wb-agent-panel__header--compact" : "wb-agent-panel__header"}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontSize: 11,
          fontFamily: "var(--font-mono, ui-monospace, monospace)",
        }}
      >
        {!compactHeader && <strong style={{ color: "var(--label)" }}>agent</strong>}
        {!compactHeader && <span style={{ color: "var(--label-secondary)" }}>{agent.scopeLabel}</span>}
        {!compactHeader && turnActive && (
          <span data-testid="agent-turn-progress" style={{ color: "var(--label-tertiary)" }} aria-live="polite">
            {`Working · ${elapsedSeconds}s`}
          </span>
        )}
        {!compactHeader && <span
          data-testid="agent-event-cursor"
          title={agent.lastEventType ? `last event: ${agent.lastEventType}` : "No Agent events yet"}
          style={{ color: "var(--label-tertiary)" }}
        >
          events #{agent.eventCursor}
        </span>}
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
      </header>}
      {terminalFailure && (
        <p
          data-testid="agent-turn-error"
          role="status"
          style={{ margin: "6px 0", color: "var(--status-fails-fg)", fontSize: 12 }}
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
        {agent.chapters && agent.chapters.length > 0 && (
          <nav className="agt-chapters" aria-label="Chapters">
            <span>Chapters</span>
            {agent.chapters.map((chapter) => (
              <button
                key={chapter.entry_id}
                type="button"
                title={`Pinned ${messageTime(chapter.at)}`}
                onClick={() => transcriptRef.current
                  ?.querySelector(`[data-entry-id="${CSS.escape(chapter.entry_id)}"]`)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })}
              >
                {chapter.title}
              </button>
            ))}
          </nav>
        )}
        {agent.messages.length === 0 && !turnActive ? (
          <div data-testid="agent-empty" className="wb-agent-terminal-empty">
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Start a task</div>
            <div>Ask about the selected node, active head, or model output.</div>
          </div>
        ) : turns.map((turn, index) => {
          const live = turnActive && index === turns.length - 1;
          return (
            <div key={turn.id} className="wb-agent-turn">
              {turn.user && renderTranscriptMessage(turn.user)}
              {!live && (turn.steps.length > 0 || turn.drafts.length > 0) && (
                <details data-testid={`agent-reasoning-${turn.id}`} className="wb-agent-reasoning">
                  <summary>
                    <span>{workSummary(turn.steps.length, turn.drafts.length)}</span>
                    {turn.seconds !== null && <span>{duration(turn.seconds)}</span>}
                  </summary>
                  <div className="wb-agent-reasoning-content">
                    {turn.steps.map(renderTranscriptMessage)}
                    {turn.drafts.map(renderTranscriptMessage)}
                  </div>
                </details>
              )}
              {turn.steps.map((message) => {
                const shown = shownRows(message);
                return shown ? <AgentRowsTable key={`rows-${message.entry_id}`} shown={shown} /> : null;
              })}
              {turn.responses.map(renderTranscriptMessage)}
            </div>
          );
        })}
        {turnActive && (
          /* The turn in progress lives in the conversation, where its reply
           * will land, instead of in boxes above that push it away. */
          <div className="wb-agent-turn wb-agent-turn--live">
            <div
              data-testid="agent-execution-trace"
              className="agt-working"
              aria-label="Agent execution progress"
              aria-live="polite"
            >
              <span className="agt-working__dot" aria-hidden="true" />
              <span>{observableActivity(agent.lastEventType)}</span>
              <span className="agt-working__time">{elapsedSeconds} s</span>
              {recentToolSteps.length > 0 && (
                <details className="agt-working__steps">
                  <summary>{recentToolSteps.length} recent {recentToolSteps.length === 1 ? "step" : "steps"}</summary>
                  <ul>{recentToolSteps.map((step, stepIndex) => <li key={`${stepIndex}:${step}`}>{step}</li>)}</ul>
                </details>
              )}
            </div>
            {agent.liveResponseText && (
              <div
                data-testid="agent-live-response"
                className="wb-agent-terminal-line"
                data-role="assistant"
                aria-label="Live Agent response"
              >
                <span className="wb-agent-terminal-marker" aria-hidden="true">{roleMarker("assistant")}</span>
                <div className="wb-agent-terminal-content wb-agent-terminal-markdown">{renderMarkdown(agent.liveResponseText)}</div>
              </div>
            )}
          </div>
        )}
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
                    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${/p_value$/.test(key) && typeof value === "number" ? formatPValue(value) : formatAgentResultValue(value)}`)
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
            {proposal.readable && proposal.readable.length > 0 ? (
              <>
                <ol data-testid="agent-proposal-readable" className="wb-agent-proposal-change" style={{ margin: "4px 0", paddingLeft: 18 }}>
                  {proposal.readable.map((line, index) => (
                    <li key={index}>{line}</li>
                  ))}
                </ol>
                <details className="wb-agent-proposal-detail">
                  <summary>Technical parameters</summary>
                  <pre style={{ whiteSpace: "pre-wrap", fontSize: 11, margin: 0 }}>
                    {JSON.stringify(proposal.changes, null, 2)}
                  </pre>
                </details>
              </>
            ) : (
              <div className="wb-agent-proposal-change">{changeSummary(proposal.changes)}</div>
            )}
            {proposal.revision > 1 && <p role="note">Parameters were revised. The Agent rationale below describes the original proposal; review the current parameter summary before confirming.</p>}
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
                    disabled={agent.confirmationBusyId !== null || editingProposalId === proposal.proposal_id}
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
                      setRevisionDraft(proposal.changes);
                      setRevisionError(null);
                    }}
                  >
                    Revise
                  </button>
                </div>
                {editingProposalId === proposal.proposal_id && (
                  <div className="wb-agent-proposal-editor">
                    <ProposalFields projectRoot={projectRoot} label={`Proposal changes ${proposal.proposal_id}`} value={revisionDraft} onChange={setRevisionDraft} onIssues={setRevisionIssues} />
                    {revisionIssues.length > 0 && <p role="status">{revisionIssues.join(" ")}</p>}
                    {revisionError && <div role="alert">{revisionError}</div>}
                    <div className="wb-agent-proposal-actions">
                      <button
                        type="button"
                        className="wb-agent-proposal-confirm"
                        aria-label={`Save revision ${proposal.proposal_id}`}
                        disabled={agent.confirmationBusyId !== null || revisionIssues.length > 0}
                        onClick={async () => {
                          try {
                            const parsed: unknown = revisionDraft;
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
      {composer ?? <AgentComposer showScope={false} variant="terminal" />}
    </section>
  );
}
