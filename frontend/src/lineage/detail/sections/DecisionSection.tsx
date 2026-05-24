// frontend/src/lineage/detail/sections/DecisionSection.tsx
//
// V1.5.0 decisions section (Step 6, T6.7). Registry order 70.
// shouldRender = (n) => n.decisions.length > 0 — gated upstream.
//
// V1.5.0 reuses V1.4.1 DecisionCard + DecisionExpanded (renamed/relocated
// to lineage/decisions/ in T7 with the same signatures). Those components
// still consume the raw DecisionPoint shape, so this section reads them
// off node.raw rather than node.decisions. Order is preserved by the
// adapter, so the two arrays line up 1:1.

import { useState } from "react";
import { DecisionCard } from "../../decisions/DecisionCard";
import { DecisionExpanded } from "../../decisions/DecisionExpanded";
import type { GraphViewNode } from "../../api/graphViewTypes";
import type { LineageNode } from "../../types";

export function DecisionSection({ node }: { node: GraphViewNode }) {
  // Count comes from the view model (registry's shouldRender contract).
  // Cards consume the raw payload because V1.4.1 DecisionCard /
  // DecisionExpanded still take DecisionPoint shape; T7 renames them and
  // the section can stop reaching into .raw at that point.
  const vmCount = node.decisions.length;
  const dps = ((node.raw as LineageNode | null)?.decision_points ?? []) as
    LineageNode["decision_points"];
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Belt-and-braces: the registry's needsTrust-equivalent gate already
  // filters decisions.length > 0, but if it's bypassed we still render
  // nothing rather than an empty heading.
  if (vmCount === 0) return null;

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <section
      aria-label="Decisions"
      data-testid="decision-section"
      style={{ marginTop: 18 }}
    >
      <div className="ln-section-label" style={{ marginBottom: 8 }}>
        Decisions ({vmCount})
      </div>
      {dps.map((dp, i) => {
        // REV-2 #4: if a node ever carries two DPs with the same
        // decision_id (adapter doesn't dedupe), React keys must still be
        // unique. Suffix with index. Expansion state still keys on
        // decision_id so both copies expand together — that's acceptable
        // for the rare duplicate case (no UX has been designed around
        // distinguishing them).
        const key = `${dp.decision_id}:${i}`;
        return expanded.has(dp.decision_id) ? (
          <DecisionExpanded key={key} dp={dp} />
        ) : (
          <DecisionCard
            key={key}
            dp={dp}
            expanded={false}
            onToggle={() => toggle(dp.decision_id)}
          />
        );
      })}
    </section>
  );
}
