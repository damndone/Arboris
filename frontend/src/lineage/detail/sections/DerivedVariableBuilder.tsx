import { useMemo, useState } from "react";
import {
  confirmStatisticalExploration,
  previewStatisticalExploration,
  type StatisticalExplorationPreview,
  type StatisticalExplorationRequest,
} from "../../statisticalExploration";

interface Props {
  projectRoot: string;
  request: StatisticalExplorationRequest;
  numericColumns: string[];
}

export function DerivedVariableBuilder({ projectRoot, request, numericColumns }: Props) {
  const [sourceColumn, setSourceColumn] = useState(numericColumns[0] ?? "");
  const [percentile, setPercentile] = useState(25);
  const [comparison, setComparison] = useState<"lte" | "gte">("lte");
  const [outputName, setOutputName] = useState("small_school");
  const [preview, setPreview] = useState<StatisticalExplorationPreview | null>(null);
  const [status, setStatus] = useState<"idle" | "previewing" | "confirming" | "complete" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const derivedRequest = useMemo<StatisticalExplorationRequest>(() => ({
    ...request,
    operation: "derive_boolean",
    selected_columns: sourceColumn ? [sourceColumn] : [],
    options: {
      source_column: sourceColumn,
      percentile,
      comparison,
      output_name: outputName,
    },
  }), [comparison, outputName, percentile, request, sourceColumn]);

  async function handlePreview() {
    setStatus("previewing");
    setError(null);
    try {
      const response = await previewStatisticalExploration(projectRoot, derivedRequest);
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
      await confirmStatisticalExploration(projectRoot, {
        ...derivedRequest,
        preview_fingerprint: preview.fingerprint,
      });
      setStatus("complete");
    } catch (reason: unknown) {
      setStatus("error");
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const derived = preview?.result.derived;
  const threshold = derived && typeof derived === "object" ? (derived as { threshold?: unknown }).threshold : null;

  return (
    <div data-testid="derived-variable-builder" className="statistical-exploration-derived">
      <strong>Derived percentile variable</strong>
      <label>
        Source column
        <select data-testid="derived-variable-source" value={sourceColumn} onChange={(event) => { setSourceColumn(event.target.value); setPreview(null); }}>
          {numericColumns.map((column) => <option key={column} value={column}>{column}</option>)}
        </select>
      </label>
      <label>
        Percentile
        <input data-testid="derived-variable-percentile" type="number" min="0" max="100" value={percentile} onChange={(event) => { setPercentile(Number(event.target.value)); setPreview(null); }} />
      </label>
      <label>
        Comparison
        <select data-testid="derived-variable-comparison" value={comparison} onChange={(event) => { setComparison(event.target.value as "lte" | "gte"); setPreview(null); }}>
          <option value="lte">≤ threshold</option>
          <option value="gte">≥ threshold</option>
        </select>
      </label>
      <label>
        New variable name
        <input data-testid="derived-variable-output" value={outputName} onChange={(event) => { setOutputName(event.target.value); setPreview(null); }} />
      </label>
      <div style={{ color: "var(--label-tertiary)" }}>The threshold is computed from the current source context and revalidated before saving.</div>
      <div>
        <button type="button" data-testid="derived-variable-preview" disabled={!sourceColumn || status === "previewing" || status === "confirming"} onClick={() => void handlePreview()}>
          {status === "previewing" ? "Previewing…" : "Preview derived variable"}
        </button>
        {preview?.status === "ready" && (
          <button type="button" data-testid="derived-variable-confirm" disabled={status === "confirming"} onClick={() => void handleConfirm()}>
            {status === "confirming" ? "Saving…" : "Save derived variable"}
          </button>
        )}
      </div>
      {preview && (
        <div data-testid="derived-variable-preview-result">
          Threshold: {String(threshold)} · fingerprint {preview.fingerprint}
        </div>
      )}
      {status === "error" && <div data-testid="derived-variable-error">{error}</div>}
      {status === "complete" && <div data-testid="derived-variable-complete">Derived variable saved as a child data node.</div>}
    </div>
  );
}
