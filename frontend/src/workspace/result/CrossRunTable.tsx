import { useEffect, useState } from "react";
import { fetchRunDetail, type ModelResult } from "../../api";
import { buildRegressionTablePacket, RegressionTable } from "../../report/RegressionTable";

/** Compare saved estimates without changing the active run or rerunning models. */
export function CrossRunTable({ projectRoot, runIds }: {projectRoot: string; runIds: string[]}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [models, setModels] = useState<ModelResult[]>([]);
  const [notes, setNotes] = useState<Array<{runId: string; notes: string[]}>>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const selectedKey = JSON.stringify(selected.filter(id => runIds.includes(id)));
  useEffect(() => {
    const ids = JSON.parse(selectedKey) as string[];
    setModels([]);
    setNotes([]);
    setError("");
    if (!ids.length) { setLoading(false); return; }
    let current = true;
    setLoading(true);
    Promise.all(ids.map(async runId => {
      const detail = await fetchRunDetail(projectRoot, runId);
      return (detail.model_results ?? []).map(model => ({...model,
        model_id: `${runId}:${model.model_id}`,
        coefficients: Object.fromEntries(Object.entries(model.coefficients ?? {}).map(([term, coefficient]) => [term, {...coefficient, source_id: `${runId}:${coefficient.source_id || `${model.model_id}.${term}`}`}])),
        model_label: `${model.model_type || model.model_id} · ${runId.split("_").pop()}`,
      }));
    })).then(results => { if (current) {
      setModels(results.flat());
      setNotes(results.flatMap((models, index) => {
        const notes = buildRegressionTablePacket(models).byGroup;
        return notes ? [{runId: ids[index], notes}] : [];
      }));
    } })
      .catch(reason => { if (current) setError(String(reason)); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [projectRoot, selectedKey]);
  if (runIds.length < 2) return null;
  return <section aria-label="Compare saved models">
    <details><summary>Compare saved models side by side</summary>
      <p>Select runs to assemble a table from their saved estimates. Columns are descriptive comparisons, not a test of coefficient differences.</p>
      {runIds.map(id => <label key={id}><input type="checkbox" aria-label={`Include run ${id}`} checked={selected.includes(id)} onChange={event => setSelected(old => event.target.checked ? [...old, id] : old.filter(value => value !== id))}/>{id.split("_").pop()} </label>)}
      {loading && <p role="status">Loading saved estimates…</p>}
      {error && <p role="alert">{error}</p>}
      {models.length > 0 && <RegressionTable packet={{...buildRegressionTablePacket(models), byGroup: undefined}}/>}
      {notes.map(group => <div key={group.runId} role="note" aria-label={`Group evidence for ${group.runId}`}><strong>Run {group.runId.split("_").pop()}</strong>{group.notes.map(note => <p key={note}>{note}</p>)}</div>)}
    </details>
  </section>;
}
