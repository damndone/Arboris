import { apiUrl, readResponse } from "../api";
import type { RequestOf, ResponseOf } from "../apiTypes";
import type { DomainMemoryCandidate } from "./domainMemoryContracts";

type Library = "global" | "project";

const jsonHeaders = { "Content-Type": "application/json" };

function memoryPath(path: string, projectRoot: string): string {
  const separator = path.includes("?") ? "&" : "?";
  return apiUrl(`${path}${separator}project_root=${encodeURIComponent(projectRoot)}`);
}

export async function retrieveDomainMemory(
  projectRoot: string,
  input: RequestOf<"/domain-memory/retrieve", "post">,
): Promise<ResponseOf<"/domain-memory/retrieve", "post">> {
  return readResponse(await fetch(memoryPath("/domain-memory/retrieve", projectRoot), {
    method: "POST", headers: jsonHeaders, body: JSON.stringify({
      facts: {}, max_entries: 8, max_bytes: 8192, ...input,
    }),
  }));
}

export async function reviewDomainMemoryCandidate(
  projectRoot: string,
  candidateId: string,
  input: RequestOf<"/domain-memory/review/candidates/{candidate_id}", "post">,
): Promise<ResponseOf<"/domain-memory/review/candidates/{candidate_id}", "post">> {
  return readResponse(await fetch(memoryPath(`/domain-memory/review/candidates/${encodeURIComponent(candidateId)}`, projectRoot), {
    method: "POST", headers: jsonHeaders, body: JSON.stringify(input),
  }));
}

export async function listDomainMemoryCandidates(
  projectRoot: string,
): Promise<ResponseOf<"/domain-memory/candidates", "get">> {
  return readResponse(
    await fetch(memoryPath("/domain-memory/candidates", projectRoot)),
  );
}

export async function fetchDomainMemorySettings(
  projectRoot: string,
): Promise<ResponseOf<"/domain-memory/settings", "get">> {
  return readResponse(await fetch(memoryPath("/domain-memory/settings", projectRoot)));
}

export async function issueMemorySettingsConfirmation(
  projectRoot: string,
  input: RequestOf<"/domain-memory/settings/confirmations", "post">,
): Promise<ResponseOf<"/domain-memory/settings/confirmations", "post">> {
  return readResponse(await fetch(memoryPath("/domain-memory/settings/confirmations", projectRoot), {
    method: "POST", headers: jsonHeaders, body: JSON.stringify(input),
  }));
}

export async function updateGlobalMemorySettings(
  projectRoot: string,
  input: RequestOf<"/domain-memory/settings/global", "put">,
): Promise<ResponseOf<"/domain-memory/settings/global", "put">> {
  return readResponse(await fetch(memoryPath("/domain-memory/settings/global", projectRoot), {
    method: "PUT", headers: jsonHeaders, body: JSON.stringify(input),
  }));
}

export async function updateProjectMemorySetting(
  projectRoot: string,
  input: RequestOf<"/domain-memory/settings/project", "put">,
): Promise<ResponseOf<"/domain-memory/settings/project", "put">> {
  return readResponse(await fetch(memoryPath("/domain-memory/settings/project", projectRoot), {
    method: "PUT", headers: jsonHeaders, body: JSON.stringify(input),
  }));
}

export async function listDomainMemoryLibrary(
  projectRoot: string,
  library: Library,
): Promise<ResponseOf<"/domain-memory/libraries/{library}", "get">> {
  return readResponse(await fetch(memoryPath(`/domain-memory/libraries/${library}`, projectRoot)));
}

export async function issueArchiveMemoryConfirmation(
  projectRoot: string,
  library: Library,
  memoryIds: string[],
): Promise<ResponseOf<"/domain-memory/libraries/{library}/archive/confirmations", "post">> {
  return readResponse(await fetch(memoryPath(`/domain-memory/libraries/${library}/archive/confirmations`, projectRoot), {
    method: "POST", headers: jsonHeaders, body: JSON.stringify({ memory_ids: memoryIds }),
  }));
}

export async function archiveMemoryLibraryEntries(
  projectRoot: string,
  library: Library,
  input: RequestOf<"/domain-memory/libraries/{library}/archive", "post">,
): Promise<ResponseOf<"/domain-memory/libraries/{library}/archive", "post">> {
  return readResponse(await fetch(memoryPath(`/domain-memory/libraries/${library}/archive`, projectRoot), {
    method: "POST", headers: jsonHeaders, body: JSON.stringify(input),
  }));
}

export type { DomainMemoryCandidate };
