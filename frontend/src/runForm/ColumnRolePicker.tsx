import type { ColumnPreview, ExcludedColumn } from "../api";

export function formatColumnMeta(column: ColumnPreview): string {
  const base = `${column.dtype} · ${column.uniqueCount} unique`;
  if (column.mean !== undefined) {
    return `${base} · mean ${column.mean.toFixed(2)} / std ${(column.std ?? 0).toFixed(2)}`;
  }
  return `${base} · ${(column.missingRate * 100).toFixed(0)}% missing`;
}

export function ColumnRolePicker({
  columns,
  excludedColumns,
  y,
  xColumns,
  onY,
  onX,
}: {
  columns: ColumnPreview[];
  excludedColumns?: ExcludedColumn[];
  y: string;
  xColumns: string[];
  onY: (column: string) => void;
  onX: (column: string, checked: boolean) => void;
}) {
  if (columns.length === 0) return null;
  return (
    <section className="column-role-picker" aria-label="column selector">
      <div className="column-role-picker__list">
        {columns.map((column) => (
          <div key={column.name} className="column-option">
            <div>
              <strong>{column.name}</strong>
              <span className="column-meta">{formatColumnMeta(column)}</span>
            </div>
            <label className="inline-choice">
              <input
                type="radio"
                name="dependent-column"
                checked={y === column.name}
                onChange={() => onY(column.name)}
              />
              y
            </label>
            <label className="inline-choice">
              <input
                data-testid={`column-x-${column.name}`}
                type="checkbox"
                checked={xColumns.includes(column.name)}
                disabled={y === column.name}
                onChange={(event) => onX(column.name, event.target.checked)}
              />
              x
            </label>
          </div>
        ))}
      </div>
      {excludedColumns && excludedColumns.length > 0 && (
        <details className="excluded-columns">
          <summary>
            {excludedColumns.length} column(s) excluded from auto-suggest
          </summary>
          <ul>
            {excludedColumns.map((col) => (
              <li key={col.name}>
                <span className="excluded-name">{col.name}</span>
                <span className="excluded-reason"> — {col.reason}</span>
                <button
                  type="button"
                  className="add-back-btn"
                  onClick={() => onX(col.name, true)}
                >
                  + add to X
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
