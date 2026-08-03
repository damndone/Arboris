import { useEffect, useMemo, useState } from "react";
import { useProjectRootOptional } from "../../../workbench/ProjectRootContext";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import {
  confirmFeatureRecipe,
  confirmDataTransform,
  confirmDataColumnsCast,
  fetchDataColumnCastContext,
  fetchDataColumnCastRecordByChildNode,
  previewFeatureRecipe,
  previewDataTransform,
  previewDataColumnsCast,
  type DataCastOutputFormat,
  type DataColumnCastContext,
  type DataColumnCastOperationRecord,
  type DataColumnCastTarget,
  type DataColumnsCastPreview,
  type DataTransformOperation,
  type DataTransformPreview,
  type FeatureRecipeOperation,
  type FeatureRecipePreview,
} from "../../dataOperations";

interface DataOperationAnnotation {
  operation_id: string;
  execution_key: string;
  recipe_path: string;
  schema_fingerprint: string;
}

/** Typed data_operation annotation stamped on cast child nodes by the backend effect. */
function dataOperationAnnotation(node: GraphViewNode): DataOperationAnnotation | null {
  const raw = node.raw as { annotations?: unknown } | null;
  if (!raw || !Array.isArray(raw.annotations)) return null;
  for (const item of raw.annotations) {
    if (
      item &&
      typeof item === "object" &&
      (item as { type?: unknown }).type === "data_operation" &&
      typeof (item as { execution_key?: unknown }).execution_key === "string"
    ) {
      const entry = item as Record<string, unknown>;
      return {
        operation_id: String(entry.operation_id ?? ""),
        execution_key: String(entry.execution_key),
        recipe_path: String(entry.recipe_path ?? ""),
        schema_fingerprint: String(entry.schema_fingerprint ?? ""),
      };
    }
  }
  return null;
}

function backendNodeId(node: GraphViewNode): string {
  const raw = node.raw as { id?: unknown } | null;
  return raw && typeof raw.id === "string" ? raw.id : node.id;
}

interface CastRow {
  column: string;
  target_dtype: DataColumnCastTarget;
}

function FeatureRecipeBuilder({
  projectRoot,
  sourceRunId,
  sourceNodeId,
  sourceContext,
}: {
  projectRoot: string;
  sourceRunId: string;
  sourceNodeId: string;
  sourceContext: DataColumnCastContext;
}) {
  const columns = sourceContext.columns.map((column) => column.name);
  const [operation, setOperation] = useState<FeatureRecipeOperation>("interaction");
  const [inputOne, setInputOne] = useState(columns[0] ?? "");
  const [inputTwo, setInputTwo] = useState(columns[1] ?? columns[0] ?? "");
  const [output, setOutput] = useState("derived_value");
  const [operator, setOperator] = useState<"add" | "subtract" | "multiply">("add");
  const [mapping, setMapping] = useState('{"1":"one","2":"two"}');
  const [preview, setPreview] = useState<FeatureRecipePreview | null>(null);
  const [status, setStatus] = useState<"idle" | "previewing" | "confirming" | "complete" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const request = useMemo(() => {
    let parameters: Record<string, unknown>;
    if (operation === "interaction") parameters = { left: inputOne, right: inputTwo };
    else if (operation === "derived_variable") parameters = { operator };
    else if (operation === "log") parameters = { input: inputOne, base: "e" };
    else if (operation === "ratio") parameters = { numerator: inputOne, denominator: inputTwo, zero_policy: "fail_closed" };
    else {
      try {
        parameters = { input: inputOne, mapping: JSON.parse(mapping) };
      } catch {
        parameters = { input: inputOne, mapping: {} };
      }
    }
    const inputs = operation === "log" || operation === "recode" ? [inputOne] : [inputOne, inputTwo];
    return {
      source_run_id: sourceRunId,
      source_node_id: sourceNodeId,
      source_artifact_id: sourceContext.source_artifact_id,
      recipe_id: `recipe_${operation}`,
      operation_id: operation,
      inputs,
      output,
      output_type: operation === "recode" ? "string" : "numeric",
      parameters,
      fit_scope: "stateless" as const,
      missing_policy: "fail_closed",
      outlier_policy: "preserve",
    };
  }, [inputOne, inputTwo, mapping, operation, operator, output, sourceContext.source_artifact_id, sourceNodeId, sourceRunId]);

  async function handlePreview() {
    setStatus("previewing");
    setError(null);
    try {
      const response = await previewFeatureRecipe(projectRoot, request);
      setPreview(response.preview);
      setStatus("idle");
    } catch (reason: unknown) {
      setStatus("error");
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function handleConfirm() {
    if (!preview || preview.status !== "ready") return;
    setStatus("confirming");
    setError(null);
    try {
      await confirmFeatureRecipe(projectRoot, { ...request, preview_fingerprint: preview.fingerprint });
      setStatus("complete");
    } catch (reason: unknown) {
      setStatus("error");
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const secondInputNeeded = operation === "interaction" || operation === "derived_variable" || operation === "ratio";
  return (
    <div data-testid="feature-recipe-builder" style={{ borderTop: "1px solid var(--separator)", paddingTop: 10, marginTop: 8 }}>
      <strong>Derived variable / recode</strong>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
        <label>Operation <select aria-label="Feature operation" value={operation} onChange={(event) => { setOperation(event.target.value as FeatureRecipeOperation); setPreview(null); }}>
          <option value="derived_variable">add / subtract / multiply</option>
          <option value="recode">recode</option>
          <option value="interaction">interaction</option>
          <option value="log">log</option>
          <option value="ratio">ratio</option>
        </select></label>
        <label>Input <select aria-label="Feature input" value={inputOne} onChange={(event) => { setInputOne(event.target.value); setPreview(null); }}>
          {columns.map((column) => <option key={column} value={column}>{column}</option>)}
        </select></label>
        {secondInputNeeded && <label>Second input <select aria-label="Feature second input" value={inputTwo} onChange={(event) => { setInputTwo(event.target.value); setPreview(null); }}>
          {columns.map((column) => <option key={column} value={column}>{column}</option>)}
        </select></label>}
        {operation === "derived_variable" && <label>Operator <select aria-label="Feature operator" value={operator} onChange={(event) => setOperator(event.target.value as typeof operator)}>
          <option value="add">add</option><option value="subtract">subtract</option><option value="multiply">multiply</option>
        </select></label>}
        {operation === "recode" && <label>Mapping JSON <input aria-label="Recode mapping" value={mapping} onChange={(event) => { setMapping(event.target.value); setPreview(null); }} /></label>}
        <label>Output <input aria-label="Feature output" value={output} onChange={(event) => { setOutput(event.target.value); setPreview(null); }} /></label>
      </div>
      <div style={{ color: "var(--label-tertiary)", marginTop: 5 }}>Preview is required. The source stays unchanged and downstream models are marked for rerun.</div>
      <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
        <button type="button" data-testid="feature-recipe-preview" disabled={!inputOne || !output || status === "previewing" || status === "confirming"} onClick={() => void handlePreview()}>{status === "previewing" ? "Previewing…" : "Preview transform"}</button>
        {preview?.status === "ready" && <button type="button" data-testid="feature-recipe-confirm" disabled={status === "confirming"} onClick={() => void handleConfirm()}>{status === "confirming" ? "Saving…" : "Confirm transform"}</button>}
      </div>
      {preview && <div data-testid="feature-recipe-preview-result">{preview.status} · {preview.row_count} rows · output: {preview.output_columns.join(", ")}</div>}
      {error && <div data-testid="feature-recipe-error">{error}</div>}
      {status === "complete" && <div data-testid="feature-recipe-complete">Typed transform saved as a child data node.</div>}
    </div>
  );
}

/** Render the typed schema diff from any data operation's record.
 *
 * All of them share `data.schema_diff.v1` but populate it differently: a cast
 * lists per-column dtype changes, code.execute reports added/removed columns
 * and a row count. Read whichever fields are present rather than branching on
 * operation_id, so a new data operation renders without touching this.
 */
function ProvenanceDiff({ record }: { record: DataColumnCastOperationRecord }) {
  const diff = record.diff_ref;
  if (!diff) return null;
  const casts =
    diff.casts ??
    (diff.column
      ? [{ column: diff.column, before_dtype: diff.before_dtype ?? "", after_dtype: diff.after_dtype ?? "" }]
      : []);
  const dtypeChanges = casts.length > 0 ? casts : (diff.dtype_changes ?? []);
  const added = diff.columns_added ?? [];
  const removed = diff.columns_removed ?? [];
  const rowsChanged =
    typeof diff.row_count_before === "number" &&
    typeof diff.row_count_after === "number" &&
    diff.row_count_before !== diff.row_count_after;
  if (dtypeChanges.length === 0 && added.length === 0 && removed.length === 0 && !rowsChanged) {
    return null;
  }
  return (
    <div data-testid="data-cast-provenance-diff">
      {rowsChanged && (
        <div>
          Rows {diff.row_count_before} → {diff.row_count_after}
        </div>
      )}
      {added.map((column) => (
        <div key={`add-${column}`}>+ {column}</div>
      ))}
      {removed.map((column) => (
        <div key={`remove-${column}`}>− {column}</div>
      ))}
      {dtypeChanges.map((c) => (
        <div key={c.column}>
          {c.column}: {c.before_dtype} → {c.after_dtype}
        </div>
      ))}
    </div>
  );
}

function DataTransformBuilder({
  projectRoot,
  sourceRunId,
  sourceNodeId,
  sourceContext,
}: {
  projectRoot: string;
  sourceRunId: string;
  sourceNodeId: string;
  sourceContext: DataColumnCastContext;
}) {
  const columns = sourceContext.columns.map((column) => column.name);
  const [operation, setOperation] = useState<DataTransformOperation>("subset");
  const [columnsText, setColumnsText] = useState(columns.join(","));
  const [filterText, setFilterText] = useState("{}");
  const [keysText, setKeysText] = useState(columns[0] ?? "");
  const [secondaryRunId, setSecondaryRunId] = useState("");
  const [secondaryNodeId, setSecondaryNodeId] = useState("stage:source");
  const [secondaryArtifactId, setSecondaryArtifactId] = useState("");
  const [preview, setPreview] = useState<DataTransformPreview | null>(null);
  const [status, setStatus] = useState<"idle" | "previewing" | "confirming" | "complete" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const request = useMemo(() => {
    let parameters: Record<string, unknown>;
    if (operation === "subset") {
      let equals: Record<string, unknown> = {};
      try { equals = JSON.parse(filterText) as Record<string, unknown>; } catch { /* server returns typed validation error */ }
      parameters = { columns: columnsText.split(",").map((value) => value.trim()).filter(Boolean), equals };
    } else if (operation === "merge") {
      parameters = { keys: keysText.split(",").map((value) => value.trim()).filter(Boolean), how: "left" };
    } else if (operation === "reshape") {
      parameters = { direction: "wide_to_long", id_columns: columns.slice(0, 1), value_columns: columns.slice(1), var_name: "variable", value_name: "value" };
    } else {
      parameters = {};
    }
    return {
      source_run_id: sourceRunId,
      source_node_id: sourceNodeId,
      source_artifact_id: sourceContext.source_artifact_id,
      operation,
      parameters,
      ...(operation === "merge" || operation === "append"
        ? { secondary_run_id: secondaryRunId, secondary_node_id: secondaryNodeId, secondary_artifact_id: secondaryArtifactId }
        : {}),
    };
  }, [columns, columnsText, filterText, keysText, operation, secondaryArtifactId, secondaryNodeId, secondaryRunId, sourceContext.source_artifact_id, sourceNodeId, sourceRunId]);

  async function handlePreview() {
    setStatus("previewing"); setError(null);
    try { const response = await previewDataTransform(projectRoot, request); setPreview(response.preview); setStatus("idle"); }
    catch (reason: unknown) { setStatus("error"); setError(reason instanceof Error ? reason.message : String(reason)); }
  }
  async function handleConfirm() {
    if (!preview || preview.status !== "ready") return;
    setStatus("confirming"); setError(null);
    try { await confirmDataTransform(projectRoot, { ...request, preview_fingerprint: preview.fingerprint }); setStatus("complete"); }
    catch (reason: unknown) { setStatus("error"); setError(reason instanceof Error ? reason.message : String(reason)); }
  }

  return (
    <div data-testid="data-transform-builder" style={{ borderTop: "1px solid var(--separator)", paddingTop: 10, marginTop: 8 }}>
      <strong>Merge / append / reshape / subset</strong>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
        <label>Operation <select aria-label="Data transform operation" value={operation} onChange={(event) => { setOperation(event.target.value as DataTransformOperation); setPreview(null); }}>
          <option value="subset">subset</option><option value="merge">merge</option><option value="append">append</option><option value="reshape">reshape wide → long</option>
        </select></label>
        {(operation === "subset" || operation === "reshape") && <label>Columns <input aria-label="Transform columns" value={columnsText} onChange={(event) => setColumnsText(event.target.value)} /></label>}
        {operation === "subset" && <label>Equals JSON <input aria-label="Subset equals" value={filterText} onChange={(event) => setFilterText(event.target.value)} /></label>}
        {operation === "merge" && <label>Join keys <input aria-label="Merge keys" value={keysText} onChange={(event) => setKeysText(event.target.value)} /></label>}
        {(operation === "merge" || operation === "append") && <>
          <label>Right run <input aria-label="Secondary run" value={secondaryRunId} onChange={(event) => setSecondaryRunId(event.target.value)} /></label>
          <label>Right node <input aria-label="Secondary node" value={secondaryNodeId} onChange={(event) => setSecondaryNodeId(event.target.value)} /></label>
          <label>Right artifact <input aria-label="Secondary artifact" value={secondaryArtifactId} onChange={(event) => setSecondaryArtifactId(event.target.value)} /></label>
        </>}
      </div>
      <div style={{ color: "var(--label-tertiary)", marginTop: 5 }}>All transforms are previewed, fingerprinted, confirmed, and written as a visible child node.</div>
      <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
        <button type="button" data-testid="data-transform-preview" disabled={status === "previewing" || status === "confirming"} onClick={() => void handlePreview()}>{status === "previewing" ? "Previewing…" : "Preview data transform"}</button>
        {preview?.status === "ready" && <button type="button" data-testid="data-transform-confirm" disabled={status === "confirming"} onClick={() => void handleConfirm()}>{status === "confirming" ? "Saving…" : "Confirm data transform"}</button>}
      </div>
      {preview && <div data-testid="data-transform-preview-result">{preview.status} · rows {preview.row_count_before} → {preview.row_count_after}</div>}
      {error && <div data-testid="data-transform-error">{error}</div>}
      {status === "complete" && <div data-testid="data-transform-complete">Data transform saved as a child data node.</div>}
    </div>
  );
}

export function DataColumnCastSection({ node }: { node: GraphViewNode }) {
  const isDatasetNode = node.kind === "dataset_stage";
  const projectRoot = useProjectRootOptional();
  const resolved = useResolvedNodeOperationContext();
  const [sourceContext, setSourceContext] = useState<DataColumnCastContext | null>(null);
  const [rows, setRows] = useState<CastRow[]>([]);
  const [outputFormat, setOutputFormat] = useState<DataCastOutputFormat>("csv");
  const [preview, setPreview] = useState<DataColumnsCastPreview | null>(null);
  const [status, setStatus] = useState<
    "idle" | "loading" | "previewing" | "confirming" | "complete" | "error"
  >("idle");
  const [error, setError] = useState<string | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [record, setRecord] = useState<DataColumnCastOperationRecord | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);

  const sourceRunId = resolved?.ok ? resolved.context.ownership.owner_run_id : null;
  const sourceNodeId = resolved?.ok ? resolved.context.operation_target.op_node_id : null;
  const provenance = dataOperationAnnotation(node);
  const childNodeId = backendNodeId(node);

  useEffect(() => {
    let cancelled = false;
    setRecord(null);
    setRecordError(null);
    if (!provenance || !projectRoot) return;
    void fetchDataColumnCastRecordByChildNode(projectRoot, childNodeId)
      .then((response) => {
        if (!cancelled) setRecord(response.operation);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setRecordError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => {
      cancelled = true;
    };
    // provenance is derived from node.raw; keying on childNodeId covers node switches.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectRoot, childNodeId, provenance !== null]);

  useEffect(() => {
    let cancelled = false;
    setSourceContext(null);
    setRows([]);
    setPreview(null);
    setError(null);
    setOperationId(null);
    if (!isDatasetNode || !projectRoot || !sourceRunId || !sourceNodeId) return;

    setStatus("loading");
    void fetchDataColumnCastContext(projectRoot, sourceRunId, sourceNodeId)
      .then((context) => {
        if (cancelled) return;
        setSourceContext(context);
        const first = context.columns[0]?.name ?? "";
        setRows(first ? [{ column: first, target_dtype: "numeric" }] : []);
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

  const usedColumns = useMemo(() => new Set(rows.map((r) => r.column)), [rows]);
  const availableToAdd = useMemo(
    () => (sourceContext?.columns ?? []).filter((c) => !usedColumns.has(c.name)),
    [sourceContext, usedColumns],
  );

  if (!isDatasetNode) return null;

  const request =
    sourceContext && sourceRunId && sourceNodeId && rows.length > 0
      ? {
          source_run_id: sourceRunId,
          source_node_id: sourceNodeId,
          source_artifact_id: sourceContext.source_artifact_id,
          casts: rows.map((r) => ({ column: r.column, target_dtype: r.target_dtype })),
          output_format: outputFormat,
        }
      : null;

  function updateRow(index: number, patch: Partial<CastRow>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
    setPreview(null);
  }

  function removeRow(index: number) {
    setRows((current) => current.filter((_, i) => i !== index));
    setPreview(null);
  }

  function addRow() {
    const next = availableToAdd[0]?.name;
    if (!next) return;
    setRows((current) => [...current, { column: next, target_dtype: "numeric" }]);
    setPreview(null);
  }

  async function handlePreview() {
    if (!projectRoot || !request) return;
    setStatus("previewing");
    setError(null);
    setPreview(null);
    try {
      const response = await previewDataColumnsCast(projectRoot, request);
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
      const response = await confirmDataColumnsCast(projectRoot, {
        ...request,
        preview_fingerprint: preview.fingerprint,
      });
      const recordId = response.operation.record_id;
      setOperationId(typeof recordId === "string" ? recordId : null);
      setStatus("complete");
    } catch (reason: unknown) {
      setStatus("error");
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const columnOptionsFor = (rowIndex: number) =>
    (sourceContext?.columns ?? []).filter(
      (c) => !usedColumns.has(c.name) || rows[rowIndex]?.column === c.name,
    );

  return (
    <section aria-label="Data column operation" data-testid="data-column-cast-section" style={{ marginTop: 18 }}>
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Data operation
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          padding: 10,
          background: "var(--bg-card-2, rgba(255,255,255,0.04))",
          borderRadius: 8,
          fontSize: 12,
        }}
      >
        {provenance && (
          <div
            data-testid="data-cast-provenance"
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 4,
              paddingBottom: 8,
              borderBottom: "1px solid var(--separator)",
            }}
          >
            <div>
              <strong>Created by {provenance.operation_id}</strong>
              {record ? (
                <>
                  {" "}· Operation Record {record.record_id} · {record.status}
                  {record.verification?.passed
                    ? " · verification passed"
                    : record.verification
                      ? " · verification failed"
                      : null}
                </>
              ) : recordError ? (
                <span style={{ color: "var(--label-tertiary)" }}> · operation record unavailable</span>
              ) : null}
            </div>
            {record && <ProvenanceDiff record={record} />}
            <div style={{ color: "var(--label-tertiary)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
              {provenance.execution_key}
            </div>
            {provenance.recipe_path && (
              <div style={{ color: "var(--label-tertiary)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                Recipe: {provenance.recipe_path}
              </div>
            )}
          </div>
        )}
        {sourceContext && (
          <div data-testid="data-cast-source-artifact" style={{ color: "var(--label-tertiary)" }}>
            Source artifact: <strong>{sourceContext.source_artifact_id}</strong> · {sourceContext.row_count} rows
          </div>
        )}
        {status === "loading" && <div>Loading typed data context…</div>}
        {status === "error" && <div data-testid="data-cast-error">{error}</div>}
        {sourceContext && (
          <>
            {rows.map((row, index) => (
              <div
                key={index}
                data-testid={`data-cast-row-${index}`}
                style={{ display: "flex", gap: 8, alignItems: "center" }}
              >
                <select
                  aria-label={`Column ${index + 1}`}
                  data-testid={`data-cast-column-${index}`}
                  value={row.column}
                  onChange={(event) => updateRow(index, { column: event.target.value })}
                >
                  {columnOptionsFor(index).map((item) => (
                    <option key={item.name} value={item.name}>
                      {item.name} ({item.dtype})
                    </option>
                  ))}
                </select>
                <span aria-hidden>→</span>
                <select
                  aria-label={`Target type ${index + 1}`}
                  data-testid={`data-cast-target-${index}`}
                  value={row.target_dtype}
                  onChange={(event) =>
                    updateRow(index, { target_dtype: event.target.value as DataColumnCastTarget })
                  }
                >
                  <option value="numeric">numeric</option>
                  <option value="string">string</option>
                  <option value="datetime">datetime</option>
                </select>
                {rows.length > 1 && (
                  <button
                    type="button"
                    data-testid={`data-cast-remove-${index}`}
                    aria-label={`Remove column ${index + 1}`}
                    onClick={() => removeRow(index)}
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <button
                type="button"
                data-testid="data-cast-add-column"
                disabled={availableToAdd.length === 0}
                onClick={addRow}
              >
                + Add column
              </button>
              <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{ color: "var(--label-tertiary)" }}>Output</span>
                <select
                  aria-label="Output format"
                  data-testid="data-cast-format"
                  value={outputFormat}
                  onChange={(event) => {
                    setOutputFormat(event.target.value as DataCastOutputFormat);
                    setPreview(null);
                  }}
                >
                  <option value="csv">CSV</option>
                  <option value="xlsx">Excel (.xlsx)</option>
                </select>
              </label>
            </div>
            <div style={{ color: "var(--label-tertiary)" }}>
              All selected columns are cast into one immutable child node. Preview is required; the source node
              stays unchanged and downstream models require rerun.
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button
                type="button"
                data-testid="data-cast-preview"
                disabled={!request || status === "previewing" || status === "confirming"}
                onClick={() => void handlePreview()}
              >
                {status === "previewing"
                  ? "Previewing…"
                  : rows.length > 1
                    ? `Preview ${rows.length} casts`
                    : "Preview cast"}
              </button>
              {preview?.status === "ready" && (
                <button
                  type="button"
                  data-testid="data-cast-confirm"
                  disabled={status === "confirming"}
                  onClick={() => void handleConfirm()}
                >
                  {status === "confirming"
                    ? "Confirming…"
                    : rows.length > 1
                      ? `Confirm ${rows.length} casts`
                      : "Confirm cast"}
                </button>
              )}
            </div>
          </>
        )}
        {preview && (
          <div data-testid="data-cast-preview-result" style={{ borderTop: "1px solid var(--separator)", paddingTop: 8 }}>
            <strong>Preview</strong> · {preview.row_count} rows · {preview.status}
            {preview.items.map((item) => (
              <div key={item.column} data-testid={`data-cast-preview-item-${item.column}`}>
                {item.column}: {item.before_dtype} → {item.after_dtype} · {item.success_count} converted ·{" "}
                {item.failure_count} failures · {item.new_missing_count} new missing
                {item.status !== "ready" && <span> · blocked</span>}
              </div>
            ))}
            {preview.downstream_invalidation.length > 0 && (
              <div>Downstream models requiring rerun: {preview.downstream_invalidation.join(", ")}</div>
            )}
          </div>
        )}
        {status === "complete" && (
          <div data-testid="data-cast-complete" style={{ color: "var(--accent-positive, #4caf50)" }}>
            Cast confirmed · Operation Record {operationId ?? "created"} · new child data node created
          </div>
        )}
        {sourceContext && sourceRunId && sourceNodeId && projectRoot && (
          <FeatureRecipeBuilder
            projectRoot={projectRoot}
            sourceRunId={sourceRunId}
            sourceNodeId={sourceNodeId}
            sourceContext={sourceContext}
          />
        )}
        {sourceContext && sourceRunId && sourceNodeId && projectRoot && (
          <DataTransformBuilder
            projectRoot={projectRoot}
            sourceRunId={sourceRunId}
            sourceNodeId={sourceNodeId}
            sourceContext={sourceContext}
          />
        )}
      </div>
    </section>
  );
}
