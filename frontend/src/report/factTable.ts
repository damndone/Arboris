// v1.6.11 slice C — deterministic citable-fact extraction.
//
// The fact table is the anti-hallucination contract: it is built HERE, from
// the same pure context resolver the drawer uses, and sent to the model as the
// only permitted source of numbers. Chips later render from this local table
// (never from model output), so an invented number can never become a chip.
import type { ForestViewModel } from "../lineage/api/graphViewTypes";
import { resolveNodeOperationContext } from "../lineage/api/nodeOperationContext";

export interface CitableFact {
  id: string;
  node_key: string;
  node_label: string;
  /** e.g. "param:covariance", "metric:r_squared", "decision:standard_errors" */
  field: string;
  label: string;
  value: unknown;
}

export interface ReportScope {
  run_id: string;
  node_count: number;
  node_keys: string[];
}

export interface FigureFactInput {
  artifact_id: string;
  chart_type: string;
  source?: {
    preview_json?: string;
    preview_truncated?: boolean;
    [key: string]: unknown;
  } | null;
}

const MAX_FIGURE_FACTS = 80;

/** Extract only bounded numeric leaves from the serve-time figure source. */
export function buildFigureFacts(
  figures: FigureFactInput[],
  startAt = 0,
): CitableFact[] {
  const facts: CitableFact[] = [];
  let counter = startAt;
  const nextId = () => `c${++counter}`;

  for (const figure of figures) {
    const source = figure.source;
    if (source?.preview_truncated) {
      facts.push({
        id: nextId(),
        node_key: `figure:${figure.artifact_id}`,
        node_label: figure.chart_type,
        field: `figure:${figure.artifact_id}:preview_truncated`,
        label: `${figure.chart_type} numeric preview truncated`,
        value: true,
      });
    }
    if (!source?.preview_json) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(source.preview_json) as unknown;
    } catch {
      continue;
    }
    const leaves: Array<{ path: string; value: number }> = [];
    collectNumericLeaves(parsed, "source", leaves, MAX_FIGURE_FACTS);
    for (const leaf of leaves) {
      facts.push({
        id: nextId(),
        node_key: `figure:${figure.artifact_id}`,
        node_label: figure.chart_type,
        field: `figure:${figure.artifact_id}:${leaf.path}`,
        label: `${figure.chart_type} · ${leaf.path}`,
        value: leaf.value,
      });
    }
  }
  return facts;
}

function collectNumericLeaves(
  value: unknown,
  path: string,
  leaves: Array<{ path: string; value: number }>,
  limit: number,
): void {
  if (leaves.length >= limit) return;
  if (typeof value === "number" && Number.isFinite(value)) {
    leaves.push({ path, value });
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => {
      collectNumericLeaves(item, `${path}[${index}]`, leaves, limit);
    });
    return;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      collectNumericLeaves(item, `${path}.${key}`, leaves, limit);
      if (leaves.length >= limit) return;
    }
  }
}

export function buildFactTable(
  forest: ForestViewModel,
  activeRunId: string,
): { facts: CitableFact[]; scope: ReportScope; fingerprints: string[] } {
  const pathNodes = forest.nodes.filter((node) => (node.runs ?? []).includes(activeRunId));
  const facts: CitableFact[] = [];
  const fingerprints: string[] = [];
  let counter = 0;
  const nextId = () => `c${++counter}`;

  for (const node of pathNodes) {
    const resolved = resolveNodeOperationContext({
      forest,
      selected_forest_node_key: node.nodeKey,
      active_head_run_id: activeRunId,
    });
    if (!resolved.ok) continue;
    const context = resolved.context;
    fingerprints.push(context.context_fingerprint);
    const nodeLabel = context.selection.display_label;

    for (const [key, value] of Object.entries(context.node_payload.params)) {
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `param:${key}`,
        label: key,
        value,
      });
    }
    const metrics = context.node_payload.metrics ?? {};
    for (const [key, value] of Object.entries(metrics)) {
      if (value === null || value === undefined) continue;
      if (typeof value === "object") continue; // scalars only — keep facts atomic
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `metric:${key}`,
        label: key,
        value,
      });
    }
    // v1.6.11 C-2 — model coefficient rows (serve-time decoration) expand into
    // atomic per-term facts so the report can cite estimates and p-values.
    const coefficientRows = Array.isArray(metrics.coefficients)
      ? metrics.coefficients
      : [];
    for (const row of coefficientRows) {
      if (!row || typeof row !== "object") continue;
      const { variable, estimate, std_error, p_value } = row as Record<string, unknown>;
      if (typeof variable !== "string" || typeof estimate !== "number") continue;
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `coef:${variable}`,
        label: `coefficient (${variable})`,
        value: estimate,
      });
      if (typeof std_error === "number") {
        facts.push({
          id: nextId(),
          node_key: node.nodeKey,
          node_label: nodeLabel,
          field: `coef_se:${variable}`,
          label: `std. error (${variable})`,
          value: std_error,
        });
      }
      if (typeof p_value === "number") {
        facts.push({
          id: nextId(),
          node_key: node.nodeKey,
          node_label: nodeLabel,
          field: `coef_p:${variable}`,
          label: `p-value (${variable})`,
          value: p_value,
        });
      }
    }
    for (const decision of context.node_payload.decisions) {
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `decision:${decision.id}`,
        label: decision.question,
        value: decision.picked,
      });
    }
  }

  return {
    facts,
    scope: {
      run_id: activeRunId,
      node_count: pathNodes.length,
      node_keys: pathNodes.map((n) => n.nodeKey),
    },
    fingerprints,
  };
}
