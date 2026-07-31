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
import type { PostEstimationResult } from "../../api";
import { useLineage } from "../../lineage/LineageContext";
import { buildAskAIContextPacket } from "../../lineage/detail/sections/askAiContextPacket";
import { resolveNodeOperationContext } from "../../lineage/api/nodeOperationContext";
import { fetchLlmConfig, fetchLlmProviders, updateLlmProvider } from "../../llm/llmApi";
import type { LlmConfigInfo, LlmProvider } from "../../llm/llmTypes";
import { useForest } from "../ForestContext";
import { useWorkbench } from "../WorkbenchStateProvider";
import { useAgentNavigationOptional } from "./agentNavigation";
import {
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
  reconcileAgentOperation,
  reviseAgentProposal,
  sendAgentTurn,
} from "./agentApi";
import type {
  AgentContextPacket,
  AgentCapabilityCatalog,
  AgentEvent,
  AgentHierarchyNode,
  AgentMessage,
  AgentModelOption,
  AgentNavigationRef,
  AgentOperationRecord,
  AgentProposal,
  AgentRole,
} from "./agentTypes";
import type { ForestViewModel } from "../../lineage/api/graphViewTypes";

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

function runFocusModelNodeKey(
  forest: { forest: ForestViewModel; activeRunId: string },
  selectedKey: string | null,
): string | null {
  const selectedNode = selectedKey
    ? forest.forest.nodes.find((node) => node.nodeKey === selectedKey)
    : undefined;
  // Detail tabs can outlive a run-rail selection. Only let an actual selected
  // node scope a Chain Agent when it belongs to the active run; otherwise the
  // active head is the authoritative run focus.
  if (selectedNode?.runs.includes(forest.activeRunId)) {
    return selectedNode.nodeKey;
  }
  // The run rail uses a `run:<id>` pseudo-selection.  It is a navigation
  // focus, not an executable node identity; bind the Agent to the active
  // model node before sending the session packet.
  if (selectedKey !== null && !selectedKey.startsWith("run:") && !selectedNode) return null;
  const activeHead = forest.forest.heads.find(
    (head) => head.runId === forest.activeRunId,
  );
  const headModel = activeHead
    ? forest.forest.nodes.find(
        (node) =>
          node.nodeHash === activeHead.headNodeHash &&
          (node.kind === "model" || node.stage === "model"),
      )
    : undefined;
  if (headModel) return headModel.nodeKey;
  const activeModel = forest.forest.nodes.find(
    (node) =>
      node.runs.includes(forest.activeRunId) &&
      (node.kind === "model" || node.stage === "model"),
  );
  return activeModel?.nodeKey ?? null;
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
  messages: AgentMessage[];
  prompt: string;
  setPrompt: (value: string) => void;
  sendPrompt: (value?: string) => Promise<void>;
  abortTurn: () => Promise<void>;
  isSubmitting: boolean;
  error: string | null;
  scopeLabel: string;
  contextUsedTokens: number;
  contextWindowTokens: number | null;
  contextPercent: number | null;
  model: string;
  modelOptions: AgentModelOption[];
  setModel: (value: string) => Promise<void>;
  sessionStatus: string;
  proposals: AgentProposal[];
  confirmationBusyId: string | null;
  confirmProposal: (proposalId: string) => Promise<void>;
  declineProposal: (proposalId: string, reason?: string) => Promise<boolean>;
  reviseProposal: (
    proposalId: string,
    baseRevision: number,
    changes: Record<string, unknown>,
  ) => Promise<boolean>;
  forkFromMessage: (entryId: string, sourceRef: AgentNavigationRef) => Promise<boolean>;
  openNavigation?: (ref: AgentNavigationRef) => boolean;
  navigationLinks: AgentNavigationRef[];
  hierarchy: AgentHierarchyNode | null;
  activeOperation: AgentOperationStatus | null;
  eventCursor: number;
  lastEventType: string | null;
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
  const [searchParams] = useSearchParams();
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [prompt, setPrompt] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState("idle");
  const [proposals, setProposals] = useState<AgentProposal[]>([]);
  const [confirmationBusyId, setConfirmationBusyId] = useState<string | null>(null);
  const [activeOperation, setActiveOperation] = useState<AgentOperationStatus | null>(null);
  const [eventCursor, setEventCursor] = useState(0);
  const [lastEventType, setLastEventType] = useState<string | null>(null);
  const [liveResponseText, setLiveResponseText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activeTurnStartedAt, setActiveTurnStartedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [navigationLinks, setNavigationLinks] = useState<AgentNavigationRef[]>([]);
  const [hierarchy, setHierarchy] = useState<AgentHierarchyNode | null>(null);
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [llmConfig, setLlmConfig] = useState<LlmConfigInfo | null>(null);
  const [capabilityCatalog, setCapabilityCatalog] = useState<AgentCapabilityCatalog | null>(null);
  const activeTurnControllerRef = useRef<AbortController | null>(null);
  const activeTurnSessionIdRef = useRef<string | null>(null);

  const selectedKey = workbench.state.selectedKey;
  const graphNodes = Array.isArray(graphModel?.nodes) ? graphModel.nodes : [];
  const selectedNode = graphNodes.find((node) => node.nodeKey === selectedKey) ?? null;
  const scopedForestNodeKey = forest
    ? runFocusModelNodeKey(forest, selectedKey)
    : null;
  const scopedSelectedNode = scopedForestNodeKey && forest
    ? forest.forest.nodes.find((node) => node.nodeKey === scopedForestNodeKey) ?? selectedNode
    : selectedNode;
  // A run-rail focus still belongs to its chain. Only an actual blank canvas
  // selection in forest mode promotes the surface to the project Main Agent.
  const isGlobalScope = Boolean(forest) && selectedNode === null && selectedKey === null;
  const contextPacket = useMemo<AgentContextPacket>(() => {
    if (isGlobalScope && forest) {
      return boundedGlobalProjectContext(projectRoot, forest);
    }
    if (forest && scopedForestNodeKey) {
      const resolved = resolveNodeOperationContext({
        forest: forest.forest,
        selected_forest_node_key: scopedForestNodeKey,
        active_head_run_id: forest.activeRunId,
      });
      if (resolved.ok) return buildAskAIContextPacket(resolved.context);
    }
    return fallbackProjectContext(runId, selectedKey);
  }, [forest, isGlobalScope, projectRoot, runId, scopedForestNodeKey, selectedKey]);

  const contextFingerprint = typeof contextPacket.context_fingerprint === "string"
    && contextPacket.context_fingerprint
    ? contextPacket.context_fingerprint
    : `${runId}:${selectedKey ?? "none"}`;
  const storageKey = isGlobalScope
    ? `workbench:agent-session:${projectRoot}:main:${encodeURIComponent(contextFingerprint)}`
    : `workbench:agent-session:${projectRoot}:${runId}:${encodeURIComponent(contextFingerprint)}`;
  const linkedSessionId = searchParams.get("agent_session") || null;
  const linkedOperationId = searchParams.get("operation") || null;
  const linkedDiffFocused = searchParams.get("diff") === "1";
  const sessionScope = linkedSessionId
    ? `workbench:agent-linked:${projectRoot}:${linkedSessionId}`
    : storageKey;
  const activeScopeRef = useRef(sessionScope);
  const optimisticMessageCounterRef = useRef(0);
  const eventCursorRef = useRef(0);
  const applyEvents = useCallback((events: AgentEvent[]) => {
    const unseen = events
      .filter((event) => event.seq > eventCursorRef.current)
      .sort((left, right) => left.seq - right.seq);
    if (unseen.length === 0) return;
    const latest = unseen[unseen.length - 1];
    eventCursorRef.current = latest.seq;
    for (const event of unseen) {
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
    setLastEventType(latest.event_type);
  }, []);
  const replayEvents = useCallback(async (
    activeSessionId: string,
    afterSeq: number,
    scope: string,
  ) => {
    const result = await getAgentEvents(projectRoot, activeSessionId, afterSeq);
    if (activeScopeRef.current !== scope || !Array.isArray(result.events)) return;
    applyEvents(result.events);
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
    activeScopeRef.current = sessionScope;
    optimisticMessageCounterRef.current = 0;
    setSessionId(null);
    setMessages([]);
    setProposals([]);
    setSessionStatus("idle");
    setPrompt("");
    setError(null);
    setNavigationLinks([]);
    setHierarchy(null);
    setActiveOperation(null);
    setIsSubmitting(false);
    setActiveTurnStartedAt(null);
    setConfirmationBusyId(null);
    setEventCursor(0);
    eventCursorRef.current = 0;
    setLastEventType(null);
    setLiveResponseText("");
    const stored = linkedSessionId ?? sessionStorage.getItem(storageKey);
    if (!stored) return () => { cancelled = true; };
    getAgentSession(projectRoot, stored)
      .then(async (session) => {
        if (cancelled) return;
        setSessionId(session.session_id);
        setMessages(session.messages);
        setProposals(session.proposals ?? []);
        setSessionStatus(session.status);
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
    .catch(() => {
        if (!linkedSessionId) sessionStorage.removeItem(storageKey);
      });
    return () => { cancelled = true; };
  }, [linkedDiffFocused, linkedOperationId, linkedSessionId, projectRoot, refreshNavigation, replayEvents, sessionScope, storageKey]);

  useEffect(() => {
    if (!sessionId || !isSubmitting) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        await replayEvents(sessionId, eventCursor, sessionScope);
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
  }, [eventCursor, isSubmitting, replayEvents, sessionId, sessionScope]);

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
        }]
      : [];
  }, [activeProvider, llmConfig?.model]);
  const model = llmConfig?.model ?? modelOptions[0]?.request_model ?? "Not configured";
  const contextUsedTokens = useMemo(
    () => Math.max(
      1,
      Math.ceil(JSON.stringify(contextPacket).length / 4)
        + messages.reduce((sum, item) => sum + Math.ceil(item.content.length / 4), 0)
        + Math.ceil(prompt.length / 4),
    ),
    [contextPacket, messages, prompt],
  );
  // Resolve a real context capacity so the ring is a live gauge, not decoration.
  // Prefer the active model's declared window; otherwise 1,000,000 when the
  // model advertises the 1M context; otherwise the config-level value. Only when
  // none of these exist do we honestly report an unknown capacity.
  const activeModelRecord = modelOptions.find((option) => option.request_model === model);
  const ONE_MILLION = 1_000_000;
  const contextWindowTokens =
    activeModelRecord?.context_window_tokens
    ?? (activeModelRecord?.supports_1m ? ONE_MILLION : null)
    ?? llmConfig?.context_window_tokens
    ?? (llmConfig?.supports_1m ? ONE_MILLION : null);
  const contextPercent = contextWindowTokens
    ? Math.min(100, (contextUsedTokens / contextWindowTokens) * 100)
    : null;
  const scopeLabel = isGlobalScope
    ? `Global Agent · ${forest?.forest.familyRunCount ?? 0} runs · ${forest?.forest.familyCount ?? 0} families`
    : scopedSelectedNode
    ? `${forest ? "Current chain" : "Run"} · ${scopedSelectedNode.title}`
    : forest
      ? `Current chain · ${forest.activeRunId}`
      : `Run · ${runId}`;

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

  const sendPrompt = useCallback(async (value = prompt) => {
    const question = value.trim();
    if (!question || isSubmitting) return;
    const requestScope = sessionScope;
    if (activeScopeRef.current !== requestScope) return;
    optimisticMessageCounterRef.current += 1;
    const optimisticMessage: AgentMessage = {
      entry_id: `local-user-${optimisticMessageCounterRef.current}`,
      role: "user",
      content: question,
      stop_reason: null,
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
              ? `chain:${forest.activeRunId}`
              : `run:${runId}`,
          run_id: isGlobalScope ? undefined : runId,
          context_packet: contextPacket,
        });
        activeSessionId = created.session_id;
        if (activeScopeRef.current !== requestScope) return;
        setSessionId(activeSessionId);
        if (!linkedSessionId) sessionStorage.setItem(storageKey, activeSessionId);
      }
      if (controller.signal.aborted) return;
      activeTurnSessionIdRef.current = activeSessionId;
      const result = await sendAgentTurn(projectRoot, activeSessionId, question, controller.signal);
      if (activeScopeRef.current !== requestScope) return;
      setMessages(result.session.messages);
      setProposals(result.session.proposals ?? []);
      setSessionStatus(result.status);
      await refreshNavigation(activeSessionId, requestScope);
      try {
        await replayEvents(activeSessionId, eventCursor, requestScope);
      } catch {
        // The durable session response still contains the completed turn.
      }
    } catch (requestError) {
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
  }, [contextPacket, eventCursor, forest, isGlobalScope, isSubmitting, linkedSessionId, projectRoot, prompt, refreshNavigation, replayEvents, runId, sessionId, sessionScope, storageKey]);

  const abortTurn = useCallback(async () => {
    const controller = activeTurnControllerRef.current;
    if (!controller || !isSubmitting) return;
    const activeSessionId = activeTurnSessionIdRef.current;
    setError(null);
    setSessionStatus("cancelling");
    if (activeSessionId) {
      try {
        await abortAgentTurn(projectRoot, activeSessionId);
      } catch {
        // A completed turn can leave the active map between the click and this
        // request. The local request still needs to stop without showing a
        // misleading provider failure.
      }
    }
    controller.abort();
    setSessionStatus("cancelled");
  }, [isSubmitting, projectRoot]);

  const confirmProposal = useCallback(async (proposalId: string) => {
    if (!sessionId || confirmationBusyId !== null) return;
    const requestScope = sessionScope;
    if (activeScopeRef.current !== requestScope) return;
    const proposal = proposals.find((item) => item.proposal_id === proposalId);
    if (!proposal || proposal.status !== "pending") return;
    const ownership = contextPacket.ownership;
    const activeHead = ownership && typeof ownership === "object"
      ? (ownership as { active_head_run_id?: unknown }).active_head_run_id
      : undefined;
    const activeHeadRunId = typeof activeHead === "string" && activeHead
      ? activeHead
      : forest?.activeRunId ?? runId;
    setConfirmationBusyId(proposalId);
    setError(null);
    try {
      const result = await confirmAgentProposal(projectRoot, sessionId, proposalId, {
        revision: proposal.revision,
        fingerprint: proposal.fingerprint,
        active_head_run_id: activeHeadRunId,
      });
      if (activeScopeRef.current !== requestScope) return;
      setProposals((current) => current.map((item) => (
        item.proposal_id === proposalId ? result.proposal : item
      )));
      // Confirmation EXECUTES (design §8.2): surface the running operation
      // and poll the idempotent reconcile endpoint until the backend proves a
      // terminal state. The forest's own polling picks up the child run.
      let operation = toOperationStatus(result.operation);
      setActiveOperation(operation);
      while (!TERMINAL_OPERATION_STATUSES.has(operation.status)) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        if (activeScopeRef.current !== requestScope) return;
        const reconciled = await reconcileAgentOperation(
          projectRoot,
          sessionId,
          operation.record_id,
        );
        if (activeScopeRef.current !== requestScope) return;
        operation = toOperationStatus(reconciled.operation);
        setActiveOperation(operation);
      }
      await refreshNavigation(sessionId, requestScope);
    } catch (requestError) {
      if (activeScopeRef.current !== requestScope) return;
      setError(requestError instanceof Error ? requestError.message : "Proposal confirmation failed");
    } finally {
      if (activeScopeRef.current === requestScope) setConfirmationBusyId(null);
    }
  }, [confirmationBusyId, contextPacket, forest?.activeRunId, projectRoot, proposals, refreshNavigation, runId, sessionId, sessionScope]);

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

  const value = useMemo<AgentSurfaceContextValue>(() => ({
    messages,
    prompt,
    setPrompt,
    sendPrompt,
    abortTurn,
    isSubmitting,
    error,
    scopeLabel,
    contextUsedTokens,
    contextWindowTokens,
    contextPercent,
    model,
    modelOptions,
    setModel,
    sessionStatus,
    proposals,
    confirmationBusyId,
    confirmProposal,
    declineProposal,
    reviseProposal,
    forkFromMessage,
    openNavigation: navigation ?? undefined,
    navigationLinks,
    hierarchy,
    activeOperation,
    eventCursor,
    lastEventType,
    liveResponseText,
    activeTurnStartedAt,
    capabilityCatalog,
  }), [
    activeOperation,
    contextPercent,
    contextUsedTokens,
    contextWindowTokens,
    error,
    isSubmitting,
    messages,
    navigationLinks,
    hierarchy,
    model,
    modelOptions,
    prompt,
    scopeLabel,
    sendPrompt,
    abortTurn,
    setModel,
    sessionStatus,
    proposals,
    confirmationBusyId,
    confirmProposal,
    declineProposal,
    reviseProposal,
    forkFromMessage,
    navigation,
    eventCursor,
    lastEventType,
    liveResponseText,
    activeTurnStartedAt,
    capabilityCatalog,
  ]);

  return <AgentSurfaceContext.Provider value={value}>{children}</AgentSurfaceContext.Provider>;
}
