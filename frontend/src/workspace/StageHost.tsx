// v1.9.0 — the stage in the Analysis view: open items as tabs across the top
// (pin, open in a new window and close come with each tab), the active one
// below. Nothing open yet says what to do next instead of showing a blank.

import type { ReactNode } from "react";
import { FoldRightIcon } from "./icons";

export function StageHost({ tabs, panel, onFold }: { tabs: ReactNode; panel: ReactNode | null; onFold?: () => void }) {
  return (
    <div className="ws-stage-host" data-testid="workspace-stage">
      <div className="ws-stage-host__bar">
        <div className="ws-stage-host__tabs">{tabs}</div>
        {onFold && (
          <button type="button" className="ws-icon-button" aria-label="Fold the details" title="Fold the details and show the whole map" onClick={onFold}>
            <FoldRightIcon />
          </button>
        )}
      </div>
      <div className="ws-stage-host__body">
        {panel ?? (
          <div className="ws-stage-host__empty">
            <p className="ws-stage-host__empty-title">Nothing open yet</p>
            <p>Choose a step on the map to see its result, checks and options here.</p>
          </div>
        )}
      </div>
    </div>
  );
}
