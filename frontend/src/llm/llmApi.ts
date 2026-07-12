import { apiUrl, readResponse } from "../api";
import type {
  LlmConfigInfo,
  LlmProvider,
  LlmProvidersResponse,
  ProviderUpsertInput,
} from "./llmTypes";

const jsonHeaders = { "Content-Type": "application/json" };

function providerPath(providerId: string, suffix = ""): string {
  return `/llm/providers/${encodeURIComponent(providerId)}${suffix}`;
}

function sanitizedUpsertInput(input: ProviderUpsertInput): ProviderUpsertInput {
  const body = { ...input };
  if (body.api_key !== undefined && body.api_key.trim() === "") {
    delete body.api_key;
  }
  if (body.clear_api_key !== true) {
    delete body.clear_api_key;
  }
  return body;
}

async function readLlmResponse<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(apiUrl(path), init);
  return readResponse<T>(response);
}

export function fetchLlmProviders(): Promise<LlmProvidersResponse> {
  return readLlmResponse<LlmProvidersResponse>("/llm/providers");
}

export function createLlmProvider(
  input: ProviderUpsertInput,
): Promise<LlmProvider> {
  return readLlmResponse<LlmProvider>("/llm/providers", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(sanitizedUpsertInput(input)),
  });
}

export function updateLlmProvider(
  providerId: string,
  input: ProviderUpsertInput,
): Promise<LlmProvider> {
  return readLlmResponse<LlmProvider>(providerPath(providerId), {
    method: "PUT",
    headers: jsonHeaders,
    body: JSON.stringify(sanitizedUpsertInput(input)),
  });
}

export function activateLlmProvider(providerId: string): Promise<LlmProvider> {
  return readLlmResponse<LlmProvider>(providerPath(providerId, "/activate"), {
    method: "POST",
  });
}

export function deleteLlmProvider(providerId: string): Promise<LlmProvider> {
  return readLlmResponse<LlmProvider>(providerPath(providerId), {
    method: "DELETE",
  });
}

export function refreshLlmProviderModels(
  providerId: string,
): Promise<LlmProvider> {
  return readLlmResponse<LlmProvider>(
    providerPath(providerId, "/models/refresh"),
    { method: "POST" },
  );
}

export function probeLlmProvider(providerId: string): Promise<LlmProvider> {
  return readLlmResponse<LlmProvider>(providerPath(providerId, "/probe"), {
    method: "POST",
  });
}

export function fetchLlmConfig(): Promise<LlmConfigInfo> {
  return readLlmResponse<LlmConfigInfo>("/llm/config");
}
