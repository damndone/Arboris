/* ThemeToggle.test.tsx — T6.3
 *
 * Asserts the 3-state segmented control wiring without touching the
 * Provider's internals. Each test mounts <ThemeProvider><ThemeToggle/></ThemeProvider>.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ThemeProvider, STORAGE_KEY } from "./ThemeProvider";
import { ThemeToggle } from "./ThemeToggle";

function installMatchMedia(initialDark: boolean) {
  const listeners: Array<(e: MediaQueryListEvent) => void> = [];
  const mql = {
    matches: initialDark,
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: (_t: string, l: (e: MediaQueryListEvent) => void) =>
      listeners.push(l),
    removeEventListener: (_t: string, l: (e: MediaQueryListEvent) => void) => {
      const i = listeners.indexOf(l);
      if (i >= 0) listeners.splice(i, 1);
    },
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn(() => mql),
  });
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  installMatchMedia(true);
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>(() => undefined)),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ThemeToggle", () => {
  it("renders 3 radio buttons inside a radiogroup", () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    const group = screen.getByRole("radiogroup", { name: "Theme" });
    const buttons = screen.getAllByRole("radio");
    expect(group).toBeInTheDocument();
    expect(buttons).toHaveLength(3);
    expect(screen.getByLabelText("Light theme")).toBeInTheDocument();
    expect(screen.getByLabelText("Use system theme")).toBeInTheDocument();
    expect(screen.getByLabelText("Dark theme")).toBeInTheDocument();
  });

  it("marks current choice as aria-checked and data-active", () => {
    render(
      <ThemeProvider initial="dark">
        <ThemeToggle />
      </ThemeProvider>,
    );
    const dark = screen.getByLabelText("Dark theme");
    expect(dark).toHaveAttribute("aria-checked", "true");
    expect(dark).toHaveAttribute("data-active", "true");
    expect(screen.getByLabelText("Light theme")).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("click updates theme, localStorage, and data-theme on <html>", () => {
    render(
      <ThemeProvider initial="dark">
        <ThemeToggle />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByLabelText("Light theme"));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(screen.getByLabelText("Light theme")).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("clicking the system option resolves effective via matchMedia", () => {
    // OS prefers dark; user picks system → effective should be dark
    render(
      <ThemeProvider initial="light">
        <ThemeToggle />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByLabelText("Use system theme"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("system");
  });

  it("labels the system choice as Auto and exposes its current effective theme", () => {
    render(
      <ThemeProvider initial="system">
        <ThemeToggle />
      </ThemeProvider>,
    );

    const system = screen.getByLabelText("Use system theme");
    expect(system).toHaveTextContent("Auto");
    expect(system).toHaveAttribute("title", "Use system theme · currently dark");
    expect(system).toHaveAttribute("data-resolved", "dark");
  });
});
