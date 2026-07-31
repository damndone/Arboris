/* frontend/src/theme/ThemeToggle.tsx
 * V1.5.1 T6 — 3-state segmented control: Light / Auto / Dark.
 *
 * "Auto" maps to `theme="system"` — the effective rendering tracks the OS.
 * Active state derives from `useTheme().theme` (the user's choice), NOT
 * `effective`, so the user can see they picked Auto even when the OS
 * happens to resolve to dark.
 *
 * Glyphs use unicode (no icon font). Tests assert by aria-label, not glyph.
 */

import { useTheme, type ThemeChoice } from "./ThemeProvider";

interface Option {
  value: ThemeChoice;
  label: string;
  glyph: string;
}

const OPTIONS: ReadonlyArray<Option> = [
  { value: "light", label: "Light theme", glyph: "☀" },
  { value: "system", label: "Use system theme", glyph: "◐" },
  { value: "dark", label: "Dark theme", glyph: "☾" },
];

export interface ThemeToggleProps {
  className?: string;
}

export function ThemeToggle({ className }: ThemeToggleProps): JSX.Element {
  const { theme, effective, setTheme } = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className={["theme-toggle", className].filter(Boolean).join(" ")}
    >
      {OPTIONS.map((opt) => {
        const active = theme === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={opt.label}
            title={
              opt.value === "system"
                ? `${opt.label} · currently ${effective}`
                : opt.label
            }
            data-active={active ? "true" : undefined}
            data-resolved={opt.value === "system" ? effective : undefined}
            onClick={() => setTheme(opt.value)}
            className="theme-toggle__btn"
          >
            <span
              className={opt.value === "system" ? "theme-toggle__auto" : undefined}
              aria-hidden="true"
            >
              {opt.value === "system" ? "Auto" : opt.glyph}
            </span>
          </button>
        );
      })}
    </div>
  );
}
