import type { NotebookContextSlice } from "./contracts";

/**
 * The visible slice: what the agent actually saw, and what actually happened.
 *
 * This panel exists because "context compiled" is not evidence. Spec §12.4
 * requires every truncation to be recorded explicitly, and the calibration in
 * §12.3 is blunt: a single run holds 59 artifacts of which 5 get a detailed
 * summary. If the surface prints "5 of 5" — or prints nothing — the reader has
 * no way to notice that 36 `time_series_json` products never reached the
 * planner. Every number below is read from the packet; none is derived except
 * the omitted count, which is presentational subtraction.
 */

function shortHash(value: string): string {
  const separator = value.indexOf(":");
  if (separator === -1) return `${value.slice(0, 8)}…`;
  return `${value.slice(0, separator + 1)}${value.slice(separator + 1, separator + 9)}…`;
}

export interface ContextSlicePanelProps {
  slice: NotebookContextSlice;
}

export function ContextSlicePanel({ slice }: ContextSlicePanelProps) {
  const budget = slice.budget_report;
  const budgetUnit = budget.unit ?? "bytes";
  const omittedCount = slice.omissions.reduce(
    (total, omission) =>
      total + Math.max(0, omission.available_count - omission.included_count),
    0,
  );

  return (
    <section className="nb-context-slice" data-testid="context-slice-panel">
      <details className="nb-context-details" data-testid="context-evidence-details">
        <summary data-testid="context-evidence-summary">
          <span>
            <span className="nb-label">Evidence and audit details</span>
            <span>{` · ${slice.trace.length} recorded events · ${omittedCount} omitted items`}</span>
          </span>
          <span className="nb-context-summary-action">Show full evidence</span>
        </summary>

        <div className="nb-context-details-body">
          <header className="nb-context-header">
            <span className="nb-label">What the agent saw</span>
            <span data-testid="context-slice-identity">
              {`${slice.context_id} · ${slice.context_profile}`}
            </span>
          </header>

          <div className="nb-context-hashes">
            <div data-testid="context-slice-generation-hash">
              {`generation_context_hash ${shortHash(slice.generation_context_hash)}`}
            </div>
            <div data-testid="context-slice-freshness-hash">
              {`freshness_dependency_fingerprint ${shortHash(
                slice.freshness_dependency_fingerprint,
              )}`}
            </div>
            <p className="nb-context-hash-note">
              Two fingerprints, kept apart on purpose: the first records what was compiled,
              only the second gates execution.
            </p>
          </div>

          <div className="nb-context-omissions">
            <span className="nb-label">Omitted from the compiled context</span>
            <ul>
              {slice.omissions.map((omission) => {
                const omitted = omission.available_count - omission.included_count;
                return (
                  <li
                    key={omission.section}
                    data-testid={`context-omission-${omission.section}`}
                    data-section={omission.section}
                  >
                    <span>
                      {`${omission.section}: ${omission.included_count} of ${omission.available_count} included, ${omitted} omitted (${omission.reason})`}
                    </span>
                    {omission.omitted_by_type.length > 0 ? (
                      <ul className="nb-context-omitted-types">
                        {omission.omitted_by_type.map((entry) => (
                          <li key={entry.artifact_type}>
                            {`${entry.count} ${entry.artifact_type} omitted`}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="nb-context-type-counts" data-testid="context-type-counts">
            <span className="nb-label">Artifact type counts (kept in full)</span>
            <ul>
              {slice.artifact_type_counts.map((entry) => (
                <li key={entry.artifact_type}>{`${entry.artifact_type} ${entry.count}`}</li>
              ))}
            </ul>
          </div>

          <div className="nb-context-budget" data-testid="context-budget-report">
            <span className="nb-label">Budget report</span>
            <ul>
              {budget.sections.map((section) => (
                <li key={section.section}>
                  {`${section.section} ${section.used_bytes} / ${section.budget_bytes} ${budgetUnit}`}
                </li>
              ))}
              <li className="nb-context-budget-total">
                {`total ${budget.total_used_bytes} / ${budget.total_budget_bytes} ${budgetUnit}`}
              </li>
            </ul>
          </div>

          <div className="nb-context-manifest" data-testid="context-source-manifest">
            <span className="nb-label">Source objects</span>
            <ul>
              {slice.source_manifest.map((entry) => (
                <li key={entry.source_ref}>
                  {`${entry.source_ref} · rev ${entry.revision} · ${entry.selection_reason}${
                    entry.never_truncated ? " · never truncated" : ""
                  }`}
                </li>
              ))}
            </ul>
          </div>

          <div className="nb-context-trace">
            <span className="nb-label">Decision chain</span>
            <ol>
              {slice.trace.map((event) => (
                <li
                  key={event.event_id}
                  data-testid={`trace-event-${event.event_id}`}
                  data-event-type={event.event_type}
                >
                  <span className="nb-trace-line">
                    {`#${event.sequence} ${event.event_type} · ${event.summary}`}
                  </span>
                  <span className="nb-trace-time">{` · ${event.occurred_at}`}</span>
                </li>
              ))}
            </ol>
            <p className="nb-context-trace-note">
              A recorded decision is evidence of what happened, not a judgement about what
              should have happened.
            </p>
          </div>
        </div>
      </details>
    </section>
  );
}
