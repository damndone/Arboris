import { useMemo, useState } from "react";
import { artifactDownloadUrl } from "../../../api";
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

export function StatisticalPlotSection({ projectRoot, request, numericColumns }: Props) {
  const [xColumn, setXColumn] = useState(numericColumns[0] ?? "");
  const [yColumn, setYColumn] = useState(numericColumns[1] ?? numericColumns[0] ?? "");
  const [preview, setPreview] = useState<StatisticalExplorationPreview | null>(null);
  const [plotArtifactId, setPlotArtifactId] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "previewing" | "confirming" | "complete" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const plotRequest = useMemo<StatisticalExplorationRequest>(() => ({
    ...request,
    operation: "scatter",
    selected_columns: [xColumn, yColumn].filter(Boolean),
    options: { x_column: xColumn, y_column: yColumn },
  }), [request, xColumn, yColumn]);

  async function handlePreview() {
    setStatus("previewing");
    setError(null);
    try {
      const response = await previewStatisticalExploration(projectRoot, plotRequest);
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
      const response = await confirmStatisticalExploration(projectRoot, {
        ...plotRequest,
        preview_fingerprint: preview.fingerprint,
      });
      const plot = (response as unknown as { plot?: { artifact_id?: unknown } }).plot;
      setPlotArtifactId(typeof plot?.artifact_id === "string" ? plot.artifact_id : null);
      setStatus("complete");
    } catch (reason: unknown) {
      setStatus("error");
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const plot = preview?.result.plot;
  const plotSummary = plot && typeof plot === "object" ? plot as { plotted_row_count?: unknown; x_column?: unknown; y_column?: unknown } : null;
  const imageUrl = plotArtifactId
    ? artifactDownloadUrl(projectRoot, request.source_run_id, plotArtifactId)
    : null;

  return (
    <div data-testid="statistical-plot-builder" className="statistical-exploration-derived">
      <strong>Scatter plot</strong>
      <label>X variable <select data-testid="statistical-plot-x" value={xColumn} onChange={(event) => { setXColumn(event.target.value); setPreview(null); }}>
        {numericColumns.map((column) => <option key={column} value={column}>{column}</option>)}
      </select></label>
      <label>Y variable <select data-testid="statistical-plot-y" value={yColumn} onChange={(event) => { setYColumn(event.target.value); setPreview(null); }}>
        {numericColumns.map((column) => <option key={column} value={column}>{column}</option>)}
      </select></label>
      <button type="button" data-testid="statistical-plot-preview" disabled={!xColumn || !yColumn || xColumn === yColumn || status === "previewing" || status === "confirming"} onClick={() => void handlePreview()}>
        {status === "previewing" ? "Previewing…" : "Preview scatter"}
      </button>
      {preview && <div data-testid="statistical-plot-preview-result">{String(plotSummary?.y_column)} versus {String(plotSummary?.x_column)} · N={String(plotSummary?.plotted_row_count)}</div>}
      {preview?.status === "ready" && <button type="button" data-testid="statistical-plot-confirm" disabled={status === "confirming"} onClick={() => void handleConfirm()}>
        {status === "confirming" ? "Saving…" : "Save plot"}
      </button>}
      {imageUrl && <img data-testid="statistical-plot-image" src={imageUrl} alt={`${String(plotSummary?.y_column)} versus ${String(plotSummary?.x_column)}`} />}
      {status === "error" && <div data-testid="statistical-plot-error">{error}</div>}
      {status === "complete" && <div data-testid="statistical-plot-complete">Plot saved as a figure artifact.</div>}
    </div>
  );
}
