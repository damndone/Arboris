import { useId, useMemo, useState } from "react";

export type StatisticalVariableColumn = {
  name: string;
  dtype: string;
};

export type StatisticalVariablePickerProps = {
  columns: StatisticalVariableColumn[];
  selectedColumns: string[];
  onChange: (columns: string[]) => void;
};

export function StatisticalVariablePicker({
  columns,
  selectedColumns,
  onChange,
}: StatisticalVariablePickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchId = useId();
  const selectedSet = useMemo(() => new Set(selectedColumns), [selectedColumns]);
  const normalizedQuery = query.trim().toLowerCase();
  const matchingColumns = useMemo(
    () => columns.filter((column) => column.name.toLowerCase().includes(normalizedQuery)),
    [columns, normalizedQuery],
  );

  function emitSelection(next: Set<string>) {
    onChange(columns.filter((column) => next.has(column.name)).map((column) => column.name));
  }

  function toggleColumn(name: string, checked: boolean) {
    const next = new Set(selectedSet);
    if (checked) next.add(name);
    else next.delete(name);
    emitSelection(next);
  }

  function selectMatching() {
    const next = new Set(selectedSet);
    matchingColumns.forEach((column) => next.add(column.name));
    emitSelection(next);
  }

  function clearMatching() {
    const next = new Set(selectedSet);
    matchingColumns.forEach((column) => next.delete(column.name));
    emitSelection(next);
  }

  return (
    <div data-testid="statistical-variable-picker">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`${searchId}-panel`}
        onClick={() => setOpen((current) => !current)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          padding: "7px 9px",
          border: "1px solid var(--separator)",
          borderRadius: 7,
          background: "var(--control-background, transparent)",
          color: "var(--label)",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <span>
          <strong>Variables</strong>
          <span style={{ marginLeft: 8, color: "var(--label-secondary)" }}>
            {selectedColumns.length} {selectedColumns.length === 1 ? "variable" : "variables"} selected
          </span>
        </span>
        <span aria-hidden="true" style={{ color: "var(--label-secondary)" }}>{open ? "⌃" : "⌄"}</span>
      </button>

      {open && (
        <div
          id={`${searchId}-panel`}
          style={{
            marginTop: 6,
            padding: 9,
            border: "1px solid var(--separator)",
            borderRadius: 7,
            background: "var(--control-background, transparent)",
          }}
        >
          <label htmlFor={searchId} style={{ display: "block", fontSize: 11, color: "var(--label-secondary)", marginBottom: 4 }}>
            Search variables
          </label>
          <input
            id={searchId}
            type="search"
            aria-label="Search variables"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by name"
            style={{ width: "100%", boxSizing: "border-box" }}
          />
          <div style={{ display: "flex", gap: 6, marginTop: 7, marginBottom: 7 }}>
            <button type="button" aria-label="Select all matching variables" onClick={selectMatching}>All</button>
            <button type="button" aria-label="Clear matching variables" onClick={clearMatching}>Clear</button>
            <span style={{ marginLeft: "auto", color: "var(--label-tertiary)", fontSize: 11, alignSelf: "center" }}>
              {matchingColumns.length} shown
            </span>
          </div>
          <div
            role="group"
            aria-label="Variable list"
            style={{ maxHeight: 220, overflowY: "auto", display: "grid", gap: 3 }}
          >
            {matchingColumns.length > 0 ? matchingColumns.map((column) => (
              <label
                key={column.name}
                style={{ display: "flex", alignItems: "center", gap: 7, padding: "5px 4px", borderRadius: 5 }}
              >
                <input
                  type="checkbox"
                  aria-label={column.name}
                  checked={selectedSet.has(column.name)}
                  onChange={(event) => toggleColumn(column.name, event.target.checked)}
                />
                <span style={{ color: "var(--label)" }}>{column.name}</span>
                <span style={{ marginLeft: "auto", color: "var(--label-tertiary)", fontSize: 11 }}>{column.dtype}</span>
              </label>
            )) : (
              <div style={{ padding: "8px 4px", color: "var(--label-tertiary)", fontSize: 12 }}>No variables match</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
