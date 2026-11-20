import { type PostEstimationResult } from "../../api";
import type { AgentContextPacket, AgentOperationRecord } from "./agentTypes";
import type { ForestViewModel } from "../../lineage/api/graphViewTypes";

/** Terminal operation-record states — reconcile polling stops here. */
export const TERMINAL_OPERATION_STATUSES = new Set([
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

export function toOperationStatus(
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

export const MAX_GLOBAL_PROJECT_NODES = 120;
export const MAX_GLOBAL_PROJECT_RUNS = 200;

export function boundedGlobalProjectContext(
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

// Which conversation a node or page continues. Kept across browser restarts
// (it was per-tab sessionStorage, so closing the tab "lost" the conversation);
// a value left in sessionStorage by an older build is carried over once.
export function readConversation(key: string): string | null {
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

export function writeConversation(key: string, sessionId: string | null): void {
  try {
    if (sessionId) localStorage.setItem(key, sessionId);
    else localStorage.removeItem(key);
    sessionStorage.removeItem(key);
  } catch {
    // Storage can be unavailable (private windows); the conversation itself is on disk.
  }
}
