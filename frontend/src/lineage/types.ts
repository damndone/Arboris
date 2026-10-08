// frontend/src/lineage/types.ts
// The per-run lineage graph (GET /runs/:id/graph), as the backend declares it
// (see apiTypes.ts).
import type { Schema } from "../apiTypes";

export type Stage = Schema<"Stage">;
export type NodeKind = Schema<"NodeKind">;
export type Trust = Schema<"Trust">;
export type DecisionPoint = Schema<"DecisionPoint">;
export type DecisionSource = DecisionPoint["source"];
export type Contestability = Schema<"Contestability">;
export type ReviewStatus = Contestability["review_status"];
export type AutoChosenReason = Schema<"AutoChosenReason">;
export type ReasonType = AutoChosenReason["reason_type"];
export type LineageNode = Schema<"GraphNodeView">;
export type LineageEdge = Schema<"GraphEdgeView">;
export type BranchRef = Schema<"GraphBranchView">;
export type GraphStats = Schema<"GraphStats">;
export type GraphResponse = Schema<"RunGraph">;
