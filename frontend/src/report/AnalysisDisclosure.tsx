import { useEffect, useState } from "react";

import { apiUrl, readResponse } from "../api";

export type DisclosureLine = {
  at: string;
  who: string;
  status: string;
  what: string;
  categories: string[];
  summary: string;
};

export type AnalysisDisclosureValue = {
  run_id: string;
  counts: {
    inferential_tests: number;
    descriptive_analyses: number;
    models: number;
    data_changes: number;
    metadata_changes: number;
    run_deletions: number;
    failed_actions: number;
  };
  inferential_tests_by: Record<string, number>;
  changes: DisclosureLine[];
  entries: DisclosureLine[];
  entries_omitted: number;
  settings: { include_in_exports: boolean; detail: "summary" | "full" };
};

async function fetchDisclosure(projectRoot: string, runId: string): Promise<AnalysisDisclosureValue> {
  const response = await fetch(
    apiUrl(`/runs/${encodeURIComponent(runId)}/analysis-disclosure?project_root=${encodeURIComponent(projectRoot)}`),
  );
  return readResponse<AnalysisDisclosureValue>(response);
}

async function saveSettings(
  projectRoot: string,
  settings: AnalysisDisclosureValue["settings"],
): Promise<AnalysisDisclosureValue["settings"]> {
  const response = await fetch(
    apiUrl(`/projects/report-disclosure?project_root=${encodeURIComponent(projectRoot)}`),
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings) },
  );
  return readResponse(response);
}

const when = (at: string) => at.slice(0, 16).replace("T", " ");

/** What else was done to this report's data, written by Workbench from the
 * analysis ledger -- never by the language model. */
export function AnalysisDisclosure({ projectRoot, runId }: { projectRoot?: string; runId: string | null }) {
  const [value, setValue] = useState<AnalysisDisclosureValue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!projectRoot || !runId) return undefined;
    let cancelled = false;
    setValue(null);
    fetchDisclosure(projectRoot, runId)
      .then((loaded) => {
        if (!cancelled) setValue(loaded);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not load the analysis path");
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId]);

  if (!projectRoot || !runId) return null;
  // Secondary to the report's own errors, so a note rather than an alert.
  if (error) {
    return (
      <div data-testid="analysis-disclosure-error" style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
        Analysis path unavailable: {error}
      </div>
    );
  }
  if (!value) return null;

  async function update(settings: AnalysisDisclosureValue["settings"]) {
    if (!projectRoot || !runId) return;
    setSaving(true);
    setError(null);
    try {
      await saveSettings(projectRoot, settings);
      // The change is itself recorded; reload so the log shows it.
      setValue(await fetchDisclosure(projectRoot, runId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save the disclosure setting");
    } finally {
      setSaving(false);
    }
  }

  const { counts, settings } = value;
  const by = value.inferential_tests_by;
  return (
    <section data-testid="analysis-disclosure" className="report-scope-summary">
      <div className="report-scope-summary__heading">
        <div>
          <strong>Analysis path</strong>
          <span>Everything done to this report&apos;s data, from the analysis ledger</span>
        </div>
        <span className="report-scope-summary__hint">
          Written by Workbench, not by the AI. Counts every test, whether or not the report shows it.
        </span>
      </div>
      <div className="report-scope-summary__facts">
        <div data-testid="analysis-disclosure-counts">
          {counts.inferential_tests} inferential test{counts.inferential_tests === 1 ? "" : "s"}
          {counts.inferential_tests > 0 && (
            <> (Agent without confirmation {by.agent_without_confirmation ?? 0} · Agent confirmed by you{" "}
              {by.agent_confirmed_by_user ?? 0} · you {by.user ?? 0})</>
          )}
          {" "}· {counts.models} model{counts.models === 1 ? "" : "s"} · {counts.descriptive_analyses} descriptive ·{" "}
          {counts.data_changes} data change{counts.data_changes === 1 ? "" : "s"} · {counts.metadata_changes} metadata
          change{counts.metadata_changes === 1 ? "" : "s"} · {counts.run_deletions} run
          {counts.run_deletions === 1 ? "" : "s"} deleted
        </div>
        {value.changes.length > 0 && (
          <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
            {value.changes.map((item) => (
              <li key={`${item.at}-${item.what}`}>
                {when(item.at)} · {item.who} · <code>{item.what}</code>
                {item.summary && <> · {item.summary}</>}
              </li>
            ))}
          </ul>
        )}
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              type="checkbox"
              style={{ width: "auto", margin: 0 }}
              checked={settings.include_in_exports}
              disabled={saving}
              onChange={(event) => void update({ ...settings, include_in_exports: event.target.checked })}
            />
            Include in exported reports
          </label>
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
            Detail
            <select
              aria-label="Disclosure detail"
              value={settings.detail}
              disabled={saving}
              onChange={(event) => void update({ ...settings, detail: event.target.value as "summary" | "full" })}
            >
              <option value="summary">Summary and data changes</option>
              <option value="full">Full analysis log</option>
            </select>
          </label>
          {!settings.include_in_exports && (
            <strong className="report-scope-summary__warning">
              Exports omit this section; the change is recorded in the log.
            </strong>
          )}
        </div>
        {value.entries.length > 0 && (
          <details>
            <summary>Full analysis log ({value.entries.length + value.entries_omitted} entries)</summary>
            <table data-testid="analysis-disclosure-log" style={{ borderCollapse: "collapse", fontSize: 12 }}>
              <tbody>
                {value.entries.map((item) => (
                  <tr key={`${item.at}-${item.what}`} style={{ borderTop: "1px solid var(--separator)" }}>
                    <td style={{ padding: "1px 6px", whiteSpace: "nowrap" }}>{when(item.at)}</td>
                    <td style={{ padding: "1px 6px" }}>{item.who}</td>
                    <td style={{ padding: "1px 6px" }}><code>{item.what}</code></td>
                    <td style={{ padding: "1px 6px" }}>{item.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </div>
    </section>
  );
}
