// v1.9.0 — the top bar on the project list: the same chrome as a project,
// with nothing project-specific in it yet. The theme switch stays here
// because Settings open inside a project.

import { ThemeToggle } from "../theme";
import { BrandIcon } from "./icons";
import "./workspace.css";
import "./workspaceTopbar.css";

export function WorkspaceLauncherBar() {
  return (
    <div className="ws-topbar__row" data-testid="workspace-launcher-bar">
      <div className="ws-topbar__start">
        <span className="ws-topbar__brand ws-topbar__brand--static">
          <BrandIcon />
          <span>Arboris</span>
        </span>
      </div>
      <span />
      <div className="ws-topbar__end">
        <ThemeToggle />
      </div>
    </div>
  );
}
