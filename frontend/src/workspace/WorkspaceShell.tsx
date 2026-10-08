// v1.9.0 — the workspace shell (design spec §8.2, §8.3.1).
//
// One grid, five regions: top bar, map, stage, Agent, bottom panel. The two
// layouts differ only in the map column's width — a registered CSS custom
// property animated with the spring token — so no region ever remounts and a
// switch can be reversed mid-flight. The divider between map and stage is
// draggable: on release the momentum-projected landing picks the nearer layout.

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import type { ViewMode } from "../workbench/state/urlSchema";
import {
  WIDE_VIEWS,
  agentWidth,
  columnSpec,
  effectiveLayout,
  mapPresentation,
  mapWidthFor,
  readAgentOpen,
  readLayout,
  releaseLayout,
  writeAgentOpen,
  writeLayout,
  type Layout,
} from "./layoutModel";
import { AgentRailIcon, FoldRightIcon } from "./icons";
import "./workspace.css";
import "./agentColumn.css";

export interface LayoutControls {
  /** The layout the user chose for this project. */
  layout: Layout;
  /** The layout on screen (wide views borrow the wide stage). */
  effective: Layout;
  setLayout: (next: Layout) => void;
  toggleLayout: () => void;
  agentOpen: boolean;
  toggleAgent: () => void;
  /** Whether a map column can be folded right now (stage open, results first or a wide view). */
  mapFoldable: boolean;
  mapHidden: boolean;
  toggleMap: () => void;
}

export type MapPresentation = "graph" | "tree";

export interface WorkspaceShellProps {
  projectRoot: string;
  view: ViewMode;
  topbar: (controls: LayoutControls) => ReactNode;
  /** Whether the stage shows. Wide views always show it; Analysis shows it when something is open. */
  stageOpen: boolean;
  /** The map region; a narrow column gets the tree, a wide map the full graph. */
  map: (presentation: MapPresentation) => ReactNode;
  stage: ReactNode;
  agent: ReactNode;
  bottom: ReactNode;
}

const DEFAULT_WIDTH = 1512;

function windowWidth(): number {
  return typeof window === "undefined" ? DEFAULT_WIDTH : window.innerWidth || DEFAULT_WIDTH;
}

function useShellWidth(ref: React.RefObject<HTMLDivElement>): number {
  const [width, setWidth] = useState(windowWidth);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const measure = () => setWidth(element.getBoundingClientRect().width || windowWidth());
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

type DragState = { pointerId: number; startX: number; startWidth: number; samples: Array<{ x: number; t: number }> };

/** Release velocity from the last ~100 ms of pointer samples, in px/ms. */
function releaseVelocity(samples: DragState["samples"]): number {
  const last = samples[samples.length - 1];
  const first = samples.find((sample) => last.t - sample.t <= 100) ?? last;
  return last.t > first.t ? (last.x - first.x) / (last.t - first.t) : 0;
}

export function WorkspaceShell({ projectRoot, view, topbar, stageOpen, map, stage, agent, bottom }: WorkspaceShellProps) {
  const shellRef = useRef<HTMLDivElement>(null);
  const shellWidth = useShellWidth(shellRef);
  const [layout, setLayoutState] = useState<Layout>(() => readLayout(projectRoot));
  const [agentOpen, setAgentOpen] = useState(readAgentOpen);
  // The Analysis map column shows by default; Data, Tables, Report and Plans
  // are wide documents, so their map column starts folded.
  const [analysisMapHidden, setAnalysisMapHidden] = useState(false);
  const [wideMapHidden, setWideMapHidden] = useState(true);
  const [dragWidth, setDragWidth] = useState<number | null>(null);
  const drag = useRef<DragState | null>(null);

  useEffect(() => setLayoutState(readLayout(projectRoot)), [projectRoot]);

  const setLayout = useCallback((next: Layout) => {
    setLayoutState(next);
    setAnalysisMapHidden(false);
    writeLayout(projectRoot, next);
  }, [projectRoot]);
  const toggleLayout = useCallback(() => setLayout(layout === "results" ? "lineage" : "results"), [layout, setLayout]);
  const toggleAgent = useCallback(() => {
    setAgentOpen((open) => {
      writeAgentOpen(!open);
      return !open;
    });
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
      if (event.key === "\\") {
        event.preventDefault();
        toggleLayout();
      } else if (event.key === ".") {
        event.preventDefault();
        toggleAgent();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleAgent, toggleLayout]);

  const spec = columnSpec(windowWidth());
  const effective = effectiveLayout(layout, view);
  const wideView = WIDE_VIEWS.has(view);
  const mapHidden = wideView ? wideMapHidden : analysisMapHidden;
  const toggleMap = () => (wideView ? setWideMapHidden(!wideMapHidden) : setAnalysisMapHidden(!analysisMapHidden));
  const regions = { layout: effective, stageOpen, mapHidden, agentOpen };
  const lineageWidth = mapWidthFor({ ...regions, layout: "lineage", stageOpen: true }, shellWidth, spec);
  const targetMap = mapWidthFor(regions, shellWidth, spec);
  const presentation = mapPresentation(regions);
  const mapFoldable = wideView || (stageOpen && effective === "results");
  const controls: LayoutControls = { layout, effective, setLayout, toggleLayout, agentOpen, toggleAgent, mapFoldable, mapHidden, toggleMap };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drag.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: targetMap, samples: [{ x: event.clientX, t: event.timeStamp }] };
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state || state.pointerId !== event.pointerId) return;
    state.samples = [...state.samples.slice(-7), { x: event.clientX, t: event.timeStamp }];
    const width = Math.min(lineageWidth + 48, Math.max(spec.map * 0.75, state.startWidth + event.clientX - state.startX));
    setDragWidth(width);
  };
  const onPointerEnd = (event: PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state || state.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    drag.current = null;
    if (dragWidth !== null) setLayout(releaseLayout(dragWidth, releaseVelocity(state.samples), { results: spec.map, lineage: lineageWidth }));
    setDragWidth(null);
  };

  const style = {
    "--ws-map": `${dragWidth ?? targetMap}px`,
    "--ws-agent": `${agentWidth(spec, agentOpen)}px`,
  } as CSSProperties;

  return (
    <div
      ref={shellRef}
      data-testid="workspace-shell"
      data-layout={effective}
      data-agent={agentOpen ? "open" : "folded"}
      data-stage={stageOpen ? "open" : "closed"}
      data-map={presentation}
      className={`ws-shell${dragWidth !== null ? " ws-shell--dragging" : ""}`}
      style={style}
    >
      <header className="ws-topbar" role="banner">{topbar(controls)}</header>
      <nav className="ws-map" aria-label="Map" hidden={presentation === "none" && dragWidth === null}>
        {map(dragWidth !== null || presentation !== "tree" ? "graph" : "tree")}
      </nav>
      {stageOpen && !wideView && (
        <div
          className="ws-divider"
          role="separator"
          tabIndex={0}
          aria-orientation="vertical"
          aria-label="Map width: drag, or use the arrow keys, to switch between results first and lineage first"
          aria-valuemin={spec.map}
          aria-valuemax={lineageWidth}
          aria-valuenow={Math.round(dragWidth ?? targetMap)}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerEnd}
          onPointerCancel={onPointerEnd}
          onDoubleClick={toggleLayout}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") setLayout("results");
            else if (event.key === "ArrowRight") setLayout("lineage");
            else if (event.key === "Enter" || event.key === " ") toggleLayout();
            else return;
            event.preventDefault();
          }}
        />
      )}
      <main className="ws-stage" aria-label="Stage" hidden={!stageOpen}>
        <div className="ws-stage__surface">{stage}</div>
      </main>
      <aside className="ws-agent" aria-label="Agent">
        {!agentOpen && (
          <div className="ws-agent__rail">
            <button type="button" className="ws-icon-button" aria-label="Show the Agent" title="Show the Agent (⌘.)" onClick={toggleAgent}>
              <AgentRailIcon />
            </button>
          </div>
        )}
        <div className="ws-agent__body" hidden={!agentOpen}>
          <div className="ws-agent__header">
            <h2 className="ws-agent__title">Agent</h2>
            <button type="button" className="ws-icon-button" aria-label="Fold the Agent" title="Fold the Agent (⌘.)" onClick={toggleAgent}>
              <FoldRightIcon />
            </button>
          </div>
          <div className="ws-agent__content">{agent}</div>
        </div>
      </aside>
      <section className="ws-bottom" aria-label="Bottom panel">{bottom}</section>
    </div>
  );
}
