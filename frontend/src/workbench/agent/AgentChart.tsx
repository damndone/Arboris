// A chart the Agent drew with show_chart: a typed specification whose numbers the server has
// checked against tool results. Drawn here as SVG; no code from the model runs.

import { useEffect, useRef, useState } from "react";
import type { AgentMessage } from "./agentTypes";

export type ChartPoint = { label?: string; series?: string; x?: number; y: number; low?: number; high?: number };
export type ChartSpec = {
  kind: "coefficients" | "bar" | "line" | "scatter";
  title: string;
  x_label?: string;
  y_label?: string;
  reference?: number;
  points: ChartPoint[];
};

export function shownChart(message: AgentMessage): ChartSpec | null {
  if (message.role !== "tool" || message.name !== "show_chart") return null;
  try {
    const payload = JSON.parse(message.content) as { ok?: unknown; output?: { chart?: ChartSpec } };
    const chart = payload.output?.chart;
    return payload.ok === true && chart && Array.isArray(chart.points) && chart.points.length > 0 ? chart : null;
  } catch {
    return null;
  }
}

const COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"];

function number(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(4)));
}

function describe(point: ChartPoint): string {
  const name = [point.series, point.label, point.x === undefined ? undefined : number(point.x)].filter(Boolean).join(" · ");
  const interval = point.low !== undefined && point.high !== undefined ? ` [${number(point.low)}, ${number(point.high)}]` : "";
  return `${name ? `${name}: ` : ""}${number(point.y)}${interval}`;
}

/** Evenly spaced round ticks covering the data. */
function ticks(low: number, high: number, count = 4): number[] {
  const span = high - low || Math.abs(high) || 1;
  const raw = span / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((unit) => unit * power).find((value) => value >= raw) ?? raw;
  const start = Math.floor(low / step) * step;
  const values: number[] = [];
  for (let value = start; value <= high + step * 1e-9; value += step) values.push(Number(value.toPrecision(10)));
  if (values[values.length - 1] < high) values.push(Number((values[values.length - 1] + step).toPrecision(10)));
  return values;
}

function useWidth() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(480);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

export function AgentChart({ chart }: { chart: ChartSpec }) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const series = [...new Set(chart.points.map((point) => point.series ?? ""))];
  const color = (point: ChartPoint) => COLORS[series.indexOf(point.series ?? "") % COLORS.length];
  const values = chart.points.flatMap((point) => [point.y, point.low, point.high]).filter((value): value is number => value !== undefined);
  if (chart.reference !== undefined) values.push(chart.reference);
  if (chart.kind === "bar") values.push(0);
  const axis = ticks(Math.min(...values), Math.max(...values));
  const low = axis[0];
  const high = axis[axis.length - 1];
  const hit = (index: number, x: number, y: number, w: number, h: number) => (
    <rect
      key={`hit-${index}`}
      className="agt-chart__hit"
      x={x} y={y} width={w} height={h}
      tabIndex={0}
      aria-label={describe(chart.points[index])}
      onMouseEnter={() => setActive(index)}
      onFocus={() => setActive(index)}
      onMouseLeave={() => setActive(null)}
      onBlur={() => setActive(null)}
    />
  );
  const whisker = (index: number, a: number, b: number, c: number, horizontal: boolean, stroke: string) => (
    horizontal
      ? <line key={`w-${index}`} x1={a} x2={b} y1={c} y2={c} stroke={stroke} strokeWidth={2} strokeLinecap="round" />
      : <line key={`w-${index}`} x1={c} x2={c} y1={a} y2={b} stroke={stroke} strokeWidth={2} strokeLinecap="round" />
  );

  let plot;
  if (chart.kind === "coefficients") {
    const gutter = Math.min(150, width * 0.34);
    const right = width - 12;
    const scale = (value: number) => gutter + ((value - low) / (high - low || 1)) * (right - gutter);
    const row = 26;
    const height = chart.points.length * row + 22;
    plot = (
      <svg height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={chart.title}>
        {axis.map((tick) => (
          <g key={tick}>
            <line className="agt-chart__grid" x1={scale(tick)} x2={scale(tick)} y1={0} y2={height - 20} />
            <text x={scale(tick)} y={height - 6} textAnchor="middle">{number(tick)}</text>
          </g>
        ))}
        {chart.reference !== undefined && <line className="agt-chart__reference" x1={scale(chart.reference)} x2={scale(chart.reference)} y1={0} y2={height - 20} />}
        {chart.points.map((point, index) => {
          const y = index * row + row / 2;
          return (
            <g key={index}>
              <text x={gutter - 8} y={y + 4} textAnchor="end">{(point.label ?? "").slice(0, Math.floor(gutter / 7))}</text>
              {point.low !== undefined && point.high !== undefined && whisker(index, scale(point.low), scale(point.high), y, true, color(point))}
              <circle cx={scale(point.y)} cy={y} r={4} fill={color(point)} stroke="var(--bg-card)" strokeWidth={2} />
              {hit(index, 0, index * row, width, row)}
            </g>
          );
        })}
      </svg>
    );
  } else {
    const left = 44;
    const right = width - 8;
    const top = 6;
    const bottom = 172;
    const height = 196 + (chart.x_label ? 14 : 0);
    const yScale = (value: number) => bottom - ((value - low) / (high - low || 1)) * (bottom - top);
    const numeric = chart.kind !== "bar" && chart.points.every((point) => point.x !== undefined);
    const xs = numeric ? chart.points.map((point) => point.x as number) : [];
    const xLow = Math.min(...xs);
    const xHigh = Math.max(...xs);
    const labels = [...new Set(chart.points.map((point) => point.label ?? ""))];
    const band = (right - left) / (labels.length || 1);
    const position = (point: ChartPoint, index: number) => {
      if (numeric) return left + 8 + (((point.x as number) - xLow) / (xHigh - xLow || 1)) * (right - left - 16);
      if (chart.kind === "bar") {
        const slot = band / (series.length + 1);
        return left + labels.indexOf(point.label ?? "") * band + slot * (series.indexOf(point.series ?? "") + 1);
      }
      return left + (index + 0.5) * ((right - left) / chart.points.length);
    };
    const barWidth = Math.max(4, Math.min(28, band / (series.length + 1) - 2));
    const every = Math.max(1, Math.ceil(labels.length / Math.max(1, Math.floor((right - left) / 70))));
    plot = (
      <svg height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={chart.title}>
        {axis.map((tick) => (
          <g key={tick}>
            <line className="agt-chart__grid" x1={left} x2={right} y1={yScale(tick)} y2={yScale(tick)} />
            <text x={left - 6} y={yScale(tick) + 4} textAnchor="end">{number(tick)}</text>
          </g>
        ))}
        {chart.reference !== undefined && <line className="agt-chart__reference" x1={left} x2={right} y1={yScale(chart.reference)} y2={yScale(chart.reference)} />}
        {chart.kind === "line" && series.map((name, seriesIndex) => (
          <polyline
            key={name}
            fill="none"
            stroke={COLORS[seriesIndex % COLORS.length]}
            strokeWidth={2}
            strokeLinejoin="round"
            points={chart.points.map((point, index) => ({ point, index }))
              .filter(({ point }) => (point.series ?? "") === name)
              .map(({ point, index }) => `${position(point, index)},${yScale(point.y)}`).join(" ")}
          />
        ))}
        {chart.points.map((point, index) => {
          const x = position(point, index);
          const y = yScale(point.y);
          const showMarker = chart.kind === "scatter" || chart.points.length <= 30;
          return (
            <g key={index}>
              {chart.kind === "bar" && (
                <rect x={x - barWidth / 2} y={Math.min(y, yScale(0))} width={barWidth} height={Math.max(1, Math.abs(yScale(0) - y))} rx={Math.min(4, barWidth / 2)} fill={color(point)} />
              )}
              {point.low !== undefined && point.high !== undefined && whisker(index, yScale(point.low), yScale(point.high), x, false, chart.kind === "bar" ? "var(--label-secondary)" : color(point))}
              {chart.kind !== "bar" && showMarker && <circle cx={x} cy={y} r={4} fill={color(point)} stroke="var(--bg-card)" strokeWidth={2} />}
              {hit(index, x - Math.max(8, barWidth / 2), top, Math.max(16, barWidth), bottom - top)}
            </g>
          );
        })}
        {!numeric && labels.map((label, index) => index % every === 0 && (
          <text key={label} x={chart.kind === "bar" ? left + (index + 0.5) * band : position({ y: 0 }, index)} y={bottom + 16} textAnchor="middle">
            {label.slice(0, Math.floor((band * every) / 7))}
          </text>
        ))}
        {numeric && ticks(xLow, xHigh).filter((tick) => tick >= xLow && tick <= xHigh).map((tick) => (
          <text key={tick} x={left + 8 + ((tick - xLow) / (xHigh - xLow || 1)) * (right - left - 16)} y={bottom + 16} textAnchor="middle">{number(tick)}</text>
        ))}
        {chart.x_label && <text x={(left + right) / 2} y={height - 2} textAnchor="middle">{chart.x_label}</text>}
      </svg>
    );
  }

  return (
    <figure ref={ref} className="agt-chart" data-testid="agent-chart">
      <figcaption className="agt-chart__title">{chart.title}</figcaption>
      {series.length > 1 && (
        <div className="agt-chart__legend">
          {series.map((name, index) => (
            <span key={name}><span className="agt-chart__swatch" style={{ background: COLORS[index % COLORS.length] }} />{name || "—"}</span>
          ))}
        </div>
      )}
      <div className="agt-chart__readout" aria-live="polite" data-testid="agent-chart-readout">
        {active === null ? (chart.y_label ?? "") : describe(chart.points[active])}
      </div>
      {plot}
      <details className="agt-chart__data">
        <summary>Data</summary>
        <table>
          <tbody>
            {chart.points.map((point, index) => (
              <tr key={index}>
                <th scope="row">{[point.series, point.label, point.x === undefined ? undefined : number(point.x)].filter(Boolean).join(" · ")}</th>
                <td>{number(point.y)}</td>
                <td>{point.low !== undefined && point.high !== undefined ? `[${number(point.low)}, ${number(point.high)}]` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
