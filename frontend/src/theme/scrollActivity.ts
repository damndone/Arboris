// v1.9.0 — scrollbars appear while something scrolls and fade when it stops
// (user review 3: "静止自动隐藏"). One capture-phase listener marks the element
// being scrolled with data-scrolling; scrollbars.css shows the thumb only there.

const IDLE_MS = 900;

export function installScrollActivity(root: Document = document): () => void {
  const timers = new Map<Element, ReturnType<typeof setTimeout>>();
  const onScroll = (event: Event) => {
    const target = event.target instanceof Element ? event.target : root.documentElement;
    if (!target) return;
    target.setAttribute("data-scrolling", "");
    clearTimeout(timers.get(target));
    timers.set(
      target,
      setTimeout(() => {
        target.removeAttribute("data-scrolling");
        timers.delete(target);
      }, IDLE_MS),
    );
  };
  root.addEventListener("scroll", onScroll, { capture: true, passive: true });
  return () => {
    root.removeEventListener("scroll", onScroll, { capture: true });
    timers.forEach((timer) => clearTimeout(timer));
  };
}
