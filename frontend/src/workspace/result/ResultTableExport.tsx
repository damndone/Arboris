import { useState } from "react";
import { exportResultTable } from "../../report/reportClient";

export function ResultTableExport({ projectRoot, runId }: { projectRoot: string; runId: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function download() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const blob = await exportResultTable({projectRoot, runId});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = `result-tables-${runId}.xlsx`;
      link.click();
      const revoke = URL.revokeObjectURL.bind(URL);
      setTimeout(() => revoke(url), 1000);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  }
  return <section aria-label="Export result tables"><button type="button" disabled={busy} onClick={() => void download()}>{busy ? "Exporting tables…" : "Export result tables (XLSX)"}</button>{error && <p role="alert">{error}</p>}</section>;
}
