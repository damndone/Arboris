import { useEffect, useState } from "react";
import type { ResponseOf, Schema } from "../apiTypes";
import { getProjectAgentPermissions, saveProjectAgentPermissions } from "./agent/agentApi";
import "./agentPermissions.css";

type PermissionView = ResponseOf<"/projects/agent-permissions", "get">;
type Rules = PermissionView["rules"];
type Effect = keyof Rules;
type Rule = Schema<"ProjectAgentPermissionRule">;

const groups = [["allow", "Allow"], ["ask", "Ask"], ["deny", "Deny"]] as const;
const classes: Array<[Rule["class"], string]> = [
  ["read", "Read"],
  ["analyze", "Analyze"],
  ["derive", "Derive"],
  ["modify", "Modify"],
  ["external", "External"],
  ["high", "High risk"],
];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The project rules request failed.";
}

export function AgentPermissionsPanel({ projectRoot }: { projectRoot: string }) {
  const [view, setView] = useState<PermissionView | null>(null);
  const [rules, setRules] = useState<Rules | null>(null);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    let current = true;
    async function load() {
      try {
        const loaded = await getProjectAgentPermissions(projectRoot);
        if (current) {
          setView(loaded);
          setRules(loaded.rules);
        }
      } catch (reason) {
        if (current) setError(errorMessage(reason));
      } finally {
        if (current) setBusy(false);
      }
    }
    void load();
    return () => { current = false; };
  }, [projectRoot, reload]);

  const dirty = Boolean(view && rules && JSON.stringify(view.rules) !== JSON.stringify(rules));

  function edit(effect: Effect, items: Rule[]) {
    setRules((previous) => previous && { ...previous, [effect]: items });
    setStatus("");
  }

  function update(effect: Effect, items: Rule[], selected: number, replacement: Rule) {
    edit(effect, items.map((item, index) => index === selected ? replacement : item));
  }

  function reloadRules() {
    setBusy(true);
    setError("");
    setStatus("");
    setReload((current) => current + 1);
  }

  async function save() {
    if (!view || !rules || busy || !dirty) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const saved = await saveProjectAgentPermissions(projectRoot, {
        expected_revision: view.revision,
        rules,
      });
      setView(saved);
      setRules(saved.rules);
      setStatus("Rules saved.");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="agent-permissions-panel" aria-label="Project Agent permissions">
      <p>Deny takes priority. Protected changes, exports, external actions, and high-risk operations still require approval.</p>
      {busy && !rules ? <p role="status">Loading rules…</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
        {rules && groups.map(([effect, title]) => {
          const items = rules[effect];
          return (
            <fieldset key={effect} disabled={busy}>
              <legend>{title}</legend>
              {items.map((rule, index) => {
                const label = `${title} rule ${index + 1}`;
                return (
                  <div className="agent-permissions-panel__rule" key={index}>
                    <label>
                      Permission class
                      <select aria-label={`${label} permission class`} value={rule.class}
                        onChange={(event) => update(effect, items, index, { ...rule, class: event.target.value as Rule["class"] })}>
                        {classes.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
                      </select>
                    </label>
                    <label>
                      Operation ID
                      <input aria-label={`${label} operation ID`} value={rule.operation_id ?? ""} placeholder="Any operation"
                        onChange={(event) => update(effect, items, index, {
                          class: rule.class,
                          ...(event.target.value ? { operation_id: event.target.value } : {}),
                        })} />
                    </label>
                    <button type="button" aria-label={`Remove ${effect} rule ${index + 1}`}
                      onClick={() => edit(effect, items.filter((_, position) => position !== index))}>
                      Remove
                    </button>
                  </div>
                );
              })}
              <button type="button" onClick={() => edit(effect, [...items, { class: "read" }])}>
                Add {effect} rule
              </button>
            </fieldset>
          );
        })}
        <div className="agent-permissions-panel__actions">
          <button type="button" onClick={reloadRules} disabled={busy}
            title={dirty ? "Discard unsaved edits and load the current project rules" : undefined}>Reload rules</button>
          <button type="submit" disabled={busy || !dirty}>Save rules</button>
          {status ? <span role="status">{status}</span> : null}
        </div>
      </form>
    </section>
  );
}
