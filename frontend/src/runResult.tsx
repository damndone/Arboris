import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  artifactDownloadUrl,
  connectRunEvents,
  fetchArtifactJson,
  fetchRunArtifacts,
  fetchRunDetail,
  reportUrl,
  type ArtifactGroup,
  type CoefficientRisk,
  type IssueRecord,
  type RunDetail,
} from "./api";
import { validateDiagnosticPreview } from "./contract/validateDiagnosticPreview";
import { FailureCard, type RecommendedAction } from "./runResult/FailureCard";
import {
  IVDiagnosticsCard,
  type IVDiagnostics,
} from "./runResult/IVDiagnosticsCard";
import {
  DIDDiagnosticsCard,
  type DIDDiagnostics,
} from "./runResult/DIDDiagnosticsCard";
import {
  CSDiagnosticsCard,
  type CSDiagnosticsData,
} from "./runResult/CSDiagnosticsCard";
import {
  DCDHResultCard,
  type DCDHResult,
} from "./runResult/DCDHResultCard";
import {
  ImputationSummary,
  type ImputationSummaryData,
} from "./runResult/ImputationSummary";
import {
  PredictionResultCard,
  type PredictionResultData,
} from "./runResult/PredictionResultCard";
import { PacketPanel } from "./workbench/repeatedMeasures/PacketPanel";
import { ArmaGarchDashboard } from "./runResult/ArmaGarchDashboard";
import { useArmaGarchArtifacts } from "./runResult/useArmaGarchArtifacts";
import { useArmaGarchCharts } from "./runResult/useArmaGarchCharts";

/** Stable identity so the loader effects do not re-run on every render. */
const NO_GROUPS: ArtifactGroup[] = [];

type Props = {
  projectRoot: string;
  runId: string;
  onError: (message: string) => void;
  // V1.5.4.1: invoked when the user clicks a recovery action on the
  // FailureCard (e.g. "Re-run with auto"). The parent (App.tsx) owns form
  // state and applies the action's form_overrides.
  onFailureAction?: (
    action: RecommendedAction,
    evidence: Record<string, unknown>,
  ) => void;
};

function statusBadgeClass(status: string): string {
  if (status === "completed") return "badge badge-ok";
  if (status === "blocked" || status === "failed") return "badge badge-warn";
  return "badge badge-neutral";
}

function statusLabel(status: string): string {
  if (!status) return "—";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function formatNumber(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(4)
    : "—";
}

function formatPValue(
  value: number | null | undefined,
  display: string | null | undefined,
): string {
  if (display) return display;
  return formatNumber(value);
}

function coefficientRows(detail: RunDetail) {
  return (detail.model_results ?? []).flatMap((model) =>
    Object.entries(model.coefficients ?? {})
      .filter(([term]) => term !== "Intercept" && !term.startsWith("C("))
      .map(([term, coefficient]) => ({
        modelId: model.model_id,
        term,
        estimate: coefficient.estimate,
        stdError: coefficient.std_error,
        pValue: coefficient.p_value,
        pValueDisplay: coefficient.p_value_display,
      })),
  );
}

function normalizeIssues(detail: RunDetail): IssueRecord[] {
  const issues = detail.errors?.issues ?? [];
  const dummyCodedColumns = dummyCodedColumnsFromModels(detail);
  if (dummyCodedColumns.size === 0) return issues;

  const normalized: IssueRecord[] = [];
  const emitted = new Set<string>();
  for (const issue of issues) {
    const column =
      typeof issue.evidence?.column === "string" ? issue.evidence.column : null;
    if (issue.code === "CATEGORICAL_CANDIDATE" && column && dummyCodedColumns.has(column)) {
      if (!emitted.has(column)) {
        normalized.push(autoDummyCodedIssue(column));
        emitted.add(column);
      }
      continue;
    }
    normalized.push(issue);
  }

  for (const column of dummyCodedColumns) {
    const alreadyPresent = normalized.some(
      (issue) =>
        issue.code === "CATEGORICAL_AUTO_DUMMY_CODED" &&
        issue.evidence?.column === column,
    );
    if (!alreadyPresent && !emitted.has(column)) {
      normalized.push(autoDummyCodedIssue(column));
    }
  }
  return normalized;
}

function dummyCodedColumnsFromModels(detail: RunDetail): Set<string> {
  const columns = new Set<string>();
  for (const model of detail.model_results ?? []) {
    for (const term of Object.keys(model.coefficients ?? {})) {
      const parsed = parseDummyCodedColumn(term);
      if (parsed) columns.add(parsed);
    }
  }
  return columns;
}

function parseDummyCodedColumn(term: string): string | null {
  const single = /^C\(Q\('(.+?)'\)\)\[T\./.exec(term);
  if (single) return single[1];
  const double = /^C\(Q\("(.+?)"\)\)\[T\./.exec(term);
  return double?.[1] ?? null;
}

function autoDummyCodedIssue(column: string): IssueRecord {
  return {
    severity: "INFO",
    code: "CATEGORICAL_AUTO_DUMMY_CODED",
    message: `Column '${column}' was detected as categorical and automatically dummy-coded.`,
    evidence: { column, preprocessing: "dummy_coded" },
    affected_stage: "data_cleaning",
    variables: [column],
    template_key: "categorical_auto_dummy",
  };
}

type ArtifactsState =
  | { status: "loading" }
  | { status: "loaded"; groups: ArtifactGroup[] }
  | { status: "error"; message: string };

type StepStatus = "pending" | "running" | "completed" | "blocked";
type StepProgress = { step: string; label: string; status: StepStatus };

const PROGRESS_STEPS: StepProgress[] = [
  { step: "ingestion", label: "Ingestion", status: "pending" },
  { step: "schema", label: "Schema", status: "pending" },
  { step: "cleaning", label: "Cleaning", status: "pending" },
  { step: "profiling", label: "Profiling", status: "pending" },
  { step: "validation", label: "Validation", status: "pending" },
  { step: "routing", label: "Routing", status: "pending" },
  { step: "model_check", label: "Model check", status: "pending" },
  { step: "y_type", label: "Y type detection", status: "pending" },
  { step: "statistical_tests", label: "Statistical tests", status: "pending" },
  { step: "estimation", label: "Estimation", status: "pending" },
  { step: "visualization", label: "Visualization", status: "pending" },
  { step: "narrative", label: "Narrative", status: "pending" },
  { step: "reporting", label: "Reporting", status: "pending" },
  { step: "export", label: "Export", status: "pending" },
];

export function RunResultView({ projectRoot, runId, onError, onFailureAction }: Props) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [artifactsState, setArtifactsState] = useState<ArtifactsState>({
    status: "loading",
  });
  const [showReport, setShowReport] = useState(false);
  const [progressSteps, setProgressSteps] =
    useState<StepProgress[]>(PROGRESS_STEPS);
  const [isLive, setIsLive] = useState(false);
  const [imputationData, setImputationData] = useState<
    ImputationSummaryData | undefined
  >();
  const [predictionResult, setPredictionResult] = useState<
    PredictionResultData | undefined
  >(undefined);
  const [ivDiagnostics, setIvDiagnostics] = useState<IVDiagnostics | undefined>(
    undefined,
  );
  const [didDiagnostics, setDidDiagnostics] = useState<
    DIDDiagnostics | undefined
  >(undefined);
  const [csDiagnostics, setCsDiagnostics] = useState<
    CSDiagnosticsData | undefined
  >(undefined);
  const [dcdhResult, setDcdhResult] = useState<DCDHResult | undefined>(undefined);
  // The graph node drawer and this page read the pack's artifacts through the
  // same hooks, so there is one loader and one rendering of a time-series result.
  // Empty (not undefined) while the listing loads: undefined would tell the
  // hooks to list the run themselves, duplicating a request this page owns.
  const loadedGroups = artifactsState.status === "loaded" ? artifactsState.groups : NO_GROUPS;
  const armaGarchArtifacts = useArmaGarchArtifacts(projectRoot, runId, loadedGroups);
  const armaGarchCharts = useArmaGarchCharts(projectRoot, runId, loadedGroups);
  const fetchIdRef = useRef(0);

  const fetchArtifacts = useCallback(() => {
    const id = ++fetchIdRef.current;
    setArtifactsState({ status: "loading" });
    fetchRunArtifacts(projectRoot, runId)
      .then((value) => {
        if (id !== fetchIdRef.current) return;
        setArtifactsState({ status: "loaded", groups: value.groups });
      })
      .catch((error) => {
        if (id !== fetchIdRef.current) return;
        const message =
          error instanceof ApiError
            ? `[${error.code ?? `HTTP ${error.status}`}] ${error.message}`
            : error instanceof Error
              ? error.message
              : "Unknown error";
        setArtifactsState({ status: "error", message });
      });
  }, [projectRoot, runId]);

  // V1.5.4.1: when the run produced an imputation_summary artifact, fetch
  // its JSON to render the ImputationSummary panel. Presence is detected
  // from the already-loaded artifacts list (RunDetail has no artifacts field).
  useEffect(() => {
    if (artifactsState.status !== "loaded") return;
    const present = artifactsState.groups.some((g) =>
      g.items.some((it) => it.artifact_id === "imputation_summary"),
    );
    if (!present) {
      setImputationData(undefined);
      return;
    }
    let cancelled = false;
    fetchArtifactJson<ImputationSummaryData>(projectRoot, runId, "imputation_summary")
      .then((data) => {
        if (!cancelled) setImputationData(data);
      })
      .catch(() => {
        if (!cancelled) setImputationData(undefined);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, artifactsState]);

  // V1.5.4.2: when the run produced a prediction_result artifact (model_id like
  // `prediction_ridge_1`), fetch its JSON to render the PredictionResultCard.
  // Mirrors the imputation_summary wiring above.
  useEffect(() => {
    if (artifactsState.status !== "loaded") return;
    const predId = artifactsState.groups
      .flatMap((g) => g.items)
      .map((it) => it.artifact_id)
      .find((id) => /^prediction_.*_1$/.test(id));
    if (!predId) {
      setPredictionResult(undefined);
      return;
    }
    let cancelled = false;
    fetchArtifactJson<PredictionResultData>(projectRoot, runId, predId)
      .then((data) => {
        if (!cancelled) setPredictionResult(data);
      })
      .catch(() => {
        if (!cancelled) setPredictionResult(undefined);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, artifactsState]);

  // V1.5.4.4: when the run produced an iv_diagnostics artifact (IV/2SLS runs),
  // fetch its JSON to render the IVDiagnosticsCard. Mirrors the wiring above.
  useEffect(() => {
    if (artifactsState.status !== "loaded") return;
    const present = artifactsState.groups.some((g) =>
      g.items.some((it) => it.artifact_id === "iv_diagnostics"),
    );
    if (!present) {
      setIvDiagnostics(undefined);
      return;
    }
    let cancelled = false;
    fetchArtifactJson<IVDiagnostics>(projectRoot, runId, "iv_diagnostics")
      .then((data) => {
        if (!cancelled) setIvDiagnostics(data);
      })
      .catch(() => {
        if (!cancelled) setIvDiagnostics(undefined);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, artifactsState]);

  // V1.5.5: when the run produced a did_diagnostics artifact (DID runs),
  // fetch its JSON to render the DIDDiagnosticsCard. Mirrors the IV wiring.
  useEffect(() => {
    if (artifactsState.status !== "loaded") return;
    const present = artifactsState.groups.some((g) =>
      g.items.some((it) => it.artifact_id === "did_diagnostics"),
    );
    if (!present) {
      setDidDiagnostics(undefined);
      return;
    }
    let cancelled = false;
    fetchArtifactJson<DIDDiagnostics>(projectRoot, runId, "did_diagnostics")
      .then((data) => {
        if (!cancelled) setDidDiagnostics(data);
      })
      .catch(() => {
        if (!cancelled) setDidDiagnostics(undefined);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, artifactsState]);

  // V1.5.6: when the run produced a cs_did artifact (Callaway-Sant'Anna runs),
  // fetch its JSON to render the CSDiagnosticsCard. Mirrors the DID wiring.
  // V1.5.8: Sun-Abraham (sa_did) writes the SAME artifact shape (dynamic event
  // study + nested honest_did {rm,sd}); the only difference is metadata.estimator.
  // Reuse the same card + state — detect whichever id is present and fetch it.
  useEffect(() => {
    if (artifactsState.status !== "loaded") return;
    const artifactId = artifactsState.groups
      .flatMap((g) => g.items)
      .map((it) => it.artifact_id)
      .find((id) => id === "cs_did" || id === "sa_did");
    if (!artifactId) {
      setCsDiagnostics(undefined);
      return;
    }
    let cancelled = false;
    fetchArtifactJson<CSDiagnosticsData>(projectRoot, runId, artifactId)
      .then((data) => {
        if (!cancelled) setCsDiagnostics(data);
      })
      .catch(() => {
        if (!cancelled) setCsDiagnostics(undefined);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, artifactsState]);

  // V1.5.9: de Chaisemartin-D'Haultfoeuille (dcdh) writes a dcdh.json artifact
  // with the EventStudyBundle-shaped result (different contract from cs/sa).
  useEffect(() => {
    if (artifactsState.status !== "loaded") return;
    const present = artifactsState.groups
      .flatMap((g) => g.items)
      .some((it) => it.artifact_id === "dcdh");
    if (!present) {
      setDcdhResult(undefined);
      return;
    }
    let cancelled = false;
    fetchArtifactJson<DCDHResult>(projectRoot, runId, "dcdh")
      .then((data) => {
        if (!cancelled) setDcdhResult(data);
      })
      .catch(() => {
        if (!cancelled) setDcdhResult(undefined);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, artifactsState]);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    fetchRunDetail(projectRoot, runId)
      .then((value) => {
        if (cancelled) return;
        setDetail(value);
      })
      .catch((error) => {
        if (cancelled) return;
        const message =
          error instanceof ApiError
            ? `[${error.code ?? `HTTP ${error.status}`}] ${error.message}`
            : error instanceof Error
              ? error.message
              : "Failed to load run detail";
        onError(message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, onError]);

  useEffect(() => {
    fetchArtifacts();
    return () => {
      fetchIdRef.current += 1;
    };
  }, [fetchArtifacts]);

  useEffect(() => {
    if (!detail || detail.status !== "running") return;
    setIsLive(true);

    const cleanup = connectRunEvents(projectRoot, runId, {
      onStepStart: (step) => {
        setProgressSteps((prev) =>
          prev.map((s) => (s.step === step ? { ...s, status: "running" } : s)),
        );
      },
      onStepComplete: (step) => {
        setProgressSteps((prev) =>
          prev.map((s) =>
            s.step === step ? { ...s, status: "completed" } : s,
          ),
        );
      },
      onStepBlocked: (step) => {
        setProgressSteps((prev) =>
          prev.map((s) => (s.step === step ? { ...s, status: "blocked" } : s)),
        );
      },
      onTerminal: () => {
        setIsLive(false);
        fetchRunDetail(projectRoot, runId).then(setDetail).catch(() => {});
        fetchArtifacts();
      },
      onError: () => {
        setIsLive(false);
      },
    });
    return cleanup;
  }, [detail?.status, projectRoot, runId, fetchArtifacts]);

  if (detail === null) {
    return <p className="muted">Loading run…</p>;
  }

  const rawPreview = detail.diagnostic_summary_preview;
  const validation = rawPreview === undefined
    ? { valid: true as const, data: undefined }
    : validateDiagnosticPreview(rawPreview);

  if (validation.valid === false) {
    if (typeof console !== "undefined") {
      console.error("[runResult] diagnostic_summary_preview failed validation:", validation.errors);
    }
  }

  const preview = validation.valid === true ? validation.data : undefined;
  const hasPreview = preview?.available === true;
  const previewInvalid = validation.valid === false;

  // Backend normalizes CATEGORICAL_CANDIDATE→AUTO_DUMMY in _normalize_issue_stream.
  // Frontend normalizeIssues is legacy fallback for old backends without preview.
  const issues: IssueRecord[] = hasPreview
    ? (detail.errors?.issues ?? [])
    : normalizeIssues(detail);
  const problemIssues = issues.filter((issue) => issue.severity === "BLOCKER");
  // V1.5.4.1: surface a structured FailureCard for explicit model-fit
  // failures. Evidence is serialized under `evidence` (GuardrailIssue.to_dict),
  // NOT `details` — same key the slice-2d invariant test locks.
  const fitFailure = problemIssues.find((i) => i.code === "MODEL_FIT_FAILED");
  const failureEvidence = (fitFailure?.evidence ?? {}) as Record<string, unknown>;
  const hasFailureCard = detail.status === "failed" && fitFailure !== undefined;
  const warningIssues = issues.filter((issue) => issue.severity === "WARNING");
  const cautionIssues = issues.filter((issue) => issue.severity === "CAUTION");
  const infoIssues = issues.filter((issue) => issue.severity === "INFO");
  const coefficients = coefficientRows(detail);

  // P0-1: Extract coefficient risk — primary model, non-empty groups only
  const coefficientRisk: CoefficientRisk | undefined = preview?.coefficient_risk as CoefficientRisk | undefined;
  const primaryModel = coefficientRisk?.models?.find((m) => m.is_primary);
  const riskGroups = primaryModel?.risk_groups?.filter((g) => g.terms.length > 0) ?? [];

  // P0-3: Report gating — browser never infers availability.
  // V1.3.1 preview: require explicit artifact_manifest.report_html.available === true.
  // Legacy (no preview): fall back to artifact_counts.report > 0.
  const reportAvailable = hasPreview
    ? (preview!.artifact_manifest as Record<string, {available?: boolean}> | undefined)
        ?.report_html?.available === true
    : (detail.artifact_counts?.report ?? 0) > 0;
  const reportManifestMissing = hasPreview && (
    !preview?.artifact_manifest ||
    !(preview.artifact_manifest as Record<string, unknown>).report_html
  );
  const reportBlocked = hasPreview && preview?.run_status?.status === "blocked";
  const reportDisabled = !reportAvailable || (hasPreview && preview?.run_status?.status === "failed");

  // P0-2: Top 1-3 restrictions and actions
  const restrictions = (preview?.interpretation_restrictions ?? []) as Array<{
    restriction_type: string; severity: string; message: string;
  }>;
  const actions = (preview?.recommended_actions ?? []) as Array<{
    action_key: string; severity: string; message: string;
  }>;

  return (
    <section className="result-panel" aria-labelledby="run-detail-heading">
      <div className="panel-heading">
        <h2 id="run-detail-heading">Run detail</h2>
        <span className={statusBadgeClass(detail.status)}>
          {statusLabel(detail.status)}
        </span>
      </div>
      {hasFailureCard && (
        <FailureCard
          evidence={failureEvidence as never}
          onAction={(action) => onFailureAction?.(action, failureEvidence)}
        />
      )}
      <ImputationSummary summary={imputationData} />
      <PredictionResultCard result={predictionResult} />
      <IVDiagnosticsCard diagnostics={ivDiagnostics} />
      <DIDDiagnosticsCard diagnostics={didDiagnostics} />
      <CSDiagnosticsCard diagnostics={csDiagnostics} />
      <DCDHResultCard result={dcdhResult} />
      <ArmaGarchDashboard artifacts={armaGarchArtifacts} charts={armaGarchCharts} />
      {(detail.model_results ?? [])
        .filter((result) => result.model_type === "linear_mixed_effects")
        .map((result) => (
          <PacketPanel key={result.model_id} result={result} />
        ))}
      {isLive && (
        <section className="progress-panel" aria-label="run progress">
          <h3 className="subhead">Progress</h3>
          <ol className="progress-list">
            {progressSteps.map((s) => (
              <li key={s.step} className={`progress-step ${s.status}`}>
                <span className={`progress-dot ${s.status}`} />
                {s.label}
              </li>
            ))}
          </ol>
        </section>
      )}

      <dl className="summary-list">
        <div>
          <dt>Run ID</dt>
          <dd className="mono">{detail.run_id}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <span className={statusBadgeClass(detail.status)}>
              {statusLabel(detail.status)}
            </span>
          </dd>
        </div>
        <div>
          <dt>Mode</dt>
          <dd>{detail.mode ?? "—"}</dd>
        </div>
        <div>
          <dt>Started</dt>
          <dd>{detail.started_at ?? "—"}</dd>
        </div>
        <div>
          <dt>Y</dt>
          <dd>{detail.y ?? "—"}</dd>
        </div>
        <div>
          <dt>X</dt>
          <dd>{(detail.x ?? []).join(", ") || "—"}</dd>
        </div>
      </dl>
      {hasPreview && preview && (
        <section className="trust-summary" aria-label="trust status">
          <div className={`trust-bar trust-${preview.trust_label}`}>
            <strong>
              {preview.trust_label === "ready_to_interpret" && "Ready to interpret"}
              {preview.trust_label === "interpret_with_caution" && "Interpret with caution"}
              {preview.trust_label === "not_ready_to_interpret" && "Not ready to interpret"}
              {preview.trust_label === "run_failed" && "Run failed"}
              {preview.trust_label === "analysis_running" && "Analysis running"}
              {!["ready_to_interpret", "interpret_with_caution", "not_ready_to_interpret", "run_failed", "analysis_running"].includes(preview.trust_label) && "Trust status unavailable"}
            </strong>
            {preview.trust_counts && (
              <span className="trust-counts">
                {preview.trust_counts.blockers > 0 && <span className="count-blocker">{preview.trust_counts.blockers} blocking</span>}
                {preview.trust_counts.warnings > 0 && <span className="count-warning">{preview.trust_counts.warnings} warnings</span>}
                {preview.trust_counts.cautions > 0 && <span className="count-caution">{preview.trust_counts.cautions} cautions</span>}
                {preview.trust_counts.info > 0 && <span className="count-info">{preview.trust_counts.info} notes</span>}
              </span>
            )}
          </div>
          {preview.primary_reasons.length > 0 && (
            <div className="trust-reasons">
              {preview.primary_reasons.map((r) => (
                <div key={r.reason_id} className={`reason reason-${r.severity.toLowerCase()}`}>
                  <strong>{r.severity}</strong>: {r.message}
                </div>
              ))}
            </div>
          )}
          {preview.model_identity && (
            <div className="trust-model-id">
              {preview.model_identity.model_label} · y = {preview.model_identity.y_variable} · n = {preview.model_identity.n_observations}
            </div>
          )}
        </section>
      )}
      {previewInvalid && (
        <section className="trust-summary trust-summary-error">
          <p>Invalid diagnostic data — see browser console for details.</p>
        </section>
      )}
      {!hasPreview && !previewInvalid && detail.diagnostic_summary_preview && (
        <section className="panel panel-neutral" aria-label="trust unavailable">
          <strong>Trust preview unavailable</strong>
          <p>{(detail.diagnostic_summary_preview.contract_warnings ?? []).join("; ") || "Diagnostic summary could not be loaded. Showing legacy results below."}</p>
        </section>
      )}
      {hasPreview && riskGroups.length > 0 && (
        <section className="coefficient-risk" aria-label="coefficient risk">
          <h3 className="subhead">Coefficient risk</h3>
          {riskGroups.map((group) => (
            <div key={group.variable} className={`risk-group risk-${group.risk_level.toLowerCase()}`}>
              <div className="risk-group-header">
                <strong>{group.display_name}</strong>
                <span className={`risk-badge badge-${group.risk_level.toLowerCase()}`}>{group.variable_kind}</span>
                <span className="risk-level">{group.risk_level}</span>
              </div>
              {group.summary && <p className="risk-summary">{group.summary}</p>}
              {group.terms.length > 0 && (
                <table className="risk-terms-table">
                  <thead><tr><th>Level</th><th>Reference</th><th>Estimate</th><th>p-value</th></tr></thead>
                  <tbody>
                    {group.terms.map((t) => (
                      <tr key={t.source_id}>
                        <td>{t.display_term}</td>
                        <td>{t.reference_level ?? "—"}</td>
                        <td>{formatNumber(t.estimate)}</td>
                        <td>{formatNumber(t.p_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </section>
      )}
      {hasPreview && (restrictions.length > 0 || actions.length > 0) && (
        <section className="interpretation-guidance" aria-label="interpretation guidance">
          <h3 className="subhead">Interpretation guidance</h3>
          {restrictions.slice(0, 3).map((r, i) => (
            <div key={`restriction-${i}`} className={`restriction restriction-${r.severity.toLowerCase()}`}>
              <strong>Do not</strong>: {r.message}
            </div>
          ))}
          {actions.slice(0, 3).map((a, i) => (
            <div key={`action-${i}`} className={`action action-${a.severity.toLowerCase()}`}>
              <strong>Recommended</strong>: {a.message}
            </div>
          ))}
        </section>
      )}
      <h3 className="subhead">Artifact counts</h3>
      <ul className="path-list" aria-label="artifact counts">
        {Object.entries(detail.artifact_counts).map(([type, count]) => (
          <li key={type} className="mono">
            {type}: {count}
          </li>
        ))}
      </ul>
      {coefficients.length > 0 && (
        <section aria-labelledby="coefficients-heading">
          <h3 id="coefficients-heading" className="subhead">
            Coefficients
          </h3>
          <div className="coefficients-table-wrap">
            <table className="coefficients-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Term</th>
                  <th>Estimate</th>
                  <th>Std. error</th>
                  <th>p-value</th>
                </tr>
              </thead>
              <tbody>
                {coefficients.map((row) => (
                  <tr key={`${row.modelId}:${row.term}`}>
                    <td>{row.modelId}</td>
                    <td>{row.term}</td>
                    <td>{formatNumber(row.estimate)}</td>
                    <td>{formatNumber(row.stdError)}</td>
                    <td>{formatPValue(row.pValue, row.pValueDisplay)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {problemIssues.length > 0 && (
        <section className="panel panel-error" role="alert">
          <strong>Issues</strong>
          <ul>
            {problemIssues.map((issue, index) => (
              <li key={index}>
                <strong>{issue.code ?? "ISSUE"}</strong>:{" "}
                <span>{issue.message ?? ""}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {warningIssues.length > 0 && (
        <section className="panel" aria-label="warnings">
          <strong>Warnings</strong>
          <ul>
            {warningIssues.map((issue, index) => (
              <li key={index}>
                <strong>{issue.code ?? "WARNING"}</strong>:{" "}
                <span>{issue.message ?? ""}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {cautionIssues.length > 0 && (
        <section className="panel" aria-label="cautions">
          <strong>Interpretation cautions</strong>
          <ul>
            {cautionIssues.map((issue, index) => (
              <li key={index}>
                <strong>{issue.code ?? "CAUTION"}</strong>:{" "}
                <span>{issue.message ?? ""}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {infoIssues.length > 0 && (
        <section className="panel" aria-label="diagnostics">
          <strong>System notes</strong>
          <ul>
            {infoIssues.map((issue, index) => (
              <li key={index}>
                <strong>{issue.code ?? "INFO"}</strong>:{" "}
                <span>{issue.message ?? ""}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section aria-labelledby="report-heading">
        <h3 id="report-heading" className="subhead">
          Report
        </h3>
        {reportManifestMissing && (
          <p className="report-warning">Report availability cannot be verified — artifact manifest is incomplete. Viewing may show partial or legacy output.</p>
        )}
        {reportBlocked && (
          <p className="report-warning">Blocking issues detected. Report is available for review but should not be treated as formal output.</p>
        )}
        {!reportAvailable && (
          <p className="report-warning">Report artifact is not available for this run.</p>
        )}
        <button
          type="button"
          onClick={() => setShowReport((value) => !value)}
          disabled={reportDisabled}
        >
          {reportDisabled ? "Report unavailable" : showReport ? "Hide report" : "View report"}
        </button>
        {reportAvailable && (
          <a
            className="report-link"
            href={reportUrl(projectRoot, runId)}
            target="_blank"
            rel="noreferrer"
          >
            Open in new tab
          </a>
        )}
        {showReport && reportAvailable && (
          <iframe
            title="Run report"
            src={reportUrl(projectRoot, runId)}
            className="report-frame"
            sandbox="allow-same-origin"
          />
        )}
      </section>
      <section aria-labelledby="artifacts-heading">
        <h3 id="artifacts-heading" className="subhead">
          Artifacts
        </h3>
        {artifactsState.status === "loading" && (
          <p className="muted">Loading artifacts…</p>
        )}
        {artifactsState.status === "loaded" &&
          artifactsState.groups.length === 0 && (
            <p className="muted">No artifacts recorded.</p>
          )}
        {artifactsState.status === "loaded" &&
          artifactsState.groups.length > 0 &&
          artifactsState.groups.map((group) => (
            <div key={group.artifact_type} className="artifact-group">
              <h4>{group.artifact_type}</h4>
              <ul>
                {group.items.map((item) => (
                  <li key={item.artifact_id}>
                    <a
                      href={artifactDownloadUrl(
                        projectRoot,
                        runId,
                        item.artifact_id,
                      )}
                    >
                      {item.artifact_id}
                    </a>
                    <span className="mono"> · {item.path}</span>
                    <span className="muted"> · {item.step}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        {artifactsState.status === "error" && (
          <div className="panel panel-error" role="alert">
            <p>Failed to load artifacts: {artifactsState.message}</p>
            <button type="button" onClick={fetchArtifacts}>
              Retry
            </button>
          </div>
        )}
      </section>
    </section>
  );
}
