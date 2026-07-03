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

import type { FC } from "react";
import type { GraphViewNode } from "../../lineage/api/graphViewTypes";
import { TrustBanner } from "../../lineage/detail/sections/TrustBanner";
import { LineageChainSection } from "../../lineage/detail/sections/LineageChainSection";
import { BasicInfoSection } from "../../lineage/detail/sections/BasicInfoSection";
import { DecisionSection } from "../../lineage/detail/sections/DecisionSection";
import { AskAISection } from "../../lineage/detail/sections/AskAISection";
import { CompareWithSourceSection } from "../../lineage/detail/sections/CompareWithSourceSection";
import { OperationSection } from "../../lineage/detail/sections/OperationSection";
import { RoleGroupsSection } from "../../lineage/detail/sections/RoleGroupsSection";
import { CodeSection } from "../../lineage/detail/sections/CodeSection";
import { DraftEditorSlot } from "../../lineage/detail/sections/DraftEditorSlot";
import { isAskAIEnabled } from "../featureFlags";
import type { RegistryEntry } from "./registryTypes";

/**
 * V1.5.2 — SectionEntry is the canonical name; SectionSpec is kept as
 * a type alias because the V1.5.0 codebase uses it in a few places.
 */
export type SectionEntry = RegistryEntry<GraphViewNode> & {
  Component: FC<{ node: GraphViewNode }>;
};

/** @deprecated use SectionEntry; alias preserved for V1.5.0 callers. */
export type SectionSpec = SectionEntry;

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
    id: "compareWithSource",
    order: 25,
    shouldRender: (n) => "runs" in n,
    Component: CompareWithSourceSection,
  },
  {
    id: "operation",
    order: 30,
    shouldRender: (n) => (n.editableSchema?.length ?? 0) > 0,
    Component: OperationSection,
  },
  {
    id: "roleGroups",
    order: 35,
    shouldRender: (n) => (n.kind === "model" || n.stage === "model") && !n.isDraft,
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
