export interface IVDiagnostics {
  identification: "under" | "just" | "over";
  weak_instruments: {
    first_stage_f: number;
    threshold: number;
    verdict: "strong" | "weak";
    message: string;
  };
  endogeneity: {
    test: string;
    statistic: number;
    pvalue: number;
    verdict: "endogenous" | "exogenous";
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
            (threshold {fmt(d.weak_instruments.threshold)})
          </span>
          <strong className={`iv-badge iv-wi-${d.weak_instruments.verdict}`}>
            {d.weak_instruments.verdict}
          </strong>
        </li>
        <li className="iv-message">{d.weak_instruments.message}</li>
        <li className="iv-row">
          <span>
            Wu-Hausman stat={fmt(d.endogeneity.statistic)} p=
            {fmt(d.endogeneity.pvalue, 3)}
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
                Sargan stat={fmt(overid.statistic)} p={fmt(overid.pvalue, 3)}
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
