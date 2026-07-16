import { useState } from "react";
import { useAgentSurface } from "./AgentSurfaceContext";
import { AgentHierarchyTree } from "./AgentHierarchyTree";
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

/** One cast entry as the user typed it, e.g. `wage → string`. */
function castLine(entry: unknown): string | null {
  if (!entry || typeof entry !== "object") return null;
  const cast = entry as { column?: unknown; target_dtype?: unknown };
  if (typeof cast.column !== "string" || typeof cast.target_dtype !== "string") return null;
  return `${cast.column} → ${cast.target_dtype}`;
}

function changeSummary(changes: Record<string, unknown>): string {
  return Object.entries(changes).map(([key, value]) => {
    if (value && typeof value === "object" && "old" in value && "new" in value) {
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

export function AgentPanel({ runId }: { runId: string; projectRoot: string }) {
  const agent = useAgentSurface();
  const [editingProposalId, setEditingProposalId] = useState<string | null>(null);
  const [revisionDraft, setRevisionDraft] = useState("");
  const [revisionError, setRevisionError] = useState<string | null>(null);
  const contextLabel = agent.contextWindowTokens === null
    ? `${agent.contextUsedTokens.toLocaleString()} tokens · capacity unknown`
    : `${agent.contextUsedTokens.toLocaleString()} / ${agent.contextWindowTokens.toLocaleString()} tokens`;

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
        <span style={{ marginLeft: "auto", color: "var(--label-tertiary)" }}>{contextLabel}</span>
        <span style={{ color: "var(--label-tertiary)" }} aria-label={`Session status: ${agent.sessionStatus}`}>
          [{agent.isSubmitting ? "thinking" : agent.sessionStatus}]
        </span>
        <span
          data-testid="agent-event-cursor"
          title={agent.lastEventType ? `last event: ${agent.lastEventType}` : "No Agent events yet"}
          style={{ color: "var(--label-tertiary)" }}
        >
          events #{agent.eventCursor}
        </span>
      </header>
      {agent.hierarchy && (
        <AgentHierarchyTree
          root={agent.hierarchy}
          openNavigation={agent.openNavigation}
        />
      )}
      {agent.navigationLinks.length > 0 && (
        <nav
          data-testid="agent-navigation-links"
          aria-label="Agent lineage links"
          className="wb-agent-navigation-links"
        >
          {agent.navigationLinks.map((link) => (
            <button
              key={`${link.kind}:${link.id}:${link.relation}`}
              type="button"
              className="wb-agent-navigation-link"
              aria-label={navigationButtonLabel(link)}
              disabled={!link.available || !agent.openNavigation}
              title={link.available ? link.label : link.reason ?? "Unavailable"}
              onClick={() => {
                if (link.available) agent.openNavigation?.(link);
              }}
            >
              <span className="wb-agent-navigation-link-relation">{link.relation}</span>
              <span>{link.label}</span>
            </button>
          ))}
        </nav>
      )}
      <div
        role="log"
        aria-label={`Agent transcript for ${runId}`}
        className="wb-agent-terminal"
      >
        {agent.messages.length === 0 ? (
          <div data-testid="agent-empty" className="wb-agent-terminal-empty">
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Start a task</div>
            <div>Ask about the selected node, active head, or model output.</div>
          </div>
        ) : (
          agent.messages.map((message) => {
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
          })
        )}
      </div>
      {/* G3: the bottom panel is a read-only transcript / inspection surface.
       *  The Agent has a single input — the composer under the graph — so this
       *  panel no longer carries a redundant, in-sync input row. Elevated
       *  capability (e.g. code.execute) is a typed, confirmed operation whose
       *  output streams here, not a second, higher-privilege input box. */}
      <div
        data-testid="agent-terminal-input-moved-hint"
        className="wb-agent-terminal-input-hint"
        style={{
          flex: "0 0 auto",
          fontFamily: "var(--font-mono, ui-monospace, monospace)",
          fontSize: 11,
          color: "var(--label-tertiary)",
        }}
      >
        <span aria-hidden="true">❯ </span>
        Input moved to the Agent bar under the graph · this panel shows the transcript, operations, and diffs
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
    </section>
  );
}
