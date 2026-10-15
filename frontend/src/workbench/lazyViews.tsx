// v1.9.0 — views that are not on screen when a project opens load on first
// use, so opening a project parses the graph and home only. Each lazy view
// keeps its own export name; the fallback is announced and holds the space.

import { lazy, Suspense, type ReactNode } from "react";

export const DataView = lazy(() => import("../dataView/DataView").then((m) => ({ default: m.DataView })));
export const TableView = lazy(() => import("./views/TableView").then((m) => ({ default: m.TableView })));
export const PipelineView = lazy(() => import("./views/PipelineView").then((m) => ({ default: m.PipelineView })));
export const ReportView = lazy(() => import("../report/ReportView").then((m) => ({ default: m.ReportView })));
export const NotebookRouteView = lazy(() =>
  import("../notebook/NotebookRouteView").then((m) => ({ default: m.NotebookRouteView })),
);

export function ViewLoading() {
  return (
    <div className="wb-view-loading" role="status" aria-live="polite">
      Loading…
    </div>
  );
}

export function LazyView({ children }: { children: ReactNode }) {
  return <Suspense fallback={<ViewLoading />}>{children}</Suspense>;
}
