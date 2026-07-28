import type { DomainMemoryCandidate } from "./domainMemoryContracts";

export interface DomainMemoryReviewQueueProps {
  candidates: DomainMemoryCandidate[];
  onReview: (candidateId: string, decision: "approved" | "rejected", revision: number) => void;
}

export function DomainMemoryReviewQueue({ candidates, onReview }: DomainMemoryReviewQueueProps) {
  return (
    <section className="nb-context-slice" data-testid="domain-memory-review-queue" aria-label="Domain memory review queue">
      <header className="nb-context-header">
        <span className="nb-label">Review memory candidates</span>
        <span>explicit review · no automatic execution</span>
      </header>
      {candidates.length === 0 ? <p>No pending memory candidates.</p> : (
        <ul>
          {candidates.map((candidate) => (
            <li key={`${candidate.candidate_id}@${candidate.revision}`}>
              <p>{candidate.compact_lesson}</p>
              <small>{`${candidate.memory_kind} · sources ${candidate.source_summary_refs.join(", ")}`}</small>
              <div>
                <button type="button" data-testid={`domain-memory-review-approve-${candidate.candidate_id}`} onClick={() => onReview(candidate.candidate_id, "approved", candidate.revision)}>Approve memory</button>
                <button type="button" data-testid={`domain-memory-review-reject-${candidate.candidate_id}`} onClick={() => onReview(candidate.candidate_id, "rejected", candidate.revision)}>Reject</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
