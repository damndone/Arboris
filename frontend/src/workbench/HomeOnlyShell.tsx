// Classic shell: project home before any run exists (moved out of
// WorkbenchRouteContainer in v1.9.0).

import { useNavigate } from "react-router-dom";
import { ProjectSwitcher } from "./WorkbenchTopbar";
import { WorkbenchHomeView } from "./views/WorkbenchHomeView";
import { rootToSlug } from "./projectSlug";

export function HomeOnlyShell({
  projectRoot,
  onOpenSettings,
}: {
  projectRoot: string;
  onOpenSettings: () => void;
}) {
  const navigate = useNavigate();

  return (
    <div
      data-testid="workbench-home-shell"
      style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}
    >
      <div
        role="toolbar"
        aria-label="Project toolbar"
        style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 16px", height: 40, borderBottom: "1px solid var(--separator)" }}
      >
        <ProjectSwitcher projectRoot={projectRoot} />
        <span style={{ color: "var(--label-secondary)", fontSize: 12 }}>Home</span>
        <button
          type="button"
          data-testid="workbench-home-graph"
          onClick={() => navigate(window.location.pathname)}
          style={{ marginLeft: "auto", padding: "4px 10px", borderRadius: 6, border: "1px solid var(--separator)", background: "transparent", color: "var(--label)", cursor: "pointer", fontSize: 12 }}
        >
          Graph
        </button>
        <button
          type="button"
          data-testid="workbench-home-shell-settings"
          onClick={onOpenSettings}
          style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid var(--separator)", background: "transparent", color: "var(--label)", cursor: "pointer", fontSize: 12 }}
        >
          Settings
        </button>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        <WorkbenchHomeView
          projectRoot={projectRoot}
          onOpenSettings={onOpenSettings}
          onOpenProject={(root) => navigate(`/p/${rootToSlug(root)}/graph`)}
        />
      </div>
    </div>
  );
}
