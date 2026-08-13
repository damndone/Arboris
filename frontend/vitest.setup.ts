import { vi } from "vitest";
import "@testing-library/jest-dom";
import * as React from "react";

// Keep every test router on the same explicit React Router v7 transition
// semantics. This is a test-harness default, not a warning suppression: an
// individual test may still override either flag when it is testing a
// deliberate compatibility mode.
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  const future = { v7_startTransition: true, v7_relativeSplatPath: true };
  return {
    ...actual,
    MemoryRouter: (props: React.ComponentProps<typeof actual.MemoryRouter>) => {
      const mergedFuture = { ...future, ...props.future };
      return React.createElement(actual.MemoryRouter, {
        ...props,
        future: mergedFuture,
      });
    },
    BrowserRouter: (props: React.ComponentProps<typeof actual.BrowserRouter>) =>
      React.createElement(actual.BrowserRouter, {
        ...props,
        future: { ...future, ...props.future },
      }),
  };
});

// React Flow uses ResizeObserver, which jsdom does not implement.
class ResizeObserverMock {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
vi.stubGlobal("ResizeObserver", ResizeObserverMock);

// React Flow also queries DOMRect.toJSON on layout — partial in jsdom.
if (!(globalThis as { DOMRect?: unknown }).DOMRect) {
  // @ts-expect-error stub
  globalThis.DOMRect = class {
    constructor(public x = 0, public y = 0, public width = 0, public height = 0) {}
  };
}
