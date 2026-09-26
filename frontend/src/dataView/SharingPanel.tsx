import { useEffect, useState } from "react";

import {
  fetchEgress,
  fetchEgressAudit,
  replaceEgressPolicy,
  type EgressAuditRecord,
  type EgressView,
} from "./dataViewApi";

const CLASS_LABELS: Record<string, string> = {
  workbench_state: "Workbench state (operations, lineage, contracts)",
  schema: "Column names and types",
  metadata: "Labels and missing-value codes",
  aggregate: "Summary statistics and frequency tables",
  model_result: "Model results",
  rows: "Individual rows",
  unclassified: "Tool output with no declared class",
};

function sameSet(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item) => right.includes(item));
}

/** What the project lets the AI provider see, and a record of what was sent. */
export function SharingPanel({ projectRoot }: { projectRoot: string }) {
  const [view, setView] = useState<EgressView | null>(null);
  const [audit, setAudit] = useState<EgressAuditRecord[]>([]);
  const [draft, setDraft] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchEgress(projectRoot), fetchEgressAudit(projectRoot, 10)])
      .then(([loaded, records]) => {
        if (cancelled) return;
        setView(loaded);
        setDraft(loaded.active_provider?.allowed_classes ?? []);
        setAudit(records);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not load sharing policy");
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot]);

  if (error) return <div role="alert" style={{ color: "var(--red, #c00)", fontSize: 12 }}>{error}</div>;
  if (!view) return <div style={{ fontSize: 12, color: "var(--label-secondary)" }}>Loading sharing policy…</div>;

  const provider = view.active_provider;
  const providerKey = provider ? provider.provider_id || provider.locality : "";
  const overridden = provider !== null && providerKey in view.policy.providers;
  const defaults = provider ? view.defaults[provider.locality] : [];

  async function save(allow: string[] | null) {
    if (!view) return;
    setSaving(true);
    setError(null);
    const providers = { ...view.policy.providers };
    if (allow === null) delete providers[providerKey];
    else providers[providerKey] = { allow };
    try {
      const next = await replaceEgressPolicy(projectRoot, { ...view.policy, providers });
      setView(next);
      setDraft(next.active_provider?.allowed_classes ?? []);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save sharing policy");
    } finally {
      setSaving(false);
    }
  }

  const protectedColumns = Object.entries(view.policy.columns).filter(
    ([, level]) => level === "sensitive" || level === "restricted",
  );
  const cell = { padding: "2px 6px", textAlign: "left" as const };
  return (
    <div data-testid="sharing-panel" style={{ fontSize: 12, border: "1px solid var(--separator)", padding: 8, marginBottom: 8 }}>
      {provider === null ? (
        <div>No AI provider is configured; nothing is sent.</div>
      ) : (
        <>
          <div style={{ marginBottom: 4 }}>
            <strong>{provider.provider_name || provider.provider_id}</strong> ({provider.locality === "local" ? "runs on this computer" : "remote service"}){" "}
            {overridden ? "· this project's setting" : "· default"} may receive:
          </div>
          <div style={{ display: "grid", gap: 2, marginBottom: 6 }}>
            {view.content_classes.map((contentClass) => (
              <label key={contentClass}>
                <input
                  type="checkbox"
                  aria-label={`Send ${CLASS_LABELS[contentClass] ?? contentClass}`}
                  checked={draft.includes(contentClass)}
                  onChange={(event) =>
                    setDraft((current) =>
                      event.target.checked ? [...current, contentClass] : current.filter((item) => item !== contentClass),
                    )
                  }
                />{" "}
                {CLASS_LABELS[contentClass] ?? contentClass}
              </label>
            ))}
          </div>
          <button type="button" disabled={saving || sameSet(draft, provider.allowed_classes)} onClick={() => void save(draft)}>
            Save for this project
          </button>{" "}
          <button type="button" disabled={saving || !overridden} onClick={() => void save(null)}>
            Use default ({defaults.length} kinds)
          </button>
        </>
      )}
      <div style={{ marginTop: 6, color: "var(--label-secondary)" }}>
        {protectedColumns.length
          ? `Values withheld for: ${protectedColumns.map(([column, level]) => `${column} (${level})`).join(", ")}. `
          : "No column is marked sensitive by this project. "}
        Personal columns such as name, phone or email are withheld from remote providers unless marked public. Change a
        column in Variable View → Sharing.
      </div>
      <div style={{ marginTop: 8, fontWeight: 600 }}>Recent sends</div>
      {audit.length === 0 ? (
        <div style={{ color: "var(--label-secondary)" }}>Nothing has been sent from this project yet.</div>
      ) : (
        <table data-testid="sharing-audit" style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ color: "var(--label-secondary)" }}>
              {["Time", "Provider", "Messages", "Withheld", "Values withheld for"].map((heading) => (
                <th key={heading} style={cell}>{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {audit.map((record) => (
              <tr key={`${record.at}-${record.payload_bytes}`} style={{ borderTop: "1px solid var(--separator)" }}>
                <td style={cell}>{new Date(record.at).toLocaleString()}</td>
                <td style={cell}>{record.provider_host}</td>
                <td style={cell}>{record.message_count}</td>
                <td style={cell}>
                  {record.withheld_count
                    ? record.decisions
                        .filter((decision) => decision.decision.startsWith("withheld"))
                        .map((decision) => decision.tool_id ?? decision.withheld_protocols?.join(", ") ?? decision.role)
                        .join(", ")
                    : "—"}
                </td>
                <td style={cell}>{record.redacted_columns.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
