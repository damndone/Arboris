// v1.6.12 T2 (V3) — typed AI interaction log.
//
// Every AI interaction (Ask AI Q&A, report generation) persists as a TYPED,
// inspectable record. This is the operation-record contract that v1.7's
// propose→confirm→execute→trace loop will extend: keeping the shape typed and
// append-only NOW is what makes AI actions auditable later, instead of another
// opaque chat box. Storage is localStorage per project (same discipline as
// reportHistory); backend persistence is a v1.7 concern.

export interface AiActivityBase {
  id: string;
  at: string; // ISO timestamp
}

export interface AskAiActivityRecord extends AiActivityBase {
  kind: "ask_ai";
  node_key: string;
  node_label: string;
  question: string;
  status: "answered" | "error";
  model?: string;
  context_fingerprint?: string;
  answer?: string;
  error?: string;
}

export interface ReportActivityRecord extends AiActivityBase {
  kind: "report_generate";
  run_id: string;
  instruction: string;
  model?: string;
  fact_count: number;
  excluded_count: number;
  /** Pointer into reportHistory — full text + fact snapshot live there. */
  report_record_id: string;
}

export type AiActivityRecord = AskAiActivityRecord | ReportActivityRecord;

const MAX_RECORDS = 50;
export const AI_ACTIVITY_EVENT = "workbench:ai-activity";

function storageKey(projectRoot: string): string {
  return `workbench:ai-activity:${projectRoot}`;
}

export function loadAiActivity(projectRoot: string): AiActivityRecord[] {
  try {
    const raw = window.localStorage.getItem(storageKey(projectRoot));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as AiActivityRecord[]) : [];
  } catch {
    return [];
  }
}

/** Append (newest first, capped). Best-effort: quota/private-mode failures
 *  never break the interaction itself. Dispatches AI_ACTIVITY_EVENT so live
 *  views (bottom panel) refresh without polling. */
export function appendAiActivity(
  projectRoot: string,
  record: AiActivityRecord,
): AiActivityRecord[] {
  const next = [record, ...loadAiActivity(projectRoot)].slice(0, MAX_RECORDS);
  try {
    window.localStorage.setItem(storageKey(projectRoot), JSON.stringify(next));
  } catch {
    /* best-effort */
  }
  try {
    window.dispatchEvent(
      new CustomEvent(AI_ACTIVITY_EVENT, { detail: { projectRoot } }),
    );
  } catch {
    /* non-browser test envs without CustomEvent */
  }
  return next;
}

export function askAiHistoryForNode(
  projectRoot: string,
  nodeKey: string,
): AskAiActivityRecord[] {
  return loadAiActivity(projectRoot).filter(
    (r): r is AskAiActivityRecord => r.kind === "ask_ai" && r.node_key === nodeKey,
  );
}

export function makeActivityId(): string {
  return `ai_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}
