// Renders the ARMA-GARCH result as a one-view dashboard inside the graph node
// drawer, so the time-series result lives in the graph rather than on the
// deprecated standalone Overview page.

import type { GraphViewNode } from "../../api/graphViewTypes";
import { useProjectRootOptional } from "../../../workbench/ProjectRootContext";
import { useArmaGarchArtifacts } from "../../../runResult/useArmaGarchArtifacts";
import { ArmaGarchDashboard } from "../../../runResult/ArmaGarchDashboard";

/** The run whose result this node shows: its owning run. */
function ownerRunId(node: GraphViewNode): string | null {
  const runs = "runs" in node && Array.isArray(node.runs) ? node.runs : [];
  return typeof runs[0] === "string" ? runs[0] : null;
}

export function ArmaGarchResultSection({ node }: { node: GraphViewNode }) {
  const projectRoot = useProjectRootOptional();
  const runId = ownerRunId(node);
  const artifacts = useArmaGarchArtifacts(projectRoot, runId);

  if (!projectRoot || !runId || !artifacts?.report) return null;

  return (
    <div data-testid="arma-garch-result-section" style={{ marginTop: 18 }}>
      <ArmaGarchDashboard artifacts={artifacts} />
    </div>
  );
}
