import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  compileAgentCutover,
  confirmCutover,
  executeCutover,
  getCutoverIdentity,
  isRetryableCutoverError,
  type CutoverBindingV1,
  type CutoverConfirmationV1,
  type CutoverExecutionResultV1,
  type CutoverIdentityV1,
  type CutoverPreviewV1,
} from "../../cutoverApi";

import "./agent.css";

type CutoverError = Error & { code?: string | null };
type BusyPhase = "compiling" | "clarifying" | "confirming" | "executing" | null;
type ActionErrorPhase = "compile" | "confirm" | "execute";

interface ClarificationField {
  field: string;
  message: string;
  allowedValues: string[];
}

interface AgentTaskHistory {
  request: string;
  status: string;
}

interface AgentSessionState {
  scopeKey: string;
  identity: CutoverIdentityV1 | null;
  identityLoading: boolean;
  identityError: string | null;
  requestText: string;
  submittedRequest: string | null;
  preview: CutoverPreviewV1 | null;
  binding: CutoverBindingV1 | null;
  confirmation: CutoverConfirmationV1 | null;
  result: CutoverExecutionResultV1 | null;
  clarificationAnswers: Record<string, string>;
  history: AgentTaskHistory[];
  busyPhase: BusyPhase;
  actionError: { phase: ActionErrorPhase; message: string } | null;
  executionRetryAvailable: boolean;
  executionRetryUsed: boolean;
}

export interface AgentCutoverContextValue {
  projectRoot: string;
  runId: string;
  state: AgentSessionState;
  changeRequestText: (value: string) => boolean;
  setClarificationAnswer: (field: string, value: string) => void;
  retryIdentity: () => void;
  compilePlan: () => Promise<void>;
  recompileWithClarifications: () => Promise<void>;
  confirmAndExecute: () => Promise<void>;
  retryExecution: () => Promise<void>;
}

const AgentCutoverContext = createContext<AgentCutoverContextValue | null>(null);

export function useAgentCutoverOptional(): AgentCutoverContextValue | null {
  return useContext(AgentCutoverContext);
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
  effect: "Effect",
  risk_level: "Risk level",
  evidence_required: "Evidence required",
};

function makeSession(scopeKey: string): AgentSessionState {
  return {
    scopeKey,
    identity: null,
    identityLoading: false,
    identityError: null,
    requestText: "",
    submittedRequest: null,
    preview: null,
    binding: null,
    confirmation: null,
    result: null,
    clarificationAnswers: {},
    history: [],
    busyPhase: null,
    actionError: null,
    executionRetryAvailable: false,
    executionRetryUsed: false,
  };
}

function errorText(error: unknown): string {
  const candidate = error as CutoverError | null;
  const code = typeof candidate?.code === "string" ? candidate.code : null;
  const message = error instanceof Error ? error.message : "Cutover request failed";
  return code ? `${code}: ${message}` : message;
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

function StructuredPlanValue({ value, path }: { value: unknown; path: string }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="wb-agent-plan-empty">None</span>;
    return (
      <ul className="wb-agent-plan-list">
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
    if (entries.length === 0) return <span className="wb-agent-plan-empty">None</span>;
    return (
      <dl className="wb-agent-plan-grid wb-agent-plan-grid--nested">
        {entries.map(([key, child]) => (
          <div className="wb-agent-plan-row" key={`${path}-${key}`}>
            <dt>{fieldLabel(key)}</dt>
            <dd>
              <StructuredPlanValue value={child} path={`${path}-${key}`} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span className="wb-agent-plan-value">{primitiveText(value)}</span>;
}

function clarificationFields(preview: CutoverPreviewV1 | null): ClarificationField[] {
  const fields = new Map<string, ClarificationField>();
  for (const item of preview?.clarifications ?? []) {
    const field = typeof item.field === "string" ? item.field.trim() : "";
    if (!field) continue;
    const message = typeof item.message === "string" && item.message.trim()
      ? item.message
      : "The server needs this field before it can compile a plan.";
    const allowedValues = Array.isArray(item.allowed_values)
      ? item.allowed_values.filter(
        (value): value is string => typeof value === "string" && value.length > 0,
      )
      : [];
    const existing = fields.get(field);
    if (existing) {
      if (!existing.message.includes(message)) existing.message = `${existing.message} ${message}`;
      existing.allowedValues = Array.from(new Set([...existing.allowedValues, ...allowedValues]));
    } else {
      fields.set(field, { field, message, allowedValues });
    }
  }
  return Array.from(fields.values());
}

function taskHistoryEntry(current: AgentSessionState): AgentTaskHistory | null {
  const request = current.submittedRequest?.trim();
  if (!request) return null;
  const clarifications = clarificationFields(current.preview).length;
  const status = current.result
    ? `Completed · ${current.result.status}`
    : current.actionError
      ? "Stopped · needs attention"
      : clarifications > 0
        ? `Needs ${clarifications} clarification${clarifications === 1 ? "" : "s"}`
        : current.confirmation
          ? "Confirmed"
          : current.preview
            ? "Plan preview ready"
            : "Submitted";
  return { request, status };
}

function AgentCutoverProviderOwner({
  projectRoot,
  runId,
  enabled = true,
  children,
}: {
  projectRoot: string;
  runId: string;
  enabled?: boolean;
  children: ReactNode;
}) {
  const scopeKey = `${projectRoot}\u0000${runId}`;
  const [session, setSession] = useState<AgentSessionState>(() => makeSession(scopeKey));
  const [identityRetry, setIdentityRetry] = useState(0);
  const scopeKeyRef = useRef(scopeKey);
  const generationRef = useRef(0);
  const actionLockRef = useRef(false);
  const activeIdentityAttemptRef = useRef<string | null>(null);
  const completedIdentityAttemptRef = useRef<string | null>(null);

  if (scopeKeyRef.current !== scopeKey) {
    scopeKeyRef.current = scopeKey;
    generationRef.current += 1;
    actionLockRef.current = false;
  }

  const scopedSession = session.scopeKey === scopeKey ? session : makeSession(scopeKey);
  const state = enabled
    && !scopedSession.identity
    && !scopedSession.identityError
    && !scopedSession.identityLoading
    ? { ...scopedSession, identityLoading: true }
    : scopedSession;
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    if (!enabled) return;
    const attemptKey = `${scopeKey}\u0000${identityRetry}`;
    if (
      completedIdentityAttemptRef.current === attemptKey
      && stateRef.current.scopeKey === scopeKey
      && stateRef.current.identity
    ) {
      return;
    }
    let cancelled = false;
    activeIdentityAttemptRef.current = attemptKey;
    setSession((current) => {
      const scoped = current.scopeKey === scopeKey ? current : makeSession(scopeKey);
      return {
        ...scoped,
        identity: null,
        identityLoading: true,
        identityError: null,
        preview: null,
        binding: null,
        confirmation: null,
        result: null,
        clarificationAnswers: {},
        busyPhase: null,
        actionError: null,
        executionRetryAvailable: false,
        executionRetryUsed: false,
      };
    });
    void getCutoverIdentity(projectRoot).then(
      (identity) => {
        if (
          cancelled
          || scopeKeyRef.current !== scopeKey
          || activeIdentityAttemptRef.current !== attemptKey
        ) return;
        completedIdentityAttemptRef.current = attemptKey;
        setSession((current) => current.scopeKey === scopeKey
          ? { ...current, identity, identityLoading: false, identityError: null }
          : current);
      },
      (error) => {
        if (
          cancelled
          || scopeKeyRef.current !== scopeKey
          || activeIdentityAttemptRef.current !== attemptKey
        ) return;
        setSession((current) => current.scopeKey === scopeKey
          ? {
            ...current,
            identity: null,
            identityLoading: false,
            identityError: errorText(error),
          }
          : current);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [enabled, identityRetry, projectRoot, scopeKey]);

  function commitFor(
    expectedScope: string,
    expectedGeneration: number,
    update: (current: AgentSessionState) => AgentSessionState,
  ): boolean {
    if (
      scopeKeyRef.current !== expectedScope
      || generationRef.current !== expectedGeneration
    ) return false;
    setSession((current) => current.scopeKey === expectedScope ? update(current) : current);
    return true;
  }

  function changeRequestText(value: string): boolean {
    if (stateRef.current.busyPhase !== null || actionLockRef.current) return false;
    const previous = taskHistoryEntry(stateRef.current);
    const replacingSubmittedTask = previous !== null && previous.request !== value.trim();
    generationRef.current += 1;
    actionLockRef.current = false;
    setSession((current) => {
      const scoped = current.scopeKey === scopeKey ? current : makeSession(scopeKey);
      return {
        ...scoped,
        requestText: value,
        submittedRequest: null,
        preview: null,
        binding: null,
        confirmation: null,
        result: null,
        clarificationAnswers: {},
        history: replacingSubmittedTask && previous
          ? [...scoped.history, previous].slice(-12)
          : scoped.history,
        busyPhase: null,
        actionError: null,
        executionRetryAvailable: false,
        executionRetryUsed: false,
      };
    });
    return true;
  }

  function setClarificationAnswer(field: string, value: string) {
    setSession((current) => current.scopeKey === scopeKey
      ? {
        ...current,
        clarificationAnswers: { ...current.clarificationAnswers, [field]: value },
      }
      : current);
  }

  async function compile(
    normalizedFields?: Record<string, unknown>,
    phase: "compiling" | "clarifying" = "compiling",
  ) {
    const current = stateRef.current;
    const text = (phase === "clarifying" ? current.submittedRequest : current.requestText)?.trim() ?? "";
    if (!current.identity || !text || current.busyPhase || actionLockRef.current) return;
    const expectedScope = scopeKey;
    const expectedGeneration = generationRef.current;
    actionLockRef.current = true;
    const selectedIdentity = current.identity;
    setSession((value) => value.scopeKey === expectedScope
      ? {
        ...value,
        requestText: text,
        submittedRequest: text,
        preview: phase === "compiling" ? null : value.preview,
        binding: null,
        confirmation: null,
        result: null,
        clarificationAnswers: phase === "compiling" ? {} : value.clarificationAnswers,
        busyPhase: phase,
        actionError: null,
        executionRetryAvailable: false,
        executionRetryUsed: false,
      }
      : value);
    try {
      const response = await compileAgentCutover(text, selectedIdentity, normalizedFields);
      commitFor(expectedScope, expectedGeneration, (value) => ({
        ...value,
        preview: response.preview,
        binding: response.binding ?? null,
        confirmation: null,
        result: null,
        clarificationAnswers: {},
        busyPhase: null,
        actionError: null,
        executionRetryAvailable: false,
        executionRetryUsed: false,
      }));
    } catch (error) {
      commitFor(expectedScope, expectedGeneration, (value) => ({
        ...value,
        busyPhase: null,
        actionError: { phase: "compile", message: errorText(error) },
      }));
    } finally {
      if (
        scopeKeyRef.current === expectedScope
        && generationRef.current === expectedGeneration
      ) actionLockRef.current = false;
    }
  }

  async function compilePlan() {
    await compile();
  }

  async function recompileWithClarifications() {
    const current = stateRef.current;
    const fields = clarificationFields(current.preview);
    if (
      fields.length === 0
      || fields.some((item) => !current.clarificationAnswers[item.field]?.trim())
    ) return;
    const normalizedFields = Object.fromEntries(fields.map((item) => [
      item.field,
      current.clarificationAnswers[item.field].trim(),
    ]));
    await compile(normalizedFields, "clarifying");
  }

  async function executeConfirmed(
    selectedBinding: CutoverBindingV1,
    selectedIdentity: CutoverIdentityV1,
    selectedConfirmation: CutoverConfirmationV1,
    expectedOperationId: string,
    expectedScope: string,
    expectedGeneration: number,
    retrying: boolean,
  ) {
    commitFor(expectedScope, expectedGeneration, (value) => ({
      ...value,
      confirmation: selectedConfirmation,
      busyPhase: "executing",
      actionError: null,
      executionRetryAvailable: false,
      executionRetryUsed: value.executionRetryUsed || retrying,
    }));
    try {
      const executed = await executeCutover(
        selectedBinding,
        selectedIdentity,
        selectedConfirmation,
        { expected_operation_id: expectedOperationId },
      );
      commitFor(expectedScope, expectedGeneration, (value) => ({
        ...value,
        result: executed.result,
        busyPhase: null,
        actionError: null,
        executionRetryAvailable: false,
      }));
    } catch (error) {
      commitFor(expectedScope, expectedGeneration, (value) => ({
        ...value,
        confirmation: selectedConfirmation,
        busyPhase: null,
        actionError: { phase: "execute", message: errorText(error) },
        executionRetryAvailable: !retrying && isRetryableCutoverError(error),
      }));
    } finally {
      if (
        scopeKeyRef.current === expectedScope
        && generationRef.current === expectedGeneration
      ) actionLockRef.current = false;
    }
  }

  async function confirmAndExecute() {
    const current = stateRef.current;
    if (
      !current.identity
      || !current.binding
      || !current.preview?.operation_id
      || current.busyPhase
      || actionLockRef.current
      || clarificationFields(current.preview).length > 0
    ) return;
    const expectedScope = scopeKey;
    const expectedGeneration = generationRef.current;
    const selectedBinding = current.binding;
    const selectedIdentity = current.identity;
    const expectedOperationId = current.preview.operation_id;
    actionLockRef.current = true;
    setSession((value) => value.scopeKey === expectedScope
      ? {
        ...value,
        busyPhase: "confirming",
        actionError: null,
        executionRetryAvailable: false,
        executionRetryUsed: false,
      }
      : value);
    let selectedConfirmation: CutoverConfirmationV1;
    try {
      const confirmed = await confirmCutover(selectedBinding, selectedIdentity);
      if (
        scopeKeyRef.current !== expectedScope
        || generationRef.current !== expectedGeneration
      ) return;
      selectedConfirmation = confirmed.confirmation;
    } catch (error) {
      commitFor(expectedScope, expectedGeneration, (value) => ({
        ...value,
        binding: null,
        busyPhase: null,
        actionError: {
          phase: "confirm",
          message: `${errorText(error)} Confirmation status is uncertain; compile a new plan before trying again.`,
        },
      }));
      if (
        scopeKeyRef.current === expectedScope
        && generationRef.current === expectedGeneration
      ) actionLockRef.current = false;
      return;
    }
    await executeConfirmed(
      selectedBinding,
      selectedIdentity,
      selectedConfirmation,
      expectedOperationId,
      expectedScope,
      expectedGeneration,
      false,
    );
  }

  async function retryExecution() {
    const current = stateRef.current;
    if (
      !current.identity
      || !current.binding
      || !current.confirmation
      || !current.preview?.operation_id
      || current.busyPhase
      || actionLockRef.current
      || !current.executionRetryAvailable
      || current.executionRetryUsed
    ) return;
    actionLockRef.current = true;
    await executeConfirmed(
      current.binding,
      current.identity,
      current.confirmation,
      current.preview.operation_id,
      scopeKey,
      generationRef.current,
      true,
    );
  }

  const value: AgentCutoverContextValue = {
    projectRoot,
    runId,
    state,
    changeRequestText,
    setClarificationAnswer,
    retryIdentity: () => setIdentityRetry((value) => value + 1),
    compilePlan,
    recompileWithClarifications,
    confirmAndExecute,
    retryExecution,
  };

  return (
    <AgentCutoverContext.Provider value={value}>
      {children}
    </AgentCutoverContext.Provider>
  );
}

export function AgentCutoverProvider({
  projectRoot,
  runId,
  enabled = true,
  children,
}: {
  projectRoot: string;
  runId: string;
  enabled?: boolean;
  children: ReactNode;
}) {
  const sharedContext = useContext(AgentCutoverContext);
  if (sharedContext) return <>{children}</>;
  return (
    <AgentCutoverProviderOwner projectRoot={projectRoot} runId={runId} enabled={enabled}>
      {children}
    </AgentCutoverProviderOwner>
  );
}

function traceState(
  complete: boolean,
  active: boolean,
  failed = false,
): "complete" | "active" | "pending" | "failed" {
  if (failed) return "failed";
  if (complete) return "complete";
  if (active) return "active";
  return "pending";
}

function TraceStep({
  label,
  state,
}: {
  label: string;
  state: "complete" | "active" | "pending" | "failed";
}) {
  const marker = state === "complete" ? "✓" : state === "active" ? "●" : state === "failed" ? "!" : "○";
  return (
    <div className="wb-agent-execution-trace__step" data-state={state}>
      <span aria-hidden="true">{marker}</span>
      <span>{label}</span>
    </div>
  );
}

function ExpandedComposer({ context }: { context: AgentCutoverContextValue }) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const { state } = context;
  const busy = state.busyPhase !== null;
  const canCompile = Boolean(state.identity && state.requestText.trim() && !busy);

  return (
    <div data-testid="agent-composer" className="wb-agent-composer wb-agent-terminal-composer">
      <div className="wb-agent-composer-input-row">
        <span className="wb-agent-terminal-input-marker" aria-hidden="true">❯</span>
        <textarea
          ref={inputRef}
          aria-label="Agent request"
          rows={1}
          value={state.requestText}
          placeholder="Ask about the current analysis or request a typed change"
          disabled={busy}
          onChange={(event) => context.changeRequestText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void context.compilePlan();
            }
          }}
        />
      </div>
      <div className="wb-agent-composer-actions">
        <div className="wb-agent-composer-actions-left">
          <button
            type="button"
            className="wb-agent-add-context"
            aria-label="Focus Agent request"
            onClick={() => inputRef.current?.focus()}
          >
            <span aria-hidden="true">＋</span>
          </button>
          <span className="wb-agent-composer-scope">
            {state.identity ? `${state.identity.project_ref} · ${context.runId}` : "Server identity required"}
          </span>
        </div>
        <div className="wb-agent-composer-actions-right">
          {busy && (
            <span className="wb-agent-session-status" role="status">
              {state.busyPhase}
            </span>
          )}
          <button
            type="button"
            className="wb-agent-send"
            aria-label="Compile plan"
            disabled={!canCompile}
            onClick={() => void context.compilePlan()}
          >
            <span aria-hidden="true">↑</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function AgentCutoverPanelContent() {
  const context = useContext(AgentCutoverContext);
  if (!context) return null;
  const { state } = context;
  const clarifications = clarificationFields(state.preview);
  const allClarificationsAnswered = clarifications.length > 0 && clarifications.every(
    (item) => Boolean(state.clarificationAnswers[item.field]?.trim()),
  );
  const busy = state.busyPhase !== null;
  const identityTrace = traceState(
    Boolean(state.identity),
    state.identityLoading,
    Boolean(state.identityError),
  );
  const planTrace = traceState(
    Boolean(state.preview),
    state.busyPhase === "compiling" || state.busyPhase === "clarifying",
    state.actionError?.phase === "compile",
  );
  const confirmationTrace = traceState(
    Boolean(state.confirmation),
    state.busyPhase === "confirming" || Boolean(state.binding && clarifications.length === 0),
    state.actionError?.phase === "confirm",
  );
  const executionTrace = traceState(
    Boolean(state.result),
    state.busyPhase === "executing",
    state.actionError?.phase === "execute",
  );

  return (
    <section
      data-testid="agent-cutover-panel"
      aria-label="Agent cutover panel"
      className="wb-agent-panel"
      aria-busy={busy || state.identityLoading}
    >
      <header className="wb-agent-cutover-header">
        <div>
          <strong>agent</strong>
          <span className="wb-agent-cutover-mode">server cutover</span>
        </div>
        <span data-testid="agent-scope-identity" className="wb-agent-cutover-scope">
          {state.identity
            ? `${state.identity.project_ref} · ${context.runId}`
            : state.identityLoading
              ? `Resolving server identity · ${context.runId}`
              : `Identity unavailable · ${context.runId}`}
        </span>
      </header>

      <div
        data-testid="agent-execution-trace"
        className="wb-agent-execution-trace"
        aria-label="Agent execution progress"
        aria-live="polite"
      >
        <TraceStep label="Server identity" state={identityTrace} />
        <TraceStep label="Plan preview" state={planTrace} />
        <TraceStep label="Confirmation" state={confirmationTrace} />
        <TraceStep label="Evidence" state={executionTrace} />
      </div>

      {state.identityError && (
        <div className="wb-agent-error-row">
          <div role="alert" className="wb-agent-error">{state.identityError}</div>
          <button
            type="button"
            className="wb-agent-proposal-revise"
            aria-label="Retry server identity"
            onClick={context.retryIdentity}
          >
            Retry
          </button>
        </div>
      )}
      {state.actionError && (
        <div role="alert" className="wb-agent-error">{state.actionError.message}</div>
      )}

      <div
        role="log"
        aria-label={`Agent history for ${context.runId}`}
        className="wb-agent-terminal"
      >
        {!state.submittedRequest && !state.preview && !state.result ? (
          <div data-testid="agent-empty" className="wb-agent-terminal-empty">
            <div className="wb-agent-cutover-empty-title">Start a task</div>
            <div>Describe the analysis in natural language. Workbench will show a server plan before confirmation.</div>
          </div>
        ) : (
          <div className="wb-agent-turn">
            {state.submittedRequest && (
              <div className="wb-agent-terminal-line" data-role="user">
                <span className="wb-agent-terminal-marker" aria-hidden="true">❯</span>
                <span className="wb-agent-terminal-content wb-agent-terminal-plain">
                  {state.submittedRequest}
                </span>
              </div>
            )}
            {state.busyPhase === "compiling" || state.busyPhase === "clarifying" ? (
              <div className="wb-agent-terminal-line" data-role="tool">
                <span className="wb-agent-terminal-marker" aria-hidden="true">⋮</span>
                <span>Compiling a server-owned typed plan…</span>
              </div>
            ) : null}
            {state.preview && (
              <div className="wb-agent-terminal-line" data-role="tool">
                <span className="wb-agent-terminal-marker" aria-hidden="true">✓</span>
                <span>
                  {clarifications.length > 0
                    ? `Server preview needs ${clarifications.length} clarification field${clarifications.length === 1 ? "" : "s"}.`
                    : state.binding
                      ? "Structured plan is ready for explicit confirmation."
                      : "Structured preview returned without an executable binding."}
                </span>
              </div>
            )}
            {state.confirmation && (
              <div className="wb-agent-terminal-line" data-role="tool">
                <span className="wb-agent-terminal-marker" aria-hidden="true">✓</span>
                <span>{`Server confirmation ${state.confirmation.confirmation_id}`}</span>
              </div>
            )}
            {state.result && (
              <div className="wb-agent-terminal-line" data-role="assistant">
                <span className="wb-agent-terminal-marker" aria-hidden="true">●</span>
                <span>{`Execution ${state.result.status}; formal evidence is available below.`}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {state.history.length > 0 && (
        <section
          data-testid="agent-task-history"
          className="wb-agent-task-history"
          aria-label="Previous Agent tasks"
        >
          <header>
            <span>Previous tasks</span>
            <span>{state.history.length}</span>
          </header>
          <ul>
            {state.history.slice().reverse().map((item, index) => (
              <li key={`${item.request}:${index}`}>
                <span>{item.request}</span>
                <small>{item.status}</small>
              </li>
            ))}
          </ul>
        </section>
      )}

      {state.preview && (
        <aside
          data-testid="agent-action-rail"
          aria-label="Agent actions"
          className="wb-agent-action-rail"
        >
          <article data-testid="agent-cutover-preview" className="wb-agent-proposal">
            <div className="wb-agent-proposal-header">
              <strong>{state.preview.operation_id ?? "Plan clarification"}</strong>
              <span>{state.preview.entrypoint}</span>
              <span className="wb-agent-proposal-status">
                {clarifications.length > 0
                  ? "needs input"
                  : state.result
                    ? state.result.status
                    : state.confirmation
                      ? "confirmed"
                      : state.binding
                        ? "preview"
                        : "not executable"}
              </span>
            </div>
            <dl className="wb-agent-plan-grid">
              {Object.entries(state.preview.plan_diff).length > 0 ? Object.entries(state.preview.plan_diff).map(
                ([key, value]) => (
                  <div className="wb-agent-plan-row" key={key}>
                    <dt>{fieldLabel(key)}</dt>
                    <dd><StructuredPlanValue value={value} path={key} /></dd>
                  </div>
                ),
              ) : (
                <div className="wb-agent-plan-row">
                  <dt>Plan</dt>
                  <dd className="wb-agent-plan-empty">The server returned an empty plan diff.</dd>
                </div>
              )}
            </dl>

            {clarifications.length > 0 && (
              <div className="wb-agent-clarifications" aria-label="Plan clarifications">
                <div className="wb-agent-proposal-detail">
                  Answer the server-required fields, then recompile the same request.
                </div>
                {clarifications.map((item) => {
                  const label = fieldLabel(item.field);
                  return (
                    <label className="wb-agent-clarification-field" key={item.field}>
                      <span>{label}</span>
                      <small>{item.message}</small>
                      {item.allowedValues.length > 0 ? (
                        <select
                          aria-label={label}
                          disabled={busy}
                          value={state.clarificationAnswers[item.field] ?? ""}
                          onChange={(event) => context.setClarificationAnswer(item.field, event.target.value)}
                        >
                          <option value="">Choose…</option>
                          {item.allowedValues.map((value) => <option key={value} value={value}>{value}</option>)}
                        </select>
                      ) : (
                        <input
                          aria-label={label}
                          disabled={busy}
                          value={state.clarificationAnswers[item.field] ?? ""}
                          onChange={(event) => context.setClarificationAnswer(item.field, event.target.value)}
                        />
                      )}
                    </label>
                  );
                })}
                <button
                  type="button"
                  className="wb-agent-proposal-confirm"
                  disabled={!allClarificationsAnswered || busy}
                  onClick={() => void context.recompileWithClarifications()}
                >
                  {state.busyPhase === "clarifying" ? "Recompiling…" : "Recompile plan"}
                </button>
              </div>
            )}

            {state.binding && clarifications.length === 0 && (
              <div className="wb-agent-confirmation-card">
                <div className="wb-agent-proposal-detail">
                  <strong>Server-bound proposal</strong>
                  <span>{state.binding.proposal_id}</span>
                </div>
                {state.confirmation && (
                  <div data-testid="agent-cutover-confirmation" className="wb-agent-proposal-detail">
                    {`Server confirmation: ${state.confirmation.confirmation_id}`}
                  </div>
                )}
                {!state.result && !state.confirmation && (
                  <button
                    type="button"
                    className="wb-agent-proposal-confirm"
                    disabled={busy}
                    onClick={() => void context.confirmAndExecute()}
                  >
                    {state.busyPhase === "confirming" || state.busyPhase === "executing"
                      ? "Working…"
                      : "Confirm and execute"}
                  </button>
                )}
                {!state.result
                  && state.confirmation
                  && state.actionError?.phase === "execute"
                  && state.executionRetryAvailable
                  && !state.executionRetryUsed && (
                  <button
                    type="button"
                    className="wb-agent-proposal-confirm"
                    disabled={busy}
                    onClick={() => void context.retryExecution()}
                  >
                    {state.busyPhase === "executing" ? "Retrying…" : "Retry execution"}
                  </button>
                )}
                {!state.result
                  && state.confirmation
                  && state.actionError?.phase === "execute"
                  && !state.executionRetryAvailable && (
                  <div className="wb-agent-proposal-detail">
                    Execution cannot be retried safely. Compile a new plan before trying again.
                  </div>
                )}
              </div>
            )}

            {state.result && (
              <div data-testid="agent-cutover-result" role="status" className="wb-agent-result-card">
                <div className="wb-agent-proposal-header">
                  <strong>{state.result.status}</strong>
                  <span className="wb-agent-proposal-status">evidence bound</span>
                </div>
                <dl className="wb-agent-result-grid">
                  <div><dt>Operation</dt><dd>{state.result.operation_id}</dd></div>
                  <div><dt>Execution instance</dt><dd>{state.result.execution_instance_hash}</dd></div>
                  <div><dt>Compilation</dt><dd>{state.result.compilation_record_id}</dd></div>
                </dl>
                {state.result.evidence_refs.length > 0 ? (
                  <ul className="wb-agent-evidence-list" aria-label="Evidence references">
                    {state.result.evidence_refs.map((reference) => <li key={reference}>{reference}</li>)}
                  </ul>
                ) : (
                  <div className="wb-agent-proposal-detail">No evidence references were returned.</div>
                )}
              </div>
            )}
          </article>
        </aside>
      )}

      <ExpandedComposer context={context} />
    </section>
  );
}

export function AgentCutoverPanel({
  projectRoot,
  runId,
}: {
  projectRoot: string;
  runId: string;
}) {
  const sharedContext = useContext(AgentCutoverContext);
  if (sharedContext) return <AgentCutoverPanelContent />;
  return (
    <AgentCutoverProvider projectRoot={projectRoot} runId={runId}>
      <AgentCutoverPanelContent />
    </AgentCutoverProvider>
  );
}

export function AgentCutoverComposer({ onExpand }: { onExpand: () => void }) {
  const context = useContext(AgentCutoverContext);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  if (!context) return null;
  const cutover = context;
  const { state } = cutover;
  const busy = state.busyPhase !== null;
  const canCompile = Boolean(state.identity && state.requestText.trim() && !busy);
  const hasActivity = Boolean(busy || state.preview || state.actionError || state.result);

  function expandAndCompile() {
    if (!canCompile) {
      onExpand();
      return;
    }
    onExpand();
    void cutover.compilePlan();
  }

  return (
    <div className="wb-agent-compact-composer-shell">
      {hasActivity && (
        <button
          type="button"
          className="wb-agent-compact-activity"
          aria-label="View Agent activity"
          onClick={onExpand}
        >
          <span>
            {state.result
              ? `Completed · ${state.result.status}`
              : state.actionError
                ? "Stopped · needs attention"
                : state.busyPhase
                  ? `Working · ${state.busyPhase}`
                  : "Plan ready · review before confirmation"}
          </span>
          <span aria-hidden="true">›</span>
        </button>
      )}
      <div className="wb-agent-compact-composer-row">
        <div data-testid="agent-compact-composer" className="wb-agent-compact-composer">
          <button
            type="button"
            className="wb-agent-add-context"
            aria-label="Focus Agent prompt"
            onClick={() => inputRef.current?.focus()}
          >
            <span aria-hidden="true">＋</span>
          </button>
          <textarea
            ref={inputRef}
            aria-label="Ask Agent"
            rows={1}
            value={state.requestText}
            placeholder="Ask about the current analysis"
            disabled={busy}
            onChange={(event) => cutover.changeRequestText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                expandAndCompile();
              }
            }}
          />
          <div className="wb-agent-compact-composer__actions">
            <span className="wb-agent-session-status">
              {state.identity ? "server" : state.identityLoading ? "identity…" : "offline"}
            </span>
            <button
              type="button"
              aria-label="Send to Agent"
              className="wb-agent-send"
              disabled={!canCompile}
              onClick={expandAndCompile}
            >
              <span aria-hidden="true">↑</span>
            </button>
          </div>
        </div>
        <button
          type="button"
          className="wb-agent-compact-composer__expand"
          aria-label="Expand Agent panel"
          title="Expand Agent panel"
          onClick={onExpand}
        >
          <span aria-hidden="true">▲</span>
        </button>
      </div>
    </div>
  );
}
