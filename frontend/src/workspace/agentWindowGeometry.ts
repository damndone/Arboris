// v1.9.0 — where the floating Agent may sit. Pure geometry, shared by the
// pointer and keyboard paths: the bubble rests against the nearer side edge
// (thrown, it lands where the throw was heading), the window stays wherever it
// is dropped inside the workspace, and a window opened from the bubble grows
// out of the bubble's corner.

export type Point = { x: number; y: number };
export type Size = { width: number; height: number };
/** The shell's size and the height of the top bar the Agent must stay below. */
export type Bounds = Size & { top: number };

export const MARGIN = 12;
export const BUBBLE = 48;

export const clamp = (n: number, low: number, high: number) => Math.max(low, Math.min(n, Math.max(low, high)));

export function keepInside(point: Point, size: Size, bounds: Bounds): Point {
  return {
    x: clamp(point.x, MARGIN, bounds.width - size.width - MARGIN),
    y: clamp(point.y, bounds.top + MARGIN, bounds.height - size.height - MARGIN),
  };
}

/** A thrown object slows like a picture-in-picture window (UIKit's fast
 *  deceleration, 0.99 per ms): it carries about 100 ms of its release speed. */
const DECELERATION = 0.99;

/** Where a released drag is heading, given its velocity in px/ms. */
export function projectRelease(point: Point, velocity: Point): Point {
  const carry = DECELERATION / (1 - DECELERATION);
  return { x: point.x + velocity.x * carry, y: point.y + velocity.y * carry };
}

/** The bubble's resting place: the side edge nearer to where it is heading. */
export function restBubble(point: Point, bounds: Bounds): Point {
  const size = { width: BUBBLE, height: BUBBLE };
  const inside = keepInside(point, size, bounds);
  const toLeft = inside.x + BUBBLE / 2 < bounds.width / 2;
  return { x: toLeft ? MARGIN : bounds.width - BUBBLE - MARGIN, y: inside.y };
}

export function defaultBubble(bounds: Bounds): Point {
  return { x: bounds.width - BUBBLE - MARGIN, y: bounds.height - BUBBLE - 56 };
}

/** A window opened from the bubble shares the bubble's outer corner. */
export function windowFromBubble(bubble: Point, size: Size, bounds: Bounds): Point {
  const onRight = bubble.x + BUBBLE / 2 >= bounds.width / 2;
  const below = bubble.y + BUBBLE / 2 >= (bounds.top + bounds.height) / 2;
  return keepInside(
    {
      x: onRight ? bubble.x + BUBBLE - size.width : bubble.x,
      y: below ? bubble.y + BUBBLE - size.height : bubble.y,
    },
    size,
    bounds,
  );
}
