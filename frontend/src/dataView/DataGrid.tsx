import { useEffect, useState } from "react";

import { fetchDatasetPage, type DatasetPage, type DatasetVariable } from "./dataViewApi";
import { matchesMissingCode, valueLabelFor } from "./metadataText";

const PAGE_SIZE = 100;

type Sort = { column: string; descending: boolean } | null;

function display(value: unknown): string {
  if (value === null || value === undefined) return "";
  // Seven significant digits: what a single-precision (Stata float) value
  // actually holds, so 84.800003 reads 84.8. Display only; the cell's title
  // carries the stored value.
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(7)));
  return String(value);
}

/** Read-only, paged view of a dataset node, SPSS "Data View" style. */
export function DataGrid({
  projectRoot,
  runId,
  nodeId,
  variables,
}: {
  projectRoot: string;
  runId: string;
  nodeId: string;
  variables: DatasetVariable[];
}) {
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<Sort>(null);
  const [showLabels, setShowLabels] = useState(false);
  const [page, setPage] = useState<DatasetPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setOffset(0);
    setSort(null);
  }, [runId, nodeId]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchDatasetPage(projectRoot, runId, nodeId, {
      offset,
      limit: PAGE_SIZE,
      sortBy: sort?.column,
      descending: sort?.descending,
    })
      .then((next) => {
        if (!cancelled) setPage(next);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not load rows");
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, nodeId, offset, sort]);

  const byName = new Map(variables.map((variable) => [variable.name, variable]));

  function toggleSort(column: string) {
    setOffset(0);
    setSort((current) => {
      if (!current || current.column !== column) return { column, descending: false };
      if (!current.descending) return { column, descending: true };
      return null;
    });
  }

  if (error) return <div role="alert" style={{ color: "var(--red, #c00)", fontSize: 12 }}>{error}</div>;
  if (!page) return <div style={{ color: "var(--label-secondary)", fontSize: 12 }}>Loading rows…</div>;

  const last = Math.min(page.offset + page.rows.length, page.total_rows);
  return (
    <div data-testid="data-grid">
      <div style={{ display: "flex", gap: 12, alignItems: "center", fontSize: 12, marginBottom: 6 }}>
        <label>
          <input
            type="checkbox"
            checked={showLabels}
            onChange={(event) => setShowLabels(event.target.checked)}
          />{" "}
          Show value labels
        </label>
        <span style={{ color: "var(--label-secondary)" }}>
          Rows {page.total_rows === 0 ? 0 : page.offset + 1}–{last} of {page.total_rows}
          {sort ? ` · sorted by ${sort.column}${sort.descending ? " (desc)" : ""} for viewing only` : ""}
        </span>
        <button
          type="button"
          disabled={page.offset === 0}
          onClick={() => setOffset(Math.max(0, page.offset - PAGE_SIZE))}
        >
          Previous
        </button>
        <button
          type="button"
          disabled={last >= page.total_rows}
          onClick={() => setOffset(page.offset + PAGE_SIZE)}
        >
          Next
        </button>
      </div>
      <div className="wb-result-table-scroll" tabIndex={0} aria-label="Data rows" style={{ maxHeight: "60vh", overflowY: "auto" }}>
        <table className="wb-result-table" style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--label-secondary)" }}>
              <th style={{ padding: "2px 8px" }}>#</th>
              {page.columns.map((column) => {
                const variable = byName.get(column);
                const marker = sort?.column === column ? (sort.descending ? " ▼" : " ▲") : "";
                return (
                  <th key={column} style={{ padding: "2px 8px", whiteSpace: "nowrap" }}>
                    <button
                      type="button"
                      onClick={() => toggleSort(column)}
                      title={variable?.variable_label ?? column}
                      style={{ background: "none", border: "none", padding: 0, font: "inherit", color: "inherit", cursor: "pointer" }}
                    >
                      {column}
                      {marker}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {page.rows.map((row, index) => (
              <tr key={page.row_numbers[index]} style={{ borderTop: "1px solid var(--separator)" }}>
                <td style={{ padding: "2px 8px", color: "var(--label-tertiary)" }}>{page.row_numbers[index]}</td>
                {page.columns.map((column) => {
                  const variable = byName.get(column);
                  const value = row[column];
                  const declaredMissing = variable ? matchesMissingCode(value, variable.user_missing_values) : false;
                  const label = showLabels && variable ? valueLabelFor(value, variable.value_labels) : undefined;
                  return (
                    <td
                      key={column}
                      data-declared-missing={declaredMissing || undefined}
                      title={declaredMissing ? "Declared missing code" : typeof value === "number" && !Number.isInteger(value) ? String(value) : undefined}
                      style={{
                        padding: "2px 8px",
                        whiteSpace: "nowrap",
                        color: declaredMissing ? "var(--label-tertiary)" : undefined,
                        fontStyle: declaredMissing ? "italic" : undefined,
                      }}
                    >
                      {label ?? display(value)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
