import type { GraphViewNode } from "../../api/graphViewTypes";
import { getCompareWithSourceGate } from "../../api/rerunProvenance";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";

export function CompareWithSourceSection(_props: { node?: GraphViewNode }) {
  const resolved = useResolvedNodeOperationContext();
  if (!resolved || !resolved.ok) return null;
  const gate = getCompareWithSourceGate(resolved.context);
  if (!gate.ok) {
    return (
      <section
        aria-label="Compare with source"
        data-testid="compare-with-source-section"
        style={{ marginTop: 18 }}
      >
        <div className="ln-section-label" style={{ marginBottom: 6 }}>
          Compare with source
        </div>
        <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
          No rerun source recorded for this node.
        </div>
      </section>
    );
  }
  return (
    <section
      aria-label="Compare with source"
      data-testid="compare-with-source-section"
      style={{ marginTop: 18 }}
    >
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Compare with source
      </div>
      <button type="button">Compare with source</button>
    </section>
  );
}
