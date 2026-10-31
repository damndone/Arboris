import { AgentUsagePanel } from "./AgentUsagePanel";
import { AgentPlanPanel } from "./AgentPlanPanel";
import { Children, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { buildTurns, duration, messageTime } from "./transcript/turns";
import { MessageActions } from "./transcript/MessageActions";
import { useAgentSurface } from "./AgentSurfaceContext";
import { agentAuditExportUrl } from "./agentApi";
import { AgentComposer } from "./AgentComposer";
import { agentTurnActive } from "./AgentRunControls";
import type { AgentMessage, AgentNavigationRef } from "./agentTypes";
import { AgentRowsTable, shownRows } from "./AgentRowsTable";
import { AgentChart, shownChart } from "./AgentChart";
import { AgentTargetRecovery } from "./AgentTargetRecovery";
import { renderMarkdown } from "../../report/markdown";
import "./agent.css";
import { formatPValue } from "../../format/numbers";
import { AgentApprovalBar } from "./AgentApprovalBar";
import { AgentProposalReceipt, receiptsByTurn } from "./AgentProposalReceipt";
import { activeToolActivityLabel, observableActivity, toolStep, type ToolStep } from "./toolActivity";

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
  const retained = "Completed operations and results remain recorded. Review the steps and resolve unfinished work before continuing.";
  if (error === "provider_output_limit") {
    return "The model reached its response limit before finishing. The reply is incomplete. Completed operations and results remain recorded. Review the recorded work, then request the remaining report in smaller steps.";
  }
  if (error === "agent_timeout") {
    return `The time limit was reached before the request finished. ${retained}`;
  }
  if (error === "analysis_recovery_limit") {
    return "The Agent stopped after reaching its recovery limit. Completed operations and results remain recorded. Inspect the failed step and resolve its recorded cause before continuing.";
  }
  if (error === "LLMUpstreamError" || error.startsWith("LLMUpstreamError:")) {
    return `The configured provider did not return a usable response. Check the selected model in Settings. ${retained}`;
  }
  if (error === "tool_runtime_error") {
    return `The Agent tool runtime stopped unexpectedly. ${retained}`;
  }
  return `The Agent stopped before completing the request (${error}). ${retained}`;
}

/** A viewing shortcut must be bound by this turn's receipt, not session history. */
function stoppedOperation(receipts: AgentMessage[]): { ref: AgentNavigationRef | null; unreadable: boolean } {
  let ref: AgentNavigationRef | null = null;
  let unreadable = false;
  for (const receipt of receipts) {
    let result: { output?: { operation?: { record_id?: unknown } } };
    try {
      result = JSON.parse(receipt.content);
    } catch {
      unreadable = true;
      continue;
    }
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      unreadable = true;
      continue;
    }
    const recordId = result.output?.operation?.record_id;
    if (typeof recordId !== "string" || !recordId) continue;
    const available = receipt.navigation.find(link => link.kind === "operation" && link.available && link.id === recordId && link.href.operation_record_id === recordId);
    if (available) ref = available;
  }
  return { ref, unreadable };
}

function useElapsedSeconds(startedAt: number | null | undefined, active: boolean): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active || startedAt == null) return undefined;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [active, startedAt]);
  return active && startedAt != null ? Math.max(0, Math.floor((now - startedAt) / 1_000)) : null;
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
    error_details?: Array<{ message?: unknown }>;
    output?: {
      saved?: unknown;
      error?: unknown;
      available?: unknown;
      reason?: unknown;
      reason_code?: unknown;
      time_series_summary?: { available?: unknown; reason?: unknown; reason_code?: unknown };
      artifact_evidence?: { available?: unknown; reason?: unknown; reason_code?: unknown };
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
    const message = Array.isArray(record.error_details)
      ? record.error_details.map(detail => detail?.message).find((message): message is string => typeof message === "string" && Boolean(message.trim()))
      : undefined;
    const detail = message?.replace(/\s+/g, " ").trim().slice(0, 240);
    return `${toolId} ✗ ${error}${detail ? ` — ${detail}` : ""}`;
  }
  if (record.output?.saved === false) {
    const error = typeof record.output.error === "string" ? record.output.error.replace(/\s+/g, " ").trim().slice(0, 240) : "";
    return `${toolId} ✗ not saved${error ? ` — ${error}` : ""}`;
  }
  const unavailable = record.output?.available === false ? record.output
    : record.output?.time_series_summary?.available === false ? record.output.time_series_summary
    : record.output?.artifact_evidence?.available === false ? record.output.artifact_evidence : null;
  if (unavailable) {
    const reason = [unavailable.reason, unavailable.reason_code].find((value): value is string => typeof value === "string" && Boolean(value.trim()));
    const detail = reason?.replace(/\s+/g, " ").trim().slice(0, 240);
    return `${toolId} ✗ result unavailable${detail ? ` — ${detail}` : ""}`;
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
/** Where the earlier conversation was summarized: collapsed, with the summary inside. */
function CompactionMarker({ message }: { message: AgentMessage }) {
  const info = message.compaction;
  const trigger = info?.trigger === "manual" ? "on request" : info?.trigger === "overflow" ? "after the model refused a long request" : "near the model's context limit";
  return (
    <details className="agt-compaction" data-testid="agent-compaction" data-entry-id={message.entry_id}>
      <summary>
        <span>Earlier conversation summarized {trigger}</span>
        <span className="agt-compaction__meta">
          {info ? `${info.summarized_messages} messages · ~${info.tokens_before.toLocaleString()} tokens before` : ""}
          {" · "}{messageTime(message.at)}
        </span>
      </summary>
      {info && !info.verified && (
        <p className="agt-compaction__warn">
          Some numbers in this summary ({info.unverified_numbers.join(", ")}) did not match the conversation; the Agent will not cite them without checking again.
        </p>
      )}
      <div className="agt-compaction__body wb-agent-terminal-markdown">{renderMarkdown(message.content)}</div>
      <p className="agt-compaction__note">The Agent now reads this summary instead of the messages above it; they stay here and in the session log.</p>
    </details>
  );
}

/** A step of the work: what it did and how it ended; its sources open from the row. */
function ToolStepRow({ step, children }: { step: ToolStep; children: ReactNode }) {
  const row = (
    <span className={`wb-agent-step wb-agent-step--${step.state}`}>
      <span className="wb-agent-step__mark" aria-hidden="true">{step.state === "failed" ? "✗" : step.state === "waiting" ? "…" : "✓"}</span>
      <span>{step.title}{step.detail && <span className="wb-agent-step__detail"> — {step.detail}</span>}</span>
    </span>
  );
  const hasMore = Children.toArray(children).length > 0;
  return (
    <div className="wb-agent-terminal-content">
      {hasMore ? <details className="wb-agent-tool-details"><summary>{row}</summary>{children}</details> : row}
    </div>
  );
}

export function workSummary(steps: number, drafts: number): string {
  const parts = [];
  if (steps > 0) parts.push(`${steps} ${steps === 1 ? "step" : "steps"}`);
  if (drafts > 0) parts.push(`${drafts} ${drafts === 1 ? "draft" : "drafts"} rewritten`);
  return parts.join(" · ");
}

function withdrawnNumbers(message: AgentMessage): string {
  const check = message.numeric_check;
  const unverified = check && "unverified" in check ? check.unverified : [];
  const numbers = unverified.map((item) => item.text).filter(Boolean);
  return numbers.length > 0 ? numbers.join(", ") : "some numbers";
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
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const stoppedWorkRef = useRef<HTMLDetailsElement | null>(null);
  const stoppedReplyRef = useRef<HTMLDivElement | null>(null);
  const [reviewProblem, setReviewProblem] = useState<string | null>(null);
  const shouldFollowTranscriptRef = useRef(true);
  const hasMeasuredTranscriptRef = useRef(false);
  const turnActive = agentTurnActive(agent);
  const elapsedSeconds = useElapsedSeconds(agent.activeTurnStartedAt, turnActive);
  const terminalFailure = turnActive
    ? null
    : terminalFailureMessage(
      agent.messages,
      agent.error,
      agent.proposals.some((proposal) => proposal.status === "pending"),
    );
  const auditSessionId = agent.navigationLinks.find(
    (link) => link.kind === "operation" && typeof link.href.session_id === "string",
  )?.href.session_id;
  const turns = buildTurns(agent.messages);
  const currentTurn = turns[turns.length - 1];
  const stoppedReply = currentTurn ? [...currentTurn.responses].reverse().find(message => message.stop_reason === "error") : undefined;
  const inspectCurrentTurn = Boolean(terminalFailure && (stoppedReply || agent.error));
  const stoppedReceipts = inspectCurrentTurn ? currentTurn?.steps.filter(message => message.role === "tool") ?? [] : [];
  const stoppedResult = stoppedOperation(stoppedReceipts);
  const lastActivityTurn = [...turns].reverse().find(turn => turn.steps.length > 0 || turn.drafts.length > 0);
  const pendingProposals = agent.proposals.filter((proposal) => proposal.status === "pending");
  const settledProposals = agent.proposals.filter((proposal) => proposal.status !== "pending");
  const receipts = receiptsByTurn(turns, settledProposals);
  const pinned = new Set((agent.chapters ?? []).map((chapter) => chapter.entry_id));
  useEffect(() => { setReviewProblem(null); }, [agent.sessionId, currentTurn?.id, terminalFailure]);
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
  }, [agent.activeToolCalls, agent.liveResponseText, agent.messages]);
  const reviewStoppedContent = (kind: "steps" | "reply") => {
    const target = kind === "steps" ? stoppedWorkRef.current : stoppedReplyRef.current;
    if (!target) {
      setReviewProblem("The recorded content could not be opened in this view. Reopen the saved conversation to inspect it.");
      return;
    }
    setReviewProblem(null);
    if (kind === "steps") {
      stoppedWorkRef.current!.open = true;
      stoppedWorkRef.current!.querySelector("summary")?.focus();
    } else {
      target.focus();
    }
    target.scrollIntoView({ block: "nearest" });
  };
  const renderTranscriptMessage = (message: AgentMessage) => {
    const sourceRef = message.navigation?.find(
      (link) => link.kind === "graph_node" && link.available,
    ) ?? message.navigation?.find((link) => link.kind === "graph_node");
    const references = message.navigation?.map((link) => (
      <button
        key={`${link.kind}:${link.id}:${link.relation}`}
        type="button"
        className="wb-agent-message-link"
        aria-label={navigationButtonLabel(link)}
        disabled={!link.available || !agent.openNavigation}
        title={!link.available ? link.reason ?? "Unavailable" : !agent.openNavigation ? "Navigation is unavailable in this view" : link.label}
        onClick={() => { if (link.available) agent.openNavigation?.(link); }}
      >
        ↗ {link.label}
      </button>
    ));
    const denseReferences = message.role !== "tool" && (references?.length ?? 0) > 3;
    const messageNavigation = message.navigation && message.navigation.length > 0 && (
      <div className="wb-agent-message-links" aria-label="Message navigation links">
        {denseReferences ? references?.slice(0, 2) : references}
        {denseReferences && <details className="wb-agent-message-references">
          <summary>{references!.length - 2} more references</summary>
          <div className="wb-agent-message-links">{references?.slice(2)}</div>
        </details>}
      </div>
    );
    const messageActions = (sourceRef || (message.role !== "tool" && message.stop_reason !== "revised" && message.stop_reason !== "tool_calls")) && (
      <MessageActions
        message={message}
        pinned={pinned.has(message.entry_id)}
        busy={turnActive}
        onRewind={agent.rewindTo}
        onFork={agent.forkConversation}
        onForkContext={sourceRef ? (entryId) => { void agent.forkFromMessage?.(entryId, sourceRef); } : undefined}
        forkContextDisabledReason={sourceRef ? !sourceRef.available ? sourceRef.reason ?? "The source node is unavailable" : !agent.forkFromMessage ? "Forking is unavailable in this view" : !sourceRef.href.run_id || !sourceRef.href.node_ref ? "The source node reference is incomplete" : undefined : undefined}
        onPin={agent.pinChapter}
        onUnpin={agent.unpinChapter}
      />
    );
    return (
      <div
        key={message.entry_id}
        data-testid={`agent-message-${message.role}`}
        data-role={message.role}
        data-entry-id={message.entry_id}
        ref={inspectCurrentTurn && message.entry_id === stoppedReply?.entry_id ? stoppedReplyRef : undefined}
        tabIndex={inspectCurrentTurn && message.entry_id === stoppedReply?.entry_id ? -1 : undefined}
        className={`wb-agent-terminal-line${message.role === "tool" ? " wb-agent-tool-receipt" : ""}`}
      >
        <span className="wb-agent-terminal-marker" title={roleLabel(message.role)}>
          {roleMarker(message.role)}
        </span>
        {message.role === "tool" ? (
          <ToolStepRow step={toolStep(toolStatusLine(message.content, message.name))}>
            {messageNavigation}
            {messageActions}
          </ToolStepRow>
        ) : message.role === "assistant" ? (
          <div className="wb-agent-terminal-content wb-agent-terminal-markdown">
            {message.reasoning?.trim() && (
              <details className="wb-agent-thinking" data-testid="agent-thinking">
                <summary>Thought</summary>
                <div className="wb-agent-thinking__text">{message.reasoning}</div>
              </details>
            )}
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
        {message.role !== "tool" && <>{messageNavigation}{messageActions}</>}
      </div>
    );
  };

  return (
    <section
      data-testid="agent-panel"
      aria-label="Agent panel"
      className="wb-agent-panel"
    >
      {compactHeader && (agent.providerSteps?.length || auditSessionId) ? (
        <div className="wb-agent-meta">
          <AgentUsagePanel events={agent.providerSteps ?? []} compact />
          {auditSessionId && (
            <a href={agentAuditExportUrl(projectRoot, auditSessionId)} target="_blank" rel="noreferrer" aria-label="Export Agent audit" title="Export Agent audit">
              Audit ↗
            </a>
          )}
        </div>
      ) : null}
      {!compactHeader && <header className="wb-agent-panel__header">
        <strong>agent</strong>
        {!compactHeader && <span style={{ color: "var(--label-secondary)" }}>{agent.scopeLabel}</span>}
        {!compactHeader && turnActive && (
          <span data-testid="agent-turn-progress" style={{ color: "var(--label-tertiary)" }} aria-live="polite">
            {elapsedSeconds === null ? "Working · time unavailable" : `Working · ${elapsedSeconds}s`}
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
      {!compactHeader && <AgentUsagePanel events={agent.providerSteps ?? []} />}
      <AgentPlanPanel key={agent.sessionId ?? "new"} />
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
          <div data-testid="agent-empty" className="wb-agent-terminal-empty" />
        ) : turns.map((turn, index) => {
          const latest = index === turns.length - 1;
          const live = turnActive && latest;
          const lastReply = turn.responses[turn.responses.length - 1];
          if (turn.summary) return <CompactionMarker key={turn.id} message={turn.summary} />;
          return (
            <div key={turn.id} className="wb-agent-turn">
              {turn.user && renderTranscriptMessage(turn.user)}
              {(turn.steps.length > 0 || turn.drafts.length > 0) && (
                <details ref={latest && inspectCurrentTurn ? stoppedWorkRef : undefined} data-testid={`agent-reasoning-${turn.id}`} className="wb-agent-reasoning" open={turn === lastActivityTurn}>
                  <summary>
                    <span>
                      {live ? "Working" : lastReply?.stop_reason === "error" ? "Stopped" : "Worked"}
                      <span className="wb-agent-work-count"> · {workSummary(turn.steps.length, turn.drafts.length)}</span>
                    </span>
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
              {turn.steps.map((message) => {
                const chart = shownChart(message);
                return chart ? <AgentChart key={`chart-${message.entry_id}`} chart={chart} /> : null;
              })}
              {turn.steps.filter((message) => message.role === "tool").map((message) => (
                <AgentTargetRecovery key={`target-recovery-${message.entry_id}`} content={message.content}
                  disabled={turnActive || agent.confirmationBusyId !== null}
                  onSelect={(prompt) => { void agent.sendPrompt(prompt); }} />
              ))}
              {turn.responses.map(renderTranscriptMessage)}
              {receipts.get(turn.id)?.map((proposal) => <AgentProposalReceipt key={proposal.proposal_id} proposal={proposal} />)}
            </div>
          );
        })}
        {receipts.get("")?.map((proposal) => <AgentProposalReceipt key={proposal.proposal_id} proposal={proposal} />)}
        {terminalFailure && (
          <div data-testid="agent-turn-error" role="status" className="wb-agent-callout">
            <span>{terminalFailure}</span>
            {inspectCurrentTurn && stoppedReceipts.length === 0 && <small className="wb-agent-stop-note">No tool receipts are recorded in this turn.</small>}
            {stoppedResult.unreadable && <small className="wb-agent-stop-note">Some receipt details could not be read. Review the recorded text before continuing.</small>}
            {(stoppedReceipts.length > 0 || (inspectCurrentTurn && stoppedReply?.content.trim())) && <div className="wb-agent-stop-actions">
              {stoppedReceipts.length > 0
                ? <button type="button" className="wb-agent-message-link" onClick={() => reviewStoppedContent("steps")}>Review recorded steps</button>
                : <button type="button" className="wb-agent-message-link" onClick={() => reviewStoppedContent("reply")}>Review stopped reply</button>}
              {stoppedResult.ref && <button type="button" className="wb-agent-message-link" disabled={!agent.openNavigation}
                title={!agent.openNavigation ? "Navigation is unavailable in this view" : stoppedResult.ref.label}
                onClick={() => {
                  setReviewProblem(agent.openNavigation?.(stoppedResult.ref!) ? null : "The recorded operation could not be opened. Review its source link in the recorded steps.");
                }}>Open recorded operation</button>}
            </div>}
            {reviewProblem && <small role="alert" className="wb-agent-stop-note">{reviewProblem}</small>}
          </div>
        )}
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
              <span className="agt-working__label">{activeToolActivityLabel(agent.activeToolCalls) ?? observableActivity(agent.lastEventType)}</span>
              <span className="agt-working__time">{elapsedSeconds === null ? "Elapsed time unavailable" : `${elapsedSeconds} s`}</span>
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
      {pendingProposals.length > 0 && (
        <aside data-testid="agent-action-rail" aria-label="Agent actions" className="wb-agent-action-rail">
          <AgentApprovalBar proposals={pendingProposals} projectRoot={projectRoot} />
        </aside>
      )}
      {composer ?? <AgentComposer showScope={false} variant="terminal" />}
    </section>
  );
}
