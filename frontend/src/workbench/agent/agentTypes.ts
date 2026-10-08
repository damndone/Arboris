/**
 * Agent API shapes, as the backend declares them (see apiTypes.ts). Only the
 * client-side context packet is defined here.
 */
import type { Schema } from "../../apiTypes";

export type AgentRole = Schema<"AgentSessionCreateRequest">["role"];
export type AgentMessage = Schema<"AgentMessage">;
export type AgentNavigationRef = Schema<"AgentNavigationRef">;
export type AgentNavigationProjection = Schema<"NavigationProjectionView">;
export type AgentHierarchyNode = Schema<"HierarchyNodeView">;
export type AgentActivityItem = Schema<"ActivityOperationItem">;
export type AgentActivityEventItem = Schema<"ActivityEventItem">;
export type AgentEvent = Schema<"AgentEvent">;
export type AgentProposal = Schema<"PublicProposal">;
export type AgentOperationRecord = Schema<"OperationRecordView">;
export type AgentSession = Schema<"AgentSession">;
export type AgentModelOption = Schema<"ProviderModel">;
export type AgentCapability = Schema<"OperationCapability">;
export type AgentCapabilityBoundaryItem = Schema<"BoundaryItem">;
export type AgentCapabilityCatalog = Schema<"AgentCapabilities">;
export type AgentSessionCreateRequest = Schema<"AgentSessionCreateRequest">;

/** What the client tells the Agent about the current view. */
export type AgentContextPacket = Record<string, unknown>;
