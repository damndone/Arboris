import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  compileNotebookCutover,
  confirmCutover,
  executeCutover,
  getCutoverIdentity,
  isRetryableCutoverError,
  type CutoverBindingV1,
  type CutoverConfirmationV1,
  type CutoverIdentityV1,
  type CutoverPreviewV1,
  type CutoverExecutionResultV1,
} from "../cutoverApi";
import {
  ensureNotebookProjection,
  getNotebook,
  listNotebooks,
  updateNotebookFocus,
  type NotebookInteractionMode,
  type NotebookRecord,
} from "./notebookApi";
import {
  listDomainMemoryCandidates,
  reviewDomainMemoryCandidate as reviewDomainMemoryCandidateApi,
} from "./domainMemoryApi";
import { DomainMemoryReviewQueue } from "./DomainMemoryReviewQueue";
import type { DomainMemoryCandidate } from "./domainMemoryContracts";

import "./notebook.css";

type NotebookError = Error & { code?: string | null; status?: number };
type BusyPhase = "compiling" | "clarifying" | "confirming" | "executing" | null;

interface ClarificationField {
  code: string;
  field: string;
  message: string;
  allowedValues: string[];
}

interface NotebookTaskHistory {
  request: string;
  status: string;
}

const FIELD_LABELS: Record<string, string> = {
  capability_id: "Capability",
  target_ref: "Target",
  data_snapshot_ref: "Data snapshot",
  data_snapshot_digest: "Data snapshot digest",
  requested_effect: "Requested effect",
  sensitivity: "Sensitivity",
  analysis_mode: "Analysis mode",
  structure: "Data structure",
  time_scope: "Time scope",
  entity_scope: "Entity scope",
  positive_class: "Positive class",
  metric: "Metric",
};

const CLOSED_FIELD_VALUES: Record<string, string[]> = {
  requested_effect: ["none", "read", "write", "model_fit", "model_predict", "report"],
  sensitivity: ["public", "internal", "sensitive", "unknown"],
};

function errorText(error: unknown): string {
  const candidate = error as NotebookError | null;
  const code = typeof candidate?.code === "string" ? candidate.code : null;
  const message = error instanceof Error ? error.message : "Notebook cutover request failed";
  return code ? `${code}: ${message}` : message;
}

function isNotFound(error: unknown): boolean {
  const candidate = error as NotebookError | null;
  return candidate?.code === "NOTEBOOK_NOT_FOUND";
}

function fieldLabel(field: string): string {
  const known = FIELD_LABELS[field];
  if (known) return known;
  const words = field.replace(/[_-]+/g, " ").trim();
  return words ? `${words.charAt(0).toUpperCase()}${words.slice(1)}` : "Additional information";
}

function primitiveText(value: unknown): string {
  if (value === null || value === undefined) return "Not provided";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") return value || "Empty";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "Invalid number";
  return "Unsupported value";
}

function cutoverScopeKey(projectRoot: string, notebookId: string | null): string {
  const notebookPart = notebookId === null ? "none" : `${notebookId.length}:${notebookId}`;
  return `${projectRoot.length}:${projectRoot}|${notebookPart}`;
}

function memoryModeStorageKey(projectRoot: string, notebookId: string): string {
  return `workbench:notebook:interaction-mode:${projectRoot}:${notebookId}`;
}

function readStoredInteractionMode(projectRoot: string, notebookId: string): NotebookInteractionMode | null {
  try {
    const value = globalThis.localStorage?.getItem(memoryModeStorageKey(projectRoot, notebookId));
    return value === "plan" || value === "action" ? value : null;
  } catch {
    return null;
  }
}

function writeStoredInteractionMode(projectRoot: string, notebookId: string, mode: NotebookInteractionMode): void {
  try {
    globalThis.localStorage?.setItem(memoryModeStorageKey(projectRoot, notebookId), mode);
  } catch {
    // A restricted browser storage context must not block the server-owned mode.
  }
}

function persistedInteractionMode(
  notebook: NotebookRecord,
  projectRoot: string,
  fallback: NotebookInteractionMode = "plan",
): NotebookInteractionMode {
  const value = notebook.user_focus?.interaction_mode;
  if (value === "plan" || value === "action") return value;
  return readStoredInteractionMode(projectRoot, notebook.notebook_id) ?? fallback;
}

type ServerAuditRecord = Record<string, unknown>;

function recordValue(value: unknown): ServerAuditRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as ServerAuditRecord
    : {};
}

function recordArray(value: unknown): ServerAuditRecord[] {
  return Array.isArray(value)
    ? value.filter((item): item is ServerAuditRecord => (
      item !== null && typeof item === "object" && !Array.isArray(item)
    ))
    : [];
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

function serverAuditFor(
  preview: CutoverPreviewV1 | null,
  result: CutoverExecutionResultV1 | null,
): {
  lifecycle: ServerAuditRecord[];
  omissions: ServerAuditRecord[];
  evidence: string[];
} {
  const planDiff = recordValue(preview?.plan_diff);
  const planAudit = recordValue(planDiff.audit);
  const resultAudit = recordValue(result?.result);
  const lifecycle = recordArray(planAudit.lifecycle ?? planDiff.lifecycle ?? resultAudit.lifecycle);
  const omissions = recordArray(planAudit.omissions ?? planDiff.omissions ?? resultAudit.omissions);
  const evidence = Array.from(new Set([
    ...stringArray(planAudit.evidence ?? planDiff.evidence ?? resultAudit.evidence),
    ...(result?.evidence_refs ?? []),
  ]));
  return { lifecycle, omissions, evidence };
}

function ServerAuditDetails({
  preview,
  result,
}: {
  preview: CutoverPreviewV1 | null;
  result: CutoverExecutionResultV1 | null;
}) {
  const audit = serverAuditFor(preview, result);
  return (
    <section className="nb-context-slice nb-cutover-audit" data-testid="notebook-cutover-audit">
      <details className="nb-context-details" data-testid="context-evidence-details">
        <summary data-testid="context-evidence-summary">
          <span>
            <span className="nb-label">Evidence and audit details</span>
            <span>{` · ${audit.lifecycle.length} recorded events · ${audit.omissions.length} omitted items`}</span>
          </span>
          <span className="nb-context-summary-action">Show full evidence</span>
        </summary>
        <div className="nb-context-details-body">
          <header className="nb-context-header">
            <span className="nb-label">Server-published audit</span>
            <span>Lifecycle, evidence references, and omissions only</span>
          </header>
          <div className="nb-cutover-audit-group">
            <span className="nb-label">Recorded events</span>
            {audit.lifecycle.length > 0 ? (
              <ol>
                {audit.lifecycle.map((event, index) => (
                  <li key={`${String(event.event_id ?? index)}-${index}`}>
                    <strong>{String(event.event_type ?? "server event")}</strong>
                    <span>{String(event.summary ?? "Recorded server lifecycle event")}</span>
                    {event.occurred_at ? <small>{String(event.occurred_at)}</small> : null}
                  </li>
                ))}
              </ol>
            ) : <p className="nb-empty">No lifecycle events were returned yet.</p>}
          </div>
          <div className="nb-cutover-audit-group">
            <span className="nb-label">Omissions</span>
            {audit.omissions.length > 0 ? (
              <ul>
                {audit.omissions.map((omission, index) => (
                  <li key={`${String(omission.section ?? index)}-${index}`}>
                    {`${String(omission.section ?? "server context")} · ${String(omission.reason ?? "omitted by server")}`}
                    {omission.omitted_count !== undefined ? ` · ${String(omission.omitted_count)} omitted` : ""}
                  </li>
                ))}
              </ul>
            ) : <p className="nb-empty">No omissions were returned by the server.</p>}
          </div>
          <div className="nb-cutover-audit-group">
            <span className="nb-label">Evidence references</span>
            {audit.evidence.length > 0 ? (
              <ul>{audit.evidence.map((reference) => <li key={reference}>{reference}</li>)}</ul>
            ) : <p className="nb-empty">No evidence references were returned yet.</p>}
          </div>
        </div>
      </details>
    </section>
  );
}

function StructuredPlanValue({ value, path }: { value: unknown; path: string }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="nb-plan-empty">None</span>;
    return (
      <ul className="nb-plan-list">
        {value.map((item, index) => (
          <li key={`${path}-${index}`}>
            <StructuredPlanValue value={item} path={`${path}-${index}`} />
          </li>
        ))}
      </ul>
    );
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="nb-plan-empty">None</span>;
    return (
      <dl className="nb-plan-grid nb-plan-grid-nested">
        {entries.map(([key, child]) => (
          <div className="nb-plan-row" key={`${path}-${key}`}>
            <dt>{fieldLabel(key)}</dt>
            <dd>
              <StructuredPlanValue value={child} path={`${path}-${key}`} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span className="nb-plan-value">{primitiveText(value)}</span>;
}

function clarificationFields(preview: CutoverPreviewV1 | null): ClarificationField[] {
  const fields = new Map<string, ClarificationField>();
  for (const item of preview?.clarifications ?? []) {
    const field = typeof item.field === "string" ? item.field.trim() : "";
    if (!field) continue;
    const message = typeof item.message === "string" && item.message.trim()
      ? item.message
      : "The server needs this field before it can compile a plan.";
    const code = typeof item.code === "string" ? item.code : "missing_required_information";
    const allowedValues = Array.isArray(item.allowed_values)
      ? item.allowed_values.filter((value): value is string => typeof value === "string" && value.length > 0)
      : [];
    const existing = fields.get(field);
    if (existing) {
      if (!existing.message.includes(message)) existing.message = `${existing.message} ${message}`;
      existing.allowedValues = Array.from(new Set([...existing.allowedValues, ...allowedValues]));
    } else {
      fields.set(field, { code, field, message, allowedValues });
    }
  }
  return Array.from(fields.values());
}

function phaseLabel(
  phase: BusyPhase,
  notebookLoading: boolean,
  identityLoading: boolean,
  notebook: NotebookRecord | null,
  identity: CutoverIdentityV1 | null,
  preview: CutoverPreviewV1 | null,
  binding: CutoverBindingV1 | null,
  result: CutoverExecutionResultV1 | null,
  hasSetupError: boolean,
): string {
  if (phase === "compiling") return "Compiling server plan";
  if (phase === "clarifying") return "Recompiling server plan with clarification answers";
  if (phase === "confirming") return "Requesting server confirmation";
  if (phase === "executing") return "Executing confirmed plan";
  if (notebookLoading || identityLoading) return "Loading Notebook and server identity";
  if (result) return "Execution completed with server evidence";
  if (binding) return "Plan ready for confirmation";
  if ((preview?.clarifications.length ?? 0) > 0) return "Clarification required before confirmation";
  if (preview) return "Server preview has no executable binding";
  if (hasSetupError) return "Setup needs attention — your draft is preserved";
  if (notebook && identity) return "Ready for a natural-language task";
  return "Select a Notebook and resolve server identity to compile";
}

export function NotebookCutoverView({
  projectRoot,
  activeRunId,
}: {
  projectRoot: string;
  activeRunId?: string | null;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedNotebookId = searchParams.get("notebook");
  const searchValue = searchParams.toString();
  const currentScopeKey = cutoverScopeKey(projectRoot, requestedNotebookId);
  const currentScopeKeyRef = useRef(currentScopeKey);
  const renderedScopeKeyRef = useRef(currentScopeKey);
  const scopeEpochRef = useRef(0);
  const intentEpochRef = useRef(0);
  const actionSequenceRef = useRef(0);
  const actionLockRef = useRef(false);
  if (renderedScopeKeyRef.current !== currentScopeKey) {
    renderedScopeKeyRef.current = currentScopeKey;
    scopeEpochRef.current += 1;
    intentEpochRef.current += 1;
    actionSequenceRef.current += 1;
    actionLockRef.current = false;
  }
  currentScopeKeyRef.current = currentScopeKey;
  const currentScopeEpoch = scopeEpochRef.current;
  const [notebook, setNotebook] = useState<NotebookRecord | null>(null);
  const [notebookStateScopeKey, setNotebookStateScopeKey] = useState<string | null>(null);
  const [notebookStateScopeEpoch, setNotebookStateScopeEpoch] = useState<number | null>(null);
  const [notebookChoices, setNotebookChoices] = useState<NotebookRecord[]>([]);
  const [chooserReason, setChooserReason] = useState<string | null>(null);
  const [identity, setIdentity] = useState<CutoverIdentityV1 | null>(null);
  const [identityStateScopeKey, setIdentityStateScopeKey] = useState<string | null>(null);
  const [identityStateScopeEpoch, setIdentityStateScopeEpoch] = useState<number | null>(null);
  const [requestText, setRequestText] = useState("");
  const [requestStateScopeEpoch, setRequestStateScopeEpoch] = useState(currentScopeEpoch);
  const [interactionMode, setInteractionMode] = useState<NotebookInteractionMode>("plan");
  const [interactionModeBusy, setInteractionModeBusy] = useState(false);
  const [submittedRequest, setSubmittedRequest] = useState<string | null>(null);
  const [taskHistory, setTaskHistory] = useState<NotebookTaskHistory[]>([]);
  const [preview, setPreview] = useState<CutoverPreviewV1 | null>(null);
  const [binding, setBinding] = useState<CutoverBindingV1 | null>(null);
  const [result, setResult] = useState<CutoverExecutionResultV1 | null>(null);
  const [confirmation, setConfirmation] = useState<CutoverConfirmationV1 | null>(null);
  const [compiledStateScopeKey, setCompiledStateScopeKey] = useState<string | null>(null);
  const [compiledStateScopeEpoch, setCompiledStateScopeEpoch] = useState<number | null>(null);
  const [compiledStateIntentEpoch, setCompiledStateIntentEpoch] = useState<number | null>(null);
  const [clarificationAnswers, setClarificationAnswers] = useState<Record<string, string>>({});
  const [busyPhase, setBusyPhase] = useState<BusyPhase>(null);
  const [notebookLoading, setNotebookLoading] = useState(true);
  const [identityLoading, setIdentityLoading] = useState(true);
  const [notebookError, setNotebookError] = useState<string | null>(null);
  const [identityError, setIdentityError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [executionRetryAvailable, setExecutionRetryAvailable] = useState(false);
  const [executionRetryUsed, setExecutionRetryUsed] = useState(false);
  const [domainMemoryCandidates, setDomainMemoryCandidates] = useState<DomainMemoryCandidate[]>([]);
  const [domainMemoryCandidateError, setDomainMemoryCandidateError] = useState<string | null>(null);
  const [domainMemoryReviewBusy, setDomainMemoryReviewBusy] = useState(false);
  const domainMemoryGenerationRef = useRef(0);
  const [retryNonce, setRetryNonce] = useState(0);

  function clearCompiledState() {
    setCompiledStateScopeKey(null);
    setCompiledStateScopeEpoch(null);
    setCompiledStateIntentEpoch(null);
    setPreview(null);
    setBinding(null);
    setConfirmation(null);
    setResult(null);
    setClarificationAnswers({});
    setActionError(null);
    setExecutionRetryAvailable(false);
    setExecutionRetryUsed(false);
  }

  function requestIsCurrent(
    scopeKey: string,
    scopeEpoch: number,
    intentEpoch?: number,
    actionSequence?: number,
  ): boolean {
    return currentScopeKeyRef.current === scopeKey
      && scopeEpochRef.current === scopeEpoch
      && (intentEpoch === undefined || intentEpochRef.current === intentEpoch)
      && (actionSequence === undefined || actionSequenceRef.current === actionSequence);
  }

  useEffect(() => {
    const requestScopeEpoch = currentScopeEpoch;
    setRequestStateScopeEpoch(requestScopeEpoch);
    setRequestText("");
    setSubmittedRequest(null);
    setTaskHistory([]);
    setBusyPhase(null);
    clearCompiledState();
  }, [currentScopeEpoch]);

  useEffect(() => {
    const requestScopeKey = currentScopeKey;
    const requestScopeEpoch = currentScopeEpoch;
    let cancelled = false;
    setIdentityStateScopeKey(requestScopeKey);
    setIdentityStateScopeEpoch(requestScopeEpoch);
    setIdentity(null);
    setIdentityLoading(true);
    setIdentityError(null);
    setBusyPhase(null);
    if (retryNonce > 0) {
      setSubmittedRequest(null);
      clearCompiledState();
    }
    void getCutoverIdentity(projectRoot).then(
      (serverIdentity) => {
        if (!cancelled && requestIsCurrent(requestScopeKey, requestScopeEpoch)) {
          setIdentity(serverIdentity);
        }
      },
      (requestError) => {
        if (!cancelled && requestIsCurrent(requestScopeKey, requestScopeEpoch)) {
          setIdentityError(errorText(requestError));
        }
      },
    ).finally(() => {
      if (!cancelled && requestIsCurrent(requestScopeKey, requestScopeEpoch)) {
        setIdentityLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [currentScopeEpoch, currentScopeKey, projectRoot, retryNonce]);

  useEffect(() => {
    const requestScopeKey = currentScopeKey;
    const requestScopeEpoch = currentScopeEpoch;
    let cancelled = false;
    setNotebookStateScopeKey(requestScopeKey);
    setNotebookStateScopeEpoch(requestScopeEpoch);
    setNotebookLoading(true);
    setNotebookError(null);
    setNotebookChoices([]);
    setChooserReason(null);
    setNotebook(null);
    void (async () => {
      let selected: NotebookRecord | null = null;
      let requestedWasMissing = false;
      if (requestedNotebookId) {
        try {
          selected = await getNotebook(projectRoot, requestedNotebookId);
        } catch (requestError) {
          if (!isNotFound(requestError)) throw requestError;
          requestedWasMissing = true;
        }
      }
      if (cancelled || !requestIsCurrent(requestScopeKey, requestScopeEpoch)) return;
      if (!selected) {
        const persisted = await listNotebooks(projectRoot);
        if (cancelled || !requestIsCurrent(requestScopeKey, requestScopeEpoch)) return;
        if (persisted.length === 1) {
          selected = persisted[0];
        } else if (persisted.length > 1) {
          if (cancelled || !requestIsCurrent(requestScopeKey, requestScopeEpoch)) return;
          setNotebookChoices(persisted);
          setChooserReason(requestedWasMissing
            ? "The requested Notebook was not found. Choose one of the persisted Notebooks; Workbench will not guess."
            : "This project has multiple Notebooks. Choose the one you want to continue.");
          return;
        } else if (activeRunId) {
          selected = await ensureNotebookProjection(projectRoot, {
            from_run_id: activeRunId,
            created_by: "user",
            title: "Analysis Notebook",
          });
        } else {
          throw Object.assign(new Error(
            "No Notebook is available for this project, and there is no active run to project into one.",
          ), { code: "NOTEBOOK_NOT_AVAILABLE" });
        }
      }
      if (cancelled || !requestIsCurrent(requestScopeKey, requestScopeEpoch)) return;
      setNotebook(selected);
      setInteractionMode(persistedInteractionMode(selected, projectRoot));
      const goal = selected.user_focus?.goal;
      setRequestText((current) => (
        current.trim() || typeof goal !== "string" ? current : goal
      ));
      setRequestStateScopeEpoch(requestScopeEpoch);
      if (requestedNotebookId !== selected.notebook_id) {
        const next = new URLSearchParams(searchValue);
        next.set("notebook", selected.notebook_id);
        setSearchParams(next, { replace: true });
      }
    })().catch((requestError) => {
      if (!cancelled && requestIsCurrent(requestScopeKey, requestScopeEpoch)) {
        setNotebookError(errorText(requestError));
      }
    }).finally(() => {
      if (!cancelled && requestIsCurrent(requestScopeKey, requestScopeEpoch)) {
        setNotebookLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [activeRunId, currentScopeEpoch, currentScopeKey, projectRoot, requestedNotebookId, retryNonce, searchValue, setSearchParams]);

  useEffect(() => {
    const generation = domainMemoryGenerationRef.current + 1;
    domainMemoryGenerationRef.current = generation;
    setDomainMemoryCandidates([]);
    setDomainMemoryCandidateError(null);
    let cancelled = false;
    void listDomainMemoryCandidates(projectRoot).then(
      (response) => {
        if (!cancelled && domainMemoryGenerationRef.current === generation) {
          setDomainMemoryCandidates(response.candidates);
        }
      },
      (requestError) => {
        if (!cancelled && domainMemoryGenerationRef.current === generation) {
          setDomainMemoryCandidateError(errorText(requestError));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [currentScopeKey, projectRoot]);

  const notebookStateIsCurrent = notebookStateScopeKey === currentScopeKey
    && notebookStateScopeEpoch === currentScopeEpoch;
  const identityStateIsCurrent = identityStateScopeKey === currentScopeKey
    && identityStateScopeEpoch === currentScopeEpoch;
  const compiledStateIsCurrent = compiledStateScopeKey === currentScopeKey
    && compiledStateScopeEpoch === currentScopeEpoch
    && compiledStateIntentEpoch === intentEpochRef.current;
  const activeRequestText = requestStateScopeEpoch === currentScopeEpoch ? requestText : "";
  const activeNotebook = notebookStateIsCurrent ? notebook : null;
  const activeNotebookChoices = notebookStateIsCurrent ? notebookChoices : [];
  const activeChooserReason = notebookStateIsCurrent ? chooserReason : null;
  const activeIdentity = identityStateIsCurrent ? identity : null;
  const activeNotebookError = notebookStateIsCurrent ? notebookError : null;
  const activeIdentityError = identityStateIsCurrent ? identityError : null;
  const activeSubmittedRequest = compiledStateIsCurrent ? submittedRequest : null;
  const activePreview = compiledStateIsCurrent ? preview : null;
  const activeBinding = compiledStateIsCurrent ? binding : null;
  const activeConfirmation = compiledStateIsCurrent ? confirmation : null;
  const activeConfirmationId = activeConfirmation?.confirmation_id ?? null;
  const activeResult = compiledStateIsCurrent ? result : null;
  const activeActionError = compiledStateIsCurrent ? actionError : null;
  const activeBusyPhase = compiledStateIsCurrent ? busyPhase : null;
  const activeNotebookLoading = !notebookStateIsCurrent || notebookLoading;
  const activeIdentityLoading = !identityStateIsCurrent || identityLoading;
  const clarifications = clarificationFields(activePreview);
  const busy = activeBusyPhase !== null;
  const allClarificationsAnswered = clarifications.length > 0 && clarifications.every(
    (item) => Boolean(clarificationAnswers[item.field]?.trim()),
  );
  const setupHasError = Boolean(activeNotebookError || activeIdentityError);
  const statusText = phaseLabel(
    activeBusyPhase,
    activeNotebookLoading,
    activeIdentityLoading,
    activeNotebook,
    activeIdentity,
    activePreview,
    activeBinding,
    activeResult,
    setupHasError,
  );

  function currentTaskHistoryEntry(): NotebookTaskHistory | null {
    const request = activeSubmittedRequest?.trim();
    if (!request) return null;
    const status = activeResult
      ? `Completed · ${activeResult.status}`
      : activeActionError
        ? "Stopped · needs attention"
        : clarifications.length > 0
          ? `Needs ${clarifications.length} clarification${clarifications.length === 1 ? "" : "s"}`
          : activeConfirmation
            ? "Confirmed"
            : activePreview
              ? "Plan preview ready"
              : "Submitted";
    return { request, status };
  }

  function chooseNotebook(selected: NotebookRecord) {
    setNotebookStateScopeKey(cutoverScopeKey(projectRoot, selected.notebook_id));
    setNotebookStateScopeEpoch(currentScopeEpoch);
    setNotebook(selected);
    setInteractionMode(persistedInteractionMode(selected, projectRoot));
    setNotebookChoices([]);
    setChooserReason(null);
    setNotebookError(null);
    const goal = selected.user_focus?.goal;
    setRequestText((current) => (
      current.trim() || typeof goal !== "string" ? current : goal
    ));
    setRequestStateScopeEpoch(currentScopeEpoch);
    const next = new URLSearchParams(searchValue);
    next.set("notebook", selected.notebook_id);
    setSearchParams(next, { replace: true });
  }

  async function changeInteractionMode(mode: NotebookInteractionMode) {
    if (!activeNotebook || mode === interactionMode || interactionModeBusy || busy) return;
    const selectedNotebookId = activeNotebook.notebook_id;
    setInteractionModeBusy(true);
    setActionError(null);
    try {
      const updated = await updateNotebookFocus(projectRoot, selectedNotebookId, {
        interaction_mode: mode,
      });
      if (!requestIsCurrent(currentScopeKey, currentScopeEpoch)) return;
      writeStoredInteractionMode(projectRoot, selectedNotebookId, mode);
      setNotebook(updated);
      setInteractionMode(persistedInteractionMode(updated, projectRoot, mode));
      // The mode is part of the server freshness contract. An older preview
      // must be recompiled before it can be confirmed or executed.
      intentEpochRef.current += 1;
      actionSequenceRef.current += 1;
      actionLockRef.current = false;
      clearCompiledState();
      setSubmittedRequest(null);
    } catch (requestError) {
      setActionError(errorText(requestError));
    } finally {
      setInteractionModeBusy(false);
    }
  }

  async function reviewMemoryCandidate(
    candidateId: string,
    decision: "approved" | "rejected",
    revision: number,
  ) {
    if (domainMemoryReviewBusy) return;
    const generation = domainMemoryGenerationRef.current;
    const actorId = activeIdentity?.actor_ref ?? "local-user";
    const now = new Date();
    setDomainMemoryReviewBusy(true);
    setDomainMemoryCandidateError(null);
    try {
      await reviewDomainMemoryCandidateApi(projectRoot, candidateId, decision === "approved"
        ? {
            decision,
            expected_revision: revision,
            actor_id: actorId,
            approved_at: now.toISOString(),
            review_after: new Date(now.getTime() + 90 * 24 * 60 * 60 * 1000).toISOString(),
          }
        : {
            decision,
            expected_revision: revision,
            actor_id: actorId,
          });
      if (generation !== domainMemoryGenerationRef.current) return;
      const response = await listDomainMemoryCandidates(projectRoot);
      if (generation === domainMemoryGenerationRef.current) setDomainMemoryCandidates(response.candidates);
    } catch (requestError) {
      if (generation === domainMemoryGenerationRef.current) setDomainMemoryCandidateError(errorText(requestError));
    } finally {
      setDomainMemoryReviewBusy(false);
    }
  }

  function changeRequestText(nextText: string) {
    const previous = currentTaskHistoryEntry();
    if (previous && previous.request !== nextText.trim()) {
      setTaskHistory((current) => [...current, previous].slice(-12));
    }
    intentEpochRef.current += 1;
    actionSequenceRef.current += 1;
    actionLockRef.current = false;
    setRequestStateScopeEpoch(currentScopeEpoch);
    setRequestText(nextText);
    clearCompiledState();
    setBusyPhase(null);
    setSubmittedRequest(null);
  }

  async function compile() {
    const text = activeRequestText.trim();
    if (!activeNotebook || !activeIdentity || !text || busy || actionLockRef.current) return;
    const requestScopeKey = currentScopeKey;
    const requestScopeEpoch = currentScopeEpoch;
    const requestIntentEpoch = intentEpochRef.current;
    const actionSequence = actionSequenceRef.current + 1;
    actionSequenceRef.current = actionSequence;
    actionLockRef.current = true;
    const selectedNotebookId = activeNotebook.notebook_id;
    const selectedIdentity = activeIdentity;
    clearCompiledState();
    setCompiledStateScopeKey(requestScopeKey);
    setCompiledStateScopeEpoch(requestScopeEpoch);
    setCompiledStateIntentEpoch(requestIntentEpoch);
    setBusyPhase("compiling");
    setRequestStateScopeEpoch(requestScopeEpoch);
    setRequestText(text);
    setSubmittedRequest(text);
    try {
      const updated = await updateNotebookFocus(projectRoot, selectedNotebookId, {
        goal: text,
        interaction_mode: interactionMode,
      });
      if (!requestIsCurrent(requestScopeKey, requestScopeEpoch, requestIntentEpoch, actionSequence)) return;
      setNotebookStateScopeKey(requestScopeKey);
      setNotebookStateScopeEpoch(requestScopeEpoch);
      setNotebook(updated);
      writeStoredInteractionMode(projectRoot, selectedNotebookId, interactionMode);
      const response = await compileNotebookCutover(
        projectRoot,
        selectedNotebookId,
        text,
        selectedIdentity,
      );
      if (!requestIsCurrent(requestScopeKey, requestScopeEpoch, requestIntentEpoch, actionSequence)) return;
      setPreview(response.preview);
      setBinding(response.binding ?? null);
    } catch (requestError) {
      if (requestIsCurrent(requestScopeKey, requestScopeEpoch, requestIntentEpoch, actionSequence)) {
        setActionError(errorText(requestError));
      }
    } finally {
      if (requestIsCurrent(requestScopeKey, requestScopeEpoch, requestIntentEpoch, actionSequence)) {
        setBusyPhase(null);
      }
      if (actionSequenceRef.current === actionSequence) actionLockRef.current = false;
    }
  }

  async function recompileWithClarifications() {
    const text = activeSubmittedRequest ?? activeRequestText.trim();
    if (
      !activeNotebook
      || !activeIdentity
      || !text
      || busy
      || !allClarificationsAnswered
      || actionLockRef.current
    ) return;
    const requestScopeKey = currentScopeKey;
    const requestScopeEpoch = currentScopeEpoch;
    const requestIntentEpoch = intentEpochRef.current + 1;
    intentEpochRef.current = requestIntentEpoch;
    const actionSequence = actionSequenceRef.current + 1;
    actionSequenceRef.current = actionSequence;
    actionLockRef.current = true;
    const normalizedFields = Object.fromEntries(
      Object.entries(clarificationAnswers)
        .map(([field, value]) => [field, value.trim()] as const)
        .filter(([, value]) => Boolean(value)),
    );
    setCompiledStateScopeKey(requestScopeKey);
    setCompiledStateScopeEpoch(requestScopeEpoch);
    setCompiledStateIntentEpoch(requestIntentEpoch);
    setBusyPhase("clarifying");
    setActionError(null);
    setBinding(null);
    setConfirmation(null);
    setResult(null);
    setExecutionRetryAvailable(false);
    setExecutionRetryUsed(false);
    try {
      const response = await compileNotebookCutover(
        projectRoot,
        activeNotebook.notebook_id,
        text,
        activeIdentity,
        normalizedFields,
      );
      if (!requestIsCurrent(requestScopeKey, requestScopeEpoch, requestIntentEpoch, actionSequence)) return;
      setPreview(response.preview);
      setBinding(response.binding ?? null);
    } catch (requestError) {
      if (requestIsCurrent(requestScopeKey, requestScopeEpoch, requestIntentEpoch, actionSequence)) {
        setActionError(errorText(requestError));
      }
    } finally {
      if (requestIsCurrent(requestScopeKey, requestScopeEpoch, requestIntentEpoch, actionSequence)) {
        setBusyPhase(null);
      }
      if (actionSequenceRef.current === actionSequence) actionLockRef.current = false;
    }
  }

  async function confirmAndExecute() {
    const retryingExecution = activeConfirmation !== null;
    if (
      !activeIdentity
      || !activeBinding
      || !activePreview?.operation_id
      || busy
      || actionLockRef.current
      || (retryingExecution && (!executionRetryAvailable || executionRetryUsed))
    ) return;
    const requestScopeKey = currentScopeKey;
    const requestScopeEpoch = currentScopeEpoch;
    const requestIntentEpoch = intentEpochRef.current;
    const actionSequence = actionSequenceRef.current + 1;
    actionSequenceRef.current = actionSequence;
    actionLockRef.current = true;
    const selectedBinding = activeBinding;
    const selectedIdentity = activeIdentity;
    const expectedOperationId = activePreview.operation_id;
    let selectedConfirmation = activeConfirmation;
    let executionStarted = false;
    if (retryingExecution) setExecutionRetryUsed(true);
    setExecutionRetryAvailable(false);
    setBusyPhase(selectedConfirmation ? "executing" : "confirming");
    setActionError(null);
    try {
      if (!selectedConfirmation) {
        const confirmed = await confirmCutover(selectedBinding, selectedIdentity);
        if (!requestIsCurrent(requestScopeKey, requestScopeEpoch, requestIntentEpoch, actionSequence)) return;
        selectedConfirmation = confirmed.confirmation;
        setConfirmation(selectedConfirmation);
      }
      setBusyPhase("executing");
      executionStarted = true;
      const executed = await executeCutover(
        selectedBinding,
        selectedIdentity,
        selectedConfirmation,
        { expected_operation_id: expectedOperationId },
      );
      if (!requestIsCurrent(requestScopeKey, requestScopeEpoch, requestIntentEpoch, actionSequence)) return;
      setResult(executed.result);
      setExecutionRetryAvailable(false);
    } catch (requestError) {
      if (requestIsCurrent(requestScopeKey, requestScopeEpoch, requestIntentEpoch, actionSequence)) {
        if (!executionStarted) {
          setBinding(null);
          setConfirmation(null);
          setActionError(
            `${errorText(requestError)} Confirmation status is uncertain; compile a new plan before trying again.`,
          );
        } else {
          setActionError(errorText(requestError));
        }
        setExecutionRetryAvailable(
          executionStarted
          && !retryingExecution
          && isRetryableCutoverError(requestError),
        );
      }
    } finally {
      if (requestIsCurrent(requestScopeKey, requestScopeEpoch, requestIntentEpoch, actionSequence)) {
        setBusyPhase(null);
      }
      if (actionSequenceRef.current === actionSequence) actionLockRef.current = false;
    }
  }

  const setupStatus = activeNotebook && activeIdentity
    ? "completed"
    : activeNotebookLoading || activeIdentityLoading
      ? "active"
      : "pending";
  const compileStatus = activePreview
    ? "completed"
    : activeBusyPhase === "compiling" || activeBusyPhase === "clarifying"
      ? "active"
      : "pending";
  const confirmationStatus = activeConfirmationId || activeResult
    ? "completed"
    : activeBusyPhase === "confirming" || Boolean(activeBinding)
      ? "active"
      : "pending";
  const executionStatus = activeResult
    ? "completed"
    : activeBusyPhase === "executing"
      ? "active"
      : "pending";

  return (
    <section
      data-testid="notebook-cutover-view"
      aria-label="Notebook cutover"
      className="nb-surface nb-cutover-surface"
      aria-busy={busy || activeNotebookLoading || activeIdentityLoading}
    >
      <header className="nb-surface-header nb-cutover-header">
        <div className="nb-cutover-heading">
          <span className="nb-label">Notebook</span>
          <h2>{activeNotebook?.title ?? "Analysis Notebook"}</h2>
          <p data-testid="notebook-header-identity" className="nb-cutover-identity">
            {activeNotebook
              ? `${activeNotebook.notebook_id} · ${activeNotebook.run_family_id}`
              : activeNotebookLoading
                ? "Resolving Notebook…"
                : "No Notebook selected"}
          </p>
        </div>
        <div
          className="nb-cutover-compiler"
          data-status={activeIdentity ? "ready" : activeIdentityLoading ? "loading" : "error"}
        >
          <span className="nb-label">Server-owned compiler</span>
          <strong data-testid="notebook-compiler-status" aria-live="polite">
            {activeIdentity
              ? "Compiler ready"
              : activeIdentityLoading
                ? "Resolving compiler identity…"
                : "Compiler unavailable"}
          </strong>
          <span>{activeIdentity?.project_ref ?? "No server identity is bound"}</span>
        </div>
      </header>

      <form
        className="nb-user-intent nb-cutover-intent"
        data-testid="notebook-user-intent"
        onSubmit={(event) => {
          event.preventDefault();
          void compile();
        }}
      >
        <span className="nb-label">Natural-language task</span>
        <section className="nb-cutover-mode" data-testid="notebook-planning-mode" aria-label="Notebook planning mode">
          <div className="nb-context-header">
            <span className="nb-label">Plan / Action</span>
            <span>{interactionMode === "action" ? "one checked path" : "compare evidence-backed paths"}</span>
          </div>
          <div className="nb-interaction-mode" role="group" aria-label="Notebook planning mode">
            <button
              type="button"
              className="nb-interaction-mode-button"
              data-testid="notebook-mode-plan"
              aria-pressed={interactionMode === "plan"}
              disabled={interactionModeBusy || busy}
              onClick={() => void changeInteractionMode("plan")}
            >
              Plan
            </button>
            <button
              type="button"
              className="nb-interaction-mode-button"
              data-testid="notebook-mode-action"
              aria-pressed={interactionMode === "action"}
              disabled={interactionModeBusy || busy}
              onClick={() => void changeInteractionMode("action")}
            >
              Action
            </button>
          </div>
          <p className="nb-interaction-mode-help">
            {interactionMode === "action"
              ? "Prepare one server-checked action. Nothing runs until you confirm."
              : "Explore a server-compiled plan before choosing whether to act. Nothing runs until you confirm."}
          </p>
        </section>
        <label htmlFor="notebook-cutover-request">What should Workbench prepare?</label>
        <textarea
          id="notebook-cutover-request"
          aria-label="Notebook request"
          rows={4}
          value={activeRequestText}
          onChange={(event) => changeRequestText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              void compile();
            }
          }}
          disabled={busy}
          placeholder="用自然语言描述研究问题、数据对象、约束和需要的证据。"
        />
        <div className="nb-cutover-composer-actions">
          <button
            type="submit"
            className="nb-button nb-button-primary"
            disabled={!activeNotebook || !activeIdentity || busy || !activeRequestText.trim()}
          >
            {activeBusyPhase === "compiling" ? "Compiling…" : "Compile notebook plan"}
          </button>
          <p>
            The server compiles a preview first. Press ⌘/Ctrl+Enter to compile; editing revokes any older preview and confirmation binding.
          </p>
        </div>
      </form>

      <section
        className="nb-planning-progress nb-cutover-progress"
        data-testid="notebook-cutover-progress"
        aria-live="polite"
      >
        <header>
          <span className="nb-label">Cutover progress</span>
          <strong>{statusText}</strong>
        </header>
        <ol>
          <li data-status={setupStatus}>Notebook scope and server identity</li>
          <li data-status={compileStatus}>Server compilation and structured preview</li>
          <li data-status={confirmationStatus}>Explicit server confirmation</li>
          <li data-status={executionStatus}>Execution and formal evidence references</li>
        </ol>
        <p>Only server-published lifecycle stages are shown; private reasoning is not exposed.</p>
      </section>

      <section className="nb-cutover-memory" data-testid="notebook-memory-managed" aria-label="Notebook memory">
        <div>
          <span className="nb-label">Memory</span>
          <strong>managed per project</strong>
          <p>Approved hints and candidate reviews stay scoped to this project. Memory never authorizes execution.</p>
        </div>
        <button
          type="button"
          className="nb-button"
          onClick={() => {
            const next = new URLSearchParams(searchParams);
            next.set("memory_settings", "1");
            setSearchParams(next);
          }}
        >
          Manage memory
        </button>
      </section>

      {activeIdentityError ? (
        <div className="nb-planning-error nb-cutover-recovery" role="alert">
          <div>
            <span className="nb-error-code">Server identity unavailable</span>
            <p>Your draft is safe and remains editable. The compiler cannot run until identity is restored.</p>
            <p>{activeIdentityError}</p>
          </div>
          <button
            type="button"
            className="nb-button"
            onClick={() => setRetryNonce((value) => value + 1)}
          >
            Retry server connection
          </button>
        </div>
      ) : null}

      {activeNotebookError ? (
        <div className="nb-planning-error nb-cutover-recovery" role="alert">
          <div>
            <span className="nb-error-code">Notebook unavailable</span>
            <p>Your draft is safe. Retry after the Notebook or active-run projection becomes available.</p>
            <p>{activeNotebookError}</p>
          </div>
          <button
            type="button"
            className="nb-button"
            onClick={() => setRetryNonce((value) => value + 1)}
          >
            Retry Notebook loading
          </button>
        </div>
      ) : null}

      {activeNotebookChoices.length > 1 ? (
        <section className="nb-cutover-chooser" data-testid="notebook-chooser">
          <header className="nb-context-header">
            <span className="nb-label">Notebook recovery</span>
            <h3>Choose a Notebook</h3>
          </header>
          <p>{activeChooserReason}</p>
          <div className="nb-cutover-choice-list">
            {activeNotebookChoices.map((choice) => (
              <article className="nb-option-card" key={choice.notebook_id}>
                <div>
                  <strong>{choice.title}</strong>
                  <p>{`${choice.notebook_id} · ${choice.run_family_id}`}</p>
                  <p>{`Active head: ${choice.active_head_run_id ?? "none"}`}</p>
                </div>
                <button
                  type="button"
                  className="nb-button"
                  onClick={() => chooseNotebook(choice)}
                >
                  {`Use ${choice.title}`}
                </button>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {activeActionError ? (
        <div className="nb-action-error" role="alert">
          <span className="nb-error-code">Cutover request failed</span>
          <span>{activeActionError}</span>
        </div>
      ) : null}

      <section className="nb-narrative nb-cutover-activity" data-testid="notebook-narrative">
        <header className="nb-context-header">
          <span className="nb-label">Activity</span>
          <span>Auditable request and server lifecycle</span>
        </header>
        {taskHistory.length > 0 && (
          <div
            data-testid="notebook-task-history"
            className="nb-task-history"
            aria-label="Previous Notebook tasks"
          >
            <header>
              <span className="nb-label">Previous tasks</span>
              <span>{taskHistory.length}</span>
            </header>
            <ul>
              {taskHistory.slice().reverse().map((item, index) => (
                <li key={`${item.request}:${index}`}>
                  <span>{item.request}</span>
                  <small>{item.status}</small>
                </li>
              ))}
            </ul>
          </div>
        )}
        {!activeSubmittedRequest ? (
          <p className={`nb-empty${taskHistory.length > 0 ? " nb-history-empty" : ""}`}>
            {taskHistory.length > 0
              ? "Ready for the next task in this Notebook scope."
              : "No task has been submitted in this Notebook scope."}
          </p>
        ) : (
          <p className="nb-narrative-entry" data-testid="notebook-activity-user" data-kind="user">
            <span className="nb-narrative-kind">user · </span>
            <span>{activeSubmittedRequest}</span>
          </p>
        )}
        {activePreview ? (
          <p className="nb-narrative-entry" data-kind="compiler">
            <span className="nb-narrative-kind">compiler · </span>
            <span>
              {clarifications.length > 0
                ? `Needs ${clarifications.length} clarification field${clarifications.length === 1 ? "" : "s"}.`
                : activeBinding
                  ? "Structured plan compiled and bound for explicit confirmation."
                  : "Structured preview returned without an executable binding."}
            </span>
          </p>
        ) : null}
        {activeConfirmationId ? (
          <p className="nb-narrative-entry" data-kind="confirmation">
            <span className="nb-narrative-kind">server confirmation · </span>
            <span>{activeConfirmationId}</span>
          </p>
        ) : null}
      </section>

      <ServerAuditDetails preview={activePreview} result={activeResult} />

      {activePreview && (
        <section className="nb-option-list nb-cutover-preview" data-testid="notebook-cutover-preview">
          <header className="nb-context-header">
            <span className="nb-label">Server preview</span>
            <span>{activePreview.operation_id ?? "Clarification pass — no operation created"}</span>
          </header>
          {Object.keys(activePreview.plan_diff).length > 0 ? (
            <dl className="nb-plan-grid">
              {Object.entries(activePreview.plan_diff)
                .filter(([key]) => !["audit", "lifecycle", "omissions", "evidence"].includes(key))
                .map(([key, value]) => (
                <div className="nb-plan-row" key={key}>
                  <dt>{fieldLabel(key)}</dt>
                  <dd>
                    <StructuredPlanValue value={value} path={key} />
                  </dd>
                </div>
                ))}
            </dl>
          ) : (
            <p className="nb-empty">The server returned an empty plan diff.</p>
          )}
        </section>
      )}

      {clarifications.length > 0 ? (
        <form
          className="nb-confirmation nb-cutover-clarifications"
          data-testid="notebook-clarifications"
          onSubmit={(event) => {
            event.preventDefault();
            void recompileWithClarifications();
          }}
        >
          <header className="nb-confirmation-header">
            <span className="nb-label">Clarification required</span>
            <strong>Answer every server-requested field</strong>
          </header>
          <p className="nb-confirmation-scope">
            These answers are normalized fields for a new server compilation. No confirmation is available yet.
          </p>
          <div className="nb-clarification-grid">
            {clarifications.map((item) => {
              const fieldId = `notebook-clarification-${item.field}`;
              const helpId = `${fieldId}-help`;
              const allowedValues = item.allowedValues.length > 0
                ? item.allowedValues
                : CLOSED_FIELD_VALUES[item.field] ?? [];
              return (
                <div className="nb-clarification-field" key={item.field}>
                  <div className="nb-clarification-field-header">
                    <label htmlFor={fieldId}>{fieldLabel(item.field)}</label>
                    <code>{item.field}</code>
                  </div>
                  <p id={helpId}>{item.message}</p>
                  {allowedValues.length > 0 ? (
                    <select
                      id={fieldId}
                      aria-describedby={helpId}
                      value={clarificationAnswers[item.field] ?? ""}
                      onChange={(event) => setClarificationAnswers((current) => ({
                        ...current,
                        [item.field]: event.target.value,
                      }))}
                      disabled={busy}
                      required
                    >
                      <option value="">Select a value</option>
                      {allowedValues.map((value) => (
                        <option value={value} key={value}>{fieldLabel(value)}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      id={fieldId}
                      aria-describedby={helpId}
                      value={clarificationAnswers[item.field] ?? ""}
                      onChange={(event) => setClarificationAnswers((current) => ({
                        ...current,
                        [item.field]: event.target.value,
                      }))}
                      disabled={busy}
                      required
                    />
                  )}
                </div>
              );
            })}
          </div>
          <div className="nb-confirmation-actions">
            <button
              type="submit"
              className="nb-button nb-button-primary"
              disabled={busy || !allClarificationsAnswered}
            >
              {activeBusyPhase === "clarifying" ? "Recompiling…" : "Recompile with answers"}
            </button>
          </div>
        </form>
      ) : null}

      {activeBinding && clarifications.length === 0 ? (
        <section
          className="nb-confirmation nb-cutover-confirmation"
          data-testid="notebook-cutover-confirmation"
        >
          <header className="nb-confirmation-header">
            <span className="nb-label">Confirmation</span>
            <strong>Server-bound plan ready</strong>
          </header>
          <p>Nothing runs until you confirm.</p>
          <dl className="nb-cutover-metadata">
            <div>
              <dt>Compilation record</dt>
              <dd>{activeBinding.compilation_record_id}</dd>
            </div>
            <div>
              <dt>Proposal</dt>
              <dd>{activeBinding.proposal_id}</dd>
            </div>
          </dl>
          {activeConfirmationId ? (
            <p className="nb-confirmation-scope">{`Server confirmation accepted: ${activeConfirmationId}`}</p>
          ) : null}
          {!activeResult && (!activeConfirmation || executionRetryAvailable) ? (
            <div className="nb-confirmation-actions">
              <button
                type="button"
                className="nb-button nb-button-primary"
                onClick={() => void confirmAndExecute()}
                disabled={busy}
              >
                {activeBusyPhase === "confirming"
                  ? "Requesting server confirmation…"
                  : activeBusyPhase === "executing"
                    ? "Executing confirmed plan…"
                    : activeConfirmation
                      ? "Retry execution"
                      : "Confirm and execute notebook plan"}
              </button>
            </div>
          ) : null}
          {!activeResult && activeConfirmation && !executionRetryAvailable ? (
            <p className="nb-confirmation-scope">
              Execution cannot be retried safely. Compile a new plan before trying again.
            </p>
          ) : null}
        </section>
      ) : null}

      {activeResult && (
        <section className="nb-success nb-cutover-result" data-testid="notebook-cutover-result" role="status">
          <header className="nb-context-header">
            <span className="nb-label">Executed result</span>
            <strong>{activeResult.status}</strong>
          </header>
          <dl className="nb-cutover-metadata">
            <div>
              <dt>Status</dt>
              <dd>{activeResult.status}</dd>
            </div>
            <div>
              <dt>Operation id</dt>
              <dd>{activeResult.operation_id}</dd>
            </div>
            <div>
              <dt>Execution instance hash</dt>
              <dd>{activeResult.execution_instance_hash}</dd>
            </div>
          </dl>
          <div className="nb-cutover-evidence">
            <span className="nb-label">Formal evidence references</span>
            {activeResult.evidence_refs.length > 0 ? (
              <ul>
                {activeResult.evidence_refs.map((reference) => <li key={reference}>{reference}</li>)}
              </ul>
            ) : (
              <p className="nb-empty">The server returned no evidence references.</p>
            )}
          </div>
        </section>
      )}

      <DomainMemoryReviewQueue
        candidates={domainMemoryCandidates}
        onReview={(candidateId, decision, revision) => {
          void reviewMemoryCandidate(candidateId, decision, revision);
        }}
      />
      {domainMemoryCandidateError ? (
        <div className="nb-action-error" data-testid="notebook-memory-error" role="alert">
          <span className="nb-error-code">Memory review unavailable</span>
          <span>{domainMemoryCandidateError}</span>
        </div>
      ) : null}
    </section>
  );
}
