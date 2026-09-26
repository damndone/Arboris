import { useEffect, useMemo, useState } from "react";

import { saveMetadata, type DatasetVariable, type MetadataPatch } from "./dataViewApi";
import {
  formatMissingCodes,
  formatValueLabels,
  parseMissingCodes,
  parseValueLabels,
} from "./metadataText";

const LEVELS = ["", "nominal", "ordinal", "scale", "count"] as const;

type Draft = { label: string; values: string; level: string; missing: string };

function draftOf(variable: DatasetVariable): Draft {
  return {
    label: variable.variable_label ?? "",
    values: formatValueLabels(variable.value_labels),
    level: variable.measurement_level && variable.measurement_level !== "unspecified" ? variable.measurement_level : "",
    missing: formatMissingCodes(variable.user_missing_values),
  };
}

type Change = { column: string; field: string; from: string; to: string };

/** Build the labels patch for edited variables; throws on unparseable input. */
export function buildMetadataPatch(
  variables: DatasetVariable[],
  drafts: Record<string, Draft>,
): { patch: MetadataPatch; changes: Change[] } {
  const patch: Record<string, Record<string, unknown>> = {};
  const changes: Change[] = [];
  const set = (field: string, column: string, value: unknown) => {
    patch[field] = { ...(patch[field] ?? {}), [column]: value };
  };
  for (const variable of variables) {
    const before = draftOf(variable);
    const after = drafts[variable.name];
    if (!after) continue;
    if (after.label.trim() !== before.label) {
      set("variable_labels", variable.name, after.label.trim() || null);
      changes.push({ column: variable.name, field: "Label", from: before.label, to: after.label.trim() });
    }
    if (after.values.trim() !== before.values) {
      const parsed = parseValueLabels(after.values);
      set("value_labels", variable.name, Object.keys(parsed).length ? parsed : null);
      changes.push({ column: variable.name, field: "Values", from: before.values, to: formatValueLabels(parsed) });
    }
    if (after.level !== before.level) {
      set("measurement_level", variable.name, after.level || null);
      changes.push({ column: variable.name, field: "Measure", from: before.level, to: after.level });
    }
    if (after.missing.trim() !== before.missing) {
      const parsed = parseMissingCodes(after.missing);
      set("user_missing_values", variable.name, parsed.length ? parsed : null);
      changes.push({ column: variable.name, field: "Missing", from: before.missing, to: formatMissingCodes(parsed) });
    }
  }
  return { patch, changes };
}

/** SPSS "Variable View": one row per variable, metadata editable in place. */
export function VariableView({
  projectRoot,
  runId,
  variables,
  totalRows,
  onSaved,
}: {
  projectRoot: string;
  runId: string;
  variables: DatasetVariable[];
  totalRows: number;
  onSaved: (newRunId: string) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [reviewing, setReviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDrafts(Object.fromEntries(variables.map((variable) => [variable.name, draftOf(variable)])));
    setReviewing(false);
    setError(null);
  }, [variables]);

  const pending = useMemo(() => {
    try {
      return { ...buildMetadataPatch(variables, drafts), problem: null as string | null };
    } catch (caught) {
      return { patch: {}, changes: [], problem: caught instanceof Error ? caught.message : String(caught) };
    }
  }, [variables, drafts]);

  function update(column: string, field: keyof Draft, value: string) {
    setReviewing(false);
    setDrafts((current) => ({ ...current, [column]: { ...current[column], [field]: value } }));
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const result = await saveMetadata(projectRoot, runId, pending.patch);
      onSaved(result.run_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  const cell = { padding: "2px 6px", verticalAlign: "top" } as const;
  return (
    <div data-testid="variable-view">
      <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, marginBottom: 6 }}>
        <span style={{ color: "var(--label-secondary)" }}>
          {variables.length} variables · {totalRows} rows · values as "1 = Low; 2 = High", missing as "-99, 900..999"
        </span>
        <button
          type="button"
          disabled={pending.changes.length === 0 || pending.problem !== null || saving}
          onClick={() => setReviewing(true)}
        >
          Review changes ({pending.changes.length})
        </button>
      </div>
      {pending.problem && (
        <div role="alert" style={{ color: "var(--red, #c00)", fontSize: 12, marginBottom: 6 }}>
          {pending.problem}
        </div>
      )}
      {reviewing && pending.changes.length > 0 && (
        <div data-testid="variable-view-review" style={{ fontSize: 12, border: "1px solid var(--separator)", padding: 8, marginBottom: 8 }}>
          <div style={{ marginBottom: 4 }}>
            Saving records these changes as a new run in the lineage. Missing-value changes change
            which rows the models use.
          </div>
          <ul style={{ margin: "0 0 6px", paddingLeft: 18 }}>
            {pending.changes.map((change) => (
              <li key={`${change.column}-${change.field}`}>
                <strong>{change.column}</strong> · {change.field}: {change.from || "—"} → {change.to || "—"}
              </li>
            ))}
          </ul>
          <button type="button" disabled={saving} onClick={() => void save()}>
            {saving ? "Saving…" : "Save as new run"}
          </button>{" "}
          <button type="button" disabled={saving} onClick={() => setReviewing(false)}>
            Keep editing
          </button>
        </div>
      )}
      {error && (
        <div role="alert" style={{ color: "var(--red, #c00)", fontSize: 12, marginBottom: 6 }}>{error}</div>
      )}
      <div className="wb-result-table-scroll" tabIndex={0} aria-label="Variables" style={{ maxHeight: "60vh", overflowY: "auto" }}>
        <table className="wb-result-table" style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--label-secondary)" }}>
              {["Name", "Type", "Label", "Values", "Measure", "Missing", "Summary"].map((heading) => (
                <th key={heading} style={cell}>{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {variables.map((variable) => {
              const draft = drafts[variable.name] ?? draftOf(variable);
              const summary = [
                `${variable.missing} blank`,
                variable.declared_missing_matches ? `${variable.declared_missing_matches} coded missing` : null,
                `${variable.unique} distinct`,
                variable.type === "numeric" && variable.min != null ? `${variable.min} to ${variable.max}` : null,
              ].filter(Boolean).join(" · ");
              return (
                <tr key={variable.name} style={{ borderTop: "1px solid var(--separator)" }}>
                  <td style={{ ...cell, fontFamily: "var(--font-mono, monospace)" }}>{variable.name}</td>
                  <td style={cell}>{variable.type}</td>
                  <td style={cell}>
                    <input aria-label={`Label of ${variable.name}`} value={draft.label} onChange={(event) => update(variable.name, "label", event.target.value)} />
                  </td>
                  <td style={cell}>
                    <input aria-label={`Value labels of ${variable.name}`} value={draft.values} onChange={(event) => update(variable.name, "values", event.target.value)} size={24} />
                  </td>
                  <td style={cell}>
                    <select aria-label={`Measure of ${variable.name}`} value={draft.level} onChange={(event) => update(variable.name, "level", event.target.value)}>
                      {LEVELS.map((level) => (
                        <option key={level} value={level}>{level || "—"}</option>
                      ))}
                    </select>
                  </td>
                  <td style={cell}>
                    <input aria-label={`Missing codes of ${variable.name}`} value={draft.missing} onChange={(event) => update(variable.name, "missing", event.target.value)} size={12} />
                  </td>
                  <td style={{ ...cell, color: "var(--label-secondary)", whiteSpace: "nowrap" }}>{summary}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
