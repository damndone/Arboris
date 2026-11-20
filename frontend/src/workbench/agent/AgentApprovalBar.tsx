// v1.9.1 — what waits for the person's OK, as one bar joined to the top of the
// message box (Claude Code's "Do you want to proceed?"): what it will do in one
// line, its main risk in a muted line, Run / Decline / Edit. The steps, expected
// effect, risks and parameters open on request. Several pending proposals show
// one group at a time. Ordinary same-turn reruns can be checked individually.
// Decided proposals leave the bar; the transcript
// keeps a receipt where they happened.

import { useEffect, useRef, useState } from "react";
import { ProposalFields } from "./ProposalFields";
import { useAgentSurfaceOptional } from "./AgentSurfaceContext";
import type { AgentProposal } from "./agentTypes";
import { changeSummary, proposalTitle } from "./proposalText";
import { groupPendingProposals } from "./proposalGroups";

export function AgentApprovalBar({ proposals, projectRoot }: { proposals: AgentProposal[]; projectRoot: string }) {
  const agent = useAgentSurfaceOptional();
  const [index, setIndex] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [issues, setIssues] = useState<string[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [unchecked, setUnchecked] = useState<Set<string>>(new Set());
  const decisionPending = useRef(false);
  const stopPending = useRef(false);
  const visibleIds = new Set(proposals.map(item => item.proposal_id));
  // Keep decided/other-kind barriers from the original session order even
  // though this bar receives only pending proposals from the composer.
  const groups = groupPendingProposals(agent?.proposals ?? proposals, agent?.capabilityCatalog)
    .map(group => group.filter(item => visibleIds.has(item.proposal_id))).filter(group => group.length > 0);
  useEffect(() => { setIndex((current) => Math.min(current, Math.max(0, groups.length - 1))); }, [groups.length]);
  if (!agent || groups.length === 0) return null;
  const group = groups[index] ?? groups[0];
  const proposal = group.find(item => item.proposal_id === reviewing) ?? group[0];
  const isBatch = group.length > 1 && typeof agent.confirmProposals === "function";
  const selectionKey = (item: AgentProposal) => `${item.proposal_id}:${item.revision}:${item.fingerprint}`;
  const selected = group.filter(item => !unchecked.has(selectionKey(item)));
  const busy = agent.confirmationBusyId !== null || acting || agent.isSubmitting
    || ["running", "working", "cancelling"].includes(agent.sessionStatus);
  const steps = proposal.readable ?? [];
  const isEditing = editing === proposal.proposal_id;
  const canStop = typeof agent.abortTurn === "function";
  const grantClass = agent.executionMode === "ask" && !isBatch ? proposal.session_grant_class : undefined;
  const edit = () => {
    if (busy || decisionPending.current || isEditing) return;
    setEditing(proposal.proposal_id);
    setDraft(proposal.changes);
    setFailure(null);
  };
  const decide = async (action: "confirm" | "decline", grantSession = false) => {
    if (busy || decisionPending.current || isEditing || proposal.status !== "pending") return;
    decisionPending.current = true;
    setActing(true);
    setFailure(null);
    try {
      if (action === "confirm") {
        if (isBatch) {
          if (!selected.length) return;
          await agent.confirmProposals!(selected.map(item => item.proposal_id));
        } else if (grantSession) await agent.confirmProposal(proposal.proposal_id, { grantSession: true });
        else await agent.confirmProposal(proposal.proposal_id);
      }
      else await agent.declineProposal(proposal.proposal_id);
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "Could not apply the proposal decision.");
    } finally {
      decisionPending.current = false;
      setActing(false);
    }
  };
  const stop = async () => {
    if (!canStop || stopPending.current) return;
    stopPending.current = true;
    try {
      await agent.abortTurn();
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "Could not request a stop.");
    } finally {
      stopPending.current = false;
    }
  };

  return (
    <article
      data-testid={`agent-proposal-${proposal.proposal_id}`}
      className="wb-agent-approval"
      aria-label={`Agent proposal ${proposal.proposal_id}`}
      tabIndex={0}
      aria-keyshortcuts={isEditing ? "Escape" : `Enter E S${canStop ? " Escape" : ""}`}
      onKeyDown={(event) => {
        if (event.defaultPrevented || event.repeat || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229
            || event.altKey || event.ctrlKey || event.metaKey || (event.shiftKey && !["e", "s"].includes(event.key.toLowerCase()))
            || !event.currentTarget.contains(document.activeElement)) return;
        if (event.key === "Escape" && isEditing) {
          event.preventDefault();
          event.stopPropagation();
          setEditing(null);
          event.currentTarget.focus();
          return;
        }
        // Native controls retain their own keys. Shortcuts belong to the card
        // itself, never to the composer or a focused control inside the card.
        if (event.target !== event.currentTarget || document.activeElement !== event.currentTarget) return;
        const key = event.key.toLowerCase();
        if (event.key === "Escape" && canStop) {
          event.preventDefault();
          event.stopPropagation();
          void stop();
        } else if (!busy && !isEditing && ["enter", "e", "s"].includes(key)) {
          event.preventDefault();
          event.stopPropagation();
          if (key === "e") edit();
          else void decide(key === "s" ? "decline" : "confirm");
        }
      }}
    >
      <div className="wb-agent-approval__head">
        <span className="wb-agent-approval__ask">{isBatch ? `Run selected? ${selected.length} of ${group.length} selected` : "Run this?"}</span>
        {proposal.revision > 1 && <span>revision {proposal.revision}</span>}
        {groups.length > 1 && (
          <span className="wb-agent-approval__pager">
            <button type="button" aria-label="Previous proposal" disabled={index === 0} onClick={() => setIndex(index - 1)}>‹</button>
            {index + 1} of {groups.length}
            <button type="button" aria-label="Next proposal" disabled={index === groups.length - 1} onClick={() => setIndex(index + 1)}>›</button>
          </span>
        )}
      </div>
      {isBatch && <ul className="wb-agent-proposal-change" aria-label="Same-turn reruns">
        {group.map(item => <li key={selectionKey(item)}>
          <label><input type="checkbox" aria-label={`Select proposal ${item.proposal_id}`}
            checked={!unchecked.has(selectionKey(item))} disabled={busy || isEditing}
            onChange={event => setUnchecked(current => {
              const next = new Set(current);
              if (event.target.checked) next.delete(selectionKey(item)); else next.add(selectionKey(item));
              return next;
            })} /> {proposalTitle(item)}</label>{" "}
          <button type="button" aria-label={`Review proposal ${item.proposal_id}`} disabled={busy || isEditing}
            aria-pressed={proposal.proposal_id === item.proposal_id}
            onClick={() => setReviewing(item.proposal_id)}>Review</button>
        </li>)}
      </ul>}
      <p className="wb-agent-approval__title">
        {proposalTitle(proposal)}
        {steps.length > 1 && <span className="wb-agent-approval__more"> · {steps.length} steps</span>}
      </p>
      {proposal.risks.length > 0 && <p className="wb-agent-approval__risk" title={proposal.risks.join("; ")}>{proposal.risks[0]}</p>}
      {proposal.revision > 1 && (
        <p role="note" className="wb-agent-approval__risk">
          Parameters were revised. The Agent rationale below describes the original proposal; review the current parameter summary before confirming.
        </p>
      )}
      <details className="wb-agent-approval__details" open={isEditing || undefined}>
        <summary>Details</summary>
        {steps.length > 0 ? (
          <ol data-testid="agent-proposal-readable" className="wb-agent-proposal-change">
            {steps.map((line, lineIndex) => <li key={lineIndex}>{line}</li>)}
          </ol>
        ) : (
          <div className="wb-agent-proposal-change">{changeSummary(proposal.changes)}</div>
        )}
        {proposal.expected_effect.length > 0 && <div className="wb-agent-proposal-detail">Expected: {proposal.expected_effect.join("; ")}</div>}
        {proposal.risks.length > 0 && <div className="wb-agent-proposal-detail">Risk: {proposal.risks.join("; ")}</div>}
        {steps.length > 0 && (
          <details className="wb-agent-proposal-detail">
            <summary>Technical parameters · {proposal.operation_id}</summary>
            <pre>{JSON.stringify(proposal.changes, null, 2)}</pre>
          </details>
        )}
        {isEditing && (
          <div className="wb-agent-proposal-editor">
            <ProposalFields projectRoot={projectRoot} label={`Proposal changes ${proposal.proposal_id}`} value={draft} onChange={setDraft} onIssues={setIssues} />
            {issues.length > 0 && <p role="status">{issues.join(" ")}</p>}
            {failure && <div role="alert">{failure}</div>}
            <div className="wb-agent-approval__actions">
              <button
                type="button"
                className="wb-agent-approval__primary"
                aria-label={`Save revision ${proposal.proposal_id}`}
                disabled={busy || issues.length > 0}
                onClick={async () => {
                  try {
                    const parsed: unknown = draft;
                    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
                      throw new Error("Changes must be a JSON object");
                    }
                    const saved = await agent.reviseProposal(proposal.proposal_id, proposal.revision, parsed as Record<string, unknown>);
                    if (saved) setEditing(null);
                  } catch (error) {
                    setFailure(error instanceof Error ? error.message : "Invalid proposal changes");
                  }
                }}
              >
                Save revision
              </button>
              <button type="button" aria-label={`Cancel revision ${proposal.proposal_id}`} onClick={() => setEditing(null)}>Cancel</button>
            </div>
          </div>
        )}
      </details>
      <small>{isEditing ? "Esc Cancel edit" : `Focus this card: ↵ Confirm · E Edit · S Skip${canStop ? " · Esc Stop" : ""}`}</small>
      {failure && !isEditing && <div role="alert">{failure}</div>}
      <div className="wb-agent-approval__actions">
        <button
          type="button"
          className="wb-agent-approval__primary"
          aria-label={isBatch ? "Run selected proposals" : `Confirm proposal ${proposal.proposal_id}`}
          disabled={busy || isEditing || (isBatch && selected.length === 0)}
          onClick={() => void decide("confirm")}
        >
          {agent.confirmationBusyId !== null ? "Running…" : isBatch ? `Run ${selected.length} selected` : "Run"}
        </button>
        <button
          type="button"
          aria-label={`Decline proposal ${proposal.proposal_id}`}
          disabled={busy || isEditing}
          onClick={() => void decide("decline")}
        >
          Decline
        </button>
        <button
          type="button"
          aria-label={`Revise proposal ${proposal.proposal_id}`}
          disabled={busy}
          onClick={edit}
        >
          Edit
        </button>
        {grantClass && <button type="button" disabled={busy || isEditing}
          aria-label={`Run and allow ${grantClass} operations in this conversation`}
          title={`Allows the ${grantClass} permission class for this conversation. Project rules and protected operations still apply.`}
          onClick={() => void decide("confirm", true)}>
          Run &amp; allow similar operations
        </button>}
      </div>
    </article>
  );
}
