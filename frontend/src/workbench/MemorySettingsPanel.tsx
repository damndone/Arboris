import { useCallback, useEffect, useRef, useState } from "react";

import {
  archiveMemoryLibraryEntries,
  fetchDomainMemorySettings,
  issueArchiveMemoryConfirmation,
  issueMemorySettingsConfirmation,
  listDomainMemoryCandidates,
  listDomainMemoryLibrary,
  reviewDomainMemoryCandidate,
  updateGlobalMemorySettings,
  updateProjectMemorySetting,
} from "../notebook/domainMemoryApi";
import type {
  DomainMemoryCandidate,
  DomainMemoryLibrary,
  DomainMemorySettings,
  MemorySettingsConfirmation,
} from "../notebook/domainMemoryContracts";
import { DomainMemoryReviewQueue } from "../notebook/DomainMemoryReviewQueue";

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
  minHeight: 0,
  border: "1px solid var(--separator, #3a3a3c)",
  borderRadius: 8,
  padding: "6px 10px",
  background: "var(--bg-card-2, rgba(255,255,255,0.06))",
  color: "var(--label, #f5f5f7)",
  cursor: "pointer",
};

const confirmationBackdropStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 1000,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 20,
  background: "rgba(0, 0, 0, 0.28)",
};

const confirmationDialogStyle: React.CSSProperties = {
  width: "min(100%, 440px)",
  boxSizing: "border-box",
  border: "1px solid var(--separator, #3a3a3c)",
  borderRadius: 12,
  padding: 18,
  background: "var(--bg-card, #fff)",
  color: "var(--label, #1c1c1e)",
  boxShadow: "0 18px 48px rgba(0, 0, 0, 0.22)",
};

const switchTrackStyle = (enabled: boolean, disabled: boolean): React.CSSProperties => ({
  position: "relative",
  flex: "0 0 auto",
  width: 48,
  height: 20,
  minHeight: 0,
  padding: 2,
  border: "none",
  borderRadius: 999,
  background: enabled ? "var(--accent, #0a84ff)" : "var(--switch-off, #78788066)",
  boxShadow: enabled ? "inset 0 0 0 1px rgba(0,0,0,0.08)" : "inset 0 0 0 1px rgba(0,0,0,0.12)",
  cursor: disabled ? "wait" : "pointer",
  opacity: disabled ? 0.6 : 1,
  transition: "background-color 160ms ease, box-shadow 160ms ease",
});

const switchThumbStyle = (enabled: boolean): React.CSSProperties => ({
  display: "block",
  width: 16,
  height: 16,
  borderRadius: "50%",
  background: "#fff",
  boxShadow: "0 1px 3px rgba(0,0,0,0.28)",
  transform: enabled ? "translateX(28px)" : "translateX(0)",
  transition: "transform 160ms ease",
});

export function MemorySettingsPanel({ projectRoot }: { projectRoot: string }) {
  const [settings, setSettings] = useState<DomainMemorySettings | null>(null);
  const [settingsProjectRoot, setSettingsProjectRoot] = useState<string | null>(null);
  const [libraries, setLibraries] = useState<Record<"global" | "project", DomainMemoryLibrary | null>>({ global: null, project: null });
  const [candidates, setCandidates] = useState<DomainMemoryCandidate[]>([]);
  const [candidatesProjectRoot, setCandidatesProjectRoot] = useState<string | null>(null);
  const [candidateError, setCandidateError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingChange | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const currentProjectRoot = useRef(projectRoot);
  const refreshGeneration = useRef(0);
  currentProjectRoot.current = projectRoot;
  const isCurrentProject = useCallback(
    (requestedProjectRoot: string) => currentProjectRoot.current === requestedProjectRoot,
    [],
  );

  const refresh = useCallback(async () => {
    if (currentProjectRoot.current !== projectRoot) return;
    const generation = refreshGeneration.current + 1;
    refreshGeneration.current = generation;
    const isCurrent = () => (
      currentProjectRoot.current === projectRoot && refreshGeneration.current === generation
    );
    const [nextSettings, globalLibrary, projectLibrary] = await Promise.all([
      fetchDomainMemorySettings(projectRoot),
      listDomainMemoryLibrary(projectRoot, "global"),
      listDomainMemoryLibrary(projectRoot, "project"),
    ]);
    if (!isCurrent()) return;
    setSettings(nextSettings);
    setSettingsProjectRoot(projectRoot);
    setLibraries({ global: globalLibrary, project: projectLibrary });
    setCandidates([]);
    setCandidatesProjectRoot(null);
    setCandidateError(null);
    try {
      const nextCandidates = await listDomainMemoryCandidates(projectRoot);
      if (!isCurrent()) return;
      setCandidates(nextCandidates.candidates);
      setCandidatesProjectRoot(projectRoot);
      setCandidateError(null);
    } catch {
      if (!isCurrent()) return;
      setCandidates([]);
      setCandidatesProjectRoot(projectRoot);
      setCandidateError("Candidate review is temporarily unavailable. Other memory settings remain available.");
    }
  }, [projectRoot]);

  useEffect(() => {
    let active = true;
    setSettings(null);
    setSettingsProjectRoot(null);
    setLibraries({ global: null, project: null });
    setCandidates([]);
    setCandidatesProjectRoot(null);
    setCandidateError(null);
    setPending(null);
    setError(null);
    setBusy(false);
    void refresh().catch((requestError) => {
      if (active) setError(errorMessage(requestError));
    });
    return () => {
      active = false;
      refreshGeneration.current += 1;
    };
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

  async function reviewCandidate(
    candidateId: string,
    decision: "approved" | "rejected",
    expectedRevision: number,
  ) {
    const requestedProjectRoot = projectRoot;
    setBusy(true);
    setError(null);
    try {
      const now = new Date();
      await reviewDomainMemoryCandidate(requestedProjectRoot, candidateId, decision === "approved"
        ? {
            decision,
            expected_revision: expectedRevision,
            actor_id: "local-user",
            approved_at: now.toISOString(),
            review_after: new Date(now.getTime() + 90 * 24 * 60 * 60 * 1000).toISOString(),
          }
        : { decision, expected_revision: expectedRevision, actor_id: "local-user" });
      if (!isCurrentProject(requestedProjectRoot)) return;
      await refresh();
    } catch (requestError) {
      if (isCurrentProject(requestedProjectRoot)) setError(errorMessage(requestError));
    } finally {
      if (isCurrentProject(requestedProjectRoot)) setBusy(false);
    }
  }

  if (!settings || settingsProjectRoot !== projectRoot) {
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
      <button
        type="button"
        role="switch"
        aria-label={label}
        aria-checked={enabled}
        aria-disabled={busy}
        disabled={busy}
        onClick={onClick}
        title={`${enabled ? "On" : "Off"} · ${label}. Hints only; no automatic execution.`}
        style={switchTrackStyle(enabled, busy)}
      >
        <span aria-hidden="true" style={switchThumbStyle(enabled)} />
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
      <section aria-label="Pending memory candidate review" style={{ marginTop: 20 }}>
        <h3 style={{ margin: "0 0 6px" }}>Pending review</h3>
        <p style={{ marginTop: 0, color: "var(--label-secondary, #98989d)" }}>
          Approving a candidate only adds a reviewed memory entry. It never runs analysis or changes a Draft.
        </p>
        {candidateError && candidatesProjectRoot === projectRoot ? <p role="status">{candidateError}</p> : (
          <DomainMemoryReviewQueue
            candidates={candidatesProjectRoot === projectRoot ? candidates : []}
            onReview={(candidateId, decision, revision) => void reviewCandidate(candidateId, decision, revision)}
          />
        )}
      </section>
      {renderLibrary("global")}
      {renderLibrary("project")}
      {pending ? <div data-testid="memory-confirmation-backdrop" style={confirmationBackdropStyle}>
        <div role="dialog" aria-modal="true" aria-label="Confirm memory change" style={confirmationDialogStyle}>
          <strong>Confirm memory change</strong>
          <p>{pending.summary}</p>
          <p>No automatic execution will occur.</p>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button type="button" disabled={busy} onClick={() => setPending(null)} style={buttonStyle}>Cancel</button>
            <button type="button" disabled={busy} onClick={() => void confirmPending()} style={buttonStyle}>Confirm</button>
          </div>
        </div>
      </div> : null}
    </section>
  );
}
