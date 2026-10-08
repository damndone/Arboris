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

function collect(drawer: Element): Entry[] {
  const entries: Entry[] = [];
  const seen = new Set<string>();
  const add = (label: string, target: Element) => {
    if (seen.has(label)) return;
    seen.add(label);
    entries.push({ label, target });
  };
  for (const element of Array.from(drawer.querySelectorAll(":scope > article[aria-label], :scope > section[aria-label], :scope > article > section[aria-labelledby]"))) {
    const labelledBy = element.getAttribute("aria-labelledby");
    const raw = labelledBy ? drawer.querySelector(`#${CSS.escape(labelledBy)}`)?.textContent ?? "" : element.getAttribute("aria-label") ?? "";
    const label = SHORT_NAMES[raw.trim()] ?? raw.trim();
    if (label) add(label, element);
  }
  return entries;
}

export function StageIndex() {
  const ref = useRef<HTMLElement>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  useEffect(() => {
    const drawer = ref.current?.closest(".detail-drawer");
    if (!drawer) return undefined;
    const update = () => setEntries(collect(drawer));
    update();
    if (typeof MutationObserver === "undefined") return undefined;
    const observer = new MutationObserver(update);
    observer.observe(drawer, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);
  return (
    <nav ref={ref} className="ws-stage-index" aria-label="Sections">
      {entries.map((entry) => (
        <button key={entry.label} type="button" className="ws-stage-index__item" onClick={() => entry.target.scrollIntoView({ behavior: "smooth", block: "start" })}>
          {entry.label}
        </button>
      ))}
    </nav>
  );
}
