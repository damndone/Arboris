// v1.9.1 — a decided proposal, in the conversation where it happened: one line
// ("✓ Approved · Assemble the completed steps into a report · 16:39"); its steps
// and operation open on request.

import type { AgentProposal } from "./agentTypes";
import { proposalOutcome, proposalTitle } from "./proposalText";

function clock(at: string): string {
  const time = new Date(at);
  return Number.isNaN(time.getTime()) ? "" : time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function AgentProposalReceipt({ proposal }: { proposal: AgentProposal }) {
  const { mark, verb } = proposalOutcome(proposal.status);
  const steps = proposal.readable ?? [];
  return (
    <details className="wb-agent-receipt" data-testid={`agent-proposal-${proposal.proposal_id}`} data-status={proposal.status}>
      <summary>
        <span className="wb-agent-receipt__mark" aria-hidden="true">{mark}</span>
        <span className="wb-agent-receipt__verb">{verb}</span>
        <span className="wb-agent-receipt__title">{proposalTitle(proposal)}</span>
        <span className="wb-agent-receipt__time">{clock(proposal.created_at)}</span>
      </summary>
      {steps.length > 1 && <ol>{steps.map((line, index) => <li key={index}>{line}</li>)}</ol>}
      <p>{proposal.operation_id} · revision {proposal.revision} · {proposal.status}</p>
    </details>
  );
}

/** Each decided proposal goes with the turn whose message came last before it;
 *  one that no turn can hold (no dated message yet) is listed under "" at the end. */
export function receiptsByTurn<T extends { id: string; user: { at?: string | null } | null }>(
  turns: T[],
  proposals: AgentProposal[],
): Map<string, AgentProposal[]> {
  const byTurn = new Map<string, AgentProposal[]>();
  const starts = turns.map((turn) => (turn.user?.at ? Date.parse(turn.user.at) : Number.NaN));
  for (const proposal of proposals) {
    const at = Date.parse(proposal.created_at);
    let chosen = -1;
    starts.forEach((start, index) => { if (!Number.isNaN(start) && start <= at) chosen = index; });
    if (chosen < 0) chosen = starts.findIndex((start) => !Number.isNaN(start));
    const id = chosen < 0 ? "" : turns[chosen].id;
    byTurn.set(id, [...(byTurn.get(id) ?? []), proposal]);
  }
  return byTurn;
}
