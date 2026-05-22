import { vi } from "vitest";
import "@testing-library/jest-dom";

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
