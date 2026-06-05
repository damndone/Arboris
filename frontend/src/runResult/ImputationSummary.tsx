export interface ImputationSummaryData {
  schema_version: number;
  method: string;
  status: string;
  rows_imputed?: number;
  imputed_columns?: string[];
  input_artifact: string;
  output_artifact: string;
  // method-specific (mice)
  m?: number;
  max_iter?: number;
  [key: string]: unknown;
}

export function ImputationSummary(props: { summary: ImputationSummaryData | undefined }) {
  const s = props.summary;
  if (!s) return null;
  const label = s.method.toUpperCase();
  const cols = s.imputed_columns ?? [];
  return (
    <section className="imputation-summary" aria-label="Imputation summary">
      <div className="imputation-summary-title">💧 Imputation applied ({label})</div>
      <ul className="imputation-summary-list">
        <li>
          Imputed <strong>{s.rows_imputed ?? 0} rows</strong>
          {cols.length > 0 && (
            <>
              {" "}
              across <strong>{cols.length} columns</strong> (
              {cols.map((c, i) => (
                <span key={c}>
                  {i > 0 ? ", " : ""}
                  <code>{c}</code>
                </span>
              ))}
              )
            </>
          )}
        </li>
        {s.method === "mice" && s.m !== undefined && (
          <li>
            <code>iterative</code> · <strong>{s.m}</strong> imputations
            {s.max_iter !== undefined && (
              <>
                {" "}
                · max <strong>{s.max_iter}</strong> iters
              </>
            )}
          </li>
        )}
        <li>
          Model lineage: <strong>{s.output_artifact}</strong>{" "}
          <span className="hint">(stats ran on {s.input_artifact})</span>
        </li>
      </ul>
    </section>
  );
}
