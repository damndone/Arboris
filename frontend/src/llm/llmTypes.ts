/**
 * LLM provider API shapes, as the backend declares them (see apiTypes.ts).
 * Only the client-side preset list is defined here.
 */
import type { Schema } from "../apiTypes";

export type LlmModel = Schema<"ProviderModel">;
export type LlmProvider = Schema<"PublicProvider">;
export type LlmProvidersResponse = Schema<"ProviderList">;
export type LlmConfigInfo = Schema<"LlmConfig">;
export type ProviderUpsertInput = Schema<"ProviderUpsertRequest">;
export type ModelsDiscoveryInput = Schema<"ModelsDiscoveryRequest">;
export type ModelsDiscoveryResult = Schema<"DiscoveredModels">;

export interface LlmProviderPreset {
  name: string;
  baseUrl: string;
}
