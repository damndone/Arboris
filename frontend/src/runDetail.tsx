import type { ReactNode } from "react";
import {
  useOutletContext,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { RunResultView } from "./runResult";
import { WorkbenchRouteContainer } from "./workbench/WorkbenchRouteContainer";

type AppContextValue = {
  projectRoot: string;
  setError: (msg: string | null) => void;
};

function TabLink({
  target,
  current,
  children,
}: {
  target: string;
  current: string;
  children: ReactNode;
}) {
  const [params, setParams] = useSearchParams();
  const isActive = current === target;
  return (
    <button
      role="tab"
      aria-selected={isActive}
      onClick={() => {
        const next = new URLSearchParams(params);
        next.set("tab", target);
        setParams(next);
      }}
      style={{
        padding: "12px 0",
        border: 0,
        background: "transparent",
        color: isActive ? "var(--tint, #0a84ff)" : "inherit",
        borderBottom: isActive
          ? "2px solid var(--tint, #0a84ff)"
          : "2px solid transparent",
        cursor: "pointer",
        fontSize: 14,
        fontWeight: isActive ? 600 : 400,
      }}
    >
      {children}
    </button>
  );
}

export function RunDetailRoute() {
  const { runId } = useParams();
  const { projectRoot, setError } = useOutletContext<AppContextValue>();
  const [params] = useSearchParams();
  const tab = params.get("tab") ?? "overview";

  if (!projectRoot) {
    return (
      <section className="panel">
        <p className="muted">Missing project_root.</p>
      </section>
    );
  }

  if (!runId) {
    return (
      <section className="panel">
        <p className="muted">Missing run ID.</p>
      </section>
    );
  }

  return (
    <div>
      <div
        role="tablist"
        style={{
          display: "flex",
          gap: 16,
          borderBottom: "1px solid var(--separator, #2e2e30)",
          padding: "0 16px",
        }}
      >
        <TabLink target="overview" current={tab}>
          Overview
        </TabLink>
        <TabLink target="lineage" current={tab}>
          Lineage
        </TabLink>
      </div>
      {tab === "lineage" ? (
        <WorkbenchRouteContainer projectRoot={projectRoot} runId={runId} />
      ) : (
        <RunResultView
          projectRoot={projectRoot}
          runId={runId}
          onError={(message) => setError(message)}
        />
      )}
    </div>
  );
}
