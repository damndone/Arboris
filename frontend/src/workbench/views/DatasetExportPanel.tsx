import { useEffect, useState } from "react";

import {
  artifactDownloadUrl,
  exportDataset,
  previewDatasetExport,
  type DatasetExportFilter,
  type DatasetExportFormat,
  type DatasetExportOptions,
  type DatasetExportPreview,
  type DatasetExportResult,
} from "../../api";
import { fetchDatasetVariables, listDatasets, type DatasetNode } from "../../dataView/dataViewApi";

const FORMATS: { format: DatasetExportFormat; label: string }[] = [
  { format: "dta", label: "Stata (.dta)" },
  { format: "sav", label: "SPSS (.sav)" },
  { format: "zsav", label: "SPSS compressed (.zsav)" },
  { format: "csv", label: "CSV (.csv)" },
  { format: "xlsx", label: "Excel (.xlsx)" },
];

const DTA_VERSIONS = [
  { version: 14, label: "Stata 14–18 (format 118)" },
  { version: 13, label: "Stata 13 (format 117, no Unicode)" },
  { version: 15, label: "Stata 15–18, over 32,767 variables (format 119)" },
] as const;

const FILTER_OPS = [
  ["eq", "="], ["ne", "≠"], ["gt", ">"], ["ge", "≥"], ["lt", "<"], ["le", "≤"],
  ["is_missing", "is missing"], ["not_missing", "is not missing"],
] as const;

type FilterDraft = { column: string; op: string; value: string };

function filterValue(text: string): unknown {
  const number = Number(text);
  return text.trim() !== "" && Number.isFinite(number) ? number : text;
}

/** Export a dataset the way the user chooses -- variables, rows, format,
 * labels, missing codes, file name -- and show what the file will hold first. */
export function DatasetExportPanel({
  projectRoot,
  runId,
  nodeId: fixedNodeId,
}: {
  projectRoot: string;
  runId: string;
  nodeId?: string;
}) {
  const [datasets, setDatasets] = useState<DatasetNode[]>([]);
  const [nodeId, setNodeId] = useState<string>(fixedNodeId ?? "stage:raw");
  const [variables, setVariables] = useState<string[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [format, setFormat] = useState<DatasetExportFormat>("dta");
  const [dtaVersion, setDtaVersion] = useState<13 | 14 | 15>(14);
  const [valueLabels, setValueLabels] = useState<"labels" | "strings" | "none">("labels");
  const [missingCodes, setMissingCodes] = useState<"as_missing" | "keep_codes">("as_missing");
  const [filename, setFilename] = useState("");
  const [filters, setFilters] = useState<FilterDraft[]>([]);
  const [preview, setPreview] = useState<DatasetExportPreview | null>(null);
  const [result, setResult] = useState<DatasetExportResult | null>(null);
  const [busy, setBusy] = useState<"preview" | "export" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (fixedNodeId) setNodeId(fixedNodeId);
  }, [fixedNodeId]);

  useEffect(() => {
    if (!projectRoot || fixedNodeId) return;
    listDatasets(projectRoot, runId).then(setDatasets).catch(() => setDatasets([]));
  }, [projectRoot, runId, fixedNodeId]);

  useEffect(() => {
    if (!projectRoot) return;
    let cancelled = false;
    fetchDatasetVariables(projectRoot, runId, nodeId)
      .then((loaded) => {
        if (cancelled) return;
        const names = loaded.variables.map((variable) => variable.name);
        setVariables(names);
        setChosen(new Set(names));
      })
      .catch(() => {
        if (!cancelled) setVariables([]);
      });
    setPreview(null);
    setResult(null);
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, nodeId]);

  function options(): DatasetExportOptions {
    const columns = variables.filter((name) => chosen.has(name));
    return {
      format,
      columns: columns.length === variables.length ? null : columns,
      filters: filters
        .filter((item) => item.column)
        .map<DatasetExportFilter>((item) =>
          item.op === "is_missing" || item.op === "not_missing"
            ? { column: item.column, op: item.op }
            : { column: item.column, op: item.op, value: filterValue(item.value) },
        ),
      dta_version: format === "dta" ? dtaVersion : undefined,
      value_labels: valueLabels,
      missing_codes: missingCodes,
      filename: filename.trim() || null,
    };
  }

  async function runPreview() {
    setBusy("preview");
    setError(null);
    setResult(null);
    try {
      setPreview(await previewDatasetExport(projectRoot, runId, nodeId, options()));
    } catch (caught) {
      setPreview(null);
      setError(caught instanceof Error ? caught.message : "Preview failed");
    } finally {
      setBusy(null);
    }
  }

  async function runExport() {
    setBusy("export");
    setError(null);
    try {
      const exported = await exportDataset(projectRoot, runId, nodeId, options());
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

  const toggle = (name: string) =>
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  const report = result?.report ?? preview;
  const row = { display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 6 } as const;
  return (
    <section data-testid="table-view-dataset-export" style={{ marginTop: 16, fontSize: 12 }}>
      <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>Export data</h3>
      <div style={row}>
        {!fixedNodeId && (
          <select aria-label="Dataset to export" value={nodeId} onChange={(event) => setNodeId(event.target.value)}>
            {(datasets.length ? datasets : [{ node_id: "stage:raw", label: "Raw input data" }, { node_id: "stage:cleaned", label: "Cleaned data" }]).map((node) => (
              <option key={node.node_id} value={node.node_id}>{node.label} ({node.node_id})</option>
            ))}
          </select>
        )}
        <select aria-label="Export format" value={format} onChange={(event) => setFormat(event.target.value as DatasetExportFormat)}>
          {FORMATS.map((item) => <option key={item.format} value={item.format}>{item.label}</option>)}
        </select>
        {format === "dta" && (
          <select aria-label="Stata version" value={dtaVersion} onChange={(event) => setDtaVersion(Number(event.target.value) as 13 | 14 | 15)}>
            {DTA_VERSIONS.map((item) => <option key={item.version} value={item.version}>{item.label}</option>)}
          </select>
        )}
        <input aria-label="File name" placeholder="file name (optional)" value={filename} onChange={(event) => setFilename(event.target.value)} size={18} />
      </div>
      <div style={row}>
        <label>
          Value labels{" "}
          <select aria-label="Value labels" value={valueLabels} onChange={(event) => setValueLabels(event.target.value as typeof valueLabels)}>
            <option value="labels">keep codes and label sets</option>
            <option value="strings">write label text instead of codes</option>
            <option value="none">codes only</option>
          </select>
        </label>
        <label>
          Declared missing codes{" "}
          <select aria-label="Declared missing codes" value={missingCodes} onChange={(event) => setMissingCodes(event.target.value as typeof missingCodes)}>
            <option value="as_missing">write as missing</option>
            <option value="keep_codes">keep as values</option>
          </select>
        </label>
      </div>
      <details style={{ marginBottom: 6 }}>
        <summary>Variables ({chosen.size} of {variables.length})</summary>
        <div style={{ ...row, marginTop: 4 }}>
          <button type="button" onClick={() => setChosen(new Set(variables))}>All</button>
          <button type="button" onClick={() => setChosen(new Set())}>None</button>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px" }}>
          {variables.map((name) => (
            <label key={name} style={{ display: "flex", gap: 4, alignItems: "center" }}>
              <input type="checkbox" style={{ width: "auto", margin: 0 }} aria-label={`Export ${name}`} checked={chosen.has(name)} onChange={() => toggle(name)} />
              {name}
            </label>
          ))}
        </div>
      </details>
      <details style={{ marginBottom: 6 }}>
        <summary>Rows ({filters.length ? `${filters.length} condition${filters.length === 1 ? "" : "s"}` : "all"})</summary>
        {filters.map((item, index) => (
          <div key={index} style={{ ...row, marginTop: 4 }}>
            <select aria-label={`Row condition ${index + 1} variable`} value={item.column}
              onChange={(event) => setFilters((current) => current.map((entry, at) => (at === index ? { ...entry, column: event.target.value } : entry)))}>
              <option value="">variable…</option>
              {variables.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
            <select aria-label={`Row condition ${index + 1} operator`} value={item.op}
              onChange={(event) => setFilters((current) => current.map((entry, at) => (at === index ? { ...entry, op: event.target.value } : entry)))}>
              {FILTER_OPS.map(([op, text]) => <option key={op} value={op}>{text}</option>)}
            </select>
            {item.op !== "is_missing" && item.op !== "not_missing" && (
              <input aria-label={`Row condition ${index + 1} value`} value={item.value} size={10}
                onChange={(event) => setFilters((current) => current.map((entry, at) => (at === index ? { ...entry, value: event.target.value } : entry)))} />
            )}
            <button type="button" onClick={() => setFilters((current) => current.filter((_, at) => at !== index))}>Remove</button>
          </div>
        ))}
        <button type="button" style={{ marginTop: 4 }} onClick={() => setFilters((current) => [...current, { column: "", op: "eq", value: "" }])}>
          Add condition
        </button>
      </details>
      <div style={row}>
        <button type="button" disabled={busy !== null || chosen.size === 0} onClick={() => void runPreview()}>
          {busy === "preview" ? "Previewing…" : "Preview"}
        </button>
        <button type="button" className="wb-button" disabled={busy !== null || chosen.size === 0 || !projectRoot} onClick={() => void runExport()}>
          {busy === "export" ? "Exporting…" : "Export"}
        </button>
      </div>
      {error && <div role="alert" style={{ color: "var(--red)", marginTop: 6 }}>{error}</div>}
      {report && (
        <div data-testid="dataset-export-report" style={{ marginTop: 6, color: "var(--label-secondary)" }}>
          <div>
            {result ? `Exported ${result.filename}` : `Preview of ${preview?.filename ?? "the file"}`} · {report.rows} rows ·{" "}
            {report.columns} columns
          </div>
          {report.notes.length === 0 ? (
            <div>All labels, measurement levels and missing codes are written.</div>
          ) : (
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {report.notes.map((note, index) => (
                <li key={`${note.column}-${note.field}-${index}`}>
                  <strong>{note.column}</strong> ({note.field}): {note.message}
                </li>
              ))}
            </ul>
          )}
          {!result && preview && preview.sample.length > 0 && (
            <table data-testid="dataset-export-sample" style={{ borderCollapse: "collapse", marginTop: 4 }}>
              <thead>
                <tr>{preview.column_names.map((name) => <th key={name} style={{ padding: "1px 6px", textAlign: "left" }}>{name}</th>)}</tr>
              </thead>
              <tbody>
                {preview.sample.map((sampleRow, index) => (
                  <tr key={index} style={{ borderTop: "1px solid var(--separator)" }}>
                    {preview.column_names.map((name) => (
                      <td key={name} style={{ padding: "1px 6px" }}>{sampleRow[name] === null || sampleRow[name] === undefined ? "" : String(sampleRow[name])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}
