// v1.9.0 — refit the graph after its container settles at a new size.
// The workspace turns this on for the map: when a layout switch or the stage
// opening or closing changes the map's width, the graph re-centres once the
// spring has finished, instead of staying framed for the old size. The classic
// shell leaves it off, so a user's zoom survives resizing the side panel.

import { createContext, useContext, useEffect, type RefObject } from "react";
import { useReactFlow } from "reactflow";

export const GraphAutoFitContext = createContext(false);

const SETTLE_MS = 380;
const MIN_CHANGE_PX = 24;

export function AutoFitOnResize({ containerRef }: { containerRef: RefObject<HTMLDivElement> }) {
  const enabled = useContext(GraphAutoFitContext);
  const { fitView } = useReactFlow();
  useEffect(() => {
    const element = containerRef.current;
    if (!enabled || !element || typeof ResizeObserver === "undefined") return undefined;
    let last = element.getBoundingClientRect();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const observer = new ResizeObserver(() => {
      const next = element.getBoundingClientRect();
      if (Math.abs(next.width - last.width) < MIN_CHANGE_PX && Math.abs(next.height - last.height) < MIN_CHANGE_PX) return;
      last = next;
      clearTimeout(timer);
      timer = setTimeout(() => fitView({ padding: 0.2, duration: 200 }), SETTLE_MS);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      clearTimeout(timer);
    };
  }, [containerRef, enabled, fitView]);
  return null;
}
