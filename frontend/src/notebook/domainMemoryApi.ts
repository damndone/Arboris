import { apiUrl, readResponse } from "../api";
import type {
  DomainMemoryPreferences,
  DomainMemoryRequestOverride,
  DomainMemoryRetrievalProjection,
  DomainMemoryScope,
} from "./domainMemoryContracts";

const jsonHeaders = { "Content-Type": "application/json" };

function memoryPath(path: string, projectRoot: string): string {
  const separator = path.includes("?") ? "&" : "?";
  return apiUrl(`${path}${separator}project_root=${encodeURIComponent(projectRoot)}`);
}

export async function retrieveDomainMemory(
  projectRoot: string,
  input: {
    requester_scope: DomainMemoryScope;
    preferences?: DomainMemoryPreferences;
    override?: DomainMemoryRequestOverride;
    facts?: Record<string, unknown>;
    now: string;
    max_entries?: number;
    max_bytes?: number;
  },
): Promise<DomainMemoryRetrievalProjection> {
  return readResponse<DomainMemoryRetrievalProjection>(await fetch(memoryPath("/domain-memory/retrieve", projectRoot), {
    method: "POST", headers: jsonHeaders, body: JSON.stringify({
      preferences: { cross_project_domain_memory_use: false, cross_project_domain_memory_iteration: false, ...input.preferences },
      override: {}, facts: {}, max_entries: 8, max_bytes: 8192, ...input,
    }),
  }));
}
