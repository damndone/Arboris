// v1.9.1 — what waits for the person's OK, as one bar joined to the top of the
// message box (Claude Code's "Do you want to proceed?"): what it will do in one
// line, its main risk in a muted line, Run / Decline / Edit. The steps, expected
// effect, risks and parameters open on request. Several pending proposals show
// one at a time ("1 of 3"). Decided proposals leave the bar; the transcript
// keeps a receipt where they happened.

import { useEffect, useState } from "react";
import { ProposalFields } from "./ProposalFields";
import { useAgentSurfaceOptional } from "./AgentSurfaceContext";
import type { AgentProposal } from "./agentTypes";
import { changeSummary, proposalTitle } from "./proposalText";

export function AgentApprovalBar({ proposals, projectRoot }: { proposals: AgentProposal[]; projectRoot: string }) {
  const agent = useAgentSurfaceOptional();
  const [index, setIndex] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [issues, setIssues] = useState<string[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  useEffect(() => { setIndex((current) => Math.min(current, Math.max(0, proposals.length - 1))); }, [proposals.length]);
  if (!agent || proposals.length === 0) return null;
  const proposal = proposals[index] ?? proposals[0];
  const busy = agent.confirmationBusyId !== null;
  const steps = proposal.readable ?? [];
  const isEditing = editing === proposal.proposal_id;

  return (
    <article
      data-testid={`agent-proposal-${proposal.proposal_id}`}
      className="wb-agent-approval"
      aria-label={`Agent proposal ${proposal.proposal_id}`}
    >
      <div className="wb-agent-approval__head">
        <span className="wb-agent-approval__ask">Run this?</span>
        {proposal.revision > 1 && <span>revision {proposal.revision}</span>}
        {proposals.length > 1 && (
          <span className="wb-agent-approval__pager">
            <button type="button" aria-label="Previous proposal" disabled={index === 0} onClick={() => setIndex(index - 1)}>‹</button>
            {index + 1} of {proposals.length}
            <button type="button" aria-label="Next proposal" disabled={index === proposals.length - 1} onClick={() => setIndex(index + 1)}>›</button>
          </span>
        )}
      </div>
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
      <div className="wb-agent-approval__actions">
        <button
          type="button"
          className="wb-agent-approval__primary"
          aria-label={`Confirm proposal ${proposal.proposal_id}`}
          disabled={busy || isEditing}
          onClick={() => void agent.confirmProposal(proposal.proposal_id)}
        >
          {agent.confirmationBusyId === proposal.proposal_id ? "Running…" : "Run"}
        </button>
        <button
          type="button"
          aria-label={`Decline proposal ${proposal.proposal_id}`}
          disabled={busy}
          onClick={() => void agent.declineProposal(proposal.proposal_id)}
        >
          Decline
        </button>
        <button
          type="button"
          aria-label={`Revise proposal ${proposal.proposal_id}`}
          disabled={busy}
          onClick={() => {
            setEditing(proposal.proposal_id);
            setDraft(proposal.changes);
            setFailure(null);
          }}
        >
          Edit
        </button>
      </div>
    </article>
  );
}
