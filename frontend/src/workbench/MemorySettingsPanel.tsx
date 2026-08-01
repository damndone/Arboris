import { useCallback, useEffect, useState } from "react";

import {
  archiveMemoryLibraryEntries,
  fetchDomainMemorySettings,
  issueArchiveMemoryConfirmation,
  issueMemorySettingsConfirmation,
  listDomainMemoryLibrary,
  updateGlobalMemorySettings,
  updateProjectMemorySetting,
} from "../notebook/domainMemoryApi";
import type {
  DomainMemoryLibrary,
  DomainMemorySettings,
  MemorySettingsConfirmation,
} from "../notebook/domainMemoryContracts";

type PendingChange = {
  confirmation: MemorySettingsConfirmation;
  summary: string;
  commit: () => Promise<void>;
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Memory settings request failed";
}

const controlStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 16,
  padding: "12px 0",
  borderBottom: "1px solid var(--separator, #3a3a3c)",
};

const buttonStyle: React.CSSProperties = {
  border: "1px solid var(--separator, #3a3a3c)",
  borderRadius: 8,
  padding: "6px 10px",
  background: "var(--bg-card-2, rgba(255,255,255,0.06))",
  color: "var(--label, #f5f5f7)",
  cursor: "pointer",
};

export function MemorySettingsPanel({ projectRoot }: { projectRoot: string }) {
  const [settings, setSettings] = useState<DomainMemorySettings | null>(null);
  const [libraries, setLibraries] = useState<Record<"global" | "project", DomainMemoryLibrary | null>>({ global: null, project: null });
  const [pending, setPending] = useState<PendingChange | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [nextSettings, globalLibrary, projectLibrary] = await Promise.all([
      fetchDomainMemorySettings(projectRoot),
      listDomainMemoryLibrary(projectRoot, "global"),
      listDomainMemoryLibrary(projectRoot, "project"),
    ]);
    setSettings(nextSettings);
    setLibraries({ global: globalLibrary, project: projectLibrary });
  }, [projectRoot]);

  useEffect(() => {
    void refresh().catch((requestError) => setError(errorMessage(requestError)));
  }, [refresh]);

  async function beginSetting(
    action: string,
    expectedRevision: number,
    summary: string,
    commit: (confirmation: MemorySettingsConfirmation) => Promise<DomainMemorySettings>,
  ) {
    setBusy(true);
    setError(null);
    try {
      const confirmation = await issueMemorySettingsConfirmation(projectRoot, {
        action,
        expected_revision: expectedRevision,
        target_refs: [],
      });
      setPending({
        confirmation,
        summary,
        commit: async () => {
          const next = await commit(confirmation);
          setSettings(next);
          await refresh();
        },
      });
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function beginArchive(library: "global" | "project", memoryIds: string[]) {
    setBusy(true);
    setError(null);
    try {
      const confirmation = await issueArchiveMemoryConfirmation(projectRoot, library, memoryIds);
      setPending({
        confirmation,
        summary: `Archive ${memoryIds.length} memory entr${memoryIds.length === 1 ? "y" : "ies"} from the ${library} library. Completed runs keep their provenance.`,
        commit: async () => {
          await archiveMemoryLibraryEntries(projectRoot, library, {
            memory_ids: memoryIds,
            confirmation_receipt: confirmation.receipt,
          });
          await refresh();
        },
      });
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function confirmPending() {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      await pending.commit();
      setPending(null);
    } catch (requestError) {
      setError(errorMessage(requestError));
      setPending(null);
    } finally {
      setBusy(false);
    }
  }

  if (!settings) {
    return <section data-testid="memory-settings-panel" aria-label="Memory settings">{error ?? "Loading memory settings…"}</section>;
  }

  const projectSettings = settings.project;
  const globalSettings = settings.global;
  const renderToggle = (
    label: string,
    enabled: boolean,
    onClick: () => void,
  ) => (
    <div style={controlStyle}>
      <span><strong>{label}</strong><br /><small>{enabled ? "On" : "Off"} · Hints only · No automatic execution</small></span>
      <button type="button" disabled={busy} onClick={onClick} style={buttonStyle}>
        {enabled ? `Disable ${label.toLowerCase()}` : `Enable ${label.toLowerCase()}`}
      </button>
    </div>
  );

  const renderLibrary = (library: "global" | "project") => {
    const entries = libraries[library]?.entries ?? [];
    const active = entries.filter((entry) => entry.state === "active");
    return (
      <section aria-label={`${library} memory library`} style={{ marginTop: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
          <h3 style={{ margin: 0 }}>{library === "global" ? "Global library" : "Project library"}</h3>
          {active.length > 0 ? <button type="button" disabled={busy} onClick={() => void beginArchive(library, active.map((entry) => entry.memory_id))} style={buttonStyle}>Archive active</button> : null}
        </div>
        {entries.length === 0 ? <p style={{ color: "var(--label-secondary, #98989d)" }}>No approved memory yet.</p> : (
          <ul style={{ paddingLeft: 0, listStyle: "none", display: "grid", gap: 8 }}>
            {entries.map((entry) => <li key={`${entry.memory_id}@${entry.revision}`} style={{ border: "1px solid var(--separator, #3a3a3c)", borderRadius: 8, padding: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
                <span><code>{entry.memory_id}@{entry.revision}</code> · {entry.state}</span>
                {entry.state === "active" ? <button type="button" disabled={busy} onClick={() => void beginArchive(library, [entry.memory_id])} style={buttonStyle}>Archive</button> : null}
              </div>
              <small style={{ color: "var(--label-secondary, #98989d)" }}>{entry.memory_kind} · {entry.domain_tags.join(", ") || "untagged"} · {entry.apply_mode === "suggest_default" ? "May suggest a default" : "Information only"}</small>
              <div style={{ marginTop: 6 }}>{entry.compact_lesson}</div>
            </li>)}
          </ul>
        )}
      </section>
    );
  };

  return (
    <section data-testid="memory-settings-panel" aria-label="Memory settings" style={{ maxWidth: 760 }}>
      <h2 style={{ margin: "0 0 6px" }}>Memory</h2>
      <p style={{ marginTop: 0, color: "var(--label-secondary, #98989d)" }}>Memory is off by default. A project never inherits global memory unless you explicitly enable it here.</p>
      {error ? <div role="alert">{error}</div> : null}
      {renderToggle("Global library", globalSettings.library_enabled, () => void beginSetting(
        globalSettings.library_enabled ? "disable_global_library" : "enable_global_library",
        globalSettings.revision,
        `${globalSettings.library_enabled ? "Disable" : "Enable"} the global memory library.`,
        (confirmation) => updateGlobalMemorySettings(projectRoot, {
          library_enabled: !globalSettings.library_enabled,
          expected_revision: globalSettings.revision,
          confirmation_receipt: confirmation.receipt,
        }),
      ))}
      {renderToggle("Project library", projectSettings.library_enabled, () => void beginSetting(
        projectSettings.library_enabled ? "disable_project_library" : "enable_project_library",
        projectSettings.revision,
        `${projectSettings.library_enabled ? "Disable" : "Enable"} this project's memory library.`,
        (confirmation) => updateProjectMemorySetting(projectRoot, {
          setting: "library_enabled", enabled: !projectSettings.library_enabled,
          expected_revision: projectSettings.revision, confirmation_receipt: confirmation.receipt,
        }),
      ))}
      {renderToggle("Use global library in this project", projectSettings.inherit_global, () => void beginSetting(
        projectSettings.inherit_global ? "disable_global_inheritance" : "enable_global_inheritance",
        projectSettings.revision,
        `${projectSettings.inherit_global ? "Stop" : "Start"} using global memory in this project.`,
        (confirmation) => updateProjectMemorySetting(projectRoot, {
          setting: "inherit_global", enabled: !projectSettings.inherit_global,
          expected_revision: projectSettings.revision, confirmation_receipt: confirmation.receipt,
        }),
      ))}
      {renderToggle("Allow candidate generation", projectSettings.candidate_generation_enabled, () => void beginSetting(
        projectSettings.candidate_generation_enabled ? "disable_candidate_generation" : "enable_candidate_generation",
        projectSettings.revision,
        `${projectSettings.candidate_generation_enabled ? "Disable" : "Enable"} bounded candidate generation for this project.`,
        (confirmation) => updateProjectMemorySetting(projectRoot, {
          setting: "candidate_generation_enabled", enabled: !projectSettings.candidate_generation_enabled,
          expected_revision: projectSettings.revision, confirmation_receipt: confirmation.receipt,
        }),
      ))}
      {renderLibrary("global")}
      {renderLibrary("project")}
      {pending ? <div role="dialog" aria-label="Confirm memory change" style={{ marginTop: 20, border: "1px solid var(--separator, #3a3a3c)", borderRadius: 10, padding: 16 }}>
        <strong>Confirm memory change</strong>
        <p>{pending.summary}</p>
        <p>No automatic execution will occur.</p>
        <button type="button" disabled={busy} onClick={() => void confirmPending()} style={buttonStyle}>Confirm</button>
        <button type="button" disabled={busy} onClick={() => setPending(null)} style={{ ...buttonStyle, marginLeft: 8 }}>Cancel</button>
      </div> : null}
    </section>
  );
}
