// v1.9.0 — Settings › Appearance: the theme (moved here from the top bar in
// the new workspace) and the workspace switch that keeps the classic shell
// one click away until the new one is the default.

import { useTheme, type ThemeChoice } from "../theme";
import { setWorkspaceMode, useWorkspaceMode, type WorkspaceMode } from "./workspaceMode";
import "./appearanceSettings.css";

const THEMES: Array<{ value: ThemeChoice; label: string }> = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "Match the system" },
];

const WORKSPACES: Array<{ value: WorkspaceMode; label: string; hint: string }> = [
  { value: "new", label: "New workspace", hint: "Results first or lineage first, one Agent column, runs and logs below." },
  { value: "classic", label: "Classic", hint: "The layout before v1.9.0, kept while the new workspace is checked." },
];

export function AppearanceSettings() {
  const { theme, setTheme } = useTheme();
  const workspace = useWorkspaceMode();
  return (
    <div className="appearance-settings" data-testid="appearance-settings">
      <fieldset className="appearance-settings__group" role="radiogroup" aria-label="Theme">
        <legend>Theme</legend>
        {THEMES.map((option) => (
          <label key={option.value} className="appearance-settings__option">
            <input type="radio" name="appearance-theme" checked={theme === option.value} onChange={() => setTheme(option.value)} />
            <span>{option.label}</span>
          </label>
        ))}
      </fieldset>
      <fieldset className="appearance-settings__group" role="radiogroup" aria-label="Workspace">
        <legend>Workspace</legend>
        {WORKSPACES.map((option) => (
          <label key={option.value} className="appearance-settings__option">
            <input type="radio" name="appearance-workspace" checked={workspace === option.value} onChange={() => setWorkspaceMode(option.value)} />
            <span>
              {option.label}
              <span className="appearance-settings__hint">{option.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
    </div>
  );
}
