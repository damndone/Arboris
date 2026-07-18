import type {
  ArtifactRef,
  EditableControl,
  ForestViewModel,
  GraphViewEdge,
  GraphViewModel,
  Head,
  HeadSetNode,
  Stage,
} from "./graphViewTypes";

export type OwnerResolution =
  | "active_head_contains_node"
  | "selected_run_hint"
  | "single_candidate"
  | "manual_candidate_selection";

export type SelectedRunHintSource =
  | "none"
  | "run_scoped_surface"
  | "manual_candidate_selection";

export type NodeState = "materialized" | "failed" | "stale";

export interface CandidateRunRef {
  run_id: string;
  op_node_id: string;
  node_hash: string;
  is_active_head: boolean;
  path_contains_node: boolean;
}

export interface RerunFromProvenance {
  owner_run_id: string;
  op_node_id: string;
  node_hash: string;
  context_fingerprint: string;
  patch_id?: string;
  rerun_request_id: string;
}

export interface ResolveNodeOperationContextInput {
  forest: ForestViewModel;
  selected_forest_node_key: string;
  active_head_run_id: string | null;
  selected_run_hint?: string | null;
  selected_run_hint_source?: SelectedRunHintSource;
}

export type ResolveNodeOperationContextResult =
  | { ok: true; context: NodeOperationContextV1 }
  | {
      ok: false;
      reason:
        | "unsupported_planned_node"
        | "missing_owner_run"
        | "ambiguous_owner_run"
        | "missing_op_node"
        | "missing_node_hash"
        | "context_stale";
      selected_node_key: string;
      active_head_run_id?: string | null;
      candidate_run_ids?: string[];
      candidate_run_refs?: CandidateRunRef[];
      node_hash?: string;
      detail?: string;
    };

export interface NodeOperationContextV1 {
  context_version: "node-operation-context/v1";
  context_kind: "executed_lineage_node";
  context_fingerprint: string;
  rerun_from?: RerunFromProvenance;
  run_rerun_from?: RerunFromProvenance;
  resolver_trace?: string[];
  selection: {
    forest_node_key: string;
    node_hash: string;
    display_label: string;
    kind: string;
    stage: string;
  };
  ownership: {
    active_head_run_id: string | null;
    candidate_run_refs: CandidateRunRef[];
    candidate_run_ids: string[];
    shared_by_run_ids: string[];
    owner_run_id: string;
    owner_resolution: OwnerResolution;
    rerun_of?: string | null;
    parent_run_id?: string | null;
  };
  operation_target: {
    owner_run_id: string;
    op_node_id: string;
    node_hash: string;
    node_state: NodeState;
    editable_schema_source?: "run_inputs" | "capabilities";
  };
  lineage_context: {
    path_run_id: string;
    upstream_path: Array<{
      key: string;
      label: string;
      kind: string;
      stage: string;
      /** v1.6.11 — longest distance from a root. Equal depth = parallel
       *  branches (e.g. variable nodes fanning out of the cleaned dataset);
       *  renderers must not draw "→" between same-depth nodes. */
      depth?: number;
    }>;
    downstream_hint?: { has_downstream: boolean; downstream_count?: number };
    active_head_path_contains_node: boolean;
  };
  node_payload: {
    decisions: HeadSetNode["decisions"];
    artifacts: Array<ArtifactRef & { ai_visibility: "metadata_only" }>;
    editable_schema: EditableControl[] | null;
    params: Record<string, unknown>;
    metrics?: Record<string, unknown>;
    execution_diagnostics?: Array<{ level: string; message: string }>;
  };
  capabilities: {
    can_rerun: boolean;
    can_ask_ai: boolean;
    can_compare: boolean;
    can_rollback_focus: boolean;
    can_edit_params: boolean;
    disabled_reasons: string[];
  };
  comparison_readiness: {
    can_compare: boolean;
    candidate_run_ids: string[];
    active_head_run_id: string | null;
    owner_run_id: string;
    parent_run_id?: string | null;
    shared_by_run_ids: string[];
  };
  context_diagnostics: { warnings: string[]; resolution_notes: string[] };
}

export function resolveNodeOperationContext(
  input: ResolveNodeOperationContextInput,
): ResolveNodeOperationContextResult {
  const source = input.selected_run_hint_source ?? "none";
  const node = input.forest.nodes.find(
    (n) => n.nodeKey === input.selected_forest_node_key,
  );
  if (!node) {
    return {
      ok: false,
      reason: "missing_op_node",
      selected_node_key: input.selected_forest_node_key,
    };
  }
  if (!node.nodeHash) {
    return {
      ok: false,
      reason: "missing_node_hash",
      selected_node_key: node.nodeKey,
    };
  }
  if (!node.opNodeId) {
    return {
      ok: false,
      reason: "missing_op_node",
      selected_node_key: node.nodeKey,
      node_hash: node.nodeHash,
    };
  }

  const candidate_run_refs = (node.runs ?? []).map((run_id) => ({
    run_id,
    op_node_id: node.opNodeId,
    node_hash: node.nodeHash!,
    is_active_head: run_id === input.active_head_run_id,
    path_contains_node: true,
  }));
  if (candidate_run_refs.length === 0) {
    return {
      ok: false,
      reason: "missing_owner_run",
      selected_node_key: node.nodeKey,
      node_hash: node.nodeHash,
    };
  }

  const activeRef = candidate_run_refs.find(
    (r) => r.run_id === input.active_head_run_id,
  );
  const hintRef = input.selected_run_hint
    ? candidate_run_refs.find(
        (r) =>
          r.run_id === input.selected_run_hint &&
          r.node_hash === node.nodeHash &&
          Boolean(r.op_node_id),
      )
    : undefined;

  let owner = activeRef;
  let owner_resolution: OwnerResolution = "active_head_contains_node";
  if (
    hintRef &&
    (source === "run_scoped_surface" || source === "manual_candidate_selection")
  ) {
    owner = hintRef;
    owner_resolution =
      source === "manual_candidate_selection"
        ? "manual_candidate_selection"
        : "selected_run_hint";
  } else if (!owner && hintRef) {
    owner = hintRef;
    owner_resolution = "selected_run_hint";
  } else if (!owner && candidate_run_refs.length === 1) {
    owner = candidate_run_refs[0];
    owner_resolution = "single_candidate";
  }

  if (!owner) {
    return {
      ok: false,
      reason: "ambiguous_owner_run",
      selected_node_key: node.nodeKey,
      active_head_run_id: input.active_head_run_id,
      candidate_run_ids: candidate_run_refs.map((r) => r.run_id),
      candidate_run_refs,
      node_hash: node.nodeHash,
      detail:
        "Multiple candidate runs own this node; explicit owner selection is required.",
    };
  }

  const ownerHead = findHead(input.forest, owner.run_id);
  const contextFingerprintInputs = stableFingerprintInput({
    candidate_run_refs,
    shared_by_run_ids: node.runs,
    owner_head_created_at: ownerHead?.createdAt ?? "",
  });
  const context_fingerprint = fingerprintParts([
    node.nodeKey,
    node.nodeHash,
    owner.run_id,
    owner.op_node_id,
    input.active_head_run_id ?? "",
    String(input.forest.schemaVersion),
    ownerHead?.createdAt ?? "",
    contextFingerprintInputs,
  ]);
  const candidateRunIds = candidate_run_refs.map((r) => r.run_id);
  const sharedByRunIds = [...node.runs];
  const activeHeadPathContainsNode = Boolean(activeRef);
  const nodeRerunFrom = node.rerunFrom;
  // A deduped forest node can be shared by several runs.  In that case the
  // node-level adapter intentionally has no single provenance value; the
  // active owner head is the authoritative run-scoped provenance instead.
  const runRerunFrom = ownerHead?.runRerunFrom ?? node.runRerunFrom;
  const resolverTrace = [
    `selected forest node: ${input.selected_forest_node_key}`,
    `active_head_run_id: ${input.active_head_run_id ?? "none"}`,
    `selected_run_hint: ${input.selected_run_hint ?? "none"}`,
    `selected_run_hint_source: ${source}`,
    `candidate_run_refs: ${JSON.stringify(candidate_run_refs)}`,
    `owner_resolution: ${owner_resolution}`,
    `owner_run_id: ${owner.run_id}`,
    `context_fingerprint_inputs: ${contextFingerprintInputs}`,
    `context_fingerprint: ${context_fingerprint}`,
    `rerun_from: ${JSON.stringify(nodeRerunFrom ?? null)}`,
    `run_rerun_from: ${JSON.stringify(runRerunFrom ?? null)}`,
  ];

  return {
    ok: true,
    context: {
      context_version: "node-operation-context/v1",
      context_kind: "executed_lineage_node",
      context_fingerprint,
      rerun_from: nodeRerunFrom,
      run_rerun_from: runRerunFrom,
      resolver_trace: resolverTrace,
      selection: {
        forest_node_key: node.nodeKey,
        node_hash: node.nodeHash,
        display_label: node.title,
        kind: node.kind,
        stage: node.stage,
      },
      ownership: {
        active_head_run_id: input.active_head_run_id,
        candidate_run_refs,
        candidate_run_ids: candidateRunIds,
        shared_by_run_ids: sharedByRunIds,
        owner_run_id: owner.run_id,
        owner_resolution,
        rerun_of: ownerHead?.rerunOf ?? null,
        parent_run_id: ownerHead?.rerunOf ?? null,
      },
      operation_target: {
        owner_run_id: owner.run_id,
        op_node_id: owner.op_node_id,
        node_hash: owner.node_hash,
        node_state: node.status === "failed" ? "failed" : "materialized",
        editable_schema_source: node.editableSchemaSource,
      },
      lineage_context: {
        path_run_id: owner.run_id,
        upstream_path: buildUpstreamPath(input.forest, node.nodeKey, owner.run_id),
        downstream_hint: buildDownstreamHint(input.forest, node.nodeKey),
        active_head_path_contains_node: activeHeadPathContainsNode,
      },
      node_payload: {
        decisions: node.decisions,
        artifacts: (node.artifacts ?? []).map((a) => ({
          ...a,
          ai_visibility: "metadata_only" as const,
        })),
        editable_schema: node.editableSchema ?? null,
        // v1.6.11 B-2 — real parameter values live in editable_schema[].value
        // (backend value-backfill from run_inputs.form). Deriving params here
        // gives Ask AI packets and node comparisons actual values instead of {}.
        params: paramsFromSchema(node.editableSchema),
        metrics: node.stats,
      },
      capabilities: resolveCapabilities(node, candidate_run_refs.length),
      comparison_readiness: {
        can_compare: candidate_run_refs.length > 1,
        candidate_run_ids: candidateRunIds,
        active_head_run_id: input.active_head_run_id,
        owner_run_id: owner.run_id,
        parent_run_id: ownerHead?.rerunOf ?? null,
        shared_by_run_ids: sharedByRunIds,
      },
      context_diagnostics: {
        warnings: [],
        resolution_notes: [`owner_resolution=${owner_resolution}`],
      },
    },
  };
}

export function explainResolveNodeOperationContext(
  input: ResolveNodeOperationContextInput,
): string {
  const result = resolveNodeOperationContext(input);
  const lines = [
    `selected forest node: ${input.selected_forest_node_key}`,
    `active_head_run_id: ${input.active_head_run_id ?? "none"}`,
    `selected_run_hint: ${input.selected_run_hint ?? "none"}`,
    `selected_run_hint_source: ${input.selected_run_hint_source ?? "none"}`,
  ];

  if (result.ok) {
    return (result.context.resolver_trace ?? lines).join("\n");
  } else {
    lines.push(`reason: ${result.reason}`);
    if (result.candidate_run_refs) {
      lines.push(`candidate_run_refs: ${JSON.stringify(result.candidate_run_refs)}`);
    }
  }

  return lines.join("\n");
}

export function makeOwnerResolutionSeedFixture(): {
  forest: ForestViewModel;
  graphModel: GraphViewModel;
  sharedNodeKey: string;
  sharedOpNodeId: string;
  activeHeadRunId: string;
} {
  const sharedNodeKey = "hash_shared_model";
  const sharedOpNodeId = "model:shared_ols";
  const source = makeHeadSetNode({
    nodeKey: "hash_source",
    opNodeId: "source:upload",
    nodeHash: "hash_source",
    title: "Source data",
    kind: "dataset",
    stage: "source",
    runs: ["run_a", "run_c"],
  });
  const shared = makeHeadSetNode({
    nodeKey: sharedNodeKey,
    opNodeId: sharedOpNodeId,
    nodeHash: sharedNodeKey,
    title: "Shared OLS model",
    kind: "model",
    stage: "model",
    runs: ["run_a", "run_c"],
    editable: true,
    editableSchemaSource: "run_inputs",
  });
  const report = makeHeadSetNode({
    nodeKey: "hash_report_c",
    opNodeId: "report:summary",
    nodeHash: "hash_report_c",
    title: "Run C report",
    kind: "report",
    stage: "report",
    runs: ["run_c"],
  });
  const edges: GraphViewEdge[] = [
    { id: "hash_source->hash_shared_model", source: source.nodeKey, target: shared.nodeKey },
    { id: "hash_shared_model->hash_report_c", source: shared.nodeKey, target: report.nodeKey },
  ];
  const heads: Head[] = [
    {
      runId: "run_a",
      headNodeHash: sharedNodeKey,
      fromNode: null,
      rerunOf: null,
      rerunReason: null,
      status: "completed",
      createdAt: "2026-06-27T00:00:00Z",
    },
    {
      runId: "run_c",
      headNodeHash: report.nodeHash,
      fromNode: sharedOpNodeId,
      rerunOf: "run_a",
      rerunReason: "manual_override",
      status: "completed",
      createdAt: "2026-06-27T00:01:00Z",
    },
  ];
  const forest: ForestViewModel = {
    schemaVersion: 2,
    legacy: false,
    nodes: [source, shared, report],
    edges,
    heads,
    familyCount: 1,
    familyRunCount: 2,
  };
  const graphModel: GraphViewModel = {
    schemaVersion: 2,
    runId: "run_c",
    legacy: false,
    nodes: forest.nodes,
    edges,
    stats: {
      nodeCount: forest.nodes.length,
      edgeCount: edges.length,
      leafCount: 1,
      hasDpCount: 0,
    },
  };

  return {
    forest,
    graphModel,
    sharedNodeKey,
    sharedOpNodeId,
    activeHeadRunId: "run_c",
  };
}

function fingerprintParts(parts: string[]): string {
  const input = JSON.stringify(parts);
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `nocv1:${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function stableFingerprintInput(input: {
  candidate_run_refs: CandidateRunRef[];
  shared_by_run_ids: string[];
  owner_head_created_at: string;
}): string {
  return JSON.stringify({
    candidate_run_refs: [...input.candidate_run_refs]
      .map((ref) => ({
        run_id: ref.run_id,
        op_node_id: ref.op_node_id,
        node_hash: ref.node_hash,
        is_active_head: ref.is_active_head,
        path_contains_node: ref.path_contains_node,
      }))
      .sort((left, right) => left.run_id.localeCompare(right.run_id)),
    shared_by_run_ids: [...input.shared_by_run_ids].sort(),
    owner_head_created_at: input.owner_head_created_at,
  });
}

/** v1.6.11 B-2 — flatten editable_schema's backfilled values into a params
 *  record. Entries without a meaningful value are skipped, so nodes with no
 *  schema (dataset/report) keep the old `{}` shape. */
function paramsFromSchema(
  schema: HeadSetNode["editableSchema"],
): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const control of schema ?? []) {
    const key = control.key;
    if (!key || control.value === undefined || control.value === null || control.value === "") {
      continue;
    }
    params[key] = control.value;
  }
  return params;
}

function buildUpstreamPath(
  forest: ForestViewModel,
  selectedNodeKey: string,
  ownerRunId: string,
): Array<{ key: string; label: string; kind: string; stage: string }> {
  const nodesByKey = new Map(forest.nodes.map((node) => [node.nodeKey, node]));
  const incomingByTarget = new Map<string, GraphViewEdge[]>();
  for (const edge of forest.edges) {
    const source = nodesByKey.get(edge.source);
    const target = nodesByKey.get(edge.target);
    if (
      !source?.runs.includes(ownerRunId) ||
      !target?.runs.includes(ownerRunId)
    ) {
      continue;
    }
    const incoming = incomingByTarget.get(edge.target) ?? [];
    incoming.push(edge);
    incomingByTarget.set(edge.target, incoming);
  }

  const visited = new Set<string>();
  const ordered: HeadSetNode[] = [];
  const visit = (key: string) => {
    if (visited.has(key)) return;
    visited.add(key);
    for (const edge of incomingByTarget.get(key) ?? []) {
      visit(edge.source);
    }
    const node = nodesByKey.get(key);
    if (node?.runs.includes(ownerRunId)) ordered.push(node);
  };

  visit(selectedNodeKey);

  // v1.6.11 — depth = longest distance from a root. Nodes sharing a depth are
  // PARALLEL (e.g. the per-variable nodes fanning out of the cleaned dataset);
  // rendering the flat topological order as one "→" chain misrepresented them
  // as sequential (user report 2026-07-12).
  const depthByKey = new Map<string, number>();
  const depthOf = (key: string): number => {
    const known = depthByKey.get(key);
    if (known !== undefined) return known;
    depthByKey.set(key, 0); // cycle guard (DAG invariant should hold anyway)
    const parents = (incomingByTarget.get(key) ?? []).map((edge) => depthOf(edge.source));
    const depth = parents.length === 0 ? 0 : Math.max(...parents) + 1;
    depthByKey.set(key, depth);
    return depth;
  };
  return ordered.map((node) => ({
    key: node.nodeKey,
    label: node.title,
    kind: node.kind,
    stage: node.stage,
    depth: depthOf(node.nodeKey),
  }));
}

function buildDownstreamHint(
  forest: ForestViewModel,
  selectedNodeKey: string,
): { has_downstream: boolean; downstream_count?: number } {
  const downstreamCount = forest.edges.filter(
    (edge) => edge.source === selectedNodeKey,
  ).length;
  return {
    has_downstream: downstreamCount > 0,
    downstream_count: downstreamCount,
  };
}

function resolveCapabilities(
  node: HeadSetNode,
  candidateCount: number,
): NodeOperationContextV1["capabilities"] {
  const canEditParams = Boolean(node.editable && node.editableSchema?.length);
  return {
    can_rerun: true,
    can_ask_ai: true,
    can_compare: candidateCount > 1,
    can_rollback_focus: candidateCount > 1,
    can_edit_params: canEditParams,
    disabled_reasons: [],
  };
}

function findHead(forest: ForestViewModel, runId: string): Head | undefined {
  return forest.heads.find((head) => head.runId === runId);
}

function makeHeadSetNode(args: {
  nodeKey: string;
  opNodeId: string;
  nodeHash: string;
  title: string;
  kind: string;
  stage: Stage;
  runs: string[];
  editable?: boolean;
  editableSchemaSource?: "capabilities" | "run_inputs";
}): HeadSetNode {
  return {
    id: args.nodeKey,
    nodeKey: args.nodeKey,
    raw: {},
    stage: args.stage,
    kind: args.kind,
    title: args.title,
    parentStageId: null,
    trust: "ok",
    decisions: [],
    opNodeId: args.opNodeId,
    nodeHash: args.nodeHash,
    producingStage: args.stage,
    casRef: null,
    runs: args.runs,
    editable: args.editable,
    editableSchema:
      args.editable === true
        ? [
            {
              kind: "text",
              key: "formula",
              label: "Formula",
              value: "y ~ x",
            },
          ]
        : undefined,
    editableSchemaSource: args.editableSchemaSource,
  };
}
