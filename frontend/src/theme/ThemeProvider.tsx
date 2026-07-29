/* frontend/src/theme/ThemeProvider.tsx
 * V1.5.1 T6 — Global theme controller.
 *
 * Owns:
 *   - the user's chosen mode: "dark" | "light" | "system"
 *   - the effective mode after resolving "system" against matchMedia
 *   - the <html data-theme="..."> attribute that drives all CSS tokens
 *   - localStorage persistence (key: STORAGE_KEY)
 *
 * Why a Context + a sync writer instead of just CSS @media (prefers-color-scheme):
 *   Users want to lock to a non-system choice; @media alone can't express that.
 *   We compute `effective` here and stamp it on <html> so CSS only sees a
 *   single source of truth: the data-theme attribute.
 *
 * Flash-of-wrong-theme: index.html runs an inline script before stylesheet
 * load that sets data-theme from localStorage (same key) so the very first
 * paint matches the user's choice. This Provider then re-evaluates on mount
 * and keeps the attr in sync as state changes — the inline script is a
 * pre-paint hint, not the authority.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemeChoice = "dark" | "light" | "system";
export type ThemeEffective = "dark" | "light";

export const STORAGE_KEY = "workbench:theme";
const ATTR = "data-theme";
const VALID: ReadonlyArray<ThemeChoice> = ["dark", "light", "system"];

export interface ThemeContextValue {
  /** What the user picked (or "system" if they haven't picked) */
  theme: ThemeChoice;
  /** What CSS is actually rendering ("dark" or "light"). */
  effective: ThemeEffective;
  /** Persist a new choice; re-evaluates `effective`. */
  setTheme: (next: ThemeChoice) => void;
}

const Ctx = createContext<ThemeContextValue | null>(null);
const NATIVE_REFRESH_MS = 30_000;

function readStored(): ThemeChoice {
  if (typeof window === "undefined") return "system";
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return VALID.includes(v as ThemeChoice) ? (v as ThemeChoice) : "system";
  } catch {
    return "system";
  }
}

function prefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    // jsdom + ancient browsers — default to dark (matches V1.5.0 lineage default).
    return true;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolve(choice: ThemeChoice): ThemeEffective {
  if (choice === "dark" || choice === "light") return choice;
  return prefersDark() ? "dark" : "light";
}

function isLoopbackHost(): boolean {
  if (typeof window === "undefined") return false;
  return ["127.0.0.1", "localhost", "::1"].includes(window.location.hostname);
}

async function readLocalSystemTheme(): Promise<ThemeEffective | null> {
  if (!isLoopbackHost() || typeof fetch !== "function") return null;
  try {
    const response = await fetch("/api/system/appearance", {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    const payload = (await response.json()) as { theme?: unknown };
    return payload.theme === "dark" || payload.theme === "light"
      ? payload.theme
      : null;
  } catch {
    return null;
  }
}

function stamp(eff: ThemeEffective): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute(ATTR, eff);
}

export interface ThemeProviderProps {
  children: ReactNode;
  /** Override initial choice (test/storybook hook). Defaults to stored value. */
  initial?: ThemeChoice;
}

export function ThemeProvider({ children, initial }: ThemeProviderProps): JSX.Element {
  const [theme, setThemeState] = useState<ThemeChoice>(() => initial ?? readStored());
  const [effective, setEffective] = useState<ThemeEffective>(() => resolve(initial ?? readStored()));

  // Sync the <html data-theme> attribute whenever `effective` changes.
  // This runs on first mount too — overriding whatever the inline script set —
  // so test environments without an inline script still get the attr.
  useEffect(() => {
    stamp(effective);
  }, [effective]);

  // System mode normally follows matchMedia. On a loopback Workbench, a
  // bounded native projection corrects embedded browsers that report the
  // host application's theme instead of the actual operating-system theme.
  useEffect(() => {
    if (theme !== "system") return;
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    let active = true;

    const refresh = async (): Promise<void> => {
      const native = await readLocalSystemTheme();
      if (active) setEffective(native ?? (mql.matches ? "dark" : "light"));
    };
    const onChange = (): void => {
      setEffective(mql.matches ? "dark" : "light");
      void refresh();
    };
    const onVisibility = (): void => {
      if (document.visibilityState === "visible") void refresh();
    };

    onChange();
    if (mql.addEventListener) mql.addEventListener("change", onChange);
    else mql.addListener?.(onChange);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", onVisibility);
    const interval = isLoopbackHost()
      ? window.setInterval(() => void refresh(), NATIVE_REFRESH_MS)
      : null;

    return () => {
      active = false;
      if (mql.removeEventListener) mql.removeEventListener("change", onChange);
      else mql.removeListener?.(onChange);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", onVisibility);
      if (interval !== null) window.clearInterval(interval);
    };
  }, [theme]);

  const setTheme = useCallback((next: ThemeChoice) => {
    if (!VALID.includes(next)) return;
    setThemeState(next);
    setEffective(resolve(next));
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Ignore quota / disabled storage.
    }
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, effective, setTheme }),
    [theme, effective, setTheme],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeContextValue {
  const v = useContext(Ctx);
  if (!v) {
    throw new Error("useTheme must be called inside <ThemeProvider>");
  }
  return v;
}
