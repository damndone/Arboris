// v1.9.0 — the page index under the stage tabs (design spec §8.3.1): one row
// that names every section of the open step and jumps to it. It reads the
// sections the details actually rendered, so it never lists one that is not
// there and picks up new ones without a list to maintain.

import { useEffect, useRef, useState } from "react";

const SHORT_NAMES: Record<string, string> = {
  "Compare with source": "Compare",
  "Compare nodes": "Compare",
  Operation: "Rerun with changes",
  "Estimated equation": "Equation",
  "Variables by role": "Roles",
  "Script export": "Reproduce",
  "Lineage path": "Lineage",
  "Basic info": "Info",
};

interface Entry {
  label: string;
  target: Element;
}

const SECTIONS = [
  ":scope > .ws-result-selection > article[aria-label]",
  ":scope > .ws-result-selection > article > section[aria-labelledby]",
  ":scope > article[aria-label]",
  ":scope > section[aria-label]",
  ":scope > article > section[aria-labelledby]",
].join(", ");

function collect(drawer: Element): Entry[] {
  const entries: Entry[] = [];
  const seen = new Set<string>();
  for (const element of Array.from(drawer.querySelectorAll(SECTIONS))) {
    const labelledBy = element.getAttribute("aria-labelledby");
    const raw = (labelledBy ? drawer.querySelector(`#${CSS.escape(labelledBy)}`)?.textContent : element.getAttribute("aria-label")) ?? "";
    const label = SHORT_NAMES[raw.trim()] ?? raw.trim();
    if (!label || seen.has(label)) continue;
    seen.add(label);
    entries.push({ label, target: element });
  }
  return entries;
}

const sameSections = (a: Entry[], b: Entry[]) => a.length === b.length && a.every((entry, i) => entry.label === b[i].label && entry.target === b[i].target);

export function StageIndex() {
  const ref = useRef<HTMLElement>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [current, setCurrent] = useState<string | null>(null);

  // The details re-render often (results arrive, forms are typed in); read the
  // sections at most once a frame and re-render only when they change.
  useEffect(() => {
    const drawer = ref.current?.closest(".detail-drawer");
    if (!drawer) return undefined;
    let frame = 0;
    const update = () => {
      frame = 0;
      const next = collect(drawer);
      setEntries((previous) => (sameSections(previous, next) ? previous : next));
    };
    update();
    if (typeof MutationObserver === "undefined") return undefined;
    const observer = new MutationObserver(() => {
      if (!frame) frame = requestAnimationFrame(update);
    });
    observer.observe(drawer, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);

  // The section under the index's band is the current one.
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined" || entries.length === 0) return undefined;
    const labels = new Map(entries.map((entry) => [entry.target, entry.label]));
    const observer = new IntersectionObserver(
      (changes) => {
        const visible = changes.filter((change) => change.isIntersecting);
        if (visible.length) setCurrent(labels.get(visible[0].target) ?? null);
      },
      { rootMargin: "-15% 0px -70% 0px" },
    );
    entries.forEach((entry) => observer.observe(entry.target));
    return () => observer.disconnect();
  }, [entries]);

  return (
    <nav ref={ref} className="ws-stage-index" aria-label="Sections">
      {entries.map((entry) => (
        <button
          key={entry.label}
          type="button"
          className="ws-stage-index__item"
          aria-current={current === entry.label ? "location" : undefined}
          onClick={() => {
            setCurrent(entry.label);
            entry.target.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
        >
          {entry.label}
        </button>
      ))}
    </nav>
  );
}
