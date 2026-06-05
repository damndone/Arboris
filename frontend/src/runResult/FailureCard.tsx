export interface RecommendedAction {
  key: string;
  label: string;
  severity: "primary" | "secondary";
  form_overrides?: Record<string, unknown>;
  hint?: string;
}

export interface FailureEvidence {
  error_code?: string;
  requested_model_type?: string;
  root_cause?: string;
  y_type?: string;
  recommended_actions?: RecommendedAction[];
}

export function FailureCard(props: {
  evidence: FailureEvidence;
  onAction: (action: RecommendedAction) => void;
}) {
  const { evidence, onAction } = props;
  const actions = evidence.recommended_actions ?? [];
  const requested = evidence.requested_model_type;

  return (
    <div className="failure-card" role="alert" aria-label="Model fit failed">
      <div className="failure-card-title">
        {requested && requested !== "auto"
          ? `The model you requested (${requested}) could not be fit on this data`
          : "Model fit failed"}
      </div>
      {evidence.root_cause && (
        <pre className="failure-card-cause">{evidence.root_cause}</pre>
      )}
      {actions.length > 0 && (
        <div className="failure-card-actions">
          {actions.map((a) => (
            <button
              key={a.key}
              type="button"
              className={`failure-action failure-action-${a.severity}`}
              title={a.hint}
              onClick={() => onAction(a)}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
