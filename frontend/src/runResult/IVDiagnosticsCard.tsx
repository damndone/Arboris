import { formatPValue } from "../format/numbers";
export interface IVDiagnostics {
  identification: "under" | "just" | "over";
  weak_instruments: {
    first_stage_f: number;
    threshold: number;
    caution_threshold?: number;
    verdict: "strong" | "caution" | "weak";
    anderson_rubin_95?: { kind: string; lower?: number; upper?: number } | null;
    message: string;
  };
  endogeneity: {
    test: string;
    statistic: number;
    pvalue: number;
    verdict: "rejects_exogeneity" | "does_not_reject" | "endogenous" | "exogenous";
    message: string;
  };
  overidentification:
    | {
        applicable: true;
        test: string;
        statistic: number;
        pvalue: number;
        verdict: "suspect" | "not_rejected";
        message: string;
      }
    | { applicable: false; verdict: string };
}

function pText(value: number): string {
  const shown = formatPValue(value);
  return shown.startsWith("<") ? `p ${shown}` : `p = ${shown}`;
}

function fmt(v: number, digits = 2): string {
  return Number.isFinite(v) ? v.toFixed(digits) : "—";
}

function identificationLabel(id: IVDiagnostics["identification"]): string {
  if (id === "under") return "under-identified";
  if (id === "just") return "just-identified";
  return "over-identified";
}

export function IVDiagnosticsCard(props: {
  diagnostics: IVDiagnostics | undefined;
}): JSX.Element | null {
  const d = props.diagnostics;
  if (!d) return null;
  const overid = d.overidentification;
  return (
    <section className="ios-card iv-diagnostics" aria-label="IV diagnostics">
      <div className="ios-card-title">
        🎯 IV diagnostics
        <span
          className={`iv-badge iv-id-${d.identification}`}
          aria-label="IV identification"
        >
          {identificationLabel(d.identification)}
        </span>
      </div>
      <ul className="ios-metric-list">
        <li className="iv-row">
          <span>
            First-stage F = {fmt(d.weak_instruments.first_stage_f)}{" "}
            (thresholds {fmt(d.weak_instruments.threshold, 0)}{d.weak_instruments.caution_threshold ? ` / ${d.weak_instruments.caution_threshold}` : ""})
          </span>
          <strong className={`iv-badge iv-wi-${d.weak_instruments.verdict}`}>
            {d.weak_instruments.verdict}
          </strong>
        </li>
        <li className="iv-message">{d.weak_instruments.message}</li>
        {d.weak_instruments.anderson_rubin_95?.kind === "interval" ? (
          <li data-testid="iv-anderson-rubin">
            Anderson–Rubin 95% set: [{fmt(d.weak_instruments.anderson_rubin_95.lower ?? NaN)},{" "}
            {fmt(d.weak_instruments.anderson_rubin_95.upper ?? NaN)}]
          </li>
        ) : null}
        <li className="iv-row">
          <span>
            Wu-Hausman stat={fmt(d.endogeneity.statistic)} {pText(d.endogeneity.pvalue)}
          </span>
          <strong className={`iv-badge iv-endo-${d.endogeneity.verdict}`}>
            {d.endogeneity.verdict}
          </strong>
        </li>
        <li className="iv-message">{d.endogeneity.message}</li>
        {overid.applicable ? (
          <>
            <li className="iv-row">
              <span>
                Sargan stat={fmt(overid.statistic)} {pText(overid.pvalue)}
              </span>
              <strong className={`iv-badge iv-overid-${overid.verdict}`}>
                {overid.verdict}
              </strong>
            </li>
            <li className="iv-message">{overid.message}</li>
          </>
        ) : (
          <li className="iv-message">{overid.verdict}</li>
        )}
      </ul>
    </section>
  );
}
