import { describe, expect, test } from "vitest";
import { keepInside, projectRelease, restBubble, windowFromBubble } from "./agentWindowGeometry";

const bounds = { width: 1512, height: 982, top: 48 };

describe("floating Agent geometry", () => {
  test("stays inside the workspace and below the top bar", () => {
    expect(keepInside({ x: -40, y: 0 }, { width: 380, height: 540 }, bounds)).toEqual({ x: 12, y: 60 });
    expect(keepInside({ x: 2000, y: 2000 }, { width: 380, height: 540 }, bounds)).toEqual({ x: 1120, y: 430 });
  });

  test("the bubble rests on the nearer side edge, and a throw carries it across", () => {
    expect(restBubble({ x: 500, y: 400 }, bounds)).toEqual({ x: 12, y: 400 });
    expect(restBubble({ x: 900, y: 400 }, bounds)).toEqual({ x: 1452, y: 400 });
    const thrown = projectRelease({ x: 500, y: 400 }, { x: 4, y: 0 });
    expect(restBubble(thrown, bounds).x).toBe(1452);
  });

  test("a window opened from the bubble grows out of its outer corner", () => {
    const size = { width: 380, height: 540 };
    expect(windowFromBubble({ x: 1452, y: 878 }, size, bounds)).toEqual({ x: 1120, y: 386 });
    expect(windowFromBubble({ x: 12, y: 80 }, size, bounds)).toEqual({ x: 12, y: 80 });
  });
});
