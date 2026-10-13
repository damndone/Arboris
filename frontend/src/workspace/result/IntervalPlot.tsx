// v1.9.0 — the slopes at a glance: each estimate (dot) with its confidence
// interval (bar) against zero, so whether an interval crosses zero reads
// without the table. The key term is in the accent colour; an interval that
// crosses zero is drawn muted. Axis ticks and each estimate are labelled.
// Drawn in SVG so positions are attributes, not inline styles.

import { formatEstimate } from "../../format/numbers";
import type { CoefficientRow } from "./resultModel";

const WIDTH = 380;
const ROW = 24;
const LABEL = 96;
const VALUE = 64;
const PLOT = WIDTH - LABEL - VALUE - 8;
const AXIS = 22;

/** Two to six round tick values covering [lo, hi]. */
export function niceTicks(lo: number, hi: number): number[] {
  const span = hi - lo || Math.abs(hi) || 1;
  const raw = span / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((candidate) => span / candidate <= 6) ?? 10 * magnitude;
  const ticks: number[] = [];
  for (let value = Math.ceil(lo / step) * step; value <= hi + step * 1e-9; value += step) ticks.push(Math.abs(value) < step * 1e-9 ? 0 : value);
  return ticks;
}

export function IntervalPlot({ rows, highlight, levelText }: { rows: CoefficientRow[]; highlight: string; levelText: string }) {
  const drawable = rows.filter((row) => row.estimate !== null).slice(0, 8);
  if (drawable.length === 0) return null;
  const values = drawable.flatMap((row) => [row.ciLow ?? row.estimate!, row.ciHigh ?? row.estimate!, 0]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min || 1) * 0.06;
  const lo = min - pad;
  const hi = max + pad;
  const x = (value: number) => LABEL + ((value - lo) / (hi - lo)) * PLOT;
  const top = drawable.length * ROW + 4;
  const height = top + AXIS;
  const ticks = niceTicks(lo, hi);

  return (
    <figure className="ws-interval">
      <figcaption className="ws-interval__caption">Slopes with {levelText}</figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${height}`}
        width={WIDTH}
        height={height}
        role="img"
        aria-label={`Slopes with ${levelText}: ${drawable
          .map((row) => `${row.label} ${formatEstimate(row.estimate)} (${formatEstimate(row.ciLow)} to ${formatEstimate(row.ciHigh)})`)
          .join(", ")}`}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={x(tick)} x2={x(tick)} y1={2} y2={top} className={tick === 0 ? "ws-interval__zero" : "ws-interval__grid"} />
            <text x={x(tick)} y={height - 6} textAnchor="middle" className="ws-interval__tick">
              {formatEstimate(tick)}
            </text>
          </g>
        ))}
        {drawable.map((row, index) => {
          const y = index * ROW + 14;
          const crossesZero = row.ciLow !== null && row.ciHigh !== null && row.ciLow <= 0 && row.ciHigh >= 0;
          const className = ["ws-interval__row", row.term === highlight && "ws-interval__row--key", crossesZero && "ws-interval__row--null"]
            .filter(Boolean)
            .join(" ");
          return (
            <g key={row.term} className={className}>
              <title>
                {`${row.label}: ${formatEstimate(row.estimate)}, ${levelText} ${formatEstimate(row.ciLow)} to ${formatEstimate(row.ciHigh)}${crossesZero ? " (crosses zero)" : ""}`}
              </title>
              <text x={LABEL - 10} y={y + 4} textAnchor="end" className="ws-interval__label">
                {row.label.length > 14 ? `${row.label.slice(0, 13)}…` : row.label}
              </text>
              {row.ciLow !== null && row.ciHigh !== null && (
                <line x1={x(row.ciLow)} x2={x(row.ciHigh)} y1={y} y2={y} className="ws-interval__bar" />
              )}
              <circle cx={x(row.estimate!)} cy={y} r={4} className="ws-interval__dot" />
              <text x={WIDTH - 4} y={y + 4} textAnchor="end" className="ws-interval__value">
                {formatEstimate(row.estimate)}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
