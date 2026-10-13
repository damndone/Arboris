import { useEffect, useState } from "react";

import { fetchDatasetPage, type DatasetPage, type DatasetVariable } from "./dataViewApi";
import { matchesMissingCode, valueLabelFor } from "./metadataText";
import { ChevronIcon } from "../workspace/icons";

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

  if (error) return <p role="alert" className="dv-alert">{error}</p>;
  if (!page) return <p className="dv-note">Loading rows…</p>;

  const last = Math.min(page.offset + page.rows.length, page.total_rows);
  // Value labels name coded values (1 → "Male"). The switch is offered only
  // when some variable here has them; otherwise it would do nothing.
  const labelled = variables.filter((variable) => Object.keys(variable.value_labels ?? {}).length > 0);
  return (
    <div data-testid="data-grid" className="dv-grid">
      <div className="dv-grid-bar">
        {labelled.length > 0 && (
          <button
            type="button"
            role="switch"
            className="dv-switch"
            aria-checked={showLabels}
            aria-label="Show value labels"
            title={`Show the label of each coded value instead of the code, for ${labelled.map((variable) => variable.name).join(", ")}`}
            onClick={() => setShowLabels(!showLabels)}
          >
            <span className="dv-switch__track" aria-hidden="true" />
            Value labels
          </button>
        )}
        <span className="dv-spacer" />
        <span>
          {sort ? `Sorted by ${sort.column}${sort.descending ? " (descending)" : ""} for viewing · ` : ""}
          Rows {page.total_rows === 0 ? 0 : page.offset + 1}–{last} of {page.total_rows.toLocaleString("en")}
        </span>
        <span className="dv-pager">
          <button
            type="button"
            className="dv-pager__step"
            aria-label="Previous"
            title="Previous rows"
            disabled={page.offset === 0}
            onClick={() => setOffset(Math.max(0, page.offset - PAGE_SIZE))}
          >
            <ChevronIcon direction="left" />
          </button>
          <button
            type="button"
            className="dv-pager__step"
            aria-label="Next"
            title="Next rows"
            disabled={last >= page.total_rows}
            onClick={() => setOffset(page.offset + PAGE_SIZE)}
          >
            <ChevronIcon direction="right" />
          </button>
        </span>
      </div>
      <div className="dv-table-wrap" tabIndex={0} aria-label="Data rows">
        <table className="dv-table">
          <thead>
            <tr>
              <th className="dv-table__n" scope="col">#</th>
              {page.columns.map((column) => {
                const variable = byName.get(column);
                const sorted = sort?.column === column;
                return (
                  <th key={column} scope="col" aria-sort={sorted ? (sort.descending ? "descending" : "ascending") : undefined}>
                    <button type="button" className="dv-table__sort" onClick={() => toggleSort(column)} title={variable?.variable_label || `Sort by ${column}`}>
                      {column}
                      {sorted && <span aria-hidden="true">{sort.descending ? "↓" : "↑"}</span>}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {page.rows.map((row, index) => (
              <tr key={page.row_numbers[index]}>
                <td className="dv-table__n">{page.row_numbers[index]}</td>
                {page.columns.map((column) => {
                  const variable = byName.get(column);
                  const value = row[column];
                  const declaredMissing = variable ? matchesMissingCode(value, variable.user_missing_values) : false;
                  const label = showLabels && variable ? valueLabelFor(value, variable.value_labels) : undefined;
                  return (
                    <td
                      key={column}
                      data-numeric={(typeof value === "number" && label === undefined) || undefined}
                      data-declared-missing={declaredMissing || undefined}
                      title={declaredMissing ? "Declared missing code" : typeof value === "number" && !Number.isInteger(value) ? String(value) : undefined}
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
