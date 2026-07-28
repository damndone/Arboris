import type { DomainMemoryRetrievalProjection } from "./domainMemoryContracts";

export interface DomainMemoryEntryListProps {
  projection: DomainMemoryRetrievalProjection;
}

export function DomainMemoryEntryList({ projection }: DomainMemoryEntryListProps) {
  return (
    <section className="nb-context-slice" data-testid="domain-memory-entry-list" aria-label="Domain memory hints">
      <header className="nb-context-header">
        <span className="nb-label">Domain-memory hints</span>
        <span data-testid="domain-memory-authority">non-authoritative</span>
      </header>
      <p data-testid="domain-memory-outcome">{projection.reason}</p>
      {projection.entries.length === 0 ? <p>No approved memory matched the current evidence.</p> : (
        <ul>
          {projection.entries.map((entry) => (
            <li key={`${entry.memory_id}@${entry.revision}`} data-testid={`domain-memory-${entry.memory_id}`}>
              <p>{entry.compact_lesson}</p>
              <small>{`${entry.memory_kind} · ${entry.recommended_effect_kind} · sources ${entry.source_summary_refs.join(", ")}`}</small>
            </li>
          ))}
        </ul>
      )}
      {projection.omissions.length > 0 ? (
        <p data-testid="domain-memory-omissions">{`${projection.omissions.length} memory entries omitted by current gates.`}</p>
      ) : null}
    </section>
  );
}
