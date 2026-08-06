import { useState } from "react";

interface CSAggCommon {
  overall: number | null;
  overall_se: number | null;
  overall_pointwise_ci?: number[];
  overall_uniform_band?: number[];
}

interface CSSimpleAgg extends CSAggCommon {
  label_kind: string;
  label: number[];
  estimate: number[];
  se: number[];
}

interface CSDynamicAgg extends CSAggCommon {
  label_kind: "event_time";
  event_time: number[];
  estimate: number[];
  se: number[];
  pointwise_ci: number[][];
  uniform_band: number[][];
  uniform_crit: number;
}

interface CSLabelAgg extends CSAggCommon {
  label_kind: string;
  label: number[];
  estimate: number[];
  se: number[];
  pointwise_ci: number[][];
  uniform_band: number[][];
  uniform_crit: number;
}

interface HonestRow {
  // rm rows use `Mbar`; sd rows use `M`. A degenerate (nan, nan) CI is
  // sanitized to JSON null by the backend (_json_safe); `f` renders null as "—".
  Mbar?: number;
  M?: number;
  lb: number | null;
  ub: number | null;
}

interface HonestTrack {
  status: "ok" | "degraded" | "not_available";
  reason: string | null;
  num_pre?: number;
  num_post?: number;
  mbar_grid?: number[];
  m_grid?: number[];
  scale?: number;
  method?: string;
  post_average?: { results: HonestRow[]; breakdown: number | null };
  per_event_time?: {
    event_time: number;
    results: HonestRow[];
    breakdown: number | null;
  }[];
}

interface HonestDidBlock {
  rm: HonestTrack;
  sd: HonestTrack;
}

export interface CSDiagnostics {
  att_gt: {
    g: number;
    t: number;
    event_time: number;
    att: number | null;
    se: number | null;
    n_treated: number;
    n_control: number;
    valid: boolean;
    warning: string | null;
  }[];
  aggregations: {
    simple: CSSimpleAgg;
    dynamic: CSDynamicAgg;
    group: CSLabelAgg;
    calendar: CSLabelAgg;
  };
  diagnostics: {
    overlap: { ps_min: number | null; ps_max: number | null };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    omitted_cells: any[];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    sample_spec: Record<string, any>;
  };
  honest_did?: HonestDidBlock;
  warnings: string[];
  metadata: {
    // V1.5.8: present as "sun_abraham" on the Sun-Abraham (sa_did) artifact;
    // absent (or another value) on the Callaway-Sant'Anna (cs_did) artifact.
    // Drives the estimator-aware card heading so an SA run is not mislabeled CS.
    estimator?: string;
    control_group: string;
    est_method: string;
    base_period: string;
    anticipation: number;
    covariates: string[];
    cluster_var: string | null;
    cluster_level?: string;
    n_clusters?: number;
    n_units: number;
    n_cohorts: number;
    n_valid_cells: number;
    n_cells: number;
    B: number;
    alpha: number;
    seed: number;
    confidence_level: number;
    band_type: string;
  };
}

export type CSDiagnosticsData =
  | CSDiagnostics
  | { available: false; error: string };

const f = (v: number | null | undefined, d = 3) =>
  v == null ? "—" : v.toFixed(d);

// V1.5.8: Sun-Abraham (sa_did) reuses this card but is a DIFFERENT estimator —
// the heading must say so, not silently read "Callaway-Sant'Anna".
const isSunAbraham = (estimator: string | undefined): boolean =>
  estimator === "sun_abraham";
const cardTitle = (estimator: string | undefined): string =>
  isSunAbraham(estimator)
    ? "Sun-Abraham (interaction-weighted) DID"
    : "Callaway-Sant'Anna DID";

function CSEventStudyChart({ dyn }: { dyn: CSDynamicAgg }) {
  const W = 260,
    H = 90,
    pad = 8;
  const xs = dyn.event_time;
  if (!xs.length) return null;
  const pts0 = xs
    .map((_, i) => ({
      i,
      coef: dyn.estimate[i],
      lo: dyn.uniform_band[i]?.[0],
      hi: dyn.uniform_band[i]?.[1],
    }))
    .filter(
      (p): p is { i: number; coef: number; lo: number; hi: number } =>
        p.coef != null && p.lo != null && p.hi != null,
    );
  if (!pts0.length) return null;
  const all = pts0.flatMap((p) => [p.coef, p.lo, p.hi]);
  const lo = Math.min(...all),
    hi = Math.max(...all);
  const sx = (i: number) =>
    pad + (i / Math.max(xs.length - 1, 1)) * (W - 2 * pad);
  const sy = (v: number) =>
    H - pad - ((v - lo) / Math.max(hi - lo, 1e-9)) * (H - 2 * pad);
  const zeroIdx = xs.findIndex((k) => k >= 0);
  const pts = pts0.map((p) => `${sx(p.i)},${sy(p.coef)}`).join(" ");
  return (
    <svg width={W} height={H} aria-label="cs-event-study-chart">
      <line x1={pad} y1={sy(0)} x2={W - pad} y2={sy(0)} stroke="#ccc" />
      {zeroIdx >= 0 && (
        <line
          x1={sx(zeroIdx)}
          y1={0}
          x2={sx(zeroIdx)}
          y2={H}
          stroke="#f55"
          strokeDasharray="4 3"
        />
      )}
      {pts0.map((p) => (
        <line
          key={p.i}
          x1={sx(p.i)}
          y1={sy(p.lo)}
          x2={sx(p.i)}
          y2={sy(p.hi)}
          stroke="#4a6cf7"
          opacity={0.5}
        />
      ))}
      <polyline points={pts} fill="none" stroke="#4a6cf7" strokeWidth={2} />
    </svg>
  );
}

function LabelTable({
  caption,
  ariaLabel,
  labelHeader,
  labels,
  estimate,
  se,
  band,
}: {
  caption: string;
  ariaLabel: string;
  labelHeader: string;
  labels: number[];
  estimate: number[];
  se: number[];
  band: number[][];
}) {
  if (!labels.length) return null;
  return (
    <table aria-label={ariaLabel}>
      <caption>{caption}</caption>
      <thead>
        <tr>
          <th>{labelHeader}</th>
          <th>Estimate</th>
          <th>SE</th>
          <th>Uniform band</th>
        </tr>
      </thead>
      <tbody>
        {labels.map((k, i) => (
          <tr key={k}>
            <td>{k}</td>
            <td>{f(estimate[i])}</td>
            <td>{f(se[i])}</td>
            <td>
              [{f(band[i]?.[0], 2)}, {f(band[i]?.[1], 2)}]
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HonestDidSensitivityTable({
  caption,
  ariaLabel,
  results,
  breakdown,
  paramKey,
  paramLabel,
}: {
  caption: string;
  ariaLabel: string;
  results: HonestRow[];
  breakdown: number | null;
  paramKey: "Mbar" | "M";
  paramLabel: string;
}) {
  return (
    <div>
      <table aria-label={ariaLabel}>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th>{paramLabel}</th>
            <th>Lower</th>
            <th>Upper</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r, i) => (
            <tr key={i}>
              <td>{f(r[paramKey], 2)}</td>
              <td>{f(r.lb, 2)}</td>
              <td>{f(r.ub, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div>
        Breakdown {paramLabel}:{" "}
        {breakdown == null ? "No breakdown (always contains 0)" : f(breakdown, 2)}
      </div>
    </div>
  );
}

function HonestTrackPanel({
  track,
  kind,
}: {
  track: HonestTrack;
  kind: "rm" | "sd";
}) {
  if (track.status === "not_available") {
    return (
      <div aria-label={`cs-honest-did-${kind}-unavailable`} className="ios-warning">
        {track.reason}
      </div>
    );
  }
  if (track.status === "degraded") {
    return (
      <div aria-label={`cs-honest-did-${kind}-degraded`} className="ios-warning">
        {track.reason}
      </div>
    );
  }
  const paramKey = kind === "rm" ? "Mbar" : "M";
  const paramLabel = kind === "rm" ? "M̄" : "M";
  const heading =
    kind === "rm"
      ? "Relative magnitude restriction (ΔRM, Rambachan-Roth)"
      : "Smoothness restriction (ΔSD) — FLCI fixed-length CI";
  const microcopy =
    kind === "rm"
      ? "The point estimate does not move; a larger M̄ means a weaker parallel-trends assumption. The breakdown M̄ is the largest relative magnitude at which the effect is still significant (CI excludes 0)."
      : "A smoothness restriction (ΔSD) on second differences, reported as an FLCI (fixed-length confidence interval). A larger M is a looser restriction.";
  return (
    <section aria-label={`cs-honest-did-${kind}-panel`}>
      <div className="ios-card-title">{heading}</div>
      <div>{microcopy}</div>
      {track.post_average && (
        <HonestDidSensitivityTable
          caption="Post-treatment average"
          ariaLabel={`cs-honest-did-${kind}-post-average`}
          results={track.post_average.results}
          breakdown={track.post_average.breakdown}
          paramKey={paramKey}
          paramLabel={paramLabel}
        />
      )}
      {(track.per_event_time ?? []).map((pet) => (
        <HonestDidSensitivityTable
          key={pet.event_time}
          caption={`Event time ${pet.event_time}`}
          ariaLabel={`cs-honest-did-${kind}-event-${pet.event_time}`}
          results={pet.results}
          breakdown={pet.breakdown}
          paramKey={paramKey}
          paramLabel={paramLabel}
        />
      ))}
    </section>
  );
}

function HonestDidPanel({ honest }: { honest: HonestDidBlock }) {
  return (
    <section aria-label="cs-honest-did-panel">
      <div className="ios-card-title">honest-DID sensitivity (Rambachan-Roth)</div>
      <HonestTrackPanel track={honest.rm} kind="rm" />
      <HonestTrackPanel track={honest.sd} kind="sd" />
    </section>
  );
}

export function CSDiagnosticsCard({
  diagnostics,
}: {
  diagnostics: CSDiagnosticsData | undefined;
}) {
  const [open, setOpen] = useState(false);
  if (!diagnostics) return null;

  if ("available" in diagnostics && diagnostics.available === false) {
    return (
      <section className="ios-card cs-diagnostics" aria-label="cs-diagnostics">
        <div className="ios-card-title">Callaway-Sant'Anna diagnostics unavailable</div>
        <div className="ios-warning">{diagnostics.error}</div>
      </section>
    );
  }

  const d = diagnostics as CSDiagnostics;
  const agg = d.aggregations;
  // Defensive: a truthy-but-incomplete artifact (e.g. a degraded write that kept
  // `available` unset but dropped aggregation keys) would otherwise throw when we
  // dereference agg.dynamic.event_time below. Render a small fallback instead.
  if (!agg || !agg.simple || !agg.dynamic || !agg.group || !agg.calendar) {
    return (
      <section className="ios-card cs-diagnostics" aria-label="cs-diagnostics">
        <div className="ios-card-title">{cardTitle(d.metadata?.estimator)}</div>
        <div className="ios-warning">Incomplete result</div>
      </section>
    );
  }
  const dyn = agg.dynamic;
  const esOk = dyn.event_time.length > 0;
  const band = agg.simple.overall_uniform_band;
  const m = d.metadata;
  const omittedCount = d.diagnostics?.omitted_cells?.length ?? 0;

  return (
    <section className="ios-card cs-diagnostics" aria-label="cs-diagnostics">
      <div className="ios-card-title">{cardTitle(m.estimator)}</div>

      <div>
        <span>Overall ATT</span>{" "}
        <strong style={{ fontSize: 20 }}>{f(agg.simple.overall, 2)}</strong>{" "}
        <span>SE {f(agg.simple.overall_se, 2)}</span>
        {band && band.length === 2 && (
          <span>
            {" "}
            · uniform band [{f(band[0], 2)}, {f(band[1], 2)}]
          </span>
        )}
      </div>

      <div>
        <span>Event study (dynamic)</span>{" "}
        {esOk ? (
          <CSEventStudyChart dyn={dyn} />
        ) : (
          <span aria-label="cs-event-study-skipped">Event study unavailable</span>
        )}
      </div>

      {d.warnings.length > 0 && (
        <ul aria-label="cs-warnings">
          {d.warnings.map((w, i) => (
            <li key={i} className="ios-warning">
              ⚠ {w}
            </li>
          ))}
        </ul>
      )}

      <button onClick={() => setOpen((v) => !v)}>
        {open ? "▾ Collapse" : "▸ Expand full data"}
      </button>

      {open && (
        <div>
          <LabelTable
            caption="By cohort (group)"
            ariaLabel="cs-group-table"
            labelHeader="Cohort"
            labels={agg.group.label}
            estimate={agg.group.estimate}
            se={agg.group.se}
            band={agg.group.uniform_band}
          />
          <LabelTable
            caption="By calendar period"
            ariaLabel="cs-calendar-table"
            labelHeader="Period"
            labels={agg.calendar.label}
            estimate={agg.calendar.estimate}
            se={agg.calendar.se}
            band={agg.calendar.uniform_band}
          />
          <div>
            Spec: method={m.est_method} · control group={m.control_group} · base period=
            {m.base_period} · units {m.n_units} · cohorts {m.n_cohorts} · valid cells
            {m.n_valid_cells}/{m.n_cells} · omitted cells {omittedCount} · confidence 
            {(m.confidence_level * 100).toFixed(0)}% · band type {m.band_type}
          </div>
          {m.cluster_level && (
            <div aria-label="cs-cluster-level">
              Cluster level:{" "}
              {m.cluster_level === "entity"
                ? "Entity"
                : `${m.cluster_level} · ${m.n_clusters ?? "?"} clusters`}
              （cluster-robust SE）
            </div>
          )}
        </div>
      )}

      {d.honest_did && <HonestDidPanel honest={d.honest_did} />}
    </section>
  );
}
