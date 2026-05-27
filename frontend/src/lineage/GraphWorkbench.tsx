// frontend/src/lineage/GraphWorkbench.tsx
//
// V1.5.2 — moved to `frontend/src/workbench/views/GraphView.tsx` per
// plan §2. This file is a back-compat re-export so existing tests
// (GraphWorkbench.test.tsx) and existing imports keep working without
// touching call sites. Remove this shim once all consumers import
// from `workbench/views/GraphView` directly.

import { GraphView } from "../workbench/views/GraphView";

export { GraphView as GraphWorkbench };
