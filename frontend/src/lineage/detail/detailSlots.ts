// v1.9.0 — what a host may add to or take out of node details. The workspace
// puts the result view under the header and leaves out sections whose job
// moved elsewhere (Ask AI is the Agent column now). The classic shell
// provides nothing, so its details are unchanged.

import { createContext, type ReactNode } from "react";
import type { GraphViewNode } from "../api/graphViewTypes";

export interface DetailSlots {
  hiddenSections?: ReadonlySet<string>;
  lead?: (node: GraphViewNode) => ReactNode;
}

export const DetailSlotsContext = createContext<DetailSlots>({});
