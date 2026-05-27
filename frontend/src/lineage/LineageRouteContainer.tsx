// frontend/src/lineage/LineageRouteContainer.tsx
//
// V1.5.2 — replaced by `workbench/WorkbenchRouteContainer.tsx` per
// plan §2. Kept as a thin delegating shim for one version so any
// direct importer (tests, plugin code) keeps working without churn.
// Remove once nothing imports `LineageRouteContainer`.

import { WorkbenchRouteContainer } from "../workbench/WorkbenchRouteContainer";

interface LineageRouteContainerProps {
  projectRoot: string;
  runId: string;
}

export function LineageRouteContainer(props: LineageRouteContainerProps) {
  return <WorkbenchRouteContainer {...props} />;
}
