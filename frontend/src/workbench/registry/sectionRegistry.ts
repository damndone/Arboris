// frontend/src/workbench/registry/sectionRegistry.ts
//
// V1.5.2 — promoted from lineage/detail/sections/sectionRegistry.ts.
//
// DetailDrawer renders DetailHeader (always, never in the registry —
// see V1.5.0 spec §8.2) followed by registered sections in `order`
// after each one's `shouldRender(node)` filter. Adding a section is
// two changes: create the component, append an entry here. DetailDrawer
// itself is not touched.
//
// Order slots (10..110) leave room for future sections without renumbering:
//   10  TrustBanner            — V1.5.0
//   20  AskAISection           — V1.5.2 (placeholder slot, P5)
//   25  CompareWithSource      — V1.6.3 source-bound compare gate
//   30  OperationSection       — V1.5.2 (placeholder slot, P5)
//   40  CodeSection            — V1.5.1 read-only (placeholder slot, P5)
//   50  LineageChainSection    — V1.5.0
//   60  BasicInfoSection       — V1.5.0
//   70  DecisionSection        — V1.5.0
//   80  CoefficientSection     — V1.5.x
//   90  ArtifactSection        — V1.5.x
//  100  PreviewSection         — V1.5.x
//  110  HistogramSection       — V1.5.x
//
// The old import path (lineage/detail/sections/sectionRegistry) still
// works via a thin re-export so consumers don't churn in this PR.

import { createElement, useEffect, useState, type FC } from "react";
import type { GraphViewNode } from "../../lineage/api/graphViewTypes";
import { useProjectRootOptional } from "../ProjectRootContext";
import {
  confirmDataOperation,
  fetchDataColumnCastContext,
  fetchDataOperationManifest,
  previewDataOperation,
} from "../../lineage/dataOperations";
import { useResolvedNodeOperationContext } from "../../lineage/detail/NodeOperationContextProvider";
import { TrustBanner } from "../../lineage/detail/sections/TrustBanner";
import { LineageChainSection } from "../../lineage/detail/sections/LineageChainSection";
import { BasicInfoSection } from "../../lineage/detail/sections/BasicInfoSection";
import { DecisionSection } from "../../lineage/detail/sections/DecisionSection";
import { AskAISection } from "../../lineage/detail/sections/AskAISection";
import { CompareWithSourceSection } from "../../lineage/detail/sections/CompareWithSourceSection";
import { AnalysisLoopSection } from "../../lineage/detail/sections/AnalysisLoopSection";
import { CompareNodeSection, isCompareNode } from "../../lineage/detail/sections/CompareNodeSection";
import { CompareNodesSection } from "../../lineage/compare/CompareNodesSection";
import { OperationSection } from "../../lineage/detail/sections/OperationSection";
import { RoleGroupsSection } from "../../lineage/detail/sections/RoleGroupsSection";
import { EstimatedEquationSection } from "../../lineage/detail/sections/EstimatedEquationSection";
import { CodeSection } from "../../lineage/detail/sections/CodeSection";
import { DraftEditorSlot } from "../../lineage/detail/sections/DraftEditorSlot";
import { CodeExecuteSection } from "../../lineage/detail/sections/CodeExecuteSection";
import { StatisticalExplorationSection } from "../../lineage/detail/sections/StatisticalExplorationSection";
import { DataColumnCastSection } from "../../lineage/detail/sections/DataColumnCastSection";
import { DataOperationsSection } from "../../lineage/detail/sections/DataOperationsSection";
import { ArmaGarchOperationSection } from "../../lineage/detail/sections/ArmaGarchOperationSection";
import { ArmaGarchResultSection } from "../../lineage/detail/sections/ArmaGarchResultSection";
import { isAskAIEnabled } from "../featureFlags";
import type { RegistryEntry } from "./registryTypes";

/** The time-series pack renders a bespoke operation form instead of the
 *  generic editable_schema controls (its schema is an opaque model_options). */
const isArmaGarch = (n: GraphViewNode): boolean =>
  "opType" in n && n.opType === "time_series.arma_garch";
const isGeneratedArmaGarchStage = (n: GraphViewNode): boolean =>
  isArmaGarch(n) && n.kind !== "model";

/**
 * V1.5.2 — SectionEntry is the canonical name; SectionSpec is kept as
 * a type alias because the V1.5.0 codebase uses it in a few places.
 */
export type SectionEntry = RegistryEntry<GraphViewNode> & {
  Component: FC<{ node: GraphViewNode }>;
};

/** @deprecated use SectionEntry; alias preserved for V1.5.0 callers. */
export type SectionSpec = SectionEntry;

/** Renderer identities are declaration-facing keys, not component imports
 * exposed to Agent/Notebook input.  The server may add a provider renderer
 * only after the corresponding typed contract and evidence packet are joined.
 */
export const V189_DECLARATION_RENDERER_KEYS = Object.freeze({
  dataConsumer: "renderer:data-consumer-evidence.v1",
  classificationEvidence: "renderer:classification-evidence.v1",
} as const);

type DataConsumerProjection = {
  status?: unknown;
  evidence_grade?: unknown;
  lineage_ref?: unknown;
  blocked_reason?: unknown;
};

function asDataConsumerProjection(node: GraphViewNode): DataConsumerProjection | null {
  const candidate = (node as GraphViewNode & { dataConsumerProjection?: unknown }).dataConsumerProjection;
  if (candidate === null || typeof candidate !== "object" || Array.isArray(candidate)) return null;
  return candidate as DataConsumerProjection;
}

/**
 * Declaration-derived, read-only consumer evidence mount. Unknown shapes are
 * disclosed as unavailable; they are never dumped as arbitrary JSON.
 */
export const DataConsumerEvidenceSection: FC<{ node: GraphViewNode }> = ({ node }) => {
  const projection = asDataConsumerProjection(node);
  if (!projection) {
    return createElement(
      "section",
      { "aria-label": "Data consumer evidence", "data-testid": "data-consumer-evidence" },
      createElement("div", { className: "ln-section-label" }, "Data consumer evidence"),
      createElement(
        "p",
        { style: { fontSize: 12, color: "var(--label-tertiary)", margin: 0 } },
        "UNAVAILABLE: no typed consumer projection was supplied.",
      ),
    );
  }
  const value = (field: keyof DataConsumerProjection, fallback: string) => {
    const candidate = projection[field];
    return typeof candidate === "string" && candidate.trim() ? candidate : fallback;
  };
  return createElement(
    "section",
    { "aria-label": "Data consumer evidence", "data-testid": "data-consumer-evidence" },
    createElement("div", { className: "ln-section-label" }, "Data consumer evidence"),
    createElement(
      "dl",
      { style: { display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 12px", margin: 0, fontSize: 12 } },
      createElement("dt", null, "Status"),
      createElement("dd", { style: { margin: 0 } }, value("status", "UNAVAILABLE")),
      createElement("dt", null, "Evidence grade"),
      createElement("dd", { style: { margin: 0 } }, value("evidence_grade", "UNAVAILABLE")),
      createElement("dt", null, "Lineage"),
      createElement("dd", { style: { margin: 0 } }, value("lineage_ref", "UNAVAILABLE")),
    ),
    typeof projection.blocked_reason === "string" && projection.blocked_reason.trim()
      ? createElement("p", { style: { fontSize: 12, color: "var(--label-tertiary)", margin: "6px 0 0" } }, `Blocked: ${projection.blocked_reason}`)
      : null,
  );
};

function dataOperationsUnavailable(message: string) {
  return createElement(
    "section",
    { "aria-label": "Data operations", "data-testid": "data-operations-unavailable" },
    createElement("div", { className: "ln-section-label" }, "Data operations"),
    createElement("p", { role: "status" }, message),
  );
}

/**
 * Canonical registry adapter for the server-owned data-operation editor.
 * It resolves identity and transport only; DataOperationsSection owns all
 * schema controls, preview gating, and typed completion validation.
 */
export const DataOperationsRegistrySection: FC<{ node: GraphViewNode }> = () => {
  const projectRoot = useProjectRootOptional();
  const resolved = useResolvedNodeOperationContext();
  const sourceRunId = resolved?.ok ? resolved.context.ownership.owner_run_id : null;
  const sourceNodeId = resolved?.ok ? resolved.context.operation_target.op_node_id : null;
  const [manifest, setManifest] = useState<unknown | null>(null);
  const [sourceArtifactId, setSourceArtifactId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setManifest(null);
    setSourceArtifactId(null);
    setLoadError(null);
    if (!projectRoot || !sourceRunId || !sourceNodeId) return () => undefined;

    void Promise.all([
      fetchDataOperationManifest(),
      fetchDataColumnCastContext(projectRoot, sourceRunId, sourceNodeId),
    ])
      .then(([nextManifest, sourceContext]) => {
        if (!active) return;
        const artifactId = sourceContext.source_artifact_id;
        if (typeof artifactId !== "string" || !artifactId.trim()) {
          setLoadError("SOURCE_ARTIFACT_UNAVAILABLE: server returned no source artifact identity.");
          return;
        }
        setManifest(nextManifest);
        setSourceArtifactId(artifactId);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setLoadError(
          `DATA_OPERATIONS_UNAVAILABLE: ${reason instanceof Error ? reason.message : String(reason)}`,
        );
      });
    return () => {
      active = false;
    };
  }, [projectRoot, sourceRunId, sourceNodeId]);

  if (!projectRoot) return dataOperationsUnavailable("PROJECT_ROOT_UNAVAILABLE");
  if (!resolved?.ok) {
    return dataOperationsUnavailable(
      `NODE_OPERATION_CONTEXT_UNAVAILABLE: ${resolved?.reason ?? "missing_context"}`,
    );
  }
  if (!sourceRunId || !sourceNodeId) {
    return dataOperationsUnavailable("NODE_OPERATION_CONTEXT_UNAVAILABLE: missing source identity.");
  }
  if (loadError) return dataOperationsUnavailable(loadError);
  if (manifest === null || sourceArtifactId === null) {
    return dataOperationsUnavailable("LOADING: server-owned data-operation manifest.");
  }

  return createElement(DataOperationsSection, {
    manifest,
    projectRoot,
    sourceIdentity: {
      source_run_id: sourceRunId,
      source_node_id: sourceNodeId,
      source_artifact_id: sourceArtifactId,
    },
    preview: previewDataOperation,
    confirm: confirmDataOperation,
  });
};

/**
 * Trust banner shows whenever the node is not trusted OR any decision
 * needs / has failed review. Mirrors V1.4.1 Inspector.tsx callout logic.
 */
function needsTrust(n: GraphViewNode): boolean {
  if (n.trust !== "ok") return true;
  return n.decisions.some(
    (d) => d.reviewStatus === "needed" || d.reviewStatus === "failed",
  );
}

export const sectionRegistry: SectionEntry[] = [
  { id: "draftEditor", order: 5, shouldRender: (n) => Boolean(n.isDraft), Component: DraftEditorSlot },
  { id: "trust", order: 10, shouldRender: needsTrust, Component: TrustBanner },
  // Ask AI is explicitly feature-flagged for v1.6.2 so read-only advisory
  // UI cannot be exposed by default during release.
  {
    id: "askAi",
    order: 20,
    shouldRender: () => isAskAIEnabled(),
    Component: AskAISection,
  },
  {
    // v1.8 slice C — a stored comparison node reads its own packet; the
    // sections below are about running a model and do not describe it.
    id: "compareNode",
    order: 24,
    shouldRender: isCompareNode,
    Component: CompareNodeSection,
  },
  {
    id: "compareWithSource",
    order: 25,
    shouldRender: (n) => "runs" in n && !isCompareNode(n) && !isGeneratedArmaGarchStage(n),
    Component: CompareWithSourceSection,
  },
  {
    // v1.6.11 B-2 — arbitrary two-node comparison (pick the partner on the canvas).
    id: "compareNodes",
    order: 26,
    shouldRender: (n) =>
      "runs" in n && !n.isDraft && !isCompareNode(n) && !isGeneratedArmaGarchStage(n),
    Component: CompareNodesSection,
  },
  {
    id: "analysisLoop",
    order: 27,
    shouldRender: (n) =>
      n.kind === "model" && !n.isDraft && "runs" in n,
    Component: AnalysisLoopSection,
  },
  {
    id: "dataColumnCast",
    order: 28,
    shouldRender: (n) =>
      n.kind === "dataset_stage" && !n.isDraft && !isGeneratedArmaGarchStage(n),
    Component: DataColumnCastSection,
  },
  {
    // v1.7 G3 — sandboxed `code.execute`, the typed operation behind "the
    // terminal can change code". Sits under the cast builder: same node, same
    // lifecycle, wider blast radius.
    id: "codeExecute",
    order: 29,
    shouldRender: (n) =>
      n.kind === "dataset_stage" && !n.isDraft && !isGeneratedArmaGarchStage(n),
    Component: CodeExecuteSection,
  },
  {
    // v1.8.9 P1 remediation — canonical user-operated data editor. The
    // server-owned manifest and node-operation context supply identity; the
    // section itself keeps preview/confirm and typed completion checks.
    id: "dataOperations",
    order: 29.25,
    shouldRender: (n) =>
      n.kind === "dataset_stage" && !n.isDraft && !isGeneratedArmaGarchStage(n),
    Component: DataOperationsRegistrySection,
  },
  {
    id: "statisticalExploration",
    order: 29.5,
    shouldRender: (n) =>
      n.kind === "dataset_stage" && !n.isDraft && !isGeneratedArmaGarchStage(n),
    Component: StatisticalExplorationSection,
  },
  {
    id: "operation",
    order: 30,
    shouldRender: (n) => (n.editableSchema?.length ?? 0) > 0 && !isArmaGarch(n),
    Component: OperationSection,
  },
  {
    // Bespoke time-series operation form (transform / orders / distribution /
    // strategy / validation) that forks a child model via the shared rerun path.
    id: "armaGarchOperation",
    order: 31,
    shouldRender: (n) => n.kind === "model" && !n.isDraft && isArmaGarch(n),
    Component: ArmaGarchOperationSection,
  },
  {
    // One-view time-series result dashboard (replaces the legacy nine-tab card).
    id: "armaGarchResult",
    order: 32,
    shouldRender: (n) => n.kind === "model" && !n.isDraft && isArmaGarch(n),
    Component: ArmaGarchResultSection,
  },
  {
    // v1.6.8 — fitted equation from the owner run's coefficients; sits right
    // above the specification so estimate vs spec read as a pair.
    id: "estimatedEquation",
    order: 34,
    // An ARMA-GARCH node has no classic coefficient equation, and the
    // dashboard already states its mean and variance specification.
    shouldRender: (n) =>
      (n.kind === "model" || n.stage === "model") && !n.isDraft && !isArmaGarch(n),
    Component: EstimatedEquationSection,
  },
  {
    id: "roleGroups",
    order: 35,
    // Outcome/predictor roles do not describe a one-series time-series
    // analysis, whose variables are a time column and a value column.
    shouldRender: (n) =>
      (n.kind === "model" || n.stage === "model") && !n.isDraft && !isArmaGarch(n),
    Component: RoleGroupsSection,
  },
  {
    id: "code",
    order: 40,
    shouldRender: (n) => Boolean(n.code?.body),
    Component: CodeSection,
  },
  {
    id: "lineage",
    order: 50,
    shouldRender: () => true,
    Component: LineageChainSection,
  },
  {
    id: "basic",
    order: 60,
    shouldRender: () => true,
    Component: BasicInfoSection,
  },
  {
    id: "decision",
    order: 70,
    shouldRender: (n) => n.decisions.length > 0,
    Component: DecisionSection,
  },
];

// Exported for testing only — `needsTrust` semantics are part of the
// trust contract (REV-2 locked these scenarios in V1.5.0 T6.4).
export const _needsTrust = needsTrust;
