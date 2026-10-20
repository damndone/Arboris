import { formatPValue } from "../format/numbers";
export interface IVDiagnostics {
  identification: "under" | "just" | "over";
  weak_instruments: {
    first_stage_f: number | null;
    first_stage_statistic?: number;
    reference_distribution?: string;
    test?: string;
    threshold: number | null;
    caution_threshold?: number | null;
    verdict: "strong" | "caution" | "weak" | "unassessed";
    anderson_rubin_95?: ARSet | null;
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

interface ARSet {
  kind: string;
  lower?: number;
  upper?: number;
  reason?: string;
  global_certification?: { status: string };
  components?: { lower: number | null; upper: number | null; lower_closed: boolean; upper_closed: boolean }[];
}

function arText(set: ARSet): string {
  if (set.kind === "unavailable") return "unavailable: " + (({
    singular_covariance_on_real_line: "the test covariance is singular at some parameter values",
    outside_exact_certification_envelope: "this design is outside the validated inversion scope",
    unsupported_covariance_for_ar: "a compatible test for this covariance has not been validated",
    weighted_ar_not_validated: "weighted inference has not been validated",
    multiple_endogenous_regressors: "a scalar confidence set requires one endogenous regressor",
    rank_deficient_auxiliary_design: "the auxiliary design is rank deficient",
  } as Record<string, string>)[set.reason ?? ""] ?? "inference has not been validated");
  let region: string;
  if (set.kind === "whole_line") region = "the whole real line";
  else if (set.kind === "empty") region = "empty";
  else if (set.components) region = set.components.map(c =>
    `${c.lower_closed ? "[" : "("}${c.lower === null ? "−∞" : fmt(c.lower, 6)}, ${c.upper === null ? "+∞" : fmt(c.upper, 6)}${c.upper_closed ? "]" : ")"}`).join(" ∪ ");
  else if (set.kind === "interval") region = `[${fmt(set.lower ?? NaN, 6)}, ${fmt(set.upper ?? NaN, 6)}]`;
  else region = "see the recorded confidence-set details";
  return region + (set.global_certification?.status === "certified"
    ? ". Global inversion verified; coverage still requires the model assumptions."
    : ". Global inversion unverified.");
}

function testLabel(name: string): string {
  return ({ wu_hausman: "Wu-Hausman", wooldridge_regression: "Wooldridge exogeneity",
    sargan: "Sargan (homoskedastic)", wooldridge_overid: "Wooldridge robust score" } as Record<string, string>)[name] ?? name;
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
            First-stage {d.weak_instruments.test === "wald_chi2" ? "Wald χ²" : "F"} = {fmt(d.weak_instruments.first_stage_statistic ?? d.weak_instruments.first_stage_f ?? NaN)}{" "}
            {d.weak_instruments.reference_distribution}
            {d.weak_instruments.threshold !== null ? ` (thresholds ${fmt(d.weak_instruments.threshold, 0)}${d.weak_instruments.caution_threshold ? ` / ${d.weak_instruments.caution_threshold}` : ""})` : ""}
          </span>
          <strong className={`iv-badge iv-wi-${d.weak_instruments.verdict}`}>
            {d.weak_instruments.verdict}
          </strong>
        </li>
        <li className="iv-message">{d.weak_instruments.message}</li>
        {d.weak_instruments.anderson_rubin_95 ? (
          <li data-testid="iv-anderson-rubin">
            Anderson–Rubin 95% set: {arText(d.weak_instruments.anderson_rubin_95)}
          </li>
        ) : null}
        <li className="iv-row">
          <span>
            {testLabel(d.endogeneity.test)} stat={fmt(d.endogeneity.statistic)} {pText(d.endogeneity.pvalue)}
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
                {testLabel(overid.test)} stat={fmt(overid.statistic)} {pText(overid.pvalue)}
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
