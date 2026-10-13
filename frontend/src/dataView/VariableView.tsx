import { useEffect, useMemo, useState } from "react";

import {
  patchColumnSensitivity,
  saveMetadata,
  SENSITIVITY_LEVELS,
  type DatasetVariable,
  type MetadataPatch,
  type SensitivityLevel,
} from "./dataViewApi";
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

const SHARING_HELP =
  "Who may see this column's values. Sensitive: never sent to a remote AI provider. " +
  "Restricted: never sent to any AI provider. The column's name is always visible.";

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
  // Sharing levels are project-wide policy, saved at once -- not a new run.
  // The project's explicit level per column; absent means the suggestion applies.
  const [explicitSharing, setExplicitSharing] = useState<Record<string, SensitivityLevel>>({});

  useEffect(() => {
    setExplicitSharing(
      Object.fromEntries(
        variables
          .filter((variable) => variable.sensitivity_source === "project" && variable.sensitivity)
          .map((variable) => [variable.name, variable.sensitivity as SensitivityLevel]),
      ),
    );
  }, [variables]);

  async function changeSharing(column: string, value: string) {
    setError(null);
    try {
      const view = await patchColumnSensitivity(projectRoot, {
        [column]: value === "" ? null : (value as SensitivityLevel),
      });
      setExplicitSharing((current) => {
        const next = { ...current };
        const level = view.policy.columns[column];
        if (level) next[column] = level;
        else delete next[column];
        return next;
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not change sharing");
    }
  }

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

  return (
    <div data-testid="variable-view" className="dv-grid">
      <div className="dv-grid-bar">
        <span>
          {variables.length} variables · {totalRows.toLocaleString("en")} rows · edit any cell; saving makes a new run
        </span>
        <span className="dv-spacer" />
        <button
          type="button"
          className={`dv-button${pending.changes.length ? " dv-button--primary" : ""}`}
          disabled={pending.changes.length === 0 || pending.problem !== null || saving}
          onClick={() => setReviewing(true)}
        >
          Review changes ({pending.changes.length})
        </button>
      </div>
      {pending.problem && <p role="alert" className="dv-alert">{pending.problem}</p>}
      {reviewing && pending.changes.length > 0 && (
        <section data-testid="variable-view-review" className="dv-sheet" aria-label="Review changes">
          <header className="dv-sheet__head">
            <div>
              <h3>Review changes</h3>
              <p>Saving records these changes as a new run in the lineage. Missing-value changes change which rows the models use.</p>
            </div>
          </header>
          <ul className="dv-changes">
            {pending.changes.map((change) => (
              <li key={`${change.column}-${change.field}`}>
                <strong>{change.column}</strong> · {change.field}: {change.from || "—"} → {change.to || "—"}
              </li>
            ))}
          </ul>
          <div className="dv-actions">
            <button type="button" className="dv-button dv-button--primary" disabled={saving} onClick={() => void save()}>
              {saving ? "Saving…" : "Save as new run"}
            </button>
            <button type="button" className="dv-button" disabled={saving} onClick={() => setReviewing(false)}>
              Keep editing
            </button>
          </div>
        </section>
      )}
      {error && <p role="alert" className="dv-alert">{error}</p>}
      <div className="dv-table-wrap" tabIndex={0} aria-label="Variables">
        <table className="dv-table dv-table--edit">
          <thead>
            <tr>
              {["Variable", "Label", "Value labels", "Measure", "Missing codes", "Sharing"].map((heading) => (
                <th key={heading} scope="col" title={heading === "Sharing" ? SHARING_HELP : undefined}>
                  <span className="dv-table__head">{heading}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {variables.map((variable) => {
              const draft = drafts[variable.name] ?? draftOf(variable);
              const summary = [
                variable.type,
                `${variable.missing} blank`,
                variable.declared_missing_matches ? `${variable.declared_missing_matches} coded missing` : null,
                `${variable.unique} distinct`,
                variable.type === "numeric" && variable.min != null ? `${variable.min} to ${variable.max}` : null,
              ].filter(Boolean).join(" · ");
              return (
                <tr key={variable.name}>
                  <td className="dv-var">
                    <span className="dv-var__name">{variable.name}</span>
                    <span className="dv-var__summary">{summary}</span>
                  </td>
                  <td>
                    <input aria-label={`Label of ${variable.name}`} placeholder="Add a label" value={draft.label} onChange={(event) => update(variable.name, "label", event.target.value)} />
                  </td>
                  <td>
                    <input aria-label={`Value labels of ${variable.name}`} placeholder="1 = Low; 2 = High" value={draft.values} onChange={(event) => update(variable.name, "values", event.target.value)} />
                  </td>
                  <td>
                    <select aria-label={`Measure of ${variable.name}`} value={draft.level} onChange={(event) => update(variable.name, "level", event.target.value)}>
                      {LEVELS.map((level) => (
                        <option key={level} value={level}>{level || "—"}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input aria-label={`Missing codes of ${variable.name}`} placeholder="-99, 900..999" value={draft.missing} onChange={(event) => update(variable.name, "missing", event.target.value)} />
                  </td>
                  <td>
                    {variable.sensitivity_suggested ? (
                      <select
                        aria-label={`Sharing of ${variable.name}`}
                        title={SHARING_HELP}
                        value={explicitSharing[variable.name] ?? ""}
                        onChange={(event) => void changeSharing(variable.name, event.target.value)}
                      >
                        <option value="">auto ({variable.sensitivity_suggested})</option>
                        {SENSITIVITY_LEVELS.map((level) => (
                          <option key={level} value={level}>{level}</option>
                        ))}
                      </select>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
