import { useEffect, useState, type ReactNode } from "react";

import {
  fetchEgress,
  fetchEgressAudit,
  replaceEgressPolicy,
  type ContentClass,
  type EgressAuditRecord,
  type EgressView,
} from "./dataViewApi";
import { ToolSheet } from "./ToolSheet";

const CLASS_LABELS: Record<ContentClass, string> = {
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
export function SharingPanel({ projectRoot, onClose }: { projectRoot: string; onClose?: () => void }) {
  const [view, setView] = useState<EgressView | null>(null);
  const [audit, setAudit] = useState<EgressAuditRecord[]>([]);
  const [draft, setDraft] = useState<ContentClass[]>([]);
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

  const sheet = (body: ReactNode) => (
    <ToolSheet
      title="AI sharing"
      description="What the AI provider may receive from this project, and a record of what was sent. Analyses here never need it."
      onClose={onClose}
      testId="sharing-panel"
    >
      {body}
    </ToolSheet>
  );
  if (error && !view) return sheet(<p role="alert" className="dv-alert">{error}</p>);
  if (!view) return sheet(<p className="dv-note">Loading sharing policy…</p>);

  const provider = view.active_provider;
  const providerKey = provider ? provider.provider_id || provider.locality : "";
  const overridden = provider !== null && providerKey in view.policy.providers;
  const defaults = provider ? view.defaults[provider.locality] : [];

  async function save(allow: ContentClass[] | null) {
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
  const timeFormat = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });
  return sheet(
    <>
      {error && <p role="alert" className="dv-alert">{error}</p>}
      {provider === null ? (
        <p className="dv-note">No AI provider is configured; nothing is sent.</p>
      ) : (
        <div className="dv-sheet__section">
          <h4>
            <span>{provider.provider_name || provider.provider_id}</span> · {provider.locality === "local" ? "runs on this computer" : "remote service"} ·{" "}
            {overridden ? "this project's setting" : "default"}
          </h4>
          <div className="dv-checklist">
            {view.content_classes.map((contentClass) => (
              <label key={contentClass}>
                <input
                  type="checkbox"
                  aria-label={`Send ${CLASS_LABELS[contentClass]}`}
                  checked={draft.includes(contentClass)}
                  onChange={(event) =>
                    setDraft((current) =>
                      event.target.checked ? [...current, contentClass] : current.filter((item) => item !== contentClass),
                    )
                  }
                />
                {CLASS_LABELS[contentClass]}
              </label>
            ))}
          </div>
          <div className="dv-actions">
            <button type="button" className="dv-button dv-button--primary" disabled={saving || sameSet(draft, provider.allowed_classes)} onClick={() => void save(draft)}>
              Save for this project
            </button>
            <button type="button" className="dv-button" disabled={saving || !overridden} onClick={() => void save(null)}>
              Use default ({defaults.length} kinds)
            </button>
          </div>
        </div>
      )}
      <p className="dv-note">
        {protectedColumns.length
          ? `Values withheld for: ${protectedColumns.map(([column, level]) => `${column} (${level})`).join(", ")}. `
          : "No column is marked sensitive by this project. "}
        Personal columns such as name, phone or email are withheld from remote providers unless marked public. Change a
        column in Variable View → Sharing.
      </p>
      <div className="dv-sheet__section">
        <h4>Recent sends</h4>
        {audit.length === 0 ? (
          <p className="dv-note">Nothing has been sent from this project yet.</p>
        ) : (
          <table data-testid="sharing-audit" className="dv-mini-table">
            <thead>
              <tr>
                {["Time", "Provider", "Messages", "Withheld", "Values withheld for"].map((heading) => (
                  <th key={heading} scope="col">{heading}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {audit.map((record) => (
                <tr key={`${record.at}-${record.payload_bytes}`}>
                  <td>{timeFormat.format(new Date(record.at))}</td>
                  <td>{record.provider_host}</td>
                  <td>{record.message_count}</td>
                  <td>
                    {record.withheld_count
                      ? record.decisions
                          .filter((decision) => decision.decision.startsWith("withheld"))
                          .map((decision) => decision.tool_id ?? decision.withheld_protocols?.join(", ") ?? decision.role)
                          .join(", ")
                      : "—"}
                  </td>
                  <td>{record.redacted_columns.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>,
  );
}
