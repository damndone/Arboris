// v1.6.11 slice B-2 — presentational renderer for a NodeComparisonResult.
//
// Readability rules (user decision, 2026-07-11): sections self-adapt — unchanged
// sections collapse to nothing, so the eye lands only on real differences.
// Values are GitHub-diff colored: removed red with −, added green with +,
// changed renders old → new with a numeric delta badge when meaningful.
import type { NodeComparisonResult } from "../api/compareNodes";
import type { CompareSection, FieldDiff } from "../api/nodeDiff";

const SECTION_TITLES: Array<[keyof NodeComparisonResult["sections"], string]> = [
  ["params", "Parameters"],
  ["decisions", "Decisions"],
  ["metrics", "Metrics"],
  ["diagnostics", "Diagnostics"],
  ["upstream_path", "Upstream path"],
];

const REMOVED_COLOR = "var(--diff-removed, #b35900)";
const ADDED_COLOR = "var(--diff-added, #1a7f37)";

export function CompareDiffView({ result }: { result: NodeComparisonResult }) {
  if (result.same_node) {
    return (
      <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
        Both sides are the same node — pick a different node to compare.
      </div>
    );
  }
  return (
    <div data-testid="compare-diff-view">
      <div style={{ fontSize: 12, marginBottom: 6 }}>
        <strong>{result.left.display_label}</strong>
        <span style={{ color: "var(--label-tertiary)" }}> vs </span>
        <strong>{result.right.display_label}</strong>
        <span style={{ color: "var(--label-tertiary)" }}>
          {" · "}
          {result.total_changed === 0
            ? "no differences"
            : `${result.total_changed} difference${result.total_changed === 1 ? "" : "s"}`}
        </span>
      </div>
      {result.cross_kind && (
        <div
          style={{ fontSize: 11, color: "var(--label-tertiary)", marginBottom: 6 }}
          data-testid="compare-cross-kind-note"
        >
          Different node kinds ({result.left.kind}/{result.left.stage} vs{" "}
          {result.right.kind}/{result.right.stage}) — fields are matched by name.
        </div>
      )}
      {result.total_changed === 0 ? (
        <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
          These nodes are identical across all compared sections.
        </div>
      ) : (
        SECTION_TITLES.map(([key, title]) => (
          <DiffSection key={key} title={title} section={result.sections[key]} />
        ))
      )}
    </div>
  );
}

function DiffSection({
  title,
  section,
}: {
  title: string;
  section: CompareSection<FieldDiff>;
}) {
  if (!section.changed) return null; // self-adapting: unchanged sections vanish
  return (
    <div style={{ marginBottom: 10 }} data-testid={`compare-section-${title}`}>
      <div className="ln-section-label" style={{ fontSize: 11, marginBottom: 4 }}>
        {title}
      </div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {section.items.map((item) => (
          <DiffRow key={item.field_id} item={item} />
        ))}
      </ul>
      {section.truncated && (
        <div style={{ fontSize: 11, color: "var(--label-tertiary)" }}>
          … {section.total_changed - section.items.length} more not shown
        </div>
      )}
    </div>
  );
}

function DiffRow({ item }: { item: FieldDiff }) {
  return (
    <li style={{ fontSize: 12, padding: "2px 0", display: "flex", gap: 6 }}>
      <span style={{ minWidth: 110, color: "var(--label-secondary)" }}>
        {item.label ?? item.field_id}
      </span>
      <span style={{ fontFamily: "ui-monospace, monospace", wordBreak: "break-word" }}>
        {item.change_type === "removed" && (
          <span style={{ color: REMOVED_COLOR }}>− {formatValue(item.old_value)}</span>
        )}
        {item.change_type === "added" && (
          <span style={{ color: ADDED_COLOR }}>+ {formatValue(item.new_value)}</span>
        )}
        {item.change_type === "changed" && (
          <>
            <span style={{ color: REMOVED_COLOR }}>{formatValue(item.old_value)}</span>
            <span style={{ color: "var(--label-tertiary)" }}> → </span>
            <span style={{ color: ADDED_COLOR }}>{formatValue(item.new_value)}</span>
            {typeof item.delta === "number" && Number.isFinite(item.delta) && (
              <span
                style={{ color: "var(--label-tertiary)", marginLeft: 6 }}
                data-testid="compare-delta"
              >
                (Δ {formatDelta(item.delta)})
              </span>
            )}
          </>
        )}
      </span>
    </li>
  );
}

function formatValue(value: unknown): string {
  if (value === undefined) return "—";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function formatNumber(value: number): string {
  if (Number.isInteger(value)) return String(value);
  const abs = Math.abs(value);
  if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) return value.toExponential(3);
  return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function formatDelta(delta: number): string {
  const text = formatNumber(delta);
  return delta > 0 ? `+${text}` : text;
}
