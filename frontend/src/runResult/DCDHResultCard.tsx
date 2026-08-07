// de Chaisemartin-D'Haultfoeuille (dcdh) result card. Renders the dynamic event
// study (placebos + effects), the sup-t uniform band, per-event-time switcher
// counts, the EXPERIMENTAL overall ATT, and sample diagnostics. It deliberately
// does NOT render a Honest-DID block — dcdh's native pre-trend tool is its
// placebos (honest_did_supported is false this version).

export interface DCDHEventStudy {
  label_kind: string;
  event_time: number[];
  estimate: number[];
  se: (number | null)[];
  pointwise_ci: [number, number][];
  uniform_band: [number, number][];
  uniform_crit: number | null;
  kind: string[]; // "placebo" | "effect"
  n_switchers: number[];
}

export interface DCDHResult {
  estimator: string;
  event_study: DCDHEventStudy;
  overall_att: { estimate: number | null; se: number | null; experimental: boolean };
  diagnostics: {
    excluded_units?: (number | string)[];
    sample?: Record<string, unknown>;
    risk_set_by_ell?: Record<string, unknown>[];
  };
  honest_did: unknown;
  honest_did_supported: boolean;
  interpretation_restrictions?: string[];
}

function fmt(x: number | null | undefined): string {
  return x === null || x === undefined || Number.isNaN(x) ? "—" : x.toFixed(4);
}

export function DCDHResultCard(props: { result?: DCDHResult }) {
  const { result } = props;
  if (!result) return null;
  const es = result.event_study;
  const oa = result.overall_att;

  return (
    <section className="diagnostics-card" aria-label="dCDH event study">
      <h3 className="subhead">de Chaisemartin-D'Haultfœuille DID (non-absorbing — dynamic event study)</h3>

      <table className="diagnostics-table" aria-label="dcdh-event-study-table">
        <thead>
          <tr>
            <th>Event time</th>
            <th>Kind</th>
            <th>Estimate</th>
            <th>SE</th>
            <th>Uniform band (sup-t)</th>
            <th>switchers</th>
          </tr>
        </thead>
        <tbody>
          {es.event_time.map((ev, i) => (
            <tr key={ev} className={es.kind[i] === "placebo" ? "dcdh-placebo-row" : "dcdh-effect-row"}>
              <td>{ev}</td>
              <td>{es.kind[i] === "placebo" ? "placebo (pre-trend)" : "effect"}</td>
              <td>{fmt(es.estimate[i])}</td>
              <td>{fmt(es.se[i])}</td>
              <td>
                [{fmt(es.uniform_band[i]?.[0])}, {fmt(es.uniform_band[i]?.[1])}]
              </td>
              <td>{es.n_switchers[i]}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="dcdh-overall" aria-label="dcdh-overall-att">
        Overall ATT: {fmt(oa.estimate)} (SE {fmt(oa.se)}）
        {oa.experimental && (
          <span className="ios-badge" aria-label="dcdh-experimental"> experimental</span>
        )}
      </div>

      {result.diagnostics.excluded_units && result.diagnostics.excluded_units.length > 0 && (
        <div className="ios-hint" aria-label="dcdh-excluded">
          Units excluded for baseline=1: {result.diagnostics.excluded_units.length}
        </div>
      )}

      {result.interpretation_restrictions?.map((r, i) => (
        <div className="ios-warning" role="note" key={i}>{r}</div>
      ))}

      {/* Honest-DID intentionally NOT rendered: dcdh uses placebos for pre-trends. */}
      {result.honest_did_supported && (
        <div aria-label="dcdh-honest-did">Honest-DID</div>
      )}
    </section>
  );
}
