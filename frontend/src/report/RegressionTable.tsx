import type { CoefficientRecord, ModelResult } from "../api";
import { formatEstimate, formatInterval, formatPValue } from "../format/numbers";

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
  /** Present when the columns are the groups of one by-group run. */
  byGroup?: string[];
};

type DifferenceTest = { label?: string; statistic?: number; df_num?: number; df_den?: number | null; p_value?: number; distribution?: string; status?: string };
type ByGroupBlock = {
  column?: string;
  key?: string;
  n_groups?: number;
  not_estimable?: Array<{ key?: string; nobs?: number; reason?: string }>;
  difference_tests?: { status?: string; reason?: string; reference_group?: string; tests?: DifferenceTest[] };
};

/** What a reader of separate groups' columns must also see: the groups left out, and the tests of a difference. */
function byGroupNotes(modelResults: readonly ModelResult[]): string[] | null {
  const block = (modelResults.find((model) => (model as { by_group?: unknown }).by_group) as { by_group?: ByGroupBlock } | undefined)?.by_group;
  if (!block?.column) return null;
  const notes = [
    `Estimated separately for each group of ${block.column} (${modelResults.length} of ${block.n_groups ?? modelResults.length} groups). Columns side by side are not a test of a difference.`,
  ];
  for (const item of block.not_estimable ?? []) {
    notes.push(`Not estimated: ${block.column} = ${item.key} (${item.nobs} rows): ${item.reason}`);
  }
  const differences = block.difference_tests;
  if (differences?.status === "estimated") {
    for (const test of differences.tests ?? []) {
      if (test.statistic === undefined) continue;
      const df = test.distribution === "F" ? `F(${test.df_num}, ${test.df_den})` : `χ²(${test.df_num})`;
      notes.push(`Group difference — ${test.label}: ${df} = ${formatEstimate(test.statistic)}, p ${formatPValue(test.p_value).startsWith("<") ? "" : "= "}${formatPValue(test.p_value)}`);
    }
  } else if (differences?.reason) {
    notes.push(`Group-difference test not available: ${differences.reason}`);
  }
  return notes;
}

/** A by-group result's header names its group: "ols [language = English]". */
function groupedLabel(label: string, model: object): string {
  const block = (model as { by_group?: { column?: string; key?: string } }).by_group;
  return block?.column ? `${label} [${block.column} = ${block.key ?? ""}]` : label;
}

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
      label: groupedLabel(labeledModel.model_label || model.model_type || id, model),
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

  const byGroup = byGroupNotes(modelResults);
  return {
    payload_schema: "workbench.regression-table",
    schema_version: 1,
    models,
    ...(byGroup ? { byGroup } : {}),
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

function displayInterval(cell: RegressionCell): string {
  return formatInterval(cell.ci_lower, cell.ci_upper);
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
                    {cell ? formatEstimate(cell.estimate) : "—"}{cell?.significance ? ` ${cell.significance}` : ""}
                    {cell?.source_id && (
                      <small style={{ display: "block", color: "var(--label-tertiary)" }}>
                        source: {cell.source_id}
                      </small>
                    )}
                  </td>,
                  <td key={`${model.id}-${row.term}-se`} style={{ padding: "2px 10px" }}>{cell ? formatEstimate(cell.std_error) : "—"}</td>,
                  <td key={`${model.id}-${row.term}-p`} style={{ padding: "2px 10px" }}>{cell ? formatPValue(cell.p_value) : "—"}</td>,
                  <td key={`${model.id}-${row.term}-ci`} style={{ padding: "2px 10px" }}>{cell ? displayInterval(cell) : "—"}</td>,
                ];
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {packet.byGroup ? (
        <div data-testid="regression-by-group" role="note" style={{ fontSize: 11, color: "var(--label-secondary)", marginTop: 6 }}>
          {packet.byGroup.map((note) => (
            <div key={note}>{note}</div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
