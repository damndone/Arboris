import { useEffect, useMemo, useState } from "react";
import { useProjectRootOptional } from "../../../workbench/ProjectRootContext";
import type { DataColumnCastContext } from "../../dataOperations";
import { fetchDataColumnCastContext } from "../../dataOperations";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import {
  confirmStatisticalExploration,
  previewStatisticalExploration,
  type StatisticalExplorationOperation,
  type StatisticalExplorationPreview,
  type StatisticalExplorationRequest,
  type StatisticalFilter,
  type StatisticalFilterOperator,
} from "../../statisticalExploration";

interface FilterRowState {
  column: string;
  operator: StatisticalFilterOperator;
  value: string;
}

const OPERATORS: Array<{ value: StatisticalFilterOperator; label: string }> = [
  { value: "eq", label: "equals" },
  { value: "neq", label: "does not equal" },
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
];

function backendNodeId(node: GraphViewNode): string {
  const raw = node.raw as { id?: unknown } | null;
  return raw && typeof raw.id === "string" ? raw.id : node.id;
}

function numericDtype(dtype: string): boolean {
  return /int|float|double|decimal|number|bool/i.test(dtype);
}

function filterValue(value: string, column: string, context: DataColumnCastContext | null): unknown {
  const dtype = context?.columns.find((item) => item.name === column)?.dtype ?? "";
  if (numericDtype(dtype) && value.trim() !== "") {
    const number = Number(value);
    return Number.isFinite(number) ? number : value;
  }
  return value;
}

function ResultSummary({ preview }: { preview: StatisticalExplorationPreview }) {
  const result = preview.result;
  const variables = result.variables;
  return (
    <div data-testid="statistical-exploration-result" style={{ borderTop: "1px solid var(--separator)", paddingTop: 8 }}>
      <strong>Preview</strong>
      <div>Rows after filters: {String(result.filtered_row_count ?? 0)}</div>
      {result.missing_policy && <div>Missing policy: {result.missing_policy}</div>}
      {Array.isArray(result.groups) ? (
        result.groups.map((group, index) => (
          <div key={index} data-testid={`statistical-exploration-group-${index}`}>
            {String(group.value)} · {String(group.filtered_row_count)} rows
          </div>
        ))
      ) : variables && !Array.isArray(variables) ? (
        Object.entries(variables).map(([name, value]) => (
          <div key={name}>
            <strong>{name}</strong>: {typeof value === "object" ? JSON.stringify(value) : String(value)}
          </div>
        ))
      ) : null}
      {typeof result.correlation_n === "number" && <div>Correlation N: {result.correlation_n}</div>}
    </div>
  );
}

export function StatisticalExplorationSection({ node }: { node: GraphViewNode }) {
  const isDatasetNode = node.kind === "dataset_stage";
  const projectRoot = useProjectRootOptional();
  const resolved = useResolvedNodeOperationContext();
  const [sourceContext, setSourceContext] = useState<DataColumnCastContext | null>(null);
  const [operation, setOperation] = useState<StatisticalExplorationOperation>("summarize");
  const [selectedColumns, setSelectedColumns] = useState<string[]>([]);
  const [filters, setFilters] = useState<FilterRowState[]>([]);
  const [preview, setPreview] = useState<StatisticalExplorationPreview | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "previewing" | "confirming" | "complete" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const sourceRunId = resolved?.ok ? resolved.context.ownership.owner_run_id : null;
  const sourceNodeId = resolved?.ok ? resolved.context.operation_target.op_node_id : null;

  useEffect(() => {
    let cancelled = false;
    setSourceContext(null);
    setSelectedColumns([]);
    setFilters([]);
    setPreview(null);
    setError(null);
    if (!isDatasetNode || !projectRoot || !sourceRunId || !sourceNodeId) return;
    setStatus("loading");
    void fetchDataColumnCastContext(projectRoot, sourceRunId, sourceNodeId)
      .then((context) => {
        if (cancelled) return;
        setSourceContext(context);
        setSelectedColumns(context.columns.map((column) => column.name));
        setStatus("idle");
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setStatus("error");
        setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [isDatasetNode, projectRoot, sourceRunId, sourceNodeId]);

  const request = useMemo<StatisticalExplorationRequest | null>(() => {
    if (!sourceContext || !sourceRunId || !sourceNodeId) return null;
    const typedFilters: StatisticalFilter[] = filters.map((filter) => ({
      column: filter.column,
      operator: filter.operator,
      value: filterValue(filter.value, filter.column, sourceContext),
    }));
    return {
      source_run_id: sourceRunId,
      source_node_id: sourceNodeId,
      source_artifact_id: sourceContext.source_artifact_id,
      operation,
      selected_columns: selectedColumns,
      filters: typedFilters,
    };
  }, [filters, operation, selectedColumns, sourceContext, sourceNodeId, sourceRunId]);

  function addFilter() {
    const first = sourceContext?.columns[0]?.name ?? "";
    setFilters((current) => [...current, { column: first, operator: "eq", value: "" }]);
    setPreview(null);
  }

  function updateFilter(index: number, patch: Partial<FilterRowState>) {
    setFilters((current) => current.map((filter, i) => (i === index ? { ...filter, ...patch } : filter)));
    setPreview(null);
  }

  function removeFilter(index: number) {
    setFilters((current) => current.filter((_, i) => i !== index));
    setPreview(null);
  }

  async function handlePreview() {
    if (!projectRoot || !request) return;
    setStatus("previewing");
    setError(null);
    try {
      const response = await previewStatisticalExploration(projectRoot, request);
      setPreview(response.preview);
      setStatus("idle");
    } catch (reason: unknown) {
      setStatus("error");
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function handleConfirm() {
    if (!projectRoot || !request || !preview || preview.status !== "ready") return;
    setStatus("confirming");
    setError(null);
    try {
      await confirmStatisticalExploration(projectRoot, {
        ...request,
        preview_fingerprint: preview.fingerprint,
      });
      setStatus("complete");
    } catch (reason: unknown) {
      setStatus("error");
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  if (!isDatasetNode) return null;

  return (
    <section aria-label="Statistical exploration" data-testid="statistical-exploration-section" style={{ marginTop: 18 }}>
      <div className="ln-section-label" style={{ marginBottom: 6 }}>Statistical exploration</div>
      <div className="statistical-exploration-panel">
        {sourceContext && (
          <div data-testid="statistical-exploration-source" style={{ color: "var(--label-tertiary)" }}>
            Source artifact: <strong>{sourceContext.source_artifact_id}</strong> · {sourceContext.row_count} rows
          </div>
        )}
        {status === "loading" && <div>Loading typed data context…</div>}
        {status === "error" && <div data-testid="statistical-exploration-error">{error}</div>}
        {sourceContext && (
          <>
            <label>
              <span>Action </span>
              <select
                data-testid="statistical-exploration-operation"
                value={operation}
                onChange={(event) => {
                  setOperation(event.target.value as StatisticalExplorationOperation);
                  setPreview(null);
                }}
              >
                <option value="summarize">Summarize</option>
                <option value="summarize_detail">Summarize detail</option>
                <option value="misstable">Missing values</option>
                <option value="corr">Correlation</option>
              </select>
            </label>
            <fieldset>
              <legend>Variables</legend>
              {sourceContext.columns.map((column) => (
                <label key={column.name} style={{ marginRight: 8 }}>
                  <input
                    type="checkbox"
                    checked={selectedColumns.includes(column.name)}
                    onChange={(event) => {
                      setSelectedColumns((current) =>
                        event.target.checked
                          ? [...current, column.name]
                          : current.filter((name) => name !== column.name),
                      );
                      setPreview(null);
                    }}
                  />
                  {column.name}
                </label>
              ))}
            </fieldset>
            <div data-testid="statistical-exploration-filters">
              <strong>Filters (AND)</strong>
              {filters.map((filter, index) => (
                <div key={index} data-testid={`statistical-filter-row-${index}`} style={{ display: "flex", gap: 6, marginTop: 6 }}>
                  <select
                    data-testid={`statistical-filter-column-${index}`}
                    value={filter.column}
                    onChange={(event) => updateFilter(index, { column: event.target.value })}
                  >
                    {sourceContext.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
                  </select>
                  <select
                    aria-label={`Filter operator ${index + 1}`}
                    value={filter.operator}
                    onChange={(event) => updateFilter(index, { operator: event.target.value as StatisticalFilterOperator })}
                  >
                    {OPERATORS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                  </select>
                  <input
                    data-testid={`statistical-filter-value-${index}`}
                    value={filter.value}
                    onChange={(event) => updateFilter(index, { value: event.target.value })}
                    placeholder="value"
                  />
                  <button type="button" onClick={() => removeFilter(index)} aria-label={`Remove filter ${index + 1}`}>×</button>
                  {index < filters.length - 1 && <span aria-label="AND">AND</span>}
                </div>
              ))}
              <button type="button" data-testid="statistical-exploration-add-filter" onClick={addFilter}>+ Add AND filter</button>
            </div>
            <div style={{ color: "var(--label-tertiary)" }}>
              Preview applies every filter as AND. The source data and model state are unchanged.
            </div>
            <div>
              <button
                type="button"
                data-testid="statistical-exploration-preview"
                disabled={!request || request.selected_columns.length === 0 || status === "previewing" || status === "confirming"}
                onClick={() => void handlePreview()}
              >
                {status === "previewing" ? "Previewing…" : "Preview"}
              </button>
              {preview?.status === "ready" && (
                <button
                  type="button"
                  data-testid="statistical-exploration-confirm"
                  disabled={status === "confirming"}
                  onClick={() => void handleConfirm()}
                >
                  {status === "confirming" ? "Saving…" : "Save exploration"}
                </button>
              )}
            </div>
            {preview && <ResultSummary preview={preview} />}
            {status === "complete" && <div data-testid="statistical-exploration-complete">Exploration saved as an artifact.</div>}
          </>
        )}
      </div>
    </section>
  );
}
