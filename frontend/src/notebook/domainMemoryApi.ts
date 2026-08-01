import { apiUrl, readResponse } from "../api";
import type {
  DomainMemoryCandidate,
  DomainMemoryRetrievalProjection,
  DomainMemorySettings,
  DomainMemoryLibrary,
  MemorySettingsConfirmation,
} from "./domainMemoryContracts";

const jsonHeaders = { "Content-Type": "application/json" };

function memoryPath(path: string, projectRoot: string): string {
  const separator = path.includes("?") ? "&" : "?";
  return apiUrl(`${path}${separator}project_root=${encodeURIComponent(projectRoot)}`);
}

export async function retrieveDomainMemory(
  projectRoot: string,
  input: {
    facts?: Record<string, unknown>;
    max_entries?: number;
    max_bytes?: number;
  },
): Promise<DomainMemoryRetrievalProjection> {
  return readResponse<DomainMemoryRetrievalProjection>(await fetch(memoryPath("/domain-memory/retrieve", projectRoot), {
    method: "POST", headers: jsonHeaders, body: JSON.stringify({
      facts: {}, max_entries: 8, max_bytes: 8192, ...input,
    }),
  }));
}

export async function reviewDomainMemoryCandidate(
  projectRoot: string,
  candidateId: string,
  input: { decision: "approved" | "rejected"; expected_revision: number; actor_id: string; approved_at?: string; review_after?: string; resolve_conflicts?: boolean },
): Promise<Record<string, unknown>> {
  return readResponse<Record<string, unknown>>(await fetch(memoryPath(`/domain-memory/review/candidates/${encodeURIComponent(candidateId)}`, projectRoot), {
    method: "POST", headers: jsonHeaders, body: JSON.stringify(input),
  }));
}

export async function fetchDomainMemorySettings(projectRoot: string): Promise<DomainMemorySettings> {
  return readResponse<DomainMemorySettings>(await fetch(memoryPath("/domain-memory/settings", projectRoot)));
}

export async function issueMemorySettingsConfirmation(
  projectRoot: string,
  input: { action: string; expected_revision: number; target_refs: string[] },
): Promise<MemorySettingsConfirmation> {
  return readResponse<MemorySettingsConfirmation>(await fetch(memoryPath("/domain-memory/settings/confirmations", projectRoot), {
    method: "POST", headers: jsonHeaders, body: JSON.stringify(input),
  }));
}

export async function updateGlobalMemorySettings(
  projectRoot: string,
  input: { library_enabled: boolean; expected_revision: number; confirmation_receipt: string },
): Promise<DomainMemorySettings> {
  return readResponse<DomainMemorySettings>(await fetch(memoryPath("/domain-memory/settings/global", projectRoot), {
    method: "PUT", headers: jsonHeaders, body: JSON.stringify(input),
  }));
}

export async function updateProjectMemorySetting(
  projectRoot: string,
  input: {
    setting: "library_enabled" | "inherit_global" | "candidate_generation_enabled";
    enabled: boolean;
    expected_revision: number;
    confirmation_receipt: string;
  },
): Promise<DomainMemorySettings> {
  return readResponse<DomainMemorySettings>(await fetch(memoryPath("/domain-memory/settings/project", projectRoot), {
    method: "PUT", headers: jsonHeaders, body: JSON.stringify(input),
  }));
}

export async function listDomainMemoryLibrary(
  projectRoot: string,
  library: "global" | "project",
): Promise<DomainMemoryLibrary> {
  return readResponse<DomainMemoryLibrary>(await fetch(memoryPath(`/domain-memory/libraries/${library}`, projectRoot)));
}

export async function issueArchiveMemoryConfirmation(
  projectRoot: string,
  library: "global" | "project",
  memoryIds: string[],
): Promise<MemorySettingsConfirmation> {
  return readResponse<MemorySettingsConfirmation>(await fetch(memoryPath(`/domain-memory/libraries/${library}/archive/confirmations`, projectRoot), {
    method: "POST", headers: jsonHeaders, body: JSON.stringify({ memory_ids: memoryIds }),
  }));
}

export async function archiveMemoryLibraryEntries(
  projectRoot: string,
  library: "global" | "project",
  input: { memory_ids: string[]; confirmation_receipt: string },
): Promise<{ archived_count: number; entries: DomainMemoryLibrary["entries"] }> {
  return readResponse<{ archived_count: number; entries: DomainMemoryLibrary["entries"] }>(await fetch(memoryPath(`/domain-memory/libraries/${library}/archive`, projectRoot), {
    method: "POST", headers: jsonHeaders, body: JSON.stringify(input),
  }));
}

export type { DomainMemoryCandidate };
