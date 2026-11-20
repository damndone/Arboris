import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import "./researchCurve.css";

export type ResearchPoint = {
  position: number;
  time: string;
  value: number;
  lower?: number;
  upper?: number;
  details?: readonly (readonly [string, string])[];
};

type ResearchCurveProps = {
  title: string;
  xLabel: string;
  yLabel: string;
  points: readonly ResearchPoint[];
  formatValue: (value: number) => string;
  bandLabel?: string;
  stem?: boolean;
  comparison?: { primary: string; label: string; values: readonly number[] };
};

const HEIGHT = 190;
const TOP = 27;
const BOTTOM = HEIGHT - 43;
const SVG_FALLBACK_WIDTH = 360;

function scale(min: number, max: number) {
  // Halving only on overflow preserves the resolution of narrow ranges.
  const divisor = Number.isFinite(max - min) ? 1 : 2;
  const low = min / divisor;
  const high = max / divisor;
  const span = high - low;
  return {
    unit: (value: number) => span === 0 ? 0.5 : (value / divisor - low) / span,
    ticks: span === 0 ? [min] : [...new Set([
      min, Math.min(high, low + span / 3) * divisor,
      Math.min(high, low + span * (2 / 3)) * divisor, max,
    ])],
  };
}

function boundedInterval(point: ResearchPoint): readonly [number, number] | undefined {
  const { lower, upper } = point;
  return lower !== undefined && upper !== undefined && Number.isFinite(lower)
    && Number.isFinite(upper) && lower <= upper ? [lower, upper] : undefined;
}

function tickTime(time: string, intraday: boolean): string {
  const iso = /^(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d(?:\.\d+)?)/.exec(time);
  if (iso) return intraday ? iso[2] : iso[1];
  return time.length > 18 ? `${time.slice(0, 8)}…${time.slice(-8)}` : time;
}

function fitText(label: string, available: number) {
  const estimated = label.length * 6.4;
  return estimated > available ? { textLength: Math.max(1, available), lengthAdjust: "spacingAndGlyphs" as const } : {};
}

function xTicks(rows: readonly { time: string; x: number }[], plotWidth: number) {
  const first = rows[0];
  const last = rows[rows.length - 1];
  const intraday = /^\d{4}-\d\d-\d\d[T ]/.test(first.time) && first.time.slice(0, 10) === last.time.slice(0, 10);
  if (rows.length === 1) return [{ x: first.x, label: tickTime(first.time, intraday), anchor: "middle" as const, available: plotWidth }];
  const count = Math.min(rows.length, 6, Math.max(2, Math.floor(plotWidth / 74) + 1));
  const candidates = Array.from({ length: count }, (_, index) => rows[Math.round(index * (rows.length - 1) / (count - 1))]);
  const shortLabels = candidates.map((row) => tickTime(row.time, intraday));
  const labels = shortLabels.map((label, index) => shortLabels.some((other, otherIndex) =>
    other === label && candidates[otherIndex].time !== candidates[index].time) ? candidates[index].time : label);
  const available = Math.max(1, (plotWidth - 8) / 2);
  const firstLabel = labels[0];
  const lastLabel = labels[count - 1];
  const ticks: { x: number; label: string; anchor: "start" | "middle" | "end"; available: number }[] = [
    { x: first.x, label: firstLabel, anchor: "start", available },
  ];
  let occupied = first.x + Math.min(available, firstLabel.length * 6.4);
  const end = last.x - Math.min(available, lastLabel.length * 6.4);
  for (let i = 1; i < count - 1; i++) {
    const row = candidates[i];
    const text = labels[i];
    const half = text.length * 3.2;
    if (row.x - half < occupied + 7 || row.x + half > end - 7) continue;
    ticks.push({ x: row.x, label: text, anchor: "middle", available: plotWidth });
    occupied = row.x + half;
  }
  ticks.push({ x: last.x, label: lastLabel, anchor: "end", available });
  return ticks;
}

export function ResearchCurve({ title, xLabel, yLabel, points, formatValue, bandLabel, stem = false, comparison }: ResearchCurveProps) {
  const plot = useRef<HTMLDivElement>(null);
  const hintId = useId();
  const tooltipId = useId();
  const [width, setWidth] = useState(SVG_FALLBACK_WIDTH);
  const [selection, setSelection] = useState<{ index: number; keyboard: boolean } | null>(null);
  const data = points.filter((point) => Number.isFinite(point.position) && Number.isFinite(point.value));
  const hasData = data.length > 0;

  useEffect(() => {
    const element = plot.current;
    if (!hasData || !element) return;
    function resize(value: number) {
      if (Number.isFinite(value) && value > 0) setWidth(Math.max(1, Math.floor(value)));
    }
    resize(element.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => resize(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, [hasData]);

  if (!hasData) return null;
  const intervals = data.map(boundedInterval);
  const compared = comparison && data.length === points.length && comparison.values.length === data.length
    && comparison.values.every(Number.isFinite) ? comparison : undefined;
  const primaryLabel = compared?.primary ?? yLabel;
  let min = stem ? 0 : Infinity;
  let max = stem ? 0 : -Infinity;
  data.forEach((point, index) => {
    min = Math.min(min, point.value, intervals[index]?.[0] ?? point.value, compared?.values[index] ?? point.value);
    max = Math.max(max, point.value, intervals[index]?.[1] ?? point.value, compared?.values[index] ?? point.value);
  });
  const yScale = scale(min, max);
  const y = (value: number) => BOTTOM - (BOTTOM - TOP) * yScale.unit(value);
  const formattedTicks = yScale.ticks.map(formatValue);
  const yLabels = new Set(formattedTicks).size === formattedTicks.length ? formattedTicks : yScale.ticks.map(String);
  const longest = Math.max(...yLabels.map((label) => label.length));
  const left = Math.min(width * 0.30, Math.max(31, Math.min(88, 12 + longest * 6.4)));
  const right = width - Math.min(13, width * 0.05);
  const xScale = scale(data[0].position, data[data.length - 1].position);
  const rows = data.map((point, index) => ({
    ...point, x: left + (right - left) * xScale.unit(point.position), y: y(point.value), interval: intervals[index],
    comparedValue: compared?.values[index],
  }));
  const timeTicks = xTicks(rows, right - left);
  const bandGroups: { x: number; interval: readonly [number, number] }[][] = [];
  let band: (typeof bandGroups)[number] = [];
  for (const row of rows) {
    if (row.interval) {
      if (band.length === 0) bandGroups.push(band);
      band.push({ x: row.x, interval: row.interval });
    } else {
      band = [];
    }
  }
  const intervalLabel = bandLabel ?? "Prediction interval";
  const active = selection === null ? undefined : rows[selection.index];

  function selectPointer(event: PointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const position = bounds.width > 0
      ? (event.clientX - bounds.left) * width / bounds.width
      : event.clientX;
    if (!Number.isFinite(position)) return;
    let nearest = 0;
    for (let i = 1; i < rows.length; i++) {
      if (Math.abs(rows[i].x - position) < Math.abs(rows[nearest].x - position)) nearest = i;
    }
    setSelection((previous) => previous?.index === nearest && !previous.keyboard ? previous : { index: nearest, keyboard: false });
  }

  function selectKeyboard(event: KeyboardEvent<SVGSVGElement>) {
    if (event.key === "Escape" && active) {
      event.preventDefault();
      event.stopPropagation();
      setSelection(null);
      return;
    }
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const last = rows.length - 1;
    setSelection((previous) => {
      const index = event.key === "Home" ? 0 : event.key === "End" ? last
        : event.key === "ArrowLeft" ? Math.max(0, (previous?.index ?? rows.length) - 1)
          : Math.min(last, (previous?.index ?? -1) + 1);
      return { index, keyboard: true };
    });
  }

  return (
    <figure className="research-curve">
      <figcaption className="research-curve__caption">
        <span>{title}</span>
        {bandGroups.length > 0 && <span className="research-curve__legend">{intervalLabel}</span>}
        {compared && <>
          <span className="research-curve__legend research-curve__legend--primary">{compared.primary}</span>
          <span className="research-curve__legend research-curve__legend--comparison">{compared.label}</span>
        </>}
      </figcaption>
      <div className="research-curve__plot" ref={plot} data-compact={width < 220 || undefined} data-comparison={Boolean(compared) || undefined}>
        <svg viewBox={`0 0 ${width} ${HEIGHT}`} preserveAspectRatio="none" role="img" aria-label={title} tabIndex={0}
          aria-describedby={active ? `${hintId} ${tooltipId}` : hintId}
          onPointerMove={selectPointer} onPointerDown={selectPointer}
          onPointerLeave={() => setSelection((previous) => previous?.keyboard ? previous : null)}
          onBlur={() => setSelection(null)} onKeyDown={selectKeyboard}>
          <text className="research-curve__axis-title" x={8} y={15} {...fitText(yLabel, width - 16)}>{yLabel}</text>
          {yScale.ticks.map((tick, index) => (
            <g key={tick} className="research-curve__tick">
              <line className="research-curve__grid" x1={left} x2={right} y1={y(tick)} y2={y(tick)} />
              <text x={left - 6} y={y(tick)} textAnchor="end" dominantBaseline="central" {...fitText(yLabels[index], left - 10)}>{yLabels[index]}</text>
            </g>
          ))}
          {timeTicks.map((tick, index) => (
            <g key={index} className="research-curve__tick">
              <line className="research-curve__grid" x1={tick.x} x2={tick.x} y1={TOP} y2={BOTTOM} />
              <text x={tick.x} y={BOTTOM + 17} textAnchor={tick.anchor} {...fitText(tick.label, tick.available)}>{tick.label}</text>
            </g>
          ))}
          <path className="research-curve__axes" d={`M${left},${TOP} V${BOTTOM} H${right}`} />
          <text className="research-curve__axis-title" x={(left + right) / 2} y={HEIGHT - 7} textAnchor="middle" {...fitText(xLabel, right - left)}>{xLabel}</text>
          {bandGroups.map((group, index) => group.length === 1
            ? <line className="research-curve__single-band" key={index} x1={group[0].x} x2={group[0].x}
                y1={y(group[0].interval[0])} y2={y(group[0].interval[1])} />
            : <polygon className="research-curve__band" key={index} points={[
                ...group.map((row) => `${row.x},${y(row.interval[1])}`),
                ...group.slice().reverse().map((row) => `${row.x},${y(row.interval[0])}`),
              ].join(" ")} />)}
          {stem ? <>
            <line className="research-curve__axes" x1={left} x2={right} y1={y(0)} y2={y(0)} />
            {rows.map((row) => <line className="research-curve__line research-curve__stem" key={row.position}
              x1={row.x} x2={row.x} y1={y(0)} y2={row.y} />)}
          </> : rows.length === 1
            ? <circle className="research-curve__point" cx={rows[0].x} cy={rows[0].y} r={3.5} />
            : <polyline className="research-curve__line" points={rows.map((row) => `${row.x},${row.y}`).join(" ")} />}
          {compared && (rows.length === 1
            ? <circle className="research-curve__comparison-point" cx={rows[0].x} cy={y(compared.values[0])} r={3.5} />
            : <polyline className="research-curve__line research-curve__line--comparison"
                points={rows.map((row, index) => `${row.x},${y(compared.values[index])}`).join(" ")} />)}
          {active && <g className="research-curve__cursor" aria-hidden="true">
            <path d={`M${active.x},${TOP} V${BOTTOM} M${left},${active.y} H${right}`} />
            <circle cx={active.x} cy={active.y} r={4} />
            {active.comparedValue !== undefined
              && <circle className="research-curve__comparison-point" cx={active.x} cy={y(active.comparedValue)} r={4} />}
          </g>}
        </svg>
        {active && <div className="research-curve__tooltip" id={tooltipId} role="tooltip" aria-label={`${title} details`}
          data-side={active.x > (left + right) / 2 ? "start" : "end"}>
          <strong>{active.time}</strong>
          <dl>
            <div><dt>{primaryLabel}</dt><dd>{String(active.value)}</dd></div>
            {compared && <div><dt>{compared.label}</dt><dd>{String(active.comparedValue)}</dd></div>}
            {active.interval && <div className="research-curve__interval">
              <dt>{intervalLabel}</dt>
              <dd><span>{String(active.interval[0])}</span>{" "}<span>to {String(active.interval[1])}</span></dd>
            </div>}
            {active.details?.map(([label, value], index) => <div key={index}><dt>{label}</dt><dd>{value}</dd></div>)}
          </dl>
        </div>}
      </div>
      <span id={hintId} className="research-curve__sr">Use Left and Right arrow keys to inspect points, Home and End to jump, or Escape to dismiss.</span>
      <span className="research-curve__sr" aria-live="polite">
        {selection?.keyboard && active ? `${active.time}. ${primaryLabel}: ${String(active.value)}.${
          compared ? ` ${compared.label}: ${String(active.comparedValue)}.` : ""
        }` : ""}
      </span>
    </figure>
  );
}
