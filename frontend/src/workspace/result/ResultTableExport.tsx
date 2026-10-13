// v1.9.0 — the result tables of a run as one Excel workbook, re-read from the
// run's saved evidence on the server.

import { useState } from "react";
import { exportResultTable } from "../../report/reportClient";

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  // The click starts the download; the URL can go once the browser has it.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ResultTableExport({ projectRoot, runId }: { projectRoot: string; runId: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function download() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      save(await exportResultTable({ projectRoot, runId }), `result-tables-${runId}.xlsx`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Export result tables">
      <button type="button" disabled={busy} onClick={() => void download()}>
        {busy ? "Exporting tables…" : "Export result tables (XLSX)"}
      </button>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
