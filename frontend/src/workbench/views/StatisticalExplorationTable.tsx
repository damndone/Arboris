import type { ArtifactItem } from "../../api";

type ExplorationPayload = {
  item: ArtifactItem;
  payload: unknown;
};

type TableCell = string | number | boolean | null | undefined;

function scalar(value: unknown): TableCell {
  if (value === null || value === undefined || typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value as TableCell;
  }
  return JSON.stringify(value);
}

/** Seven significant digits, as the Data view shows numbers; the full values
 *  stay in the saved artifact and reach the Agent unrounded. */
function shown(value: number): number {
  return Number.isInteger(value) ? value : Number(value.toPrecision(7));
}

const OPERATION_TITLES: Record<string, string> = {
  summarize: "Summarize",
  summarize_detail: "Summarize detail",
  misstable: "Missing values",
  tabulate: "Frequencies",
  corr: "Correlation",
  derive_boolean: "Derived percentile variable",
};

const STATISTIC_LABELS: Record<string, string> = {
  obs: "Obs",
  mean: "Mean",
  std_dev: "Std. dev.",
  min: "Min",
  max: "Max",
  variance: "Variance",
  sum: "Sum",
  skewness: "Skewness",
  kurtosis: "Kurtosis",
  smallest: "Smallest 4",
  largest: "Largest 4",
  missing: "Missing",
  nonmissing: "Non-missing",
};

/** One variable's statistics as table cells: numbers rounded for reading,
 *  the percentile grid spread into its own columns (p1 ... p99), the four
 *  smallest and largest values as a list, and the percentile method left to
 *  the caption instead of repeated in every row. */
function statisticCells(value: Record<string, unknown>): Record<string, TableCell> {
  const cells: Record<string, TableCell> = {};
  for (const [key, cell] of Object.entries(value)) {
    if (key === "quantile_method") continue;
    if (key === "percentiles" && cell && typeof cell === "object" && !Array.isArray(cell)) {
      for (const [name, number] of Object.entries(cell as Record<string, unknown>)) {
        cells[name] = typeof number === "number" ? shown(number) : scalar(number);
      }
      continue;
    }
    const label = STATISTIC_LABELS[key] ?? key;
    if (Array.isArray(cell)) {
      cells[label] = cell.map((item) => (typeof item === "number" ? shown(item) : String(item))).join(", ");
    } else {
      cells[label] = typeof cell === "number" ? shown(cell) : scalar(cell);
    }
  }
  return cells;
}

function usesStataPercentiles(result: Record<string, unknown>): boolean {
  return JSON.stringify(result).includes("stata_summarize_detail");
}

function resultOf(payload: unknown): Record<string, unknown> {
  if (!payload || typeof payload !== "object") return {};
  const record = payload as Record<string, unknown>;
  return record.result && typeof record.result === "object"
    ? record.result as Record<string, unknown>
    : record;
}

/** `corr` returns `variables` as a list, so the mapping branches below skip it.
 *  Without this the matrix reached the table as "available as the downloadable
 *  artifact" and the correlations were unreadable in the product. */
function correlationRowsOf(result: Record<string, unknown>): Array<Record<string, TableCell>> | null {
  const variables = result.variables;
  const matrix = result.matrix;
  if (!Array.isArray(variables) || !Array.isArray(matrix)) return null;
  if (matrix.length !== variables.length) return null;
  const names = variables.map((name) => String(name));
  return names.map((name, index) => {
    const row = matrix[index];
    const entry: Record<string, TableCell> = { variable: name };
    names.forEach((column, position) => {
      const cell = Array.isArray(row) ? row[position] : null;
      entry[column] = typeof cell === "number" ? Number(cell.toFixed(4)) : scalar(cell);
    });
    return entry;
  });
}

function rowsOf(result: Record<string, unknown>): Array<Record<string, TableCell>> {
  const correlation = correlationRowsOf(result);
  if (correlation) return correlation;
  // Frequency tables (tabulate) arrive as one flat row per variable value.
  if (Array.isArray(result.rows)) {
    return result.rows
      .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object")
      .map((row) => Object.fromEntries(
        Object.entries(row).map(([key, cell]) => [key, key === "value" && cell === null ? "(missing)" : scalar(cell)]),
      ));
  }
  const groups = Array.isArray(result.groups) ? result.groups : [];
  if (groups.length > 0) {
    return groups.flatMap((group) => {
      if (!group || typeof group !== "object") return [];
      const groupRecord = group as Record<string, unknown>;
      const variables = groupRecord.variables;
      if (!variables || typeof variables !== "object" || Array.isArray(variables)) {
        return [{ group: scalar(groupRecord.value), rows: scalar(groupRecord.filtered_row_count) }];
      }
      return Object.entries(variables as Record<string, unknown>).map(([variable, value]) => ({
        group: scalar(groupRecord.value),
        rows: scalar(groupRecord.filtered_row_count),
        variable,
        ...(value && typeof value === "object" && !Array.isArray(value)
          ? statisticCells(value as Record<string, unknown>)
          : { value: scalar(value) }),
      }));
    });
  }

  const variables = result.variables;
  if (variables && typeof variables === "object" && !Array.isArray(variables)) {
    return Object.entries(variables as Record<string, unknown>).map(([variable, value]) => ({
      variable,
      ...(value && typeof value === "object" && !Array.isArray(value)
        ? statisticCells(value as Record<string, unknown>)
        : { value: scalar(value) }),
    }));
  }

  return [];
}

function ExplorationResultTable({ payload }: { payload: ExplorationPayload }) {
  const result = resultOf(payload.payload);
  const rows = rowsOf(result);
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const groupCount = Array.isArray(result.groups) ? result.groups.length : 0;
  const sourceRows = typeof result.source_row_count === "number" ? result.source_row_count : null;
  const filteredRows = typeof result.filtered_row_count === "number" ? result.filtered_row_count : null;

  return (
    <div data-testid={`statistical-exploration-table-${payload.item.artifact_id}`} style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label)", marginBottom: 4 }}>
        {OPERATION_TITLES[String(result.operation)] ?? String(result.operation ?? "Statistical exploration")}
      </div>
      <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginBottom: 8 }}>
        {sourceRows !== null ? `${sourceRows} source rows` : null}
        {filteredRows !== null ? ` · ${filteredRows} rows after filters` : null}
        {groupCount > 0 ? ` · ${groupCount} groups` : null}
        {usesStataPercentiles(result) ? " · percentiles as Stata's summarize, detail" : null}
        {Array.isArray(result.non_numeric_columns) && result.non_numeric_columns.length > 0
          ? ` · not summarised (not numeric): ${result.non_numeric_columns.join(", ")}`
          : null}
      </div>
      {rows.length > 0 ? (
        <div
          className="wb-result-table-scroll"
          data-testid="table-view-statistical-exploration-scroll"
          tabIndex={0}
          aria-label="Statistical exploration table scroll region"
        >
          <table className="wb-result-table" style={{ borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--label-secondary)" }}>
                {columns.map((column) => <th key={column} style={{ padding: "4px 8px", whiteSpace: "nowrap" }}>{column}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index} style={{ borderTop: "1px solid var(--separator)" }}>
                  {columns.map((column) => <td key={column} style={{ padding: "4px 8px", whiteSpace: "nowrap" }}>{String(row[column] ?? "—")}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ color: "var(--label-tertiary)", fontSize: 12 }}>Result is available as the downloadable artifact.</div>
      )}
    </div>
  );
}

export function StatisticalExplorationTable({ explorations }: { explorations: ExplorationPayload[] }) {
  if (explorations.length === 0) return null;
  return (
    <section data-testid="table-view-statistical-exploration">
      <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>Statistical exploration</h3>
      {explorations.map((exploration) => <ExplorationResultTable key={exploration.item.artifact_id} payload={exploration} />)}
    </section>
  );
}
