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
  warnings: string[];
  metadata: {
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
          <th>估计</th>
          <th>SE</th>
          <th>一致带</th>
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
        <div className="ios-card-title">Callaway-Sant'Anna 诊断不可用</div>
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
        <div className="ios-card-title">Callaway-Sant'Anna DID</div>
        <div className="ios-warning">结果不完整</div>
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
      <div className="ios-card-title">Callaway-Sant'Anna DID</div>

      <div>
        <span>总体 ATT</span>{" "}
        <strong style={{ fontSize: 20 }}>{f(agg.simple.overall, 2)}</strong>{" "}
        <span>SE {f(agg.simple.overall_se, 2)}</span>
        {band && band.length === 2 && (
          <span>
            {" "}
            · 一致带 [{f(band[0], 2)}, {f(band[1], 2)}]
          </span>
        )}
      </div>

      <div>
        <span>事件研究 (动态)</span>{" "}
        {esOk ? (
          <CSEventStudyChart dyn={dyn} />
        ) : (
          <span aria-label="cs-event-study-skipped">事件研究不可用</span>
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
        {open ? "▾ 收起" : "▸ 展开完整数据"}
      </button>

      {open && (
        <div>
          <LabelTable
            caption="按队列 (group)"
            ariaLabel="cs-group-table"
            labelHeader="队列"
            labels={agg.group.label}
            estimate={agg.group.estimate}
            se={agg.group.se}
            band={agg.group.uniform_band}
          />
          <LabelTable
            caption="按日历期 (calendar)"
            ariaLabel="cs-calendar-table"
            labelHeader="期"
            labels={agg.calendar.label}
            estimate={agg.calendar.estimate}
            se={agg.calendar.se}
            band={agg.calendar.uniform_band}
          />
          <div>
            规格: 估计法={m.est_method} · 对照组={m.control_group} · 基期=
            {m.base_period} · 单位数 {m.n_units} · 队列数 {m.n_cohorts} · 有效格
            {m.n_valid_cells}/{m.n_cells} · 省略格 {omittedCount} · 置信度
            {(m.confidence_level * 100).toFixed(0)}% · 带类型 {m.band_type}
          </div>
          {m.cluster_level && (
            <div aria-label="cs-cluster-level">
              聚类层级:{" "}
              {m.cluster_level === "entity"
                ? "实体 (entity)"
                : `${m.cluster_level} · ${m.n_clusters ?? "?"} 簇`}
              （cluster-robust SE）
            </div>
          )}
        </div>
      )}
    </section>
  );
}
