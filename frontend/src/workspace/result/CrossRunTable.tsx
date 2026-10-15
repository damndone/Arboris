// v1.9.0 — saved estimates from several runs in one regression table. It reads
// what each run stored; nothing is re-estimated and the active run does not
// change. Columns are descriptive, not a test of coefficient differences.

import { useEffect, useState } from "react";
import { fetchRunDetail, type ModelResult } from "../../api";
import { buildRegressionTablePacket, RegressionTable } from "../../report/RegressionTable";

type GroupNotes = { runId: string; notes: string[] };

const shortRun = (runId: string) => runId.split("_").pop() ?? runId;

/** A run's models, with ids and evidence sources prefixed by the run so columns from different runs never collide. */
function fromRun(runId: string, models: ModelResult[]): ModelResult[] {
  return models.map((model) => ({
    ...model,
    model_id: `${runId}:${model.model_id}`,
    model_label: `${model.model_type || model.model_id} · ${shortRun(runId)}`,
    coefficients: Object.fromEntries(
      Object.entries(model.coefficients ?? {}).map(([term, coefficient]) => [
        term,
        { ...coefficient, source_id: `${runId}:${coefficient.source_id || `${model.model_id}.${term}`}` },
      ]),
    ),
  }));
}

export function CrossRunTable({ projectRoot, runIds }: { projectRoot: string; runIds: string[] }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [models, setModels] = useState<ModelResult[]>([]);
  const [notes, setNotes] = useState<GroupNotes[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const selectedKey = JSON.stringify(selected.filter((id) => runIds.includes(id)));

  useEffect(() => {
    const ids = JSON.parse(selectedKey) as string[];
    setModels([]);
    setNotes([]);
    setError("");
    if (!ids.length) {
      setLoading(false);
      return undefined;
    }
    let live = true;
    setLoading(true);
    Promise.all(ids.map(async (runId) => fromRun(runId, (await fetchRunDetail(projectRoot, runId)).model_results ?? [])))
      .then((perRun) => {
        if (!live) return;
        setModels(perRun.flat());
        setNotes(
          perRun.flatMap((runModels, index) => {
            const byGroup = buildRegressionTablePacket(runModels).byGroup;
            return byGroup ? [{ runId: ids[index], notes: byGroup }] : [];
          }),
        );
      })
      .catch((reason) => live && setError(String(reason)))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [projectRoot, selectedKey]);

  if (runIds.length < 2) return null;
  const toggle = (id: string, on: boolean) => setSelected((old) => (on ? [...old, id] : old.filter((value) => value !== id)));

  return (
    <section aria-label="Compare saved models">
      <details>
        <summary>Compare saved models side by side</summary>
        <p>Choose runs to put their saved estimates in one table. Columns are descriptive comparisons, not a test of coefficient differences.</p>
        <div className="ws-run-choices" role="group" aria-label="Runs to compare">
          {runIds.map((id) => (
            <label key={id} className="ws-run-choice" title={id}>
              <input type="checkbox" aria-label={`Include run ${id}`} checked={selected.includes(id)} onChange={(event) => toggle(id, event.target.checked)} />
              {shortRun(id)}
            </label>
          ))}
        </div>
        {loading && <p role="status">Loading saved estimates…</p>}
        {error && <p role="alert">{error}</p>}
        {models.length > 0 && <RegressionTable packet={{ ...buildRegressionTablePacket(models), byGroup: undefined }} />}
        {notes.map((group) => (
          <div key={group.runId} role="note" aria-label={`Group evidence for ${group.runId}`}>
            <strong>Run {shortRun(group.runId)}</strong>
            {group.notes.map((note) => <p key={note}>{note}</p>)}
          </div>
        ))}
      </details>
    </section>
  );
}
