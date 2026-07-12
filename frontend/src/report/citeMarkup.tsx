// v1.6.11 slice C — [[c:ID]] marker parsing + chip rendering.
//
// Chips render from the LOCAL fact table: a marker whose id is not in the
// table becomes an explicit "unverified" chip instead of silently showing the
// model's number. Clicking a verified chip jumps to its node on the graph.
import type { CitableFact } from "./factTable";

const CITE_PATTERN = /\[\[c:([A-Za-z0-9_-]+)\]\]/g;

export type CiteSegment =
  | { type: "text"; text: string }
  | { type: "cite"; id: string };

export function parseCiteSegments(text: string): CiteSegment[] {
  const segments: CiteSegment[] = [];
  let lastIndex = 0;
  for (const match of text.matchAll(CITE_PATTERN)) {
    const index = match.index ?? 0;
    if (index > lastIndex) segments.push({ type: "text", text: text.slice(lastIndex, index) });
    segments.push({ type: "cite", id: match[1] });
    lastIndex = index + match[0].length;
  }
  if (lastIndex < text.length) segments.push({ type: "text", text: text.slice(lastIndex) });
  return segments;
}

export function CiteChip({
  id,
  fact,
  onJump,
}: {
  id: string;
  fact: CitableFact | undefined;
  onJump?: (nodeKey: string) => void;
}) {
  if (!fact) {
    return (
      <span
        data-testid="cite-chip-unverified"
        title={`Citation ${id} does not match any known fact — unverified model output`}
        style={{
          display: "inline-block",
          padding: "0 6px",
          margin: "0 2px",
          borderRadius: 999,
          fontSize: 11,
          border: "1px solid var(--diff-removed, #b35900)",
          color: "var(--diff-removed, #b35900)",
        }}
      >
        unverified
      </span>
    );
  }
  return (
    <button
      type="button"
      data-testid="cite-chip"
      title={`${fact.node_label} · ${fact.field} — click to view the node`}
      onClick={() => onJump?.(fact.node_key)}
      style={{
        display: "inline-block",
        padding: "0 6px",
        margin: "0 2px",
        borderRadius: 999,
        fontSize: 11,
        border: "1px solid var(--separator)",
        background: "var(--bg-card-2, rgba(0,0,0,0.05))",
        // global `button` paints WHITE text; chips must use the label color.
        color: "var(--label)",
        minHeight: 0,
        fontWeight: 500,
        cursor: onJump ? "pointer" : "default",
      }}
    >
      {fact.label}: {formatFactValue(fact.value)}
    </button>
  );
}

export function formatFactValue(value: unknown): string {
  if (typeof value === "number" && !Number.isInteger(value)) {
    return value.toPrecision(4).replace(/0+$/, "").replace(/\.$/, "");
  }
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
