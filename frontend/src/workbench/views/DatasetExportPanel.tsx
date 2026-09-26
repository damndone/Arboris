import { useState } from "react";

import {
  artifactDownloadUrl,
  exportDataset,
  type DatasetExportFormat,
  type DatasetExportResult,
} from "../../api";

const SOURCES = [
  { nodeId: "stage:raw", label: "Source data (as uploaded, missing codes kept)" },
  { nodeId: "stage:cleaned", label: "Cleaned data (as analysed)" },
] as const;

const FORMATS: { format: DatasetExportFormat; label: string }[] = [
  { format: "sav", label: "SPSS (.sav)" },
  { format: "zsav", label: "SPSS compressed (.zsav)" },
  { format: "dta", label: "Stata (.dta)" },
];

/** Export a run's dataset to SPSS/Stata and say what the format could not hold. */
export function DatasetExportPanel({
  projectRoot,
  runId,
}: {
  projectRoot: string;
  runId: string;
}) {
  const [nodeId, setNodeId] = useState<string>(SOURCES[0].nodeId);
  const [busy, setBusy] = useState<DatasetExportFormat | null>(null);
  const [result, setResult] = useState<DatasetExportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(format: DatasetExportFormat) {
    setBusy(format);
    setError(null);
    setResult(null);
    try {
      const exported = await exportDataset(projectRoot, runId, nodeId, format);
      setResult(exported);
      const link = document.createElement("a");
      link.href = artifactDownloadUrl(projectRoot, runId, exported.artifact_id);
      link.download = exported.filename;
      link.click();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Export failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section data-testid="table-view-dataset-export" style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>Export data</h3>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", fontSize: 12 }}>
        <select
          aria-label="Dataset to export"
          value={nodeId}
          onChange={(event) => setNodeId(event.target.value)}
          disabled={busy !== null}
        >
          {SOURCES.map((source) => (
            <option key={source.nodeId} value={source.nodeId}>
              {source.label}
            </option>
          ))}
        </select>
        {FORMATS.map(({ format, label }) => (
          <button
            key={format}
            type="button"
            className="wb-button"
            disabled={busy !== null || !projectRoot}
            onClick={() => void run(format)}
          >
            {busy === format ? "Exporting…" : label}
          </button>
        ))}
      </div>
      {error && (
        <div role="alert" style={{ color: "var(--red, #c00)", fontSize: 12, marginTop: 6 }}>
          {error}
        </div>
      )}
      {result && (
        <div data-testid="dataset-export-report" style={{ fontSize: 12, marginTop: 6, color: "var(--label-secondary)" }}>
          <div>
            {result.filename} · {result.report.rows} rows · {result.report.columns} columns
          </div>
          {result.report.notes.length === 0 ? (
            <div>All labels, measurement levels and missing codes were written.</div>
          ) : (
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {result.report.notes.map((note, index) => (
                <li key={`${note.column}-${note.field}-${index}`}>
                  <strong>{note.column}</strong> ({note.field}): {note.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
