import { useEffect, useState } from "react";
import { ApiError, fetchRuns } from "../../api";
import { fetchLlmConfig } from "../../llm/llmApi";
import type { LlmConfigInfo } from "../../llm/llmTypes";
import { listRecents, removeRecent, touchRecent } from "../../launcher/recents";
import type { RecentProject } from "../../launcher/recents";
import { CreateProjectModal } from "../../launcher/CreateProjectModal";

export interface WorkbenchHomeViewProps {
  projectRoot?: string;
  onOpenSettings?: () => void;
  onCreateProject?: () => void;
  onOpenProject?: (root: string) => void;
}

type LlmState =
  | { status: "loading"; config: null; error: null }
  | { status: "ready"; config: LlmConfigInfo; error: null }
  | { status: "error"; config: null; error: string };

function projectName(root: string): string {
  return root.split("/").filter(Boolean).pop() ?? root;
}

function formatContextWindow(tokens: number | null): string {
  if (tokens === null) return "Unavailable";
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M tokens`;
  return `${Math.round(tokens / 1_000)}K tokens`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to load LLM status";
}

function RecentProjectCard({
  recent,
  current,
  probing,
  onOpen,
}: {
  recent: RecentProject;
  current: boolean;
  probing: boolean;
  onOpen: (root: string) => void;
}) {
  return (
    <li>
      <button
        type="button"
        data-testid={`workbench-home-recent-${recent.root}`}
        onClick={() => onOpen(recent.root)}
        disabled={probing}
        style={{
          width: "100%",
          minHeight: 92,
          padding: 16,
          textAlign: "left",
          border: "1px solid var(--separator, #3a3a3c)",
          borderRadius: 12,
          background: "var(--bg-card-2, rgba(255,255,255,0.04))",
          color: "var(--label, #f5f5f7)",
          cursor: probing ? "default" : "pointer",
        }}
      >
        <strong style={{ display: "block", fontSize: 15 }}>
          {projectName(recent.root)}
          {current && (
            <span
              style={{
                marginLeft: 8,
                color: "var(--tint, #0a84ff)",
                fontSize: 11,
                fontWeight: 500,
              }}
            >
              Current
            </span>
          )}
        </strong>
        <span
          className="mono"
          style={{
            display: "block",
            marginTop: 8,
            color: "var(--label-secondary, #98989d)",
            fontSize: 12,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {recent.root}
        </span>
        <span
          style={{
            display: "block",
            marginTop: 8,
            color: "var(--label-tertiary, #8e8e93)",
            fontSize: 11,
          }}
        >
          {probing ? "Opening…" : `Last opened ${recent.lastOpened}`}
        </span>
      </button>
    </li>
  );
}

export function WorkbenchHomeView({
  projectRoot = "",
  onOpenSettings,
  onCreateProject,
  onOpenProject,
}: WorkbenchHomeViewProps) {
  const [recents, setRecents] = useState<RecentProject[]>(() => listRecents());
  const [probingRoot, setProbingRoot] = useState<string | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [llm, setLlm] = useState<LlmState>({
    status: "loading",
    config: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    void fetchLlmConfig()
      .then((config) => {
        if (!cancelled) setLlm({ status: "ready", config, error: null });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLlm({ status: "error", config: null, error: errorMessage(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function reconcileRecentProjects() {
      const saved = listRecents();
      await Promise.all(
        saved.map(async (recent) => {
          try {
            await fetchRuns(recent.root);
          } catch (error: unknown) {
            // A recent is a local pointer, not a project registry. Remove it
            // when the backend proves that its directory moved or disappeared;
            // transient/backend errors stay visible for a later retry.
            if (error instanceof ApiError && error.code === "PROJECT_NOT_FOUND") {
              removeRecent(recent.root);
            }
          }
        }),
      );

      if (projectRoot) {
        try {
          await fetchRuns(projectRoot);
          touchRecent(projectRoot);
        } catch {
          // The graph route may still be loading; do not manufacture a recent
          // entry until the backend confirms this project root.
        }
      }

      if (!cancelled) setRecents(listRecents());
    }

    void reconcileRecentProjects();
    return () => {
      cancelled = true;
    };
  }, [projectRoot]);

  async function openProject(root: string) {
    if (probingRoot) return;
    setProbingRoot(root);
    setProjectError(null);
    try {
      await fetchRuns(root);
    } catch (error: unknown) {
      if (error instanceof ApiError && error.code === "PROJECT_NOT_FOUND") {
        removeProject(root);
        // A missing recent is a stale local pointer, not a navigable route
        // failure. Remove it and keep the user on Home without an alert that
        // looks like the graph route itself has failed.
        setProjectError(null);
      } else {
        setProjectError(error instanceof Error ? error.message : "Unable to open project");
      }
      return;
    } finally {
      setProbingRoot(null);
    }
    touchRecent(root);
    setRecents(listRecents());
    onOpenProject?.(root);
  }

  function removeProject(root: string) {
    removeRecent(root);
    setRecents(listRecents());
  }

  function createProject() {
    if (onCreateProject) onCreateProject();
    else setCreateModalOpen(true);
  }

  const currentProject = projectRoot
    ? recents.find((recent) => recent.root === projectRoot)
    : undefined;

  return (
    <section
      data-testid="workbench-home"
      aria-labelledby="workbench-home-title"
      style={{
        flex: 1,
        minHeight: 0,
        overflow: "auto",
        padding: "32px clamp(20px, 5vw, 72px) 56px",
        boxSizing: "border-box",
        color: "var(--label, #f5f5f7)",
      }}
    >
      <div style={{ maxWidth: 1080, margin: "0 auto" }}>
        <header style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <p style={{ margin: "0 0 8px", color: "var(--label-secondary, #98989d)", fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase" }}>
              Workbench
            </p>
            <h1 id="workbench-home-title" style={{ margin: 0, fontSize: 30, letterSpacing: "-0.02em" }}>
              Project home
            </h1>
            <p style={{ margin: "10px 0 0", color: "var(--label-secondary, #98989d)" }}>
              Continue an analysis, switch projects, or start a new one.
            </p>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
            {onCreateProject && (
              <button
                type="button"
                data-testid="workbench-home-new-project"
                onClick={createProject}
                style={{ padding: "9px 14px", borderRadius: 8, border: "1px solid var(--tint, #0a84ff)", background: "var(--tint, #0a84ff)", color: "white", cursor: "pointer" }}
              >
                New project
              </button>
            )}
          </div>
        </header>

        {currentProject && (
          <article
            data-testid="workbench-home-current-project"
            style={{ marginTop: 28, padding: 20, borderRadius: 14, border: "1px solid var(--tint, #0a84ff)", background: "var(--tint-bg, rgba(10,132,255,0.12))" }}
          >
            <span style={{ color: "var(--label-secondary, #98989d)", fontSize: 12 }}>Continue current project</span>
            <h2 style={{ margin: "7px 0 4px", fontSize: 20 }}>{projectName(projectRoot)}</h2>
            <span className="mono" style={{ color: "var(--label-secondary, #98989d)", fontSize: 12 }}>{projectRoot}</span>
            <button
              type="button"
              data-testid="workbench-home-continue"
              onClick={() => openProject(projectRoot)}
              style={{ display: "block", marginTop: 16, padding: "8px 12px", borderRadius: 7, border: "1px solid var(--separator, #3a3a3c)", background: "transparent", color: "var(--label, #f5f5f7)", cursor: "pointer" }}
            >
              Open project
            </button>
          </article>
        )}

        <section aria-labelledby="recent-projects-title" style={{ marginTop: 32 }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
            <h2 id="recent-projects-title" style={{ margin: 0, fontSize: 17 }}>Recent projects</h2>
            <span style={{ color: "var(--label-tertiary, #8e8e93)", fontSize: 12 }}>{recents.length} saved</span>
          </div>
          {recents.length === 0 ? (
            <p data-testid="workbench-home-empty-recent" style={{ color: "var(--label-secondary, #98989d)" }}>
              No recent projects yet. Create a project to begin.
            </p>
          ) : (
            <ul data-testid="workbench-home-recents" style={{ listStyle: "none", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12, padding: 0, margin: "14px 0 0" }}>
              {recents.map((recent) => (
                <RecentProjectCard
                  key={recent.root}
                  recent={recent}
                  current={recent.root === projectRoot}
                  onOpen={openProject}
                  probing={probingRoot === recent.root}
                />
              ))}
            </ul>
          )}
          {projectError && (
            <p role="alert" style={{ color: "var(--danger, #ff453a)" }}>
              {projectError}
            </p>
          )}
        </section>

        <section
          data-testid="workbench-home-llm-card"
          aria-labelledby="llm-status-title"
          style={{ marginTop: 32, padding: 20, borderRadius: 14, border: "1px solid var(--separator, #3a3a3c)", background: "var(--bg-card-2, rgba(255,255,255,0.04))" }}
        >
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
            <div>
              <h2 id="llm-status-title" style={{ margin: 0, fontSize: 17 }}>LLM connection</h2>
              <p style={{ margin: "7px 0 0", color: "var(--label-secondary, #98989d)", fontSize: 13 }}>The active provider used by Ask AI.</p>
            </div>
            {onOpenSettings && (
              <button type="button" onClick={onOpenSettings} style={{ padding: "6px 10px", borderRadius: 7, border: "1px solid var(--separator, #3a3a3c)", background: "transparent", color: "var(--label, #f5f5f7)", cursor: "pointer" }}>
                Configure
              </button>
            )}
          </div>
          {llm.status === "loading" && <p data-testid="workbench-home-llm-loading" aria-live="polite" style={{ color: "var(--label-secondary, #98989d)" }}>Loading connection status…</p>}
          {llm.status === "error" && <p data-testid="workbench-home-llm-error" role="alert" style={{ color: "var(--danger, #ff453a)" }}>{llm.error}</p>}
          {llm.status === "ready" && (
            <dl data-testid="workbench-home-llm-ready" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14, margin: "18px 0 0" }}>
              <div><dt style={{ color: "var(--label-secondary, #98989d)", fontSize: 12 }}>Provider</dt><dd style={{ margin: "4px 0 0" }}>{llm.config.provider_name ?? "Not configured"}</dd></div>
              <div><dt style={{ color: "var(--label-secondary, #98989d)", fontSize: 12 }}>Model</dt><dd className="mono" style={{ margin: "4px 0 0", fontSize: 12 }}>{llm.config.model ?? "—"}</dd></div>
              <div><dt style={{ color: "var(--label-secondary, #98989d)", fontSize: 12 }}>Context</dt><dd style={{ margin: "4px 0 0" }}>{formatContextWindow(llm.config.context_window_tokens)}</dd></div>
              <div><dt style={{ color: "var(--label-secondary, #98989d)", fontSize: 12 }}>1M context</dt><dd style={{ margin: "4px 0 0" }}>{llm.config.supports_1m ? "Supported" : "Not enabled"}</dd></div>
              <div><dt style={{ color: "var(--label-secondary, #98989d)", fontSize: 12 }}>API key</dt><dd style={{ margin: "4px 0 0" }}>{llm.config.key_present ? "Configured" : "Missing"}</dd></div>
            </dl>
          )}
        </section>

        <CreateProjectModal
          open={createModalOpen}
          onClose={() => setCreateModalOpen(false)}
          onCreated={(root) => {
            setCreateModalOpen(false);
            openProject(root);
          }}
        />
      </div>
    </section>
  );
}
