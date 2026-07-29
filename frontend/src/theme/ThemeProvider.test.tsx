/* ThemeProvider.test.tsx — T6.2
 *
 * Covers the contract that downstream tracks rely on:
 *   - default choice is "system" (no stored value)
 *   - setTheme writes localStorage and stamps <html data-theme>
 *   - "system" mode follows matchMedia change events
 *   - listener cleanup on unmount
 *
 * matchMedia is stubbed per-test (jsdom omits it). We use a minimal
 * MediaQueryList stub that records change-listener attach/detach so
 * the cleanup test can assert correctness.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, renderHook, waitFor } from "@testing-library/react";
import {
  STORAGE_KEY,
  ThemeProvider,
  useTheme,
  type ThemeChoice,
} from "./ThemeProvider";

type Listener = (e: MediaQueryListEvent) => void;

interface MqlStub extends MediaQueryList {
  __setMatches: (v: boolean) => void;
  __listeners: Listener[];
}

function makeMql(initial: boolean): MqlStub {
  const listeners: Listener[] = [];
  const obj = {
    matches: initial,
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: vi.fn((_type: string, l: Listener) => listeners.push(l)),
    removeEventListener: vi.fn((_type: string, l: Listener) => {
      const i = listeners.indexOf(l);
      if (i >= 0) listeners.splice(i, 1);
    }),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MqlStub;
  obj.__listeners = listeners;
  obj.__setMatches = (v: boolean) => {
    (obj as { matches: boolean }).matches = v;
    listeners.forEach((fn) => fn({ matches: v } as MediaQueryListEvent));
  };
  return obj;
}

function installMatchMedia(initialDark: boolean): MqlStub {
  const mql = makeMql(initialDark);
  vi.stubGlobal("matchMedia", vi.fn(() => mql));
  // jsdom doesn't put matchMedia on window by default — also stub via window.
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn(() => mql),
  });
  return mql;
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>(() => undefined)),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ThemeProvider", () => {
  it("defaults choice to 'system' and stamps data-theme from matchMedia", () => {
    installMatchMedia(true); // OS prefers dark
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.theme).toBe("system");
    expect(result.current.effective).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("setTheme persists to localStorage and updates data-theme synchronously", () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useTheme(), { wrapper });
    act(() => result.current.setTheme("light"));
    expect(result.current.theme).toBe("light");
    expect(result.current.effective).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
  });

  it("system mode follows matchMedia change events", () => {
    const mql = installMatchMedia(false); // OS light
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.effective).toBe("light");
    act(() => mql.__setMatches(true));
    expect(result.current.effective).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("uses the local Workbench native appearance when the embedded browser signal differs", async () => {
    installMatchMedia(true); // Embedded browser reports dark.
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ theme: "light", source: "darwin-native" }),
    } as Response);

    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.effective).toBe("dark");
    await waitFor(() => expect(result.current.effective).toBe("light"));
    expect(fetch).toHaveBeenCalledWith(
      "/api/system/appearance",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("locked mode (dark/light) ignores matchMedia changes", () => {
    const mql = installMatchMedia(false);
    const { result } = renderHook(() => useTheme(), { wrapper });
    act(() => result.current.setTheme("dark"));
    expect(result.current.effective).toBe("dark");
    act(() => mql.__setMatches(true)); // OS would flip, but we're locked
    expect(result.current.effective).toBe("dark");
  });

  it("removes the matchMedia listener on unmount", () => {
    const mql = installMatchMedia(true);
    const { unmount } = render(
      <ThemeProvider>
        <div>child</div>
      </ThemeProvider>,
    );
    expect(mql.__listeners.length).toBeGreaterThan(0);
    unmount();
    expect(mql.__listeners.length).toBe(0);
  });

  it("seeds from localStorage on first render", () => {
    window.localStorage.setItem(STORAGE_KEY, "light");
    installMatchMedia(true); // OS dark but stored = light → light wins
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.theme).toBe("light");
    expect(result.current.effective).toBe("light");
  });

  it("rejects invalid setTheme values without changing state", () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useTheme(), { wrapper });
    const before = result.current.theme;
    act(() => result.current.setTheme("neon" as ThemeChoice));
    expect(result.current.theme).toBe(before);
  });
});
