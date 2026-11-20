import { useTheme, type ThemeChoice } from "../theme";
import "./appearanceSettings.css";

const THEMES: Array<{ value: ThemeChoice; label: string }> = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "Match the system" },
];

export function AppearanceSettings() {
  const { theme, setTheme } = useTheme();
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
    </div>
  );
}
