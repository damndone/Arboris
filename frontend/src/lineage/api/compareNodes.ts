// General two-node comparison (v1.6.11 slice B).
//
// Unlike `compareWithSource` (which requires rerun provenance linking a node to
// its source), this compares ANY two selected nodes on the forest. Both share
// the `nodeDiff` engine, so a diff means the same thing on either surface.

import type { NodeOperationContextV1 } from "./nodeOperationContext";
import {
  CompareSection,
  decisionSection,
  diagnosticsSection,
  FieldDiff,
  recordSection,
  upstreamPathSection,
} from "./nodeDiff";

export interface CompareNodeRef {
  forest_node_key: string;
  node_hash: string;
  display_label: string;
  kind: string;
  stage: string;
  owner_run_id: string;
  context_fingerprint: string;
}

export interface NodeComparisonResult {
  compare_version: "compare-nodes/v1";
  compare_kind: "arbitrary_pair";
  /** True when the two selections are the same forest node (nothing to compare). */
  same_node: boolean;
  /** True when the nodes are different kinds/stages (diff still valid, but note it). */
  cross_kind: boolean;
  left: CompareNodeRef;
  right: CompareNodeRef;
  sections: {
    params: CompareSection<FieldDiff>;
    decisions: CompareSection<FieldDiff>;
    metrics: CompareSection<FieldDiff>;
    diagnostics: CompareSection<FieldDiff>;
    upstream_path: CompareSection<FieldDiff>;
  };
  /** Total changed fields across all sections — drives the "N differences" header. */
  total_changed: number;
}

export function buildNodeComparison(
  left: NodeOperationContextV1,
  right: NodeOperationContextV1,
): NodeComparisonResult {
  const sections = {
    params: recordSection("parameter", left.node_payload.params, right.node_payload.params),
    decisions: decisionSection(left.node_payload.decisions, right.node_payload.decisions),
    metrics: recordSection(
      "metric",
      left.node_payload.metrics ?? {},
      right.node_payload.metrics ?? {},
    ),
    diagnostics: diagnosticsSection(
      left.node_payload.execution_diagnostics,
      right.node_payload.execution_diagnostics,
    ),
    upstream_path: upstreamPathSection(left, right),
  };
  const total_changed = Object.values(sections).reduce(
    (sum, section) => sum + section.total_changed,
    0,
  );
  return {
    compare_version: "compare-nodes/v1",
    compare_kind: "arbitrary_pair",
    same_node: left.selection.forest_node_key === right.selection.forest_node_key,
    cross_kind:
      left.selection.kind !== right.selection.kind ||
      left.selection.stage !== right.selection.stage,
    left: nodeRef(left),
    right: nodeRef(right),
    sections,
    total_changed,
  };
}

function nodeRef(context: NodeOperationContextV1): CompareNodeRef {
  return {
    forest_node_key: context.selection.forest_node_key,
    node_hash: context.selection.node_hash,
    display_label: context.selection.display_label,
    kind: context.selection.kind,
    stage: context.selection.stage,
    owner_run_id: context.ownership.owner_run_id,
    context_fingerprint: context.context_fingerprint,
  };
}
