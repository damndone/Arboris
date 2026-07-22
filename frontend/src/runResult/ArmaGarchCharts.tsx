// Inline SVG rendering for the pack's `ts.chart.*` artifacts.
//
// The pack has always persisted thirteen chart artifacts, but nothing drew
// them, so the evidence existed only as JSON. These are dependency-free
// primitives in the same plain-SVG style as the DID/CS cards.
//
// Two honesty rules run through the file. Long series are decimated to keep the
// DOM bounded, and any decimated chart says so rather than silently showing a
// thinned series as if it were complete. Correlograms draw the +-1.96/sqrt(n)
// band so a reader can see which spikes are actually distinguishable from zero.

import { useRef } from "react";

const W = 560;
const H = 180;
const PAD = 28;
const MAX_POINTS = 700;

type Row = Record<string, unknown>;

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Even-stride decimation; the caller reports the reduction to the reader. */
function decimate<T>(items: T[], limit = MAX_POINTS): { points: T[]; kept: boolean } {
  if (items.length <= limit) return { points: items, kept: true };
  const stride = Math.ceil(items.length / limit);
  return { points: items.filter((_, index) => index % stride === 0), kept: false };
}

function extent(values: number[]): [number, number] {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  return lo === hi ? [lo - 1, hi + 1] : [lo, hi];
}

function Frame({
  title,
  note,
  children,
  exportable = true,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
  exportable?: boolean;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const downloadSvg = () => {
    const source = bodyRef.current?.querySelector("svg");
    if (!source) return;
    const svg = source.cloneNode(true) as SVGSVGElement;
    svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const accessibleTitle = document.createElementNS("http://www.w3.org/2000/svg", "title");
    accessibleTitle.textContent = title;
    svg.prepend(accessibleTitle);
    if (note) {
      const description = document.createElementNS("http://www.w3.org/2000/svg", "desc");
      description.textContent = `Displayed data: ${note}.`;
      accessibleTitle.after(description);
    }
    const blob = new Blob([new XMLSerializer().serializeToString(svg)], {
      type: "image/svg+xml;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "chart"}.svg`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };
  return (
    <figure style={{ margin: "12px 0 0" }}>
      <figcaption className="muted" style={{ fontSize: 12, marginBottom: 2, display: "flex", gap: 6 }}>
        <span>
          {title}
          {note ? <span> · {note}</span> : null}
        </span>
        {exportable ? (
          <button
            type="button"
            onClick={downloadSvg}
            aria-label={`Download ${title} SVG`}
            title="Downloads the displayed SVG only; full structured evidence remains in JSON."
          >
            SVG
          </button>
        ) : null}
      </figcaption>
      <div ref={bodyRef} style={{ overflowX: "auto" }}>{children}</div>
    </figure>
  );
}

function EmptyChart({ title, reason }: { title: string; reason: string }) {
  return (
    <Frame title={title} exportable={false}>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        {reason}
      </p>
    </Frame>
  );
}

/** A single-value-per-position line, indexed by row order. */
export function SeriesChart({
  title,
  rows: source,
  valueKey,
  color = "#4a6cf7",
  zeroLine = false,
}: {
  title: string;
  rows: Row[];
  valueKey: string;
  color?: string;
  zeroLine?: boolean;
}) {
  const values = source.map((row) => num(row[valueKey])).filter((v): v is number => v !== null);
  if (values.length < 2) {
    return <EmptyChart title={title} reason="Not enough finite observations to plot." />;
  }
  const { points, kept } = decimate(values);
  const [lo, hi] = extent(points);
  const sx = (i: number) => PAD + (i / Math.max(points.length - 1, 1)) * (W - 2 * PAD);
  const sy = (v: number) => H - PAD - ((v - lo) / (hi - lo)) * (H - 2 * PAD);
  const path = points.map((v, i) => `${sx(i)},${sy(v)}`).join(" ");

  return (
    <Frame
      title={title}
      note={
        kept
          ? `${values.length} observations`
          : `${values.length} observations, drawn every ${Math.ceil(values.length / MAX_POINTS)}th`
      }
    >
      <svg width={W} height={H} aria-label={title} role="img">
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#ccc" />
        {zeroLine && lo < 0 && hi > 0 && (
          <line x1={PAD} y1={sy(0)} x2={W - PAD} y2={sy(0)} stroke="#ccc" strokeDasharray="3 3" />
        )}
        <polyline points={path} fill="none" stroke={color} strokeWidth={1.2} />
        <text x={PAD} y={12} fontSize={10} fill="#8e8e93">
          {hi.toPrecision(4)}
        </text>
        <text x={PAD} y={H - PAD + 12} fontSize={10} fill="#8e8e93">
          {lo.toPrecision(4)}
        </text>
      </svg>
    </Frame>
  );
}

/** Correlogram with the +-1.96/sqrt(n) band, so spikes can be judged. */
export function CorrelogramChart({
  title,
  rows: source,
  observationCount,
}: {
  title: string;
  rows: Row[];
  observationCount: number | null;
}) {
  const bars = source
    .map((row) => ({ lag: num(row.lag), value: num(row.value) }))
    .filter((row): row is { lag: number; value: number } => row.lag !== null && row.value !== null)
    .filter((row) => row.lag > 0);
  if (bars.length === 0) {
    return <EmptyChart title={title} reason="No autocorrelation values were persisted." />;
  }
  const band =
    observationCount && observationCount > 0 ? 1.96 / Math.sqrt(observationCount) : null;
  const magnitudes = bars.map((bar) => Math.abs(bar.value));
  const limit = Math.max(...magnitudes, band ?? 0, 0.1);
  const sx = (i: number) => PAD + (i / Math.max(bars.length - 1, 1)) * (W - 2 * PAD);
  const sy = (v: number) => H / 2 - (v / limit) * (H / 2 - PAD);

  return (
    <Frame
      title={title}
      note={band ? `95% band +-${band.toFixed(3)}` : "95% band unavailable"}
    >
      <svg width={W} height={H} aria-label={title} role="img">
        <line x1={PAD} y1={sy(0)} x2={W - PAD} y2={sy(0)} stroke="#ccc" />
        {band !== null && (
          <>
            <line x1={PAD} y1={sy(band)} x2={W - PAD} y2={sy(band)} stroke="#f55" strokeDasharray="4 3" />
            <line x1={PAD} y1={sy(-band)} x2={W - PAD} y2={sy(-band)} stroke="#f55" strokeDasharray="4 3" />
          </>
        )}
        {bars.map((bar, index) => (
          <line
            key={bar.lag}
            x1={sx(index)}
            y1={sy(0)}
            x2={sx(index)}
            y2={sy(bar.value)}
            stroke={band !== null && Math.abs(bar.value) > band ? "#f55" : "#4a6cf7"}
            strokeWidth={2}
          />
        ))}
      </svg>
    </Frame>
  );
}

/** Standardized-residual QQ plot against the 45-degree reference. */
export function QQChart({ title, rows: source }: { title: string; rows: Row[] }) {
  const pairs = source
    .map((row) => ({
      theoretical: num(row.theoretical_quantile),
      observed: num(row.observed),
    }))
    .filter(
      (row): row is { theoretical: number; observed: number } =>
        row.theoretical !== null && row.observed !== null,
    );
  if (pairs.length < 2) {
    return <EmptyChart title={title} reason="Not enough quantile pairs to plot." />;
  }
  const { points, kept } = decimate(pairs);
  const all = points.flatMap((p) => [p.theoretical, p.observed]);
  const [lo, hi] = extent(all);
  const sx = (v: number) => PAD + ((v - lo) / (hi - lo)) * (W - 2 * PAD);
  const sy = (v: number) => H - PAD - ((v - lo) / (hi - lo)) * (H - 2 * PAD);

  return (
    <Frame
      title={title}
      note={kept ? `${pairs.length} points` : `${pairs.length} points, thinned for display`}
    >
      <svg width={W} height={H} aria-label={title} role="img">
        <line x1={sx(lo)} y1={sy(lo)} x2={sx(hi)} y2={sy(hi)} stroke="#f55" strokeDasharray="4 3" />
        {points.map((p, index) => (
          <circle key={index} cx={sx(p.theoretical)} cy={sy(p.observed)} r={1.3} fill="#4a6cf7" />
        ))}
      </svg>
    </Frame>
  );
}

/** Observed series inside one or two predictive-interval bands. */
export function IntervalBandChart({
  title,
  rows: source,
  observedKey,
  bands,
  markKey,
}: {
  title: string;
  rows: Row[];
  observedKey: string;
  bands: { lowerKey: string; upperKey: string; color: string; label: string }[];
  markKey?: string;
}) {
  const usable = source.filter((row) => num(row[observedKey]) !== null);
  if (usable.length < 2) {
    return <EmptyChart title={title} reason="No observations with a finite value." />;
  }
  const { points, kept } = decimate(usable);
  const values = points.flatMap((row) =>
    [
      num(row[observedKey]),
      ...bands.flatMap((band) => [num(row[band.lowerKey]), num(row[band.upperKey])]),
    ].filter((v): v is number => v !== null),
  );
  const [lo, hi] = extent(values);
  const sx = (i: number) => PAD + (i / Math.max(points.length - 1, 1)) * (W - 2 * PAD);
  const sy = (v: number) => H - PAD - ((v - lo) / (hi - lo)) * (H - 2 * PAD);
  const line = (key: string) =>
    points
      .map((row, index) => {
        const value = num(row[key]);
        return value === null ? null : `${sx(index)},${sy(value)}`;
      })
      .filter((point): point is string => point !== null)
      .join(" ");

  return (
    <Frame
      title={title}
      note={[
        kept ? `${usable.length} origins` : `${usable.length} origins, thinned for display`,
        ...bands.map((band) => band.label),
      ].join(" · ")}
    >
      <svg width={W} height={H} aria-label={title} role="img">
        {bands.map((band) => (
          <g key={band.label}>
            <polyline points={line(band.lowerKey)} fill="none" stroke={band.color} strokeWidth={1} opacity={0.75} />
            <polyline points={line(band.upperKey)} fill="none" stroke={band.color} strokeWidth={1} opacity={0.75} />
          </g>
        ))}
        <polyline points={line(observedKey)} fill="none" stroke="#1c1c1e" strokeWidth={1.2} />
        {markKey &&
          points.map((row, index) => {
            const value = num(row[observedKey]);
            if (value === null || row[markKey] !== true) return null;
            return <circle key={index} cx={sx(index)} cy={sy(value)} r={2.6} fill="#f55" />;
          })}
      </svg>
    </Frame>
  );
}

/** Two series on independent scales; neither may be read against the other's axis. */
export function DualAxisChart({
  title,
  rows: source,
  leftKey,
  rightKey,
  leftLabel,
  rightLabel,
}: {
  title: string;
  rows: Row[];
  leftKey: string;
  rightKey: string;
  leftLabel: string;
  rightLabel: string;
}) {
  const usable = source.filter(
    (row) => num(row[leftKey]) !== null && num(row[rightKey]) !== null,
  );
  if (usable.length < 2) {
    return <EmptyChart title={title} reason="No observations with both series finite." />;
  }
  const { points, kept } = decimate(usable);
  const [leftLo, leftHi] = extent(points.map((row) => num(row[leftKey]) as number));
  const [rightLo, rightHi] = extent(points.map((row) => num(row[rightKey]) as number));
  const sx = (i: number) => PAD + (i / Math.max(points.length - 1, 1)) * (W - 2 * PAD);
  const project = (v: number, lo: number, hi: number) =>
    H - PAD - ((v - lo) / (hi - lo)) * (H - 2 * PAD);
  const line = (key: string, lo: number, hi: number) =>
    points
      .map((row, index) => `${sx(index)},${project(num(row[key]) as number, lo, hi)}`)
      .join(" ");

  return (
    <Frame
      title={title}
      note={`${leftLabel} (left) vs ${rightLabel} (right)${kept ? "" : ", thinned for display"} · independent scales`}
    >
      <svg width={W} height={H} aria-label={title} role="img">
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#ccc" />
        <polyline
          points={line(leftKey, leftLo, leftHi)}
          fill="none"
          stroke="#8e8e93"
          strokeWidth={1}
          opacity={0.8}
        />
        <polyline
          points={line(rightKey, rightLo, rightHi)}
          fill="none"
          stroke="#f55"
          strokeWidth={1.4}
        />
      </svg>
    </Frame>
  );
}
