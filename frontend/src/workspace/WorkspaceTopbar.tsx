// v1.9.0 — the workspace top bar (design spec §8.3.1).
// Left: map toggle, home, project. Middle: views in working order.
// Right: layout switch, search, new analysis, analysis actions, settings.

import type { ReactNode } from "react";
import type { ViewMode } from "../workbench/state/urlSchema";
import { ProjectSwitcher } from "../workbench/WorkbenchTopbar";
import type { LayoutControls } from "./WorkspaceShell";
import { BrandIcon, LineageIcon, PlusIcon, ResultsIcon, SearchIcon, SettingsIcon, SidebarIcon } from "./icons";
import "./workspaceTopbar.css";

export const WORKSPACE_VIEWS: ReadonlyArray<{ id: ViewMode; label: string }> = [
  { id: "data", label: "Data" },
  { id: "graph", label: "Analysis" },
  { id: "table", label: "Tables" },
  { id: "report", label: "Report" },
  { id: "notebook", label: "Plans" },
];

export interface WorkspaceTopbarProps {
  projectRoot: string;
  view: ViewMode;
  /** Absent on project home, which has no map, stage or layout. */
  controls?: LayoutControls;
  /** Analysis-level actions (Rerun) from the shared action registry. */
  actions: ReactNode;
  newAnalysisLabel?: string;
  /** Views that cannot open yet, with the reason shown as their tooltip. */
  disabledViews?: Partial<Record<ViewMode, string>>;
  onView: (view: ViewMode) => void;
  onHome: () => void;
  onOpenSettings: () => void;
  onNewAnalysis?: () => void;
}

function openSearch() {
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }));
}

export function WorkspaceTopbar({
  projectRoot,
  view,
  controls,
  actions,
  newAnalysisLabel = "New analysis",
  disabledViews = {},
  onView,
  onHome,
  onOpenSettings,
  onNewAnalysis,
}: WorkspaceTopbarProps) {
  return (
    <div className="ws-topbar__row" data-testid="workspace-topbar">
      <div className="ws-topbar__start">
        {controls?.mapFoldable && (
          <button
            type="button"
            className="ws-icon-button"
            aria-label={controls.mapHidden ? "Show the map" : "Hide the map"}
            aria-pressed={!controls.mapHidden}
            onClick={controls.toggleMap}
          >
            <SidebarIcon />
          </button>
        )}
        <button type="button" className="ws-topbar__brand" aria-label="Arboris home" onClick={onHome}>
          <BrandIcon />
          <span aria-hidden="true">Arboris</span>
        </button>
        <span className="ws-topbar__rule" aria-hidden="true" />
        <ProjectSwitcher projectRoot={projectRoot} />
      </div>

      <div className="ws-segmented ws-topbar__views" role="tablist" aria-label="View">
        {WORKSPACE_VIEWS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            className="ws-segmented__item"
            aria-selected={view === item.id}
            aria-disabled={disabledViews[item.id] ? true : undefined}
            title={disabledViews[item.id]}
            data-testid={`workspace-view-${item.id}`}
            onClick={() => {
              if (!disabledViews[item.id]) onView(item.id);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="ws-topbar__end">
        {controls && (
        <div className="ws-segmented ws-segmented--small" role="group" aria-label="Layout">
          <button
            type="button"
            className="ws-segmented__item"
            aria-pressed={controls.layout === "results"}
            title="Results first (⌘\)"
            onClick={() => controls.setLayout("results")}
          >
            <ResultsIcon />
            Results first
          </button>
          <button
            type="button"
            className="ws-segmented__item"
            aria-pressed={controls.layout === "lineage"}
            title="Lineage first (⌘\)"
            onClick={() => controls.setLayout("lineage")}
          >
            <LineageIcon />
            Lineage first
          </button>
        </div>
        )}
        <button type="button" className="ws-icon-button" aria-label="Search (⌘K)" title="Search (⌘K)" onClick={openSearch}>
          <SearchIcon />
        </button>
        {onNewAnalysis && (
          <button type="button" className="ws-button ws-button--primary" onClick={onNewAnalysis}>
            <PlusIcon />
            {newAnalysisLabel}
          </button>
        )}
        {actions}
        <button type="button" className="ws-icon-button" aria-label="Settings" title="Settings" onClick={onOpenSettings}>
          <SettingsIcon />
        </button>
      </div>
    </div>
  );
}
