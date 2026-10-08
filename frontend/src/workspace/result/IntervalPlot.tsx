// v1.9.0 — estimates with their intervals on one axis, the key term in the
// accent colour and a zero line for reference. Drawn in SVG so positions are
// attributes, not inline styles.

import { formatEstimate } from "../../format/numbers";
import type { CoefficientRow } from "./resultModel";

const WIDTH = 320;
const ROW = 24;
const LABEL = 112;
const PLOT = WIDTH - LABEL - 8;

export function IntervalPlot({ rows, highlight, levelText }: { rows: CoefficientRow[]; highlight: string; levelText: string }) {
  const drawable = rows.filter((row) => row.estimate !== null).slice(0, 8);
  if (drawable.length === 0) return null;
  const values = drawable.flatMap((row) => [row.ciLow ?? row.estimate!, row.ciHigh ?? row.estimate!, 0]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min || 1) * 0.08;
  const lo = min - pad;
  const hi = max + pad;
  const x = (value: number) => LABEL + ((value - lo) / (hi - lo)) * PLOT;
  const height = drawable.length * ROW + 22;
  return (
    <figure className="ws-interval">
      <svg
        viewBox={`0 0 ${WIDTH} ${height}`}
        width={WIDTH}
        height={height}
        role="img"
        aria-label={`Estimates with ${levelText}: ${drawable.map((row) => `${row.label} ${formatEstimate(row.estimate)}`).join(", ")}`}
      >
        <line x1={x(0)} x2={x(0)} y1={4} y2={height - 18} className="ws-interval__zero" />
        {drawable.map((row, index) => {
          const y = index * ROW + 14;
          const key = row.term === highlight;
          return (
            <g key={row.term} className={key ? "ws-interval__row ws-interval__row--key" : "ws-interval__row"}>
              <text x={LABEL - 10} y={y + 4} textAnchor="end" className="ws-interval__label">
                {row.label.length > 16 ? `${row.label.slice(0, 15)}…` : row.label}
              </text>
              {row.ciLow !== null && row.ciHigh !== null && (
                <line x1={x(row.ciLow)} x2={x(row.ciHigh)} y1={y} y2={y} className="ws-interval__bar" />
              )}
              <circle cx={x(row.estimate!)} cy={y} r={4.5} className="ws-interval__dot" />
            </g>
          );
        })}
        <text x={x(0)} y={height - 4} textAnchor="middle" className="ws-interval__tick">0</text>
      </svg>
    </figure>
  );
}
