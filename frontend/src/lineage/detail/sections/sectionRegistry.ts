// frontend/src/lineage/detail/sections/sectionRegistry.ts
//
// V1.5.0 DetailDrawer section registry (Step 6, T6.1).
//
// The DetailDrawer renders DetailHeader (always, never in the registry —
// see spec §8.2) followed by the registered sections in `order` after
// each one's `shouldRender(node)` filter. Adding a section in V1.5.x is
// two changes: create the component, append an entry here. DetailDrawer
// itself is not touched.
//
// Order slots (10..110) leave room for future sections without renumbering:
//   10  TrustBanner            — V1.5.0 (this file)
//   20  AskAISection           — V1.5.2
//   30  OperationSection       — V1.5.2
//   40  CodeSection            — V1.5.1 read-only
//   50  LineageChainSection    — V1.5.0
//   60  BasicInfoSection       — V1.5.0
//   70  DecisionSection        — V1.5.0
//   80  CoefficientSection     — V1.5.x
//   90  ArtifactSection        — V1.5.x
//  100  PreviewSection         — V1.5.x
//  110  HistogramSection       — V1.5.x
//
// Spec §8.1 / §8.2.

import type { FC } from "react";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { TrustBanner } from "./TrustBanner";
import { LineageChainSection } from "./LineageChainSection";
import { BasicInfoSection } from "./BasicInfoSection";
import { DecisionSection } from "./DecisionSection";

export interface SectionSpec {
  id: string;
  order: number;
  shouldRender: (node: GraphViewNode) => boolean;
  Component: FC<{ node: GraphViewNode }>;
}

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

export const sectionRegistry: SectionSpec[] = [
  { id: "trust", order: 10, shouldRender: needsTrust, Component: TrustBanner },
  { id: "lineage", order: 50, shouldRender: () => true, Component: LineageChainSection },
  { id: "basic", order: 60, shouldRender: () => true, Component: BasicInfoSection },
  {
    id: "decision",
    order: 70,
    shouldRender: (n) => n.decisions.length > 0,
    Component: DecisionSection,
  },
];

// Exported for testing only — `needsTrust` semantics are part of the
// trust contract (REV-2 will lock these scenarios in T6.4).
export const _needsTrust = needsTrust;
