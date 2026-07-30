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
          ? Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, cell]) => [key, scalar(cell)]))
          : { value: scalar(value) }),
      }));
    });
  }

  const variables = result.variables;
  if (variables && typeof variables === "object" && !Array.isArray(variables)) {
    return Object.entries(variables as Record<string, unknown>).map(([variable, value]) => ({
      variable,
      ...(value && typeof value === "object" && !Array.isArray(value)
        ? Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, cell]) => [key, scalar(cell)]))
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
        {String(result.operation ?? "Statistical exploration")}
      </div>
      <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginBottom: 8 }}>
        {sourceRows !== null ? `${sourceRows} source rows` : null}
        {filteredRows !== null ? ` · ${filteredRows} rows after filters` : null}
        {groupCount > 0 ? ` · ${groupCount} groups` : null}
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
