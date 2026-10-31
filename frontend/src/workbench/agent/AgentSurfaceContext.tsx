import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, type PostEstimationResult } from "../../api";
import { useLineage } from "../../lineage/LineageContext";
import { buildAskAIContextPacket } from "../../lineage/detail/sections/askAiContextPacket";
import { resolveNodeOperationContext } from "../../lineage/api/nodeOperationContext";
import { focusFromWorkbench, resolveFocus } from "./focus";
import { detectLlmProviderModels, fetchLlmConfig, fetchLlmProviders, updateLlmProvider } from "../../llm/llmApi";
import type { LlmConfigInfo, LlmProvider } from "../../llm/llmTypes";
import { useForest } from "../ForestContext";
import { useWorkbench } from "../WorkbenchStateProvider";
import { useAgentNavigationOptional } from "./agentNavigation";
import {
  approveAgentPlan, getAgentPlan, getAgentPlanVerification, patchAgentPlan, getAgentTurnState, continueAgentTurn, resumeAgentTurn, queueAgentTurnMessage,
  abortAgentTurn,
  createAgentSession,
  createAgentForkProposal,
  confirmAgentProposal,
  declineAgentProposal,
  fallbackProjectContext,
  getAgentEvents,
  getAgentCapabilities,
  getAgentOperationProjection,
  getAgentSession,
  getAgentSessionProjection,
  forkAgentSession,
  pinAgentChapter,
  reconcileAgentOperation,
  rewindAgentSession,
  compactAgentSession,
  unpinAgentChapter,
  reviseAgentProposal,
  sendAgentTurn,
} from "./agentApi";
import type {
  AgentPlan, AgentPlanPatch, AgentPlanVersion, AgentPlanVerification, AgentDurableTurn,
  AgentChapter,
  AgentSession,
  AgentContextPacket,
  AgentCapabilityCatalog,
  AgentEvent,
  AgentHierarchyNode,
  AgentMessage,
  AgentModelOption,
  AgentModelSettings,
  AgentNavigationRef,
  AgentOperationRecord,
  AgentProposal,
  AgentRole,
} from "./agentTypes";
import type { ForestViewModel } from "../../lineage/api/graphViewTypes";
import { groupPendingProposals } from "./proposalGroups";
import { updateActiveToolCalls, type ActiveToolCall } from "./toolActivity";

/** Terminal operation-record states — reconcile polling stops here. */
const TERMINAL_OPERATION_STATUSES = new Set([
  "completed",
  "failed",
  "stale",
  "cancelled",
]);

export interface AgentOperationStatus {
  record_id: string;
  operation_id: string;
  status: string;
  target_run_id: string | null;
  /** Program output captured from a sandboxed operation (code.execute). */
  stdout: string | null;
  /** Results of declared post-estimation steps in a completed workflow.
   *
   * A confirmed workflow that reports only "completed" leaves the question
   * that prompted it unanswered, so the transcript carries the numbers it
   * produced. */
  postEstimationResults: PostEstimationResult[];
  diff_ref: Record<string, unknown> | null;
  verification: Record<string, unknown>;
  diffFocused: boolean;
}

function toOperationStatus(
  record: AgentOperationRecord,
  diffFocused = false,
): AgentOperationStatus {
  const outputs = record.outputs as
    | {
        target_run_id?: unknown;
        stdout?: unknown;
        post_estimation_results?: unknown;
      }
    | undefined;
  const target = outputs && typeof outputs === "object" ? outputs.target_run_id : null;
  const stdout = outputs && typeof outputs === "object" ? outputs.stdout : null;
  const rawResults =
    outputs && typeof outputs === "object" ? outputs.post_estimation_results : null;
  const rawDiff = record.diff_ref;
  const rawVerification = record.verification;
  return {
    record_id: record.record_id,
    operation_id: record.operation_id,
    status: record.status,
    target_run_id: typeof target === "string" ? target : null,
    stdout: typeof stdout === "string" && stdout.length > 0 ? stdout : null,
    postEstimationResults: Array.isArray(rawResults)
      ? (rawResults.filter(
          (entry) =>
            entry !== null &&
            typeof entry === "object" &&
            typeof (entry as PostEstimationResult).operation_id === "string" &&
            typeof (entry as PostEstimationResult).result === "object",
        ) as PostEstimationResult[])
      : [],
    diff_ref: rawDiff && typeof rawDiff === "object"
      ? rawDiff as Record<string, unknown>
      : null,
    verification: rawVerification && typeof rawVerification === "object"
      ? rawVerification as Record<string, unknown>
      : {},
    diffFocused,
  };
}

const MAX_GLOBAL_PROJECT_NODES = 120;
const MAX_GLOBAL_PROJECT_RUNS = 200;

function boundedGlobalProjectContext(
  projectRoot: string,
  forest: { forest: ForestViewModel; activeRunId: string },
): AgentContextPacket {
  const view = forest.forest;
  const nodes = view.nodes.slice(0, MAX_GLOBAL_PROJECT_NODES).map((node) => ({
    node_key: node.nodeKey,
    kind: node.kind,
    stage: node.stage,
    title: node.title,
    summary: node.summary ?? null,
    runs: node.runs.slice(0, 12),
  }));
  const runs = Array.from(new Set(view.nodes.flatMap((node) => node.runs)))
    .slice(0, MAX_GLOBAL_PROJECT_RUNS);
  const heads = view.heads.map((head) => ({
    run_id: head.runId,
    head_node_hash: head.headNodeHash,
    status: head.status,
    rerun_of: head.rerunOf,
    created_at: head.createdAt,
  }));
  const headFingerprint = view.heads
    .map((head) => `${head.runId}:${head.headNodeHash ?? "none"}:${head.status ?? "unknown"}`)
    .join("|");

  return {
    packet_version: "agent-project-context/v1",
    context_fingerprint: `project:${projectRoot}:heads:${headFingerprint}:nodes:${view.nodes.length}`,
    scope: "global_project",
    project_overview: {
      family_count: view.familyCount,
      run_count: view.familyRunCount,
      active_head_run_id: forest.activeRunId,
      heads,
      runs,
      nodes,
      truncation: {
        nodes_truncated: view.nodes.length > MAX_GLOBAL_PROJECT_NODES,
        runs_truncated: runs.length >= MAX_GLOBAL_PROJECT_RUNS,
        raw_datasets_included: false,
        full_artifacts_included: false,
      },
    },
    response_guardrails: {
      advisory_text_only: true,
      executable_actions_allowed: false,
      graph_mutations_allowed: false,
      file_reads_allowed: false,
      must_disclose_visibility_limits: true,
    },
  };
}

export interface AgentSurfaceContextValue {
  executionMode?: "ask" | "auto";
  setExecutionMode?: (mode: "ask" | "auto") => void;
  /** Reveal the current plan without approving or executing it. */
  showPlan?: () => void;
  planViewRequest?: number;
  plan?: AgentPlan | null;
  planVersions?: AgentPlanVersion[];
  planBusy?: boolean;
  planError?: string | null;
  planVerification?: AgentPlanVerification | null;
  planVerificationBusy?: boolean;
  planVerificationError?: string | null;
  verifyPlan?: () => Promise<void>;
  refreshPlan?: () => Promise<void>;
  savePlan?: (draft: AgentPlanPatch) => Promise<void>;
  approvePlan?: (version: number) => Promise<void>;
  approveAndRunPlan?: (version: number) => Promise<void>;
  durableTurns?: AgentDurableTurn[];
  providerSteps?: AgentEvent[];
  continueTurn?: () => Promise<void>;
  resumeTurn?: (turnId: string) => Promise<void>;
  queueTurnMessage?: (kind: "steer" | "follow_up", text: string) => Promise<void>;
  queueMessageBusy?: boolean;
  queueMessageNotice?: string | null;
  messages: AgentMessage[];
  prompt: string;
  setPrompt: (value: string) => void;
  executionPolicy?: "auto_read_only" | "proposal_only";
  setExecutionPolicy?: (value: "auto_read_only" | "proposal_only") => void;
  sendPrompt: (value?: string) => Promise<void>;
  abortTurn: () => Promise<void>;
  isSubmitting: boolean;
  error: string | null;
  scopeLabel: string;
  contextUsedTokens: number;
  contextWindowTokens: number | null;
  contextPercent: number | null;
  /** The model declares no window; ``contextWindowTokens`` is the server's assumption. */
  contextWindowAssumed?: boolean;
  /** Above this the earlier conversation is summarized before the next step. */
  compactAtTokens?: number | null;
  /** Summarize the earlier conversation now (optionally keeping something in particular). */
  compactConversation?: (focus?: string) => Promise<void>;
  compacting?: boolean;
  /** The conversation shown, once it has been started. */
  sessionId?: string | null;
  /** Start a new conversation for this view (the current one stays in the list). */
  newConversation?: () => void;
  /** Continue another of the project's conversations in this view. */
  openConversation?: (sessionId: string) => void;
  model: string;
  modelOptions: AgentModelOption[];
  setModel: (value: string) => Promise<void>;
  /** Save the thinking effort or context window of one of the active provider's models. */
  setModelSettings?: (requestModel: string, patch: AgentModelSettings) => Promise<void>;
  sessionStatus: string;
  proposals: AgentProposal[];
  confirmationBusyId: string | null;
  confirmProposal: (proposalId: string) => Promise<void>;
  confirmProposals?: (proposalIds: string[]) => Promise<void>;
  declineProposal: (proposalId: string, reason?: string) => Promise<boolean>;
  reviseProposal: (
    proposalId: string,
    baseRevision: number,
    changes: Record<string, unknown>,
  ) => Promise<boolean>;
  forkFromMessage: (entryId: string, sourceRef: AgentNavigationRef) => Promise<boolean>;
  /** Messages pinned as chapters in this conversation. */
  chapters?: AgentChapter[];
  /** Go back to just before one of your messages; its text returns to the input. */
  rewindTo?: (entryId: string) => Promise<void>;
  /** Continue in a new conversation sharing this one up to a message. */
  forkConversation?: (entryId: string) => Promise<void>;
  pinChapter?: (entryId: string, title: string) => Promise<void>;
  unpinChapter?: (entryId: string) => Promise<void>;
  openNavigation?: (ref: AgentNavigationRef) => boolean;
  navigationLinks: AgentNavigationRef[];
  hierarchy: AgentHierarchyNode | null;
  activeOperation: AgentOperationStatus | null;
  eventCursor: number;
  lastEventType: string | null;
  activeToolCalls?: ActiveToolCall[];
  liveResponseText: string;
  activeTurnStartedAt?: number | null;
  capabilityCatalog?: AgentCapabilityCatalog | null;
}

export const AgentSurfaceContext = createContext<AgentSurfaceContextValue | null>(null);

export function useAgentSurface(): AgentSurfaceContextValue {
  const context = useContext(AgentSurfaceContext);
  if (!context) throw new Error("useAgentSurface must be used inside AgentSurfaceProvider");
  return context;
}

export function useAgentSurfaceOptional(): AgentSurfaceContextValue | null {
  return useContext(AgentSurfaceContext);
}

// Which conversation a node or page continues. Kept across browser restarts
// (it was per-tab sessionStorage, so closing the tab "lost" the conversation);
// a value left in sessionStorage by an older build is carried over once.
function readConversation(key: string): string | null {
  try {
    const stored = localStorage.getItem(key);
    if (stored) return stored;
    const legacy = sessionStorage.getItem(key);
    if (legacy) {
      localStorage.setItem(key, legacy);
      sessionStorage.removeItem(key);
    }
    return legacy;
  } catch {
    return null;
  }
}

function writeConversation(key: string, sessionId: string | null): void {
  try {
    if (sessionId) localStorage.setItem(key, sessionId);
    else localStorage.removeItem(key);
    sessionStorage.removeItem(key);
  } catch {
    // Storage can be unavailable (private windows); the conversation itself is on disk.
  }
}

export function AgentSurfaceProvider({
  projectRoot,
  runId,
  children,
}: {
  projectRoot: string;
  runId: string;
  children: ReactNode;
}) {
  const { model: graphModel } = useLineage();
  const forest = useForest();
  const workbench = useWorkbench();
  const navigation = useAgentNavigationOptional();
  const [searchParams, setSearchParams] = useSearchParams();
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [chapters, setChapters] = useState<AgentChapter[]>([]);
  const draftKey = `workbench:agent-draft:${projectRoot}`;
  const [prompt, setPromptState] = useState(() => {
    try {
      return sessionStorage.getItem(draftKey) ?? "";
    } catch {
      return "";
    }
  });
  const latestPromptRef = useRef(prompt);
  latestPromptRef.current = prompt;
  const setPrompt = useCallback((value: string) => {
    setPromptState(value);
    try {
      if (value) sessionStorage.setItem(draftKey, value);
      else sessionStorage.removeItem(draftKey);
    } catch {
      // Storage may be unavailable; the draft still lives for this page.
    }
  }, [draftKey]);
  const [{executionMode, executionPolicy}, setExecutionSettings] = useState<{
    executionMode: "ask" | "auto"; executionPolicy: "auto_read_only" | "proposal_only";
  }>({executionMode: "ask", executionPolicy: "proposal_only"});
  const setExecutionMode = useCallback((mode: "ask" | "auto") => {
    setExecutionSettings(current => ({executionMode: mode,
      executionPolicy: mode === "auto" ? "auto_read_only" : current.executionPolicy}));
  }, []);
  const setExecutionPolicy = useCallback((policy: "auto_read_only" | "proposal_only") => {
    setExecutionSettings(current => ({executionPolicy: policy,
      executionMode: policy === "proposal_only" ? "ask" : current.executionMode}));
  }, []);
  const [planViewRequest, setPlanViewRequest] = useState(0);
  const showPlan = useCallback(() => setPlanViewRequest(request => request + 1), []);
  const [plan, setPlan] = useState<AgentPlan|null>(null);
  const latestPlanRef = useRef(plan);
  latestPlanRef.current = plan;
  const [planVersions, setPlanVersions] = useState<AgentPlanVersion[]>([]);
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState<string|null>(null);
  const [planVerification, setPlanVerification] = useState<AgentPlanVerification | null>(null);
  const [planVerificationBusy, setPlanVerificationBusy] = useState(false);
  const [planVerificationError, setPlanVerificationError] = useState<string | null>(null);
  const planVerificationRevision = useRef(0);
  const [durableTurns, setDurableTurns] = useState<AgentDurableTurn[]>([]);
  const [queueMessageBusy, setQueueMessageBusy] = useState(false);
  const [queueMessageNotice, setQueueMessageNotice] = useState<string|null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  useEffect(() => { setPlanViewRequest(0); }, [sessionId]);
  useEffect(() => {
    planVerificationRevision.current += 1;
    setPlanVerification(null);setPlanVerificationBusy(false);setPlanVerificationError(null);
  }, [sessionId, plan?.plan_id, plan?.version]);
  const planReadRevisionRef = useRef(0);
  const turnReadRevisionRef = useRef(0);
  const currentSessionRef = useRef(sessionId);
  currentSessionRef.current = sessionId;
  const [persistedSessionStatus, setSessionStatus] = useState("idle");
  // How full the next request is, as the server builds it (tool results and
  // standing instructions included, earlier summarized parts not).
  const [serverContext, setServerContext] = useState<AgentSession["context"] | null>(null);
  const [compacting, setCompacting] = useState(false);
  // Bumped to load another conversation (or none) for the same view.
  const [conversationVersion, setConversationVersion] = useState(0);
  const restoredSessionRef = useRef<string | null>(null);
  const [proposals, setProposals] = useState<AgentProposal[]>([]);
  const latestProposalsRef = useRef(proposals);
  latestProposalsRef.current = proposals;
  const [confirmationBusyId, setConfirmationBusyId] = useState<string | null>(null);
  const [activeOperation, setActiveOperation] = useState<AgentOperationStatus | null>(null);
  const [eventCursor, setEventCursor] = useState(0);
  const [providerSteps, setProviderSteps] = useState<AgentEvent[]>([]);
  const [lastEventType, setLastEventType] = useState<string | null>(null);
  const [activeToolCalls, setActiveToolCalls] = useState<ActiveToolCall[]>([]);
  const [liveResponseText, setLiveResponseText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Session metadata and replayed progress can outlive the runtime. Confirmed
  // interrupted checkpoints take precedence, including over a late session poll.
  // An explicit Resume still owns its live request while recovery is in flight.
  const sessionStatus = !isSubmitting && durableTurns.length > 0
    && durableTurns.every(turn => turn.status === "interrupted")
    ? "interrupted" : persistedSessionStatus;
  const [activeTurnStartedAt, setActiveTurnStartedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [navigationLinks, setNavigationLinks] = useState<AgentNavigationRef[]>([]);
  const [hierarchy, setHierarchy] = useState<AgentHierarchyNode | null>(null);
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [llmConfig, setLlmConfig] = useState<LlmConfigInfo | null>(null);
  const [capabilityCatalog, setCapabilityCatalog] = useState<AgentCapabilityCatalog | null>(null);
  const activeTurnControllerRef = useRef<AbortController | null>(null);
  const activeTurnSessionIdRef = useRef<string | null>(null);
  const confirmationControllerRef = useRef<AbortController | null>(null);
  useEffect(() => () => { confirmationControllerRef.current?.abort(); }, []);

  const selectedKey = workbench.state.selectedKey;
  const graphNodes = Array.isArray(graphModel?.nodes) ? graphModel.nodes : [];
  const selectedNode = graphNodes.find((node) => node.nodeKey === selectedKey) ?? null;
  // One Agent; its scope follows the focus (agent/focus.ts): a page's declared
  // focus (the Data page's dataset), else the graph selection -- in the run
  // that owns the node, not the active run's head -- else the project.
  const declaredFocus = workbench.state.agentFocus;
  // Whichever changed last wins: a node selected after a run switch is the
  // focus even in another run; a run switched after a selection outranks the
  // leftover detail tab. A restored URL selection is authoritative on first render.
  const activeRunForFocus = forest?.activeRunId ?? runId;
  const lastFocusChange = useRef<"selection" | "run">(selectedKey ? "selection" : "run");
  const previousSelection = useRef(selectedKey);
  const previousActiveRun = useRef(activeRunForFocus);
  if (previousSelection.current !== selectedKey) {
    lastFocusChange.current = "selection";
    previousSelection.current = selectedKey;
  }
  if (previousActiveRun.current !== activeRunForFocus) {
    lastFocusChange.current = "run";
    previousActiveRun.current = activeRunForFocus;
  }
  const staleSelectionRunId = lastFocusChange.current === "run"
    && selectedNode !== null
    && forest
    && !forest.forest.nodes.find((node) => node.nodeKey === selectedKey)?.runs.includes(activeRunForFocus)
    ? activeRunForFocus
    : null;
  const resolvedFocus = useMemo(
    () => resolveFocus(
      focusFromWorkbench({ projectRoot, declared: declaredFocus, selectedKey, staleSelectionRunId }),
      { projectRoot, activeRunId: activeRunForFocus, forest: forest?.forest ?? null },
    ),
    [activeRunForFocus, declaredFocus, forest, projectRoot, selectedKey, staleSelectionRunId],
  );
  const scopeRunId = resolvedFocus.runId || runId;
  const scopedForestNodeKey = resolvedFocus.nodeKey;
  const scopedSelectedNode = scopedForestNodeKey && forest
    ? forest.forest.nodes.find((node) => node.nodeKey === scopedForestNodeKey) ?? selectedNode
    : selectedNode;
  const isGlobalScope = resolvedFocus.role === "main";
  const contextPacket = useMemo<AgentContextPacket>(() => {
    if (isGlobalScope && forest) {
      return boundedGlobalProjectContext(projectRoot, forest);
    }
    if (forest && scopedForestNodeKey) {
      const resolved = resolveNodeOperationContext({
        forest: forest.forest,
        selected_forest_node_key: scopedForestNodeKey,
        // The chain of the run that owns the focused node.
        active_head_run_id: scopeRunId,
      });
      if (resolved.ok) return buildAskAIContextPacket(resolved.context);
    }
    return fallbackProjectContext(scopeRunId, selectedKey);
  }, [forest, isGlobalScope, projectRoot, scopeRunId, scopedForestNodeKey, selectedKey]);

  const contextFingerprint = typeof contextPacket.context_fingerprint === "string"
    && contextPacket.context_fingerprint
    ? contextPacket.context_fingerprint
    : `${runId}:${selectedKey ?? "none"}`;
  const baseStorageKey = isGlobalScope
    ? `workbench:agent-session:${projectRoot}:main:${encodeURIComponent(contextFingerprint)}`
    : `workbench:agent-session:${projectRoot}:${scopeRunId}:${encodeURIComponent(contextFingerprint)}`;
  // Report and plan context can share a run fingerprint with a graph node.
  // Keep legacy node history, but never reuse its authoritative focus for a page.
  const storageKey = ["report", "plan", "dataset"].includes(resolvedFocus.focus.kind)
    ? `${baseStorageKey}:focus:${resolvedFocus.focus.kind}:${encodeURIComponent(resolvedFocus.focus.id)}`
    : baseStorageKey;
  const linkedSessionId = ["report", "plan", "dataset"].includes(resolvedFocus.focus.kind)
    ? null : searchParams.get("agent_session") || null;
  const linkedOperationId = searchParams.get("operation") || null;
  const linkedDiffFocused = searchParams.get("diff") === "1";
  const sessionScope = linkedSessionId
    ? `workbench:agent-linked:${projectRoot}:${linkedSessionId}`
    : storageKey;
  const activeScopeRef = useRef(sessionScope);
  const optimisticMessageCounterRef = useRef(0);
  const eventCursorRef = useRef(0);
  const activeEventCommandRef = useRef<{ commandId: string | null; startedAt: number | null } | null>(null);
  const applyEvents = useCallback((events: AgentEvent[]) => {
    const unseen = events
      .filter((event) => event.seq > eventCursorRef.current)
      .sort((left, right) => left.seq - right.seq);
    if (unseen.length === 0) return;
    const latest = unseen[unseen.length - 1];
    const observations = unseen.filter(event => event.event_type === "provider_step");
    if (observations.length) setProviderSteps(current => [...current, ...observations]);
    eventCursorRef.current = latest.seq;
    setActiveToolCalls(current => updateActiveToolCalls(current, unseen));
    for (const event of unseen) {
      if (event.event_type === "turn_start") {
        const commandId = event.command_id ?? null;
        if (!activeEventCommandRef.current || activeEventCommandRef.current.commandId !== commandId) {
          const startedAt = Date.parse(event.created_at);
          activeEventCommandRef.current = { commandId, startedAt: Number.isFinite(startedAt) ? startedAt : null };
        }
        // Tool and numeric-rewrite rounds share the request's clock. The
        // session/turn status owns whether the timer is visible or running.
        setActiveTurnStartedAt(activeEventCommandRef.current.startedAt);
      }
      if (event.event_type === "message_start") {
        setLiveResponseText("");
      } else if (event.event_type === "message_update") {
        const delta = event.payload.delta;
        if (typeof delta === "string" && delta) {
          setLiveResponseText((current) => `${current}${delta}`);
        }
      } else if (
        event.event_type === "message_end"
        || event.event_type === "aborted"
        || event.event_type === "error"
      ) {
        setLiveResponseText("");
      }
    }
    setEventCursor((current) => Math.max(current, latest.seq));
    // Usage observations do not change the work currently visible to the user.
    const activity = [...unseen].reverse().find(event => event.event_type !== "provider_step");
    if (activity) setLastEventType(activity.event_type);
  }, []);
  const replayEvents = useCallback(async (
    activeSessionId: string,
    afterSeq: number,
    scope: string,
  ) => {
    const result = await getAgentEvents(projectRoot, activeSessionId, afterSeq);
    if (activeScopeRef.current !== scope || currentSessionRef.current !== activeSessionId || !Array.isArray(result.events)) return;
    applyEvents(result.events);
    return result.events.filter(event => event.seq > afterSeq);
  }, [applyEvents, projectRoot]);
  const refreshNavigation = useCallback(async (
    activeSessionId: string,
    scope: string,
  ) => {
    try {
      const result = await getAgentSessionProjection(projectRoot, activeSessionId);
      if (activeScopeRef.current !== scope) return;
      const links = result?.projection?.links;
      if (Array.isArray(links)) setNavigationLinks(links);
      setHierarchy(result?.projection?.hierarchy ?? null);
    } catch {
      // Navigation is an optional projection; a session remains usable when
      // the read-only projection endpoint is unavailable.
    }
  }, [projectRoot]);
  useEffect(() => {
    let cancelled = false;
    activeTurnControllerRef.current?.abort();
    activeTurnControllerRef.current = null;
    activeTurnSessionIdRef.current = null;
    confirmationControllerRef.current?.abort();
    confirmationControllerRef.current = null;
    activeScopeRef.current = sessionScope;
    optimisticMessageCounterRef.current = 0;
    currentSessionRef.current = null;
    planReadRevisionRef.current += 1;turnReadRevisionRef.current += 1;
    setSessionId(null);
    setExecutionMode("ask");latestPlanRef.current=null;setPlan(null);setPlanVersions([]);setPlanError(null);setPlanBusy(false);
    setPlanVerification(null);setPlanVerificationBusy(false);setPlanVerificationError(null);
    setDurableTurns([]);setQueueMessageNotice(null);setQueueMessageBusy(false);
    setMessages([]);
    setServerContext(null);
    setChapters([]);
    setProposals([]);
    setSessionStatus("idle");
    // The unsent draft is the person's, not the session's: it stays when the
    // view (and with it the Agent's scope) changes (user review 3).
    setError(null);
    setNavigationLinks([]);
    setHierarchy(null);
    setActiveOperation(null);
    setIsSubmitting(false);
    setActiveTurnStartedAt(null);
    activeEventCommandRef.current = null;
    setConfirmationBusyId(null);
    setEventCursor(0);
    setProviderSteps([]);
    eventCursorRef.current = 0;
    setLastEventType(null);
    setActiveToolCalls([]);
    setLiveResponseText("");
    const restored = restoredSessionRef.current;
    const stored = restored ?? linkedSessionId ?? readConversation(storageKey);
    if (restored && !linkedSessionId) writeConversation(storageKey, restored);
    if (!stored) return () => { cancelled = true; };
    getAgentSession(projectRoot, stored)
      .then(async (session) => {
        if (cancelled) return;
        if (restoredSessionRef.current === restored) restoredSessionRef.current = null;
        setSessionId(session.session_id);
        setMessages(session.messages);
        setServerContext(session.context ?? null);
        setChapters(session.chapters ?? []);
        setProposals(session.proposals ?? []);
        setSessionStatus(session.status ?? "idle");
        setExecutionMode(session.execution_mode ?? "ask");
        await refreshNavigation(session.session_id, sessionScope);
        if (linkedOperationId) {
          try {
            const operation = await getAgentOperationProjection(
              projectRoot,
              session.session_id,
              linkedOperationId,
            );
            if (!cancelled && activeScopeRef.current === sessionScope) {
              setActiveOperation(toOperationStatus(operation.operation, linkedDiffFocused));
            }
          } catch {
            // The linked session remains usable when an operation focus is stale.
          }
        }
        try {
          await replayEvents(session.session_id, 0, sessionScope);
        } catch {
          // A session remains usable when its optional event replay is unavailable.
        }
      })
    .catch((reason: unknown) => {
        if (cancelled) return;
        // Only a conversation the server no longer has is forgotten: a
        // restarting backend or a dropped connection must not lose the
        // binding, which now outlives the tab.
        if ((reason as Partial<ApiError> | null)?.status === 404) {
          if (!linkedSessionId) writeConversation(storageKey, null);
          return;
        }
        setError("The conversation could not be loaded. It is still saved; reload to try again.");
      });
    return () => { cancelled = true; };
  }, [conversationVersion, linkedDiffFocused, linkedOperationId, linkedSessionId, projectRoot, refreshNavigation, replayEvents, sessionScope, storageKey]);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    let refreshPending = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const events = await replayEvents(sessionId, eventCursorRef.current, sessionScope);
        if (cancelled) return;
        // Other entry points can continue a session while this page is idle or
        // awaiting approval. Keep tailing; token deltas and usage observations
        // use their existing projections without downloading the full history.
        if (events?.some(event => !["message_update", "provider_step"].includes(event.event_type))) refreshPending = true;
        if (refreshPending) {
          const result = await getAgentSession(projectRoot, sessionId);
          if (!cancelled && currentSessionRef.current === sessionId && activeScopeRef.current === sessionScope) {
            setMessages(result.messages);setProposals(result.proposals ?? []);setSessionStatus(result.status ?? "idle");
            refreshPending = false;
          }
        }
      } catch {
        // The request-response turn remains authoritative if polling fails.
      }
      if (!cancelled) timer = setTimeout(poll, 500);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [isSubmitting, replayEvents, sessionId, sessionScope, projectRoot]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchLlmProviders(), fetchLlmConfig()])
      .then(([providerResult, config]) => {
        if (cancelled) return;
        setProviders(Array.isArray(providerResult?.providers) ? providerResult.providers : []);
        setLlmConfig(config && typeof config === "object" ? config : null);
      })
      .catch(() => {
        if (!cancelled) setLlmConfig(null);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getAgentCapabilities(projectRoot)
      .then((catalog) => {
        if (!cancelled) setCapabilityCatalog(catalog);
      })
      .catch(() => {
        if (!cancelled) setCapabilityCatalog(null);
      });
    return () => { cancelled = true; };
  }, [projectRoot]);

  // v1.9.1: what the active provider's model list reports (window, thinking efforts,
  // image input) updates its configured models, once per provider per page; a
  // provider that reports nothing, or a failure, leaves them as they are.
  const detectedProviders = useRef(new Set<string>());
  useEffect(() => {
    const providerId = llmConfig?.provider_id;
    if (!providerId || detectedProviders.current.has(providerId)) return;
    detectedProviders.current.add(providerId);
    let cancelled = false;
    Promise.resolve()
      .then(() => detectLlmProviderModels(providerId))
      .then(async (updated) => {
        const refreshed = await fetchLlmConfig();
        if (cancelled || !updated?.id) return;
        setProviders((current) => current.map((provider) => provider.id === updated.id ? updated : provider));
        if (refreshed && typeof refreshed === "object") setLlmConfig(refreshed);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [llmConfig?.provider_id]);

  const activeProvider = providers.find((provider) => provider.id === llmConfig?.provider_id);
  const modelOptions = useMemo(() => {
    const options = Array.isArray(activeProvider?.models)
      ? activeProvider.models.map((model) => ({ ...model }))
      : [];
    if (options.length > 0) return options;
    return llmConfig?.model
      ? [{
          display_name: llmConfig.model,
          request_model: llmConfig.model,
          context_window_tokens: llmConfig.context_window_tokens,
          supports_1m: llmConfig.supports_1m,
          supports_vision: llmConfig.supports_vision,
          // No provider record to save a choice on: the menu shows no thinking or limit control.
          reasoning_efforts: [],
          reasoning_effort: null,
          context_limit_tokens: null,
        }]
      : [];
  }, [activeProvider, llmConfig?.model]);
  const model = llmConfig?.model ?? modelOptions[0]?.request_model ?? "Not configured";
  // The server's estimate of the next request when there is a session; the
  // visible messages alone leave out tool results and the standing context.
  const contextUsedTokens = useMemo(
    () => Math.max(
      1,
      serverContext
        ? serverContext.estimated_tokens + Math.ceil(prompt.length / 4)
        : Math.ceil(JSON.stringify(contextPacket).length / 4)
          + messages.reduce((sum, item) => sum + Math.ceil(item.content.length / 4), 0)
          + Math.ceil(prompt.length / 4),
    ),
    [contextPacket, messages, prompt, serverContext],
  );
  // Resolve a real context capacity so the ring is a live gauge, not decoration.
  // Prefer the active model's declared window; otherwise 1,000,000 when the
  // model advertises the 1M context; otherwise the config-level value; then
  // the window the server assumes for compaction, shown as an assumption.
  const activeModelRecord = modelOptions.find((option) => option.request_model === model);
  const ONE_MILLION = 1_000_000;
  const modelWindow = activeModelRecord?.context_window_tokens ?? (activeModelRecord?.supports_1m ? ONE_MILLION : null);
  const limit = activeModelRecord?.context_limit_tokens ?? null;
  const declaredWindow =
    (modelWindow !== null && limit !== null ? Math.min(modelWindow, limit) : modelWindow ?? limit)
    ?? llmConfig?.context_window_tokens
    ?? (llmConfig?.supports_1m ? ONE_MILLION : null)
    ?? (serverContext?.window_declared ? serverContext.window_tokens : null);
  const contextWindowAssumed = declaredWindow === null && Boolean(serverContext);
  const contextWindowTokens = declaredWindow ?? serverContext?.window_tokens ?? null;
  const contextPercent = contextWindowTokens
    ? Math.min(100, (contextUsedTokens / contextWindowTokens) * 100)
    : null;
  const linkedTarget = linkedSessionId ? proposals[proposals.length - 1]?.target : null;
  const linkedNode = linkedTarget && forest?.forest.nodes.find(node =>
    node.opNodeId === linkedTarget.node_ref && node.runs.includes(String(linkedTarget.run_id)),
  );
  const scopeLabel = linkedSessionId
    ? linkedNode ? linkedNode.title : "Linked Agent session"
    : isGlobalScope && resolvedFocus.focus.kind === "project"
    ? `Global Agent · ${forest?.forest.familyRunCount ?? 0} runs · ${forest?.forest.familyCount ?? 0} families`
    : resolvedFocus.label;

  const setModel = useCallback(async (value: string) => {
    if (!activeProvider || value === llmConfig?.model) return;
    setError(null);
    try {
      const updated = await updateLlmProvider(activeProvider.id, { model: value });
      setProviders((current) => current.map((provider) => provider.id === updated.id ? updated : provider));
      setLlmConfig((current) => current ? { ...current, model: updated.model } : current);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to update Agent model");
    }
  }, [activeProvider, llmConfig?.model]);

  const setModelSettings = useCallback(async (requestModel: string, patch: AgentModelSettings) => {
    if (!activeProvider) return;
    setError(null);
    try {
      const models = (activeProvider.models ?? []).map((item) =>
        item.request_model === requestModel ? { ...item, ...patch } : item);
      const updated = await updateLlmProvider(activeProvider.id, { models });
      setProviders((current) => current.map((provider) => provider.id === updated.id ? updated : provider));
      // The config's window is the working one: the model's, capped by the limit just saved.
      setLlmConfig(await fetchLlmConfig());
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to update the model settings");
    }
  }, [activeProvider, llmConfig?.model]);

  const latestAdmissionRef = useRef({isSubmitting, sessionStatus, durableTurns, executionMode});
  latestAdmissionRef.current = {isSubmitting, sessionStatus, durableTurns, executionMode};

  const refreshPlan = useCallback(async () => {
    if (!sessionId || activeScopeRef.current !== sessionScope) return;
    const scope = sessionScope;
    const revision = ++planReadRevisionRef.current;
    try {
      const result = await getAgentPlan(projectRoot, sessionId);
      if (activeScopeRef.current !== scope || currentSessionRef.current !== sessionId || revision !== planReadRevisionRef.current) return;
      latestPlanRef.current=result.plan;setPlan(result.plan);setPlanVersions(result.versions);setPlanError(null);
    } catch (reason) {
      if (activeScopeRef.current === scope && currentSessionRef.current === sessionId && revision === planReadRevisionRef.current) setPlanError(reason instanceof Error ? reason.message : "Could not load plan.");
    }
  }, [projectRoot,sessionId,sessionScope]);
  const verifyPlan = useCallback(async () => {
    if (!sessionId || !latestPlanRef.current || planVerificationBusy) return;
    const scope = sessionScope;
    const revision = ++planVerificationRevision.current;
    setPlanVerification(null);setPlanVerificationError(null);setPlanVerificationBusy(true);
    try {
      const result = await getAgentPlanVerification(projectRoot, sessionId);
      if (activeScopeRef.current !== scope || currentSessionRef.current !== sessionId || revision !== planVerificationRevision.current) return;
      if (latestPlanRef.current?.plan_id !== result.plan_id || latestPlanRef.current.version !== result.plan_version) {
        setPlanVerificationError("The plan changed. Reload it and check the current deliverables.");
        return;
      }
      setPlanVerification(result);
    } catch (reason) {
      if (activeScopeRef.current === scope && currentSessionRef.current === sessionId && revision === planVerificationRevision.current)
        setPlanVerificationError(reason instanceof Error ? reason.message : "Could not verify registered deliverables.");
    } finally {
      if (activeScopeRef.current === scope && currentSessionRef.current === sessionId && revision === planVerificationRevision.current) setPlanVerificationBusy(false);
    }
  }, [projectRoot,sessionId,sessionScope,planVerificationBusy]);
  const refreshTurnState = useCallback(async () => {
    if (!sessionId || activeScopeRef.current !== sessionScope) return;
    const scope = sessionScope;
    const revision = ++turnReadRevisionRef.current;
    try {
      const result = await getAgentTurnState(projectRoot,sessionId);
      if (activeScopeRef.current === scope && currentSessionRef.current === sessionId && revision === turnReadRevisionRef.current) setDurableTurns(result.turns);
    } catch (reason) {
      if (activeScopeRef.current === scope && currentSessionRef.current === sessionId && revision === turnReadRevisionRef.current) setError(reason instanceof Error ? reason.message : "Could not load turn recovery state.");
    }
  }, [projectRoot,sessionId,sessionScope]);
  useEffect(() => { void refreshPlan();void refreshTurnState(); }, [refreshPlan,refreshTurnState,eventCursor,isSubmitting]);
  const savePlan = useCallback(async (draft: AgentPlanPatch) => {
    if (!sessionId || planBusy) return;
    const scope = sessionScope;
    planReadRevisionRef.current += 1;
    setPlanBusy(true);setPlanError(null);
    try {
      const result = await patchAgentPlan(projectRoot,sessionId,draft);
      if (activeScopeRef.current === scope && currentSessionRef.current === sessionId) {latestPlanRef.current=result.plan;setPlan(result.plan);await refreshPlan();}
    } finally { if (activeScopeRef.current === scope && currentSessionRef.current === sessionId) setPlanBusy(false); }
  }, [projectRoot,sessionId,sessionScope,planBusy,refreshPlan]);
  const approvePlanVersion = useCallback(async (version: number): Promise<AgentPlan | null> => {
    if (!sessionId || planBusy) return null;
    const scope = sessionScope;
    planReadRevisionRef.current += 1;
    setPlanBusy(true);setPlanError(null);
    try {
      const result = await approveAgentPlan(projectRoot,sessionId,version);
      if (activeScopeRef.current !== scope || currentSessionRef.current !== sessionId) return null;
      latestPlanRef.current=result.plan;setPlan(result.plan);
      await refreshPlan();
      return result.plan;
    } catch (reason) {
      if (activeScopeRef.current === scope && currentSessionRef.current === sessionId) setPlanError(reason instanceof Error ? reason.message : "Could not approve plan.");
      return null;
    } finally { if (activeScopeRef.current === scope && currentSessionRef.current === sessionId) setPlanBusy(false); }
  }, [projectRoot,sessionId,sessionScope,planBusy,refreshPlan]);
  const approvePlan = useCallback(async (version: number) => { await approvePlanVersion(version); }, [approvePlanVersion]);
  const queueTurnMessage = useCallback(async (kind: "steer"|"follow_up", text: string) => {
    if (!sessionId || !text.trim() || queueMessageBusy || activeScopeRef.current !== sessionScope) return;
    const scope = sessionScope;
    setQueueMessageBusy(true);setQueueMessageNotice(null);
    try {
      await queueAgentTurnMessage(projectRoot,sessionId,kind,text.trim());
      if (activeScopeRef.current === scope && currentSessionRef.current === sessionId) {if (latestPromptRef.current === text) setPrompt("");setQueueMessageNotice(kind === "steer" ? "Direction queued for the next tool boundary." : "Follow-up queued after this turn.");}
    } catch(reason) {
      if (activeScopeRef.current === scope && currentSessionRef.current === sessionId) setError(reason instanceof Error ? reason.message : "Could not queue message.");
    } finally {if (activeScopeRef.current === scope && currentSessionRef.current === sessionId) setQueueMessageBusy(false);}
  }, [projectRoot,sessionId,sessionScope,queueMessageBusy,setPrompt]);
  const runContinuation = useCallback(async (turnId?: string) => {
    if (!sessionId || isSubmitting || activeTurnControllerRef.current) return;
    if (!turnId && (["running","working","cancelling"].includes(sessionStatus) || durableTurns.length)) return;
    const scope = sessionScope;
    if (activeScopeRef.current !== scope) return;
    const controller = new AbortController();
    activeTurnControllerRef.current=controller;activeTurnSessionIdRef.current=sessionId;
    setIsSubmitting(true);setActiveTurnStartedAt(Date.now());setError(null);
    try {
      const result = turnId ? await resumeAgentTurn(projectRoot,sessionId,turnId,controller.signal) : await continueAgentTurn(projectRoot,sessionId,{
        execution_mode:executionMode,execution_policy:executionPolicy,...(isGlobalScope ? {context_packet:contextPacket} : {}),
      },controller.signal);
      if (activeScopeRef.current !== scope || currentSessionRef.current !== sessionId || controller.signal.aborted) return;
      setMessages(result.session.messages);setServerContext(result.session.context ?? null);
      setChapters(result.session.chapters ?? []);setProposals(result.session.proposals ?? []);setSessionStatus(result.status ?? "idle");
      if (result.session.execution_mode) setExecutionMode(result.session.execution_mode);
      await refreshNavigation(sessionId,scope);await replayEvents(sessionId,eventCursorRef.current,scope);
    } catch(reason) {
      if (activeScopeRef.current === scope && currentSessionRef.current === sessionId) setError(controller.signal.aborted ? null : reason instanceof Error ? reason.message : "Could not continue turn.");
    } finally {
      if(activeTurnControllerRef.current===controller){activeTurnControllerRef.current=null;activeTurnSessionIdRef.current=null;}
      if(activeScopeRef.current===scope && currentSessionRef.current===sessionId){setIsSubmitting(false);setActiveTurnStartedAt(null);void refreshTurnState();void refreshPlan();}
    }
  }, [projectRoot,sessionId,sessionScope,isSubmitting,sessionStatus,durableTurns,executionMode,executionPolicy,isGlobalScope,contextPacket,refreshNavigation,replayEvents,refreshTurnState,refreshPlan]);
  const continueTurn = useCallback(() => runContinuation(),[runContinuation]);
  const resumeTurn = useCallback((turnId: string) => runContinuation(turnId),[runContinuation]);

  const approveAndRunPlan = useCallback(async (version: number) => {
    const scope = sessionScope;
    const admissible = () => {
      const current = latestAdmissionRef.current;
      return current.executionMode === "auto" && !current.isSubmitting && !activeTurnControllerRef.current
        && !["running","working","cancelling"].includes(current.sessionStatus) && current.durableTurns.length === 0
        && activeScopeRef.current === scope && currentSessionRef.current === sessionId;
    };
    if (!sessionId || !admissible() || latestPlanRef.current?.version !== version) return;
    const approved = await approvePlanVersion(version);
    if (!approved || !admissible()) return;
    const current = latestPlanRef.current;
    if (approved.version !== version || approved.approved_version !== version || approved.status !== "approved"
        || current?.plan_id !== approved.plan_id || current.version !== version
        || current.approved_version !== version || current.status !== "approved") {
      setPlanError("The plan changed. Review the current version before running it.");
      return;
    }
    await runContinuation();
  }, [sessionId,sessionScope,approvePlanVersion,runContinuation]);

  const sendPrompt = useCallback(async (value = prompt) => {
    const question = value.trim();
    if (!question || isSubmitting || activeTurnControllerRef.current || confirmationControllerRef.current || ["running","working","cancelling"].includes(sessionStatus)) return;
    if (durableTurns.length) {setError("An unfinished turn needs recovery. Resume the original turn before sending a new request.");return;}
    const requestScope = sessionScope;
    if (activeScopeRef.current !== requestScope) return;
    optimisticMessageCounterRef.current += 1;
    const optimisticMessage: AgentMessage = {
      entry_id: `local-user-${optimisticMessageCounterRef.current}`,
      at: new Date().toISOString(),
      role: "user",
      content: question,
      name: null,
      stop_reason: null,
      error: null,
      navigation: [],
    };
    // The transcript is the conversation surface, so a sent turn must be
    // visible before the provider round-trip completes. The durable response
    // replaces this optimistic entry with its canonical entry_id; if the
    // provider fails, the user turn remains visible beside the error.
    setMessages((current) => [...current, optimisticMessage]);
    setPrompt("");
    setIsSubmitting(true);
    setActiveTurnStartedAt(Date.now());
    setError(null);
    setLiveResponseText("");
    setActiveToolCalls([]);
    const controller = new AbortController();
    activeTurnControllerRef.current = controller;
    activeTurnSessionIdRef.current = null;
    try {
      let activeSessionId = sessionId;
      if (!activeSessionId) {
        const role: AgentRole = isGlobalScope ? "main" : "chain";
        const created = await createAgentSession(projectRoot, {
          role,
          chain_id: isGlobalScope
            ? `project:${projectRoot}`
            : forest
              ? `chain:${scopeRunId}`
              : `run:${scopeRunId}`,
          run_id: isGlobalScope ? undefined : scopeRunId,
          context_packet: contextPacket,
          focus: {
            kind: resolvedFocus.focus.kind,
            id: resolvedFocus.focus.id,
            ...(resolvedFocus.runId ? { run_id: resolvedFocus.runId } : {}),
            label: scopeLabel,
          },
        });
        activeSessionId = created.session_id;
        if (activeScopeRef.current !== requestScope) return;
        setSessionId(activeSessionId);
        if (!linkedSessionId) writeConversation(storageKey, activeSessionId);
      }
      if (controller.signal.aborted) return;
      activeTurnSessionIdRef.current = activeSessionId;
      // The project-level Agent gets the current overview with every turn, so
      // runs made since the session began are visible to it.
      const result = await sendAgentTurn(
        projectRoot,
        activeSessionId,
        question,
        controller.signal,
        isGlobalScope ? (contextPacket as Record<string, unknown>) : undefined,
        executionPolicy,
        executionMode,
      );
      if (activeScopeRef.current !== requestScope || activeTurnControllerRef.current !== controller || controller.signal.aborted) return;
      setMessages(result.session.messages);
      setServerContext(result.session.context ?? null);
      setChapters(result.session.chapters ?? []);
      setProposals(result.session.proposals ?? []);
      setSessionStatus(result.status ?? "idle");
      await refreshNavigation(activeSessionId, requestScope);
      try {
        await replayEvents(activeSessionId, eventCursor, requestScope);
      } catch {
        // The durable session response still contains the completed turn.
      }
    } catch (requestError) {
      if (activeScopeRef.current !== requestScope) return;
      if (controller.signal.aborted) {
        setError(null);
        setSessionStatus("cancelled");
      } else {
        setError(requestError instanceof Error ? requestError.message : "Agent turn failed");
        setSessionStatus("failed");
      }
    } finally {
      if (activeTurnControllerRef.current === controller) {
        activeTurnControllerRef.current = null;
        activeTurnSessionIdRef.current = null;
      }
      if (activeScopeRef.current === requestScope) {
        setIsSubmitting(false);
        setActiveTurnStartedAt(null);
      }
    }
  }, [contextPacket, eventCursor, executionPolicy, executionMode, sessionStatus, durableTurns, forest, isGlobalScope, isSubmitting, linkedSessionId, projectRoot, prompt, refreshNavigation, replayEvents, resolvedFocus, runId, scopeLabel, scopeRunId, sessionId, sessionScope, storageKey]);

  const abortTurn = useCallback(async () => {
    const controller = activeTurnControllerRef.current;
    const requestScope = sessionScope;
    // Stopping confirmation suppresses the next model request; the operation's
    // durable receipt still determines whether its effect completed.
    if (confirmationControllerRef.current) {
      confirmationControllerRef.current.abort();
      if (!controller) return;
    }
    if (!isSubmitting && !["running","working","cancelling"].includes(sessionStatus)) return;
    const activeSessionId = activeTurnSessionIdRef.current ?? sessionId;
    setError(null);
    setSessionStatus("cancelling");
    if (activeSessionId) {
      try {
        await abortAgentTurn(projectRoot, activeSessionId);
      } catch (reason) {
        // Only this typed response proves the server has no active owner.
        // A transport/server failure must leave the original request attached.
        if (!(reason instanceof ApiError && reason.status === 409 && reason.code === "AGENT_TURN_NOT_ACTIVE")) {
          if (activeScopeRef.current !== requestScope || currentSessionRef.current !== activeSessionId
              || (controller && activeTurnControllerRef.current !== controller)) return;
          const detail = reason instanceof Error ? ` ${reason.message}` : "";
          setError(`Could not confirm a stop. The server may still be running. Retry Stop or inspect the original turn before starting another request.${detail}`);
          setSessionStatus((current) => current === "cancelling"
            ? (isSubmitting || sessionStatus === "cancelling" ? "running" : sessionStatus) : current);
          return;
        }
      }
    }
    if (activeScopeRef.current !== requestScope
        || (activeSessionId && currentSessionRef.current !== activeSessionId)
        || (controller && activeTurnControllerRef.current !== controller)) return;
    controller?.abort();
    if (controller) setSessionStatus("cancelled");
  }, [isSubmitting, projectRoot, sessionId, sessionStatus, sessionScope]);

  const confirmProposals = useCallback(async (proposalIds: string[]) => {
    if (!sessionId || confirmationBusyId !== null || confirmationControllerRef.current) return;
    const requestScope = sessionScope;
    if (activeScopeRef.current !== requestScope) return;
    const selected = proposalIds.map(id => proposals.find(item => item.proposal_id === id));
    if (!selected.length || new Set(proposalIds).size !== selected.length
        || selected.some(item => !item || item.status !== "pending")) return;
    const batch = selected as AgentProposal[];
    if (batch.length > 1 && (batch.some(item => item.session_id !== sessionId) || !groupPendingProposals(proposals, capabilityCatalog).some(group =>
      batch.every(item => group.includes(item))))) {
      setError("These proposals require separate confirmations.");
      return;
    }
    const ownership = contextPacket.ownership;
    const activeHead = ownership && typeof ownership === "object"
      ? (ownership as { active_head_run_id?: unknown }).active_head_run_id
      : undefined;
    const controller = new AbortController();
    confirmationControllerRef.current = controller;
    setConfirmationBusyId(batch[0].proposal_id);
    setError(null);
    const ownsSession = () => activeScopeRef.current === requestScope && currentSessionRef.current === sessionId;
    try {
      for (const proposal of batch) {
        if (controller.signal.aborted || !ownsSession()) return;
        const latest = latestProposalsRef.current.find(item => item.proposal_id === proposal.proposal_id);
        if (!latest || latest.status !== "pending" || latest.revision !== proposal.revision || latest.fingerprint !== proposal.fingerprint) {
          throw new Error("A selected proposal changed. Review it before confirming again.");
        }
        const proposalId = proposal.proposal_id;
        setConfirmationBusyId(proposalId);
        const proposalHead = proposal.preconditions.active_head_run_id;
        const activeHeadRunId = typeof proposalHead === "string" && proposalHead
          ? proposalHead
          : typeof activeHead === "string" && activeHead ? activeHead
          : forest?.activeRunId ?? runId;
        const result = await confirmAgentProposal(projectRoot, sessionId, proposalId, {
          revision: proposal.revision,
          fingerprint: proposal.fingerprint,
          active_head_run_id: activeHeadRunId,
        });
        if (!ownsSession()) return;
        setProposals((current) => current.map((item) => (
          item.proposal_id === proposalId ? result.proposal : item
        )));
        // Confirmation EXECUTES (design §8.2): surface the running operation
        // and poll the idempotent reconcile endpoint until the backend proves a
        // terminal state. The forest's own polling picks up the child run.
        let operation = toOperationStatus(result.operation);
        setActiveOperation(operation);
        // Keep the real approval/initial operation receipt, but Stop or a
        // closed surface ends observation; it does not cancel the operation.
        if (controller.signal.aborted) return;
        while (!TERMINAL_OPERATION_STATUSES.has(operation.status)) {
          if (controller.signal.aborted || !ownsSession()) return;
          await new Promise<void>((resolve) => {
            const finish = () => {
              clearTimeout(timer);
              controller.signal.removeEventListener("abort", finish);
              resolve();
            };
            const timer = setTimeout(finish, 1500);
            controller.signal.addEventListener("abort", finish, { once: true });
          });
          if (controller.signal.aborted || !ownsSession()) return;
          const reconciled = await reconcileAgentOperation(
            projectRoot,
            sessionId,
            operation.record_id,
          );
          if (controller.signal.aborted || !ownsSession()) return;
          operation = toOperationStatus(reconciled.operation);
          setActiveOperation(operation);
        }
        await refreshNavigation(sessionId, requestScope);
        if (!ownsSession()) return;
        if (operation.status !== "completed") {
          setError(`Operation ${proposalId} ${operation.status}. Remaining proposals were not run.`);
          return;
        }
      }
      if (!controller.signal.aborted && ownsSession()) await runContinuation();
    } catch (requestError) {
      if (!ownsSession()) return;
      setError(requestError instanceof Error ? requestError.message : "Proposal confirmation failed");
    } finally {
      if (confirmationControllerRef.current === controller) confirmationControllerRef.current = null;
      if (ownsSession()) setConfirmationBusyId(null);
    }
  }, [capabilityCatalog, confirmationBusyId, contextPacket, forest?.activeRunId, projectRoot, proposals, refreshNavigation, runContinuation, runId, sessionId, sessionScope]);
  const confirmProposal = useCallback((proposalId: string) => confirmProposals([proposalId]), [confirmProposals]);

  const declineProposal = useCallback(async (proposalId: string, reason?: string) => {
    if (!sessionId || confirmationBusyId !== null) return false;
    const requestScope = sessionScope;
    if (activeScopeRef.current !== requestScope) return false;
    const proposal = proposals.find((item) => item.proposal_id === proposalId);
    if (!proposal || proposal.status !== "pending") return false;
    setConfirmationBusyId(proposalId);
    setError(null);
    try {
      const result = await declineAgentProposal(projectRoot, sessionId, proposalId, reason);
      if (activeScopeRef.current !== requestScope) return false;
      setProposals((current) => current.map((item) => (
        item.proposal_id === proposalId ? result.proposal : item
      )));
      await refreshNavigation(sessionId, requestScope);
      await replayEvents(sessionId, eventCursor, requestScope);
      return true;
    } catch (requestError) {
      if (activeScopeRef.current === requestScope) {
        setError(requestError instanceof Error ? requestError.message : "Proposal decline failed");
      }
      return false;
    } finally {
      if (activeScopeRef.current === requestScope) setConfirmationBusyId(null);
    }
  }, [confirmationBusyId, eventCursor, projectRoot, proposals, refreshNavigation, replayEvents, sessionId, sessionScope]);

  const reviseProposal = useCallback(async (
    proposalId: string,
    baseRevision: number,
    changes: Record<string, unknown>,
  ) => {
    if (!sessionId || confirmationBusyId !== null) return false;
    const requestScope = sessionScope;
    if (activeScopeRef.current !== requestScope) return false;
    const proposal = proposals.find((item) => item.proposal_id === proposalId);
    if (!proposal || proposal.status !== "pending") return false;
    setConfirmationBusyId(proposalId);
    setError(null);
    try {
      const result = await reviseAgentProposal(projectRoot, sessionId, proposalId, {
        base_revision: baseRevision,
        changes,
      });
      if (activeScopeRef.current !== requestScope) return false;
      setProposals((current) => current.map((item) => (
        item.proposal_id === proposalId ? result.proposal : item
      )));
      await refreshNavigation(sessionId, requestScope);
      await replayEvents(sessionId, eventCursor, requestScope);
      return true;
    } catch (requestError) {
      if (activeScopeRef.current === requestScope) {
        setError(requestError instanceof Error ? requestError.message : "Proposal revision failed");
      }
      return false;
    } finally {
      if (activeScopeRef.current === requestScope) setConfirmationBusyId(null);
    }
  }, [confirmationBusyId, eventCursor, projectRoot, proposals, refreshNavigation, replayEvents, sessionId, sessionScope]);

  const forkFromMessage = useCallback(async (
    entryId: string,
    sourceRef: AgentNavigationRef,
  ) => {
    if (!sessionId || confirmationBusyId !== null) return false;
    if (sourceRef.kind !== "graph_node") return false;
    const sourceRunId = sourceRef.href.run_id;
    const sourceNodeRef = sourceRef.href.node_ref;
    if (!sourceRunId || !sourceNodeRef) return false;
    const requestScope = sessionScope;
    if (activeScopeRef.current !== requestScope) return false;
    const activeHeadRunId = forest?.activeRunId ?? runId;
    const busyId = `fork:${entryId}`;
    setConfirmationBusyId(busyId);
    setError(null);
    try {
      const result = await createAgentForkProposal(projectRoot, {
        session_id: sessionId,
        source_run_id: sourceRunId,
        source_node_ref: sourceNodeRef,
        source_session_entry_id: entryId,
        active_head_run_id: activeHeadRunId,
      });
      if (activeScopeRef.current !== requestScope) return false;
      setProposals((current) => [
        ...current.filter((item) => item.proposal_id !== result.proposal.proposal_id),
        result.proposal,
      ]);
      navigation?.(result.navigation);
      await refreshNavigation(sessionId, requestScope);
      await replayEvents(sessionId, eventCursor, requestScope);
      return true;
    } catch (requestError) {
      if (activeScopeRef.current === requestScope) {
        setError(requestError instanceof Error ? requestError.message : "Agent fork proposal failed");
      }
      return false;
    } finally {
      if (activeScopeRef.current === requestScope) setConfirmationBusyId(null);
    }
  }, [confirmationBusyId, eventCursor, forest, navigation, projectRoot, refreshNavigation, replayEvents, runId, sessionId, sessionScope]);

  // Conversation history: rewind, fork and chapters (user review 3). A
  // rewind keeps the later turns in the session log; a fork becomes the
  // conversation this view continues; both put a message back in the input
  // when they go back before it.
  const showSession = useCallback((session: AgentSession) => {
    setMessages(session.messages);
    setServerContext(session.context ?? null);
    setChapters(session.chapters ?? []);
    setProposals(session.proposals ?? []);
    setSessionStatus(session.status ?? "idle");
    setExecutionMode(session.execution_mode ?? "ask");
  }, []);
  const historyAction = useCallback(async (run: () => Promise<void>, failure: string) => {
    if (isSubmitting) return;
    setError(null);
    try {
      await run();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : failure);
    }
  }, [isSubmitting]);
  const rewindTo = useCallback((entryId: string) => historyAction(async () => {
    if (!sessionId) return;
    const scope = sessionScope;
    const change = await rewindAgentSession(projectRoot, sessionId, entryId);
    if (activeScopeRef.current !== scope || currentSessionRef.current !== sessionId) return;
    restoredSessionRef.current = change.session.session_id;
    writeConversation(storageKey, change.session.session_id);
    if (linkedSessionId) {
      const params = new URLSearchParams(searchParams);
      params.set("agent_session", change.session.session_id);
      params.delete("operation");params.delete("diff");
      setSearchParams(params, {replace:true});
    }
    if (change.lineage) {
      if (change.lineage.run_id) forest?.setActiveRunId(change.lineage.run_id);
      const focus = change.lineage.focus;
      workbench.dispatch.setAgentFocus(focus ? {kind:focus.kind,id:focus.id,runId:focus.run_id ?? undefined} : null);
    }
    setSessionId(change.session.session_id);
    showSession(change.session);
    if (change.restored_prompt) setPrompt(change.restored_prompt);
    setConversationVersion(value => value + 1);
  }, "Could not restore the analysis"), [historyAction, projectRoot, sessionId, sessionScope, storageKey,
    linkedSessionId, searchParams, setSearchParams, forest, workbench.dispatch, setPrompt, showSession]);
  const forkConversation = useCallback((entryId: string) => historyAction(async () => {
    if (!sessionId) return;
    const change = await forkAgentSession(projectRoot, sessionId, entryId);
    setSessionId(change.session.session_id);
    if (!linkedSessionId) writeConversation(storageKey, change.session.session_id);
    showSession(change.session);
    if (change.restored_prompt) setPrompt(change.restored_prompt);
    await refreshNavigation(change.session.session_id, sessionScope);
  }, "Could not fork the conversation"), [historyAction, linkedSessionId, projectRoot, refreshNavigation, sessionId, sessionScope, setPrompt, showSession, storageKey]);
  const pinChapter = useCallback((entryId: string, title: string) => historyAction(async () => {
    if (!sessionId) return;
    showSession(await pinAgentChapter(projectRoot, sessionId, entryId, title));
  }, "Could not pin the chapter"), [historyAction, projectRoot, sessionId, showSession]);
  const unpinChapter = useCallback((entryId: string) => historyAction(async () => {
    if (!sessionId) return;
    showSession(await unpinAgentChapter(projectRoot, sessionId, entryId));
  }, "Could not remove the chapter"), [historyAction, projectRoot, sessionId, showSession]);
  const compactConversation = useCallback((focus?: string) => historyAction(async () => {
    if (!sessionId) return;
    setCompacting(true);
    try {
      showSession(await compactAgentSession(projectRoot, sessionId, focus));
    } finally {
      setCompacting(false);
    }
  }, "Could not summarize the conversation"), [historyAction, projectRoot, sessionId, showSession]);
  // Conversations as a list: this view continues the one chosen here until
  // another is chosen or a new one is started.
  const switchConversation = useCallback((nextSessionId: string | null) => {
    if (isSubmitting) return;
    writeConversation(storageKey, nextSessionId);
    if (searchParams.get("agent_session")) {
      const next = new URLSearchParams(searchParams);
      next.delete("agent_session");
      next.delete("operation");
      next.delete("diff");
      setSearchParams(next, { replace: true });
    }
    setConversationVersion((version) => version + 1);
  }, [isSubmitting, searchParams, setSearchParams, storageKey]);
  const newConversation = useCallback(() => switchConversation(null), [switchConversation]);
  const openConversation = useCallback((nextSessionId: string) => switchConversation(nextSessionId), [switchConversation]);

  const value = useMemo<AgentSurfaceContextValue>(() => ({
    executionMode,setExecutionMode,showPlan,planViewRequest,plan,planVersions,planBusy,planError,refreshPlan,savePlan,approvePlan,approveAndRunPlan,
    planVerification,planVerificationBusy,planVerificationError,verifyPlan,
    durableTurns,continueTurn,resumeTurn,queueTurnMessage,queueMessageBusy,queueMessageNotice,
    messages,
    prompt,
    setPrompt,
    executionPolicy,
    setExecutionPolicy,
    sendPrompt,
    abortTurn,
    isSubmitting,
    error,
    scopeLabel,
    contextUsedTokens,
    contextWindowTokens,
    contextPercent,
    contextWindowAssumed,
    compactAtTokens: serverContext?.compact_at_tokens ?? null,
    compactConversation,
    compacting,
    sessionId,
    newConversation,
    openConversation,
    model,
    modelOptions,
    setModel,
    setModelSettings,
    sessionStatus,
    proposals,
    confirmationBusyId,
    confirmProposal,
    confirmProposals,
    declineProposal,
    reviseProposal,
    forkFromMessage,
    chapters,
    rewindTo,
    forkConversation,
    pinChapter,
    unpinChapter,
    openNavigation: navigation ?? undefined,
    navigationLinks,
    hierarchy,
    activeOperation,
    eventCursor,providerSteps,
    lastEventType,
    activeToolCalls,
    liveResponseText,
    activeTurnStartedAt,
    capabilityCatalog,
  }), [
    executionMode,showPlan,planViewRequest,plan,planVersions,planBusy,planError,refreshPlan,savePlan,approvePlan,approveAndRunPlan,
    planVerification,planVerificationBusy,planVerificationError,verifyPlan,
    durableTurns,continueTurn,resumeTurn,queueTurnMessage,queueMessageBusy,queueMessageNotice,
    activeOperation,
    contextPercent,
    contextUsedTokens,
    contextWindowTokens,
    contextWindowAssumed,
    serverContext,
    compactConversation,
    compacting,
    sessionId,
    newConversation,
    openConversation,
    error,
    isSubmitting,
    messages,
    navigationLinks,
    hierarchy,
    model,
    modelOptions,
    prompt,
    executionPolicy,
    scopeLabel,
    sendPrompt,
    abortTurn,
    setModel,
    setModelSettings,
    sessionStatus,
    proposals,
    confirmationBusyId,
    confirmProposal,
    confirmProposals,
    declineProposal,
    reviseProposal,
    forkFromMessage,
    chapters,
    rewindTo,
    forkConversation,
    pinChapter,
    unpinChapter,
    navigation,
    eventCursor,providerSteps,
    lastEventType,
    activeToolCalls,
    liveResponseText,
    activeTurnStartedAt,
    capabilityCatalog,
  ]);

  return <AgentSurfaceContext.Provider value={value}>{children}</AgentSurfaceContext.Provider>;
}
