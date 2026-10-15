// v1.9.0 — the map as a column (design spec §8.3.1). When the stage is open
// in results first, the map narrows to a navigator: the same lineage as the
// graph, drawn as a tree of cards that fits 280px. A chain stays at one
// indent; a branch steps in, so the shape of the analysis reads at a glance.

import type { GraphViewEdge, GraphViewNode, Stage, Trust } from "../lineage/api/graphViewTypes";
import "./mapTree.css";

export interface MapRow {
  node: GraphViewNode;
  /** "data": the data part; "analysis": models and what hangs off them. */
  group: "data" | "analysis";
  depth: number;
}

const DATA_STAGES: ReadonlySet<Stage> = new Set<Stage>(["source", "eda", "clean", "transform", "unknown"]);
const ANALYSIS_STAGES: ReadonlySet<Stage> = new Set<Stage>(["model", "compare"]);

/**
 * Rows in reading order. The data part comes first as a tree (a chain stays at
 * one indent, a branch steps in); then each model, one step in, followed by
 * what hangs off it (diagnostics, figures, reports). A node reached twice is
 * listed once, under its first parent.
 */
export function mapRows(nodes: GraphViewNode[], edges: GraphViewEdge[]): MapRow[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const children = new Map<string, string[]>();
  const hasParent = new Set<string>();
  for (const edge of edges) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) continue;
    children.set(edge.source, [...(children.get(edge.source) ?? []), edge.target]);
    hasParent.add(edge.target);
  }
  const rows: MapRow[] = [];
  const seen = new Set<string>();
  const place = (id: string, depth: number, group: MapRow["group"] = "data") => {
    seen.add(id);
    rows.push({ node: byId.get(id)!, depth, group });
  };
  const kidsIn = (id: string, stages: ReadonlySet<Stage> | null) =>
    (children.get(id) ?? []).filter((child) => !seen.has(child) && (!stages || stages.has(byId.get(child)!.stage)));

  const visitData = (id: string, depth: number) => {
    if (seen.has(id)) return;
    place(id, depth);
    const next = kidsIn(id, DATA_STAGES);
    next.forEach((child) => visitData(child, next.length > 1 ? depth + 1 : depth));
  };
  const visitOutputs = (id: string, depth: number) => {
    for (const child of kidsIn(id, null)) {
      if (ANALYSIS_STAGES.has(byId.get(child)!.stage) || DATA_STAGES.has(byId.get(child)!.stage)) continue;
      place(child, depth, "analysis");
      visitOutputs(child, depth);
    }
  };

  nodes.filter((n) => !hasParent.has(n.id) && DATA_STAGES.has(n.stage)).forEach((root) => visitData(root.id, 0));
  nodes.filter((n) => DATA_STAGES.has(n.stage)).forEach((n) => visitData(n.id, 0));
  for (const n of nodes.filter((node) => ANALYSIS_STAGES.has(node.stage))) {
    if (seen.has(n.id)) continue;
    place(n.id, 0, "analysis");
    visitOutputs(n.id, 1);
  }
  nodes.forEach((n) => {
    if (!seen.has(n.id)) place(n.id, 0);
  });
  return rows;
}

const TRUST_LABEL: Partial<Record<Trust, string>> = {
  review: "Needs review",
  caution: "Caution",
  blocker: "Blocked",
};

function StageGlyph({ stage }: { stage: Stage }) {
  const paths: Record<string, string> = {
    source: "M2 3.5h12v9H2zM2 6.5h12M6.5 6.5v6",
    eda: "M3 13V8M8 13V3M13 13V6",
    clean: "M3 8.5 6.5 12 13 4.5",
    transform: "M3 5h8l-2-2M13 11H5l2 2",
    model: "M2.5 12.5 6 8l3 2.5 4.5-6",
    diag: "M8 2.5 13.5 4v4c0 3-2.3 5-5.5 6-3.2-1-5.5-3-5.5-6V4z",
    viz: "M2.5 13.5h11M4 11V7M8 11V4M12 11V8",
    report: "M4 2h5.5L12 4.5V14H4zM6 7.5h4M6 10h4",
    compare: "M5 3v10M11 3v10M2.5 8h11",
  };
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[stage] ?? "M8 4.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z"} />
    </svg>
  );
}

export function MapTree({
  nodes,
  edges,
  selectedKey,
  onSelect,
}: {
  nodes: GraphViewNode[];
  edges: GraphViewEdge[];
  selectedKey: string | null;
  onSelect: (nodeKey: string) => void;
}) {
  const rows = mapRows(nodes, edges);
  if (rows.length === 0) return <p className="ws-map-tree__empty">No steps yet. Import data to begin.</p>;
  const groups: Array<{ id: MapRow["group"]; label: string }> = [
    { id: "data", label: "Data" },
    { id: "analysis", label: "Analyses" },
  ];
  return (
    <div className="ws-map-tree">
      {groups.map(({ id, label }) => {
        const groupRows = rows.filter((row) => row.group === id);
        if (groupRows.length === 0) return null;
        return (
          <section key={id} className="ws-map-tree__group" aria-labelledby={`ws-map-${id}`}>
            <h3 id={`ws-map-${id}`} className="ws-map-tree__heading">{label}</h3>
            <ul className="ws-map-tree__list" aria-label={id === "data" ? "Data steps" : "Analyses"}>
              {groupRows.map(({ node, depth }) => {
                const flag = TRUST_LABEL[node.trust];
                const detail = node.summary ?? node.subtitle;
                return (
                  <li key={node.id} data-depth={Math.min(depth, 6)}>
                    <button
                      type="button"
                      className="ws-map-tree__card"
                      data-stage={node.stage}
                      data-draft={node.isDraft ? "true" : undefined}
                      aria-current={node.nodeKey === selectedKey ? "true" : undefined}
                      onClick={() => onSelect(node.nodeKey)}
                    >
                      <span className="ws-map-tree__glyph"><StageGlyph stage={node.stage} /></span>
                      <span className="ws-map-tree__text">
                        <span className="ws-map-tree__title">{node.title}</span>
                        {detail && <span className="ws-map-tree__detail">{detail}</span>}
                      </span>
                      {flag && <span className="ws-map-tree__flag" data-trust={node.trust}>{flag}</span>}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
