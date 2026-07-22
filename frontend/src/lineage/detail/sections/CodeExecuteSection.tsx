import { useEffect, useState } from "react";
import { useProjectRootOptional } from "../../../workbench/ProjectRootContext";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import {
  authorizeCodeExecuteRisk,
  confirmCodeExecute,
  fetchDataColumnCastContext,
  previewCodeExecute,
  type CodeExecutePreview,
  type CodeExecuteRiskAuthorization,
  type DataCastOutputFormat,
  type DataColumnCastContext,
} from "../../dataOperations";

const STARTER_CODE = "# df is the source data. Bind `result` to the DataFrame you want.\nresult = df\n";

/** The schema diff the user is actually confirming. */
function SchemaDiff({ preview }: { preview: CodeExecutePreview }) {
  const unchanged =
    preview.columns_added.length === 0 &&
    preview.columns_removed.length === 0 &&
    preview.dtype_changes.length === 0 &&
    preview.row_count_before === preview.row_count_after;
  return (
    <div data-testid="code-execute-diff" style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div>
        Rows {preview.row_count_before} → {preview.row_count_after}
      </div>
      {preview.columns_added.map((column) => (
        <div key={`add-${column}`} style={{ color: "var(--ok, #4ade80)" }}>
          + {column}
        </div>
      ))}
      {preview.columns_removed.map((column) => (
        <div key={`remove-${column}`} style={{ color: "var(--danger, #f87171)" }}>
          − {column}
        </div>
      ))}
      {preview.dtype_changes.map((change) => (
        <div key={`dtype-${change.column}`}>
          {change.column}: {change.before_dtype} → {change.after_dtype}
        </div>
      ))}
      {unchanged && <div style={{ opacity: 0.7 }}>Schema and row count unchanged.</div>}
    </div>
  );
}

export function CodeExecuteSection({ node }: { node: GraphViewNode }) {
  const projectRoot = useProjectRootOptional();
  const resolved = useResolvedNodeOperationContext();
  const isDatasetNode = node.kind === "dataset_stage";

  const [sourceContext, setSourceContext] = useState<DataColumnCastContext | null>(null);
  const [code, setCode] = useState<string>(STARTER_CODE);
  const [outputFormat, setOutputFormat] = useState<DataCastOutputFormat>("csv");
  const [preview, setPreview] = useState<CodeExecutePreview | null>(null);
  const [status, setStatus] = useState<
    "idle" | "loading" | "previewing" | "authorizing" | "confirming" | "complete" | "error"
  >("idle");
  const [error, setError] = useState<string | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [riskAcknowledged, setRiskAcknowledged] = useState(false);
  const [riskAuthorization, setRiskAuthorization] =
    useState<CodeExecuteRiskAuthorization | null>(null);

  const sourceRunId = resolved?.ok ? resolved.context.ownership.owner_run_id : null;
  const sourceNodeId = resolved?.ok ? resolved.context.operation_target.op_node_id : null;
  const unavailableReason = !projectRoot
    ? "project_root_unavailable"
    : resolved && !resolved.ok
      ? resolved.reason
      : resolved === null
        ? "operation_context_unavailable"
        : null;

  useEffect(() => {
    let cancelled = false;
    setSourceContext(null);
    setPreview(null);
    setError(null);
    setOperationId(null);
    setRiskAcknowledged(false);
    setRiskAuthorization(null);
    if (!isDatasetNode || !projectRoot || !sourceRunId || !sourceNodeId) return;

    setStatus("loading");
    void fetchDataColumnCastContext(projectRoot, sourceRunId, sourceNodeId)
      .then((context) => {
        if (cancelled) return;
        setSourceContext(context);
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

  if (!isDatasetNode) return null;

  const request =
    sourceContext && sourceRunId && sourceNodeId && code.trim()
      ? {
          source_run_id: sourceRunId,
          source_node_id: sourceNodeId,
          source_artifact_id: sourceContext.source_artifact_id,
          code,
          language: "python" as const,
          output_format: outputFormat,
        }
      : null;

  function invalidateExecutionState() {
    setPreview(null);
    setRiskAcknowledged(false);
    setRiskAuthorization(null);
    setOperationId(null);
    setError(null);
    setStatus((current) =>
      current === "loading" ||
      current === "previewing" ||
      current === "authorizing" ||
      current === "confirming"
        ? current
        : "idle",
    );
  }

  async function handlePreview() {
    if (!projectRoot || !request) return;
    setStatus("previewing");
    setError(null);
    setPreview(null);
    setRiskAcknowledged(false);
    setRiskAuthorization(null);
    setOperationId(null);
    try {
      const response = await previewCodeExecute(projectRoot, request);
      setPreview(response.preview);
      setStatus("idle");
    } catch (reason: unknown) {
      setStatus("error");
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function handleAuthorizeRisk() {
    if (!projectRoot || !request || !preview || preview.status !== "ready" || !riskAcknowledged) return;
    setStatus("authorizing");
    setError(null);
    try {
      const response = await authorizeCodeExecuteRisk(projectRoot, {
        ...request,
        preview_fingerprint: preview.fingerprint,
        acknowledge_risk: true,
      });
      setRiskAuthorization(response.risk_authorization);
      setStatus("idle");
    } catch (reason: unknown) {
      setStatus("error");
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function handleConfirm() {
    if (
      !projectRoot ||
      !request ||
      !preview ||
      preview.status !== "ready" ||
      !riskAuthorization
    ) return;
    setStatus("confirming");
    setError(null);
    try {
      const response = await confirmCodeExecute(projectRoot, {
        ...request,
        preview_fingerprint: preview.fingerprint,
        risk_authorization_id: riskAuthorization.authorization_id,
        risk_authorization_token: riskAuthorization.token,
      });
      const recordId = response.operation.record_id;
      setOperationId(typeof recordId === "string" ? recordId : null);
      setStatus("complete");
    } catch (reason: unknown) {
      setStatus("error");
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const busy = status === "previewing" || status === "authorizing" || status === "confirming";

  return (
    <section
      aria-label="Run code"
      data-testid="code-execute-section"
      style={{ marginTop: 18 }}
    >
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Run code
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
        <div style={{ opacity: 0.75, lineHeight: 1.5 }}>
          Runs in a sandbox: no network, and this node&apos;s data is read-only — the code
          cannot overwrite it. Your code gets <code>df</code> and must bind{" "}
          <code>result</code> to a DataFrame, which becomes a new child data node.
        </div>

        {sourceContext && (
          <div data-testid="code-execute-columns" style={{ opacity: 0.75 }}>
            df: {sourceContext.row_count} rows ·{" "}
            {sourceContext.columns.map((column) => column.name).join(", ")}
          </div>
        )}

        {unavailableReason && (
          <div
            role="status"
            data-testid="code-execute-unavailable"
            style={{ color: "var(--label-tertiary)" }}
          >
            Run preview is disabled: {unavailableReason}. This node has no resolvable,
            materialized data payload for the operation.
          </div>
        )}

        <label htmlFor="code-execute-code" style={{ opacity: 0.75 }}>
          Python
        </label>
        <textarea
          id="code-execute-code"
          data-testid="code-execute-code"
          value={code}
          disabled={busy || unavailableReason !== null}
          spellCheck={false}
          rows={8}
          onChange={(event) => {
            setCode(event.target.value);
            // The preview and any applied state are only meaningful for this code.
            invalidateExecutionState();
          }}
          style={{
            fontFamily: "var(--font-mono, ui-monospace, monospace)",
            fontSize: 12,
            padding: 8,
            borderRadius: 6,
            border: "1px solid var(--separator)",
            background: "var(--bg-input, rgba(0,0,0,0.25))",
            color: "var(--text-primary, #e5e7eb)",
            resize: "vertical",
          }}
        />

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label htmlFor="code-execute-format" style={{ opacity: 0.75 }}>
            Output
          </label>
          <select
            id="code-execute-format"
            data-testid="code-execute-format"
            value={outputFormat}
            disabled={busy || unavailableReason !== null}
            onChange={(event) => {
              setOutputFormat(event.target.value as DataCastOutputFormat);
              invalidateExecutionState();
            }}
          >
            <option value="csv">CSV</option>
            <option value="xlsx">Excel (.xlsx)</option>
          </select>

          <button
            type="button"
            data-testid="code-execute-preview-button"
            onClick={() => void handlePreview()}
            disabled={!request || busy}
          >
            {status === "previewing" ? "Running…" : "Run preview"}
          </button>
          <button
            type="button"
            data-testid="code-execute-confirm-button"
            className="primary"
            onClick={() => void handleConfirm()}
            disabled={!preview || preview.status !== "ready" || !riskAuthorization || busy}
          >
            {status === "confirming" ? "Applying…" : "Apply as new node"}
          </button>
        </div>

        {preview?.status === "blocked" && (
          <div
            data-testid="code-execute-error"
            style={{
              whiteSpace: "pre-wrap",
              fontFamily: "var(--font-mono, ui-monospace, monospace)",
              color: "var(--danger, #f87171)",
              maxHeight: 200,
              overflow: "auto",
            }}
          >
            {preview.error}
          </div>
        )}

        {preview?.status === "ready" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <SchemaDiff preview={preview} />
            {preview.stdout && (
              <pre
                data-testid="code-execute-stdout"
                style={{
                  margin: 0,
                  padding: 6,
                  maxHeight: 140,
                  overflow: "auto",
                  background: "var(--bg-input, rgba(0,0,0,0.25))",
                  borderRadius: 6,
                  fontSize: 11,
                }}
              >
                {preview.stdout}
              </pre>
            )}
            <div style={{ opacity: 0.7 }}>
              Nothing has been written yet — this ran on a copy. Applying creates the
              child node and marks downstream models for rerun.
            </div>
            <div
              data-testid="code-execute-risk-warning"
              style={{
                padding: 8,
                border: "1px solid var(--danger, #f87171)",
                borderRadius: 6,
                lineHeight: 1.45,
              }}
            >
              sandboxed does not mean low risk. This code still creates a new child
              data node and can invalidate downstream model results.
              <label style={{ display: "flex", gap: 6, marginTop: 6, alignItems: "flex-start" }}>
                <input
                  type="checkbox"
                  data-testid="code-execute-risk-acknowledgement"
                  checked={riskAcknowledged}
                  disabled={busy || riskAuthorization !== null}
                  onChange={(event) => {
                    setRiskAcknowledged(event.target.checked);
                    if (!event.target.checked) setRiskAuthorization(null);
                  }}
                />
                <span>I understand this is a high-risk operation and want to continue.</span>
              </label>
            </div>
            {!riskAuthorization ? (
              <button
                type="button"
                data-testid="code-execute-authorize-button"
                disabled={!riskAcknowledged || busy}
                onClick={() => void handleAuthorizeRisk()}
              >
                {status === "authorizing" ? "Authorizing…" : "Authorize high-risk operation"}
              </button>
            ) : (
              <div data-testid="code-execute-risk-authorized" style={{ color: "var(--ok, #4ade80)" }}>
                Risk authorization granted · expires {riskAuthorization.expires_at}
              </div>
            )}
          </div>
        )}

        {status === "complete" && (
          <div data-testid="code-execute-complete" style={{ color: "var(--ok, #4ade80)" }}>
            Applied{operationId ? ` · Operation Record ${operationId}` : ""}
          </div>
        )}

        {status === "error" && error && (
          <div data-testid="code-execute-fetch-error" style={{ color: "var(--danger, #f87171)" }}>
            {error}
          </div>
        )}
      </div>
    </section>
  );
}
