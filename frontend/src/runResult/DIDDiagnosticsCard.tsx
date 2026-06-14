import { useState } from "react";

export interface DIDDiagnostics {
  att: { estimate: number; std_error: number; pvalue: number; ci: [number, number];
    spec: string; covariance: string };
  event_study: { applicable: boolean; message?: string; event_time: number[];
    coef: (number | null)[]; se: (number | null)[]; ci_lower: (number | null)[];
    ci_upper: (number | null)[]; ref_period: number };
  parallel_trends: { test: string; statistic: number | null; pvalue: number | null;
    n_pre_leads: number; verdict: "not_rejected" | "rejected"; message: string };
  goodman_bacon: { applicable: boolean; message?: string;
    components: { type: string; weight: number; estimate: number }[];
    weighted_avg: number | null; forbidden_weight: number | null };
  spec: { entity: string; time: string; cohort: string; n_treated_units: number;
    n_never_treated: number; staggered: boolean; mode: string };
  interpretation_restriction?: string;
}

function EventStudyChart({ es }: { es: DIDDiagnostics["event_study"] }) {
  const W = 260, H = 90, pad = 8;
  const xs = es.event_time;
  if (!xs.length) return null;
  // Only keep indices where coef + both CI bounds are non-null.
  const pts0 = xs
    .map((_, i) => ({ i, coef: es.coef[i], lo: es.ci_lower[i], hi: es.ci_upper[i] }))
    .filter((p): p is { i: number; coef: number; lo: number; hi: number } =>
      p.coef != null && p.lo != null && p.hi != null);
  if (!pts0.length) return null;
  const all = pts0.flatMap((p) => [p.coef, p.lo, p.hi]);
  const lo = Math.min(...all), hi = Math.max(...all);
  const sx = (i: number) => pad + (i / Math.max(xs.length - 1, 1)) * (W - 2 * pad);
  const sy = (v: number) => H - pad - ((v - lo) / Math.max(hi - lo, 1e-9)) * (H - 2 * pad);
  const zeroIdx = xs.findIndex((k) => k >= 0);
  const pts = pts0.map((p) => `${sx(p.i)},${sy(p.coef)}`).join(" ");
  return (
    <svg width={W} height={H} aria-label="did-event-study-chart">
      <line x1={pad} y1={sy(0)} x2={W - pad} y2={sy(0)} stroke="#ccc" />
      {zeroIdx >= 0 && <line x1={sx(zeroIdx)} y1={0} x2={sx(zeroIdx)} y2={H}
        stroke="#f55" strokeDasharray="4 3" />}
      {pts0.map((p) => (
        <line key={p.i} x1={sx(p.i)} y1={sy(p.lo)} x2={sx(p.i)} y2={sy(p.hi)}
          stroke="#4a6cf7" opacity={0.5} />
      ))}
      <polyline points={pts} fill="none" stroke="#4a6cf7" strokeWidth={2} />
    </svg>
  );
}

const f = (v: number | null, d = 3) => (v == null ? "—" : v.toFixed(d));

export function DIDDiagnosticsCard({ diagnostics }: { diagnostics: DIDDiagnostics | undefined }) {
  const [open, setOpen] = useState(false);
  const d = diagnostics;
  if (!d) return null;
  const esOk = d.event_study.applicable !== false && d.event_study.event_time.length > 0;
  const baconOk = d.goodman_bacon.applicable !== false;
  const ptColor = d.parallel_trends.verdict === "not_rejected" ? "#137a3a" : "#c0392b";
  const ptText = d.parallel_trends.verdict === "not_rejected" ? "未拒绝" : "已拒绝";
  return (
    <section className="ios-card did-diagnostics" aria-label="did-diagnostics">
      <div className="ios-card-title">DID 诊断</div>
      <div>
        <span>ATT</span>{" "}
        <strong style={{ fontSize: 20 }}>{d.att.estimate.toFixed(2)}</strong>{" "}
        <span>SE {d.att.std_error.toFixed(2)} · p {d.att.pvalue.toFixed(3)} · 95%CI
          [{d.att.ci[0].toFixed(2)}, {d.att.ci[1].toFixed(2)}]</span>
      </div>

      <div>
        <span>事件研究</span>{" "}
        {esOk ? <EventStudyChart es={d.event_study} />
              : <span aria-label="did-event-study-skipped">事件研究不可识别(单一处理时点或缺少参照期)</span>}
      </div>

      <div>
        平行趋势 <span style={{ color: ptColor }}>{ptText}</span>
        {d.parallel_trends.pvalue != null && <> (p={d.parallel_trends.pvalue.toFixed(3)})</>}
      </div>

      <div>
        Goodman-Bacon{" "}
        {baconOk && d.goodman_bacon.forbidden_weight != null
          ? <>坏比较权重 {(d.goodman_bacon.forbidden_weight * 100).toFixed(0)}% · 加权均值 {(d.goodman_bacon.weighted_avg ?? 0).toFixed(2)}</>
          : <span>不可用</span>}
      </div>

      <button onClick={() => setOpen((v) => !v)}>{open ? "▾ 收起" : "▸ 展开完整数据"}</button>

      {open && (
        <div>
          {esOk && (
            <table aria-label="did-event-study-table">
              <thead><tr><th>event_time</th><th>coef</th><th>se</th><th>95% CI</th></tr></thead>
              <tbody>
                {d.event_study.event_time.map((k, i) => (
                  <tr key={k}>
                    <td>{k}</td><td>{f(d.event_study.coef[i])}</td>
                    <td>{f(d.event_study.se[i])}</td>
                    <td>[{f(d.event_study.ci_lower[i], 2)}, {f(d.event_study.ci_upper[i], 2)}]</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {baconOk && (
            <table aria-label="did-bacon-table">
              <thead><tr><th>比较类型</th><th>权重</th><th>估计</th></tr></thead>
              <tbody>
                {d.goodman_bacon.components.map((c, i) => (
                  <tr key={i}><td>{c.type}</td><td>{c.weight.toFixed(2)}</td>
                    <td>{c.estimate.toFixed(2)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          <div>规格: entity={d.spec.entity} · time={d.spec.time} · 处理单位
            {d.spec.n_treated_units} · 从不处理 {d.spec.n_never_treated} · 错位
            {d.spec.staggered ? "是" : "否"}</div>
          {d.interpretation_restriction && (
            <div role="note" style={{ borderLeft: "3px solid #f0a020", paddingLeft: 8 }}>
              ⚠ {d.interpretation_restriction}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
