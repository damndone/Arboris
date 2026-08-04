import type { CoefficientRecord, ModelResult } from "../api";

export type SignificanceLevels = Record<string, number>;

export const DEFAULT_SIGNIFICANCE_LEVELS: SignificanceLevels = {
  "***": 0.01,
  "**": 0.05,
  "*": 0.1,
};

export type RegressionCell = CoefficientRecord & {
  significance: string;
};

export type RegressionTablePacket = {
  payload_schema: "workbench.regression-table";
  schema_version: 1;
  models: Array<{
    id: string;
    label: string;
    nobs?: number;
    r_squared?: number | null;
  }>;
  rows: Array<{
    term: string;
    label: string;
    models: Record<string, RegressionCell | null>;
  }>;
  significance: {
    cutoffs: SignificanceLevels;
    legend: string;
  };
};

export function buildRegressionTablePacket(
  modelResults: readonly ModelResult[],
  significanceLevels: SignificanceLevels = DEFAULT_SIGNIFICANCE_LEVELS,
  variableLabels: Readonly<Record<string, string>> = {},
): RegressionTablePacket {
  const orderedCutoffs = Object.entries(significanceLevels)
    .map(([marker, cutoff]) => [marker, Number(cutoff)] as const)
    .sort((left, right) => left[1] - right[1]);
  const models = modelResults.map((model) => {
    const labeledModel = model as ModelResult & { model_label?: string };
    const id = model.model_id;
    return {
      id,
      label: labeledModel.model_label || model.model_type || id,
      nobs: model.nobs,
      r_squared: model.r_squared,
    };
  });
  const rowsByTerm = new Map<
    string,
    { term: string; label: string; models: Record<string, RegressionCell | null> }
  >();

  modelResults.forEach((model) => {
    Object.entries(model.coefficients ?? {}).forEach(([term, coefficient]) => {
      const row = rowsByTerm.get(term) ?? {
        term,
        label: variableLabels[term] ?? term,
        models: {},
      };
      row.models[model.model_id] = {
        ...coefficient,
        significance: significanceMarker(coefficient.p_value, orderedCutoffs),
      };
      rowsByTerm.set(term, row);
    });
  });

  return {
    payload_schema: "workbench.regression-table",
    schema_version: 1,
    models,
    rows: [...rowsByTerm.values()].map((row) => ({
      ...row,
      models: Object.fromEntries(
        models.map((model) => [model.id, row.models[model.id] ?? null]),
      ),
    })),
    significance: {
      cutoffs: Object.fromEntries(orderedCutoffs),
      legend: orderedCutoffs
        .map(([marker, cutoff]) => `${marker} p < ${cutoff}`)
        .join("; "),
    },
  };
}

function significanceMarker(
  pValue: number | null | undefined,
  orderedCutoffs: readonly (readonly [string, number])[],
): string {
  if (pValue === null || pValue === undefined || !Number.isFinite(pValue)) {
    return "";
  }
  return orderedCutoffs.find(([, cutoff]) => pValue < cutoff)?.[0] ?? "";
}

function displayValue(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : String(value);
}

function displayInterval(cell: RegressionCell): string {
  if (cell.ci_lower === null || cell.ci_lower === undefined
    || cell.ci_upper === null || cell.ci_upper === undefined) {
    return "—";
  }
  return `[${cell.ci_lower}, ${cell.ci_upper}]`;
}

export function RegressionTable({
  packet,
}: {
  packet: RegressionTablePacket;
}) {
  if (packet.rows.length === 0) return null;

  return (
    <section aria-label="Regression evidence" data-testid="regression-evidence">
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Regression evidence
      </div>
      <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginBottom: 6 }}>
        Significance: {packet.significance.legend}
      </div>
      <table data-testid="regression-table" style={{ fontSize: 12, borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left", padding: "2px 10px 2px 0" }}>Term</th>
            {packet.models.map((model) => (
              <th
                key={model.id}
                colSpan={4}
                style={{ textAlign: "left", padding: "2px 10px" }}
              >
                {model.label} ({model.id})
              </th>
            ))}
          </tr>
          <tr>
            <th />
            {packet.models.flatMap((model) => [
              <th key={`${model.id}-estimate`} style={{ textAlign: "left", padding: "2px 10px" }}>Estimate</th>,
              <th key={`${model.id}-se`} style={{ textAlign: "left", padding: "2px 10px" }}>Std. error</th>,
              <th key={`${model.id}-p`} style={{ textAlign: "left", padding: "2px 10px" }}>p-value</th>,
              <th key={`${model.id}-ci`} style={{ textAlign: "left", padding: "2px 10px" }}>95% CI</th>,
            ])}
          </tr>
        </thead>
        <tbody>
          {packet.rows.map((row) => (
            <tr key={row.term}>
              <td style={{ padding: "2px 10px 2px 0" }}>{row.label} ({row.term})</td>
              {packet.models.flatMap((model) => {
                const cell = row.models[model.id];
                return [
                  <td key={`${model.id}-${row.term}-estimate`} style={{ padding: "2px 10px" }}>
                    {cell ? displayValue(cell.estimate) : "—"}{cell?.significance ? ` ${cell.significance}` : ""}
                    {cell?.source_id && (
                      <small style={{ display: "block", color: "var(--label-tertiary)" }}>
                        source: {cell.source_id}
                      </small>
                    )}
                  </td>,
                  <td key={`${model.id}-${row.term}-se`} style={{ padding: "2px 10px" }}>{cell ? displayValue(cell.std_error) : "—"}</td>,
                  <td key={`${model.id}-${row.term}-p`} style={{ padding: "2px 10px" }}>{cell ? displayValue(cell.p_value) : "—"}</td>,
                  <td key={`${model.id}-${row.term}-ci`} style={{ padding: "2px 10px" }}>{cell ? displayInterval(cell) : "—"}</td>,
                ];
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
