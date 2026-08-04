import type { PredictionResearchEvidence } from "../api";

function fmt(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "—";
}

export function PredictionResearchReportSections(props: {
  evidence: PredictionResearchEvidence | null | undefined;
}) {
  const evidence = props.evidence;
  if (!evidence) return null;

  if (evidence.status === "legacy") {
    return (
      <div data-testid="prediction-research-report-sections" className="ios-card" style={{ marginBottom: 12 }}>
        <section role="region" aria-label="Known limitations">
          <div className="ios-card-title">📜 Predictive research compatibility</div>
          <p className="ios-warning">{evidence.message}</p>
          <p>
            Protocol: <strong>{evidence.protocol ?? "legacy_random_split_v0"}</strong> · Validation: <strong>{evidence.validation ?? "payload_not_evaluated"}</strong> · Comparability: <strong>{evidence.comparability ?? "legacy_only"}</strong>
          </p>
        </section>
      </div>
    );
  }

  if (evidence.status !== "validated") return null;
  const development = evidence.development?.cv ?? [];
  const metrics = evidence.oos?.metrics ?? {};
  const controls = evidence.controls ?? [];

  return (
    <div data-testid="prediction-research-report-sections" className="ios-card" style={{ marginBottom: 12 }}>
      <section role="region" aria-label="Development evidence">
        <div className="ios-card-title">Development evidence</div>
        <p>
          SplitPlan <code>{evidence.split_plan_hash ?? "—"}</code> · {development.length} development fold record(s)
        </p>
      </section>
      <section role="region" aria-label="Final holdout evidence">
        <div className="ios-card-title">Final holdout evidence</div>
        <p>
          n = <strong>{evidence.oos?.n ?? "—"}</strong> · R² = <strong>{fmt(metrics.r2)}</strong> · RMSE = <strong>{fmt(metrics.rmse)}</strong>
        </p>
      </section>
      <section role="region" aria-label="Negative-control evidence">
          <div className="ios-card-title">Negative-control evidence</div>
          <p>
            {controls.length > 0
            ? controls.map((control, index) => (
                <span key={`${control.control ?? "control"}-${index}`}>
                  {index > 0 ? ", " : ""}
                  <strong>{control.control ?? "unnamed"}</strong>: {control.status ?? "receipt"}
                </span>
              ))
            : "No negative-control receipts"}
          </p>
      </section>
      <section role="region" aria-label="Known limitations">
        <div className="ios-card-title">Known limitations</div>
        {(evidence.limits ?? []).length > 0
          ? <ul>{evidence.limits?.map((limit) => <li key={limit}>{limit}</li>)}</ul>
          : <p>No additional limitations recorded.</p>}
      </section>
    </div>
  );
}
