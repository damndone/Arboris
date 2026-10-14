import { afterEach, expect, test, vi } from "vitest";
import { installScrollActivity } from "./scrollActivity";

afterEach(() => vi.useRealTimers());

test("an element is marked while it scrolls and unmarked once it stops", () => {
  vi.useFakeTimers();
  const uninstall = installScrollActivity();
  const box = document.createElement("div");
  document.body.append(box);
  box.dispatchEvent(new Event("scroll"));
  expect(box.hasAttribute("data-scrolling")).toBe(true);
  vi.advanceTimersByTime(500);
  box.dispatchEvent(new Event("scroll"));
  vi.advanceTimersByTime(800);
  expect(box.hasAttribute("data-scrolling")).toBe(true);
  vi.advanceTimersByTime(200);
  expect(box.hasAttribute("data-scrolling")).toBe(false);
  uninstall();
  box.remove();
});
