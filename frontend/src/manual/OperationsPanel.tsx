import { useEffect, useRef, useState } from "react";
import { listDatasets, fetchDatasetPage } from "../dataView/dataViewApi";
import { readResponse } from "../api";
import { catalog, execute, manualUrl, type Operation, type Target, type Outcome } from "./manualApi";
import { SchemaField, initialValue, type JsonSchema } from "./SchemaFields";
import "./manual.css";
import { validateValue } from "./schemaModel";
import { dedicatedTargetReason } from "./dedicatedTarget";
export type ModelChoice = {
    runId: string;
    nodeId: string;
    label: string;
};
type Choice = {
    label: string;
    target: Target;
    columns: string[];
};
type Step = {
    step_id: string;
    operation_id: string;
    spec: Record<string, unknown>;
};
const uid = () => crypto.randomUUID();
export function OperationsPanel({ projectRoot, runId, models, initialSearch = "", onClose, onRefresh, onOpenRun, onDedicated }: {
    projectRoot: string;
    runId: string;
    initialSearch?: string;
    models: ModelChoice[];
    onClose: () => void;
    onRefresh: () => void;
    onOpenRun: (runId: string) => void;
    onDedicated: (id: string, target?: Target) => void;
}) {
    // A newly produced run can become active while this editor is still open.
    // Keep this operation session bound to its original source and receipt.
    const [sourceRunId] = useState(runId);
    const [choices, setChoices] = useState<Choice[]>([]);
    const [refreshRevision,setRefreshRevision]=useState(0);
    const [targetIndex, setTargetIndex] = useState("");
    const [operations, setOperations] = useState<Operation[]>([]);
    const [search, setSearch] = useState(initialSearch);
    useEffect(() => setSearch(initialSearch), [initialSearch]);
    const [steps, setSteps] = useState<Step[]>([]);
    const [outcome, setOutcome] = useState<Outcome | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [catalogBusy, setCatalogBusy] = useState(true);
    const [artifact, setArtifact] = useState<unknown>();
    const requestId = useRef(uid());
    const pending = useRef(false);
    const choice = choices[Number(targetIndex)];
    const target = targetIndex === "" ? undefined : choice?.target;
    const targetKey = JSON.stringify(target);
    const form = useRef<HTMLFormElement>(null);
    const invalidate = () => { setOutcome(null); setArtifact(undefined); setError(""); requestId.current = uid(); };
    const modelKey = JSON.stringify(models);
    const selectedTarget = useRef(targetKey);
    selectedTarget.current = targetKey;
    useEffect(() => {
        let current = true;
        (async () => {
            const datasets = sourceRunId ? await listDatasets(projectRoot, sourceRunId) : [];
            const data = await Promise.all(datasets.map(async (d) => { const page = await fetchDatasetPage(projectRoot, sourceRunId, d.node_id, { offset: 0, limit: 1 }); return { label: `Data · ${d.label} · ${d.node_id} · ${sourceRunId}`, target: { kind: "dataset_node", run_id: sourceRunId, node_id: d.node_id, artifact_id: page.artifact_id } as Target, columns: page.columns }; }));
            const all = [...data, ...models.map(m => ({ label: `Model · ${m.label} · ${m.runId}`, target: { kind: "model_node", run_id: m.runId, node_id: m.nodeId } as Target, columns: [] }))];
            if (current) {
                const index = all.findIndex(c => JSON.stringify(c.target) === selectedTarget.current);
                setChoices(all);
                setTargetIndex(index >= 0 ? String(index) : all.length ? "0" : "");
                if (selectedTarget.current && index < 0) {
                    invalidate();
                    setSteps([]);
                }
            }
        })().catch(e => current && setError(String(e)));
        return () => { current = false; };
    }, [projectRoot, sourceRunId, modelKey, refreshRevision]);
    useEffect(() => {
        let current = true;
        setCatalogBusy(true);
        setOperations([]);
        catalog(projectRoot, target).then(v => { if (current)
            setOperations(v.operations); }).catch(e => current && setError(String(e))).finally(() => current && setCatalogBusy(false));
        return () => { current = false; };
    }, [projectRoot, targetKey]);
    function changeStep(index: number, spec: Record<string, unknown>) { invalidate(); setSteps(old => old.map((s, i) => i === index ? { ...s, spec } : s)); }
    function add(op: Operation) {
        invalidate();
        let spec = (initialValue(op.spec_schema as JsonSchema) ?? {}) as Record<string, unknown>;
        if (target?.kind === "model_node" && (op.spec_schema as JsonSchema).properties?.model_ref)
            spec = { ...spec, model_ref: target.node_id, model_run_id: target.run_id };
        setSteps(old => [...old, { step_id: `step_${old.length + 1}_${uid().slice(0, 4)}`, operation_id: op.id, spec }]);
    }
    async function submit(confirm = false) {
        if (pending.current || !form.current?.reportValidity())
            return;
        const issues = steps.flatMap((step,index) => {
            const op=operations.find(o=>o.id===step.operation_id);
            if(!op) return [`Step ${index+1}: operation declaration is unavailable.`];
            const schema=op.spec_schema as JsonSchema;
            const {source,...fields}=step.spec;
            const earlier=steps.slice(0,index);
            if(source && !earlier.some(s=>s.step_id===(source as {from_step?:string}).from_step)) return [`Step ${index+1}: the selected dataset producer no longer exists before this step.`];
            if(typeof step.spec.model_ref==='string'&&step.spec.model_ref.startsWith('step:')) {
                const [,producerId,branchId]=step.spec.model_ref.split(':');
                const producer=earlier.find(s=>s.step_id===producerId);
                if(!producer||!Array.isArray(producer.spec.branches)||!producer.spec.branches.some(b=>(b as {branch_id?:unknown})?.branch_id===branchId)) return [`Step ${index+1}: select a declared model branch from an earlier step.`];
            }
            return validateValue(schema, schema.properties?.source ? step.spec : fields, schema, `Step ${index+1}`);
        });
        if(issues.length){setError(issues.join("\n"));return;}
        if (!target && !confirm)
            return;
        pending.current = true;
        setBusy(true);
        setError("");
        try {
            const body = confirm && outcome ? { mode: "confirm" as const, request_id: outcome.request_id, preview_id: outcome.preview_id, fingerprint: outcome.fingerprint } : { mode: "preview" as const, request_id: requestId.current, target, steps };
            const result = await execute(projectRoot, body);
            setOutcome(result);
            if (result.status === "completed" || result.status === "partial" || result.status === "failed") {
                setRefreshRevision(value=>value+1);onRefresh();
            }
        }
        catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
        finally {
            pending.current = false;
            setBusy(false);
        }
    }
    async function readArtifact(run: string, id: string) { setError(""); try {
        const r = await fetch(manualUrl(projectRoot, `/runs/${encodeURIComponent(run)}/artifacts/${encodeURIComponent(id)}`));
        if (!r.ok)
            await readResponse(r);
        if (r.headers.get('content-type')?.includes('json'))
            setArtifact(await r.json());
        else
            setArtifact('Use the artifact link to open or download this result.');
    }
    catch (e) {
        setError(String(e));
    } }
    const groups = operations.filter(op => `${op.name} ${op.id} ${op.category}`.toLowerCase().includes(search.toLowerCase())).reduce<Record<string, Operation[]>>((groups, op) => { (groups[op.category] ??= []).push(op); return groups; }, {});
    return <section className="manual-panel" aria-label="Analyze operations"><header><h2>Analyze</h2><button type="button" onClick={onClose} disabled={busy}>Close Analyze</button></header>
    <p>Choose an operation and its data or model. Runs locally without a language model.</p>
    {error && <p role="alert">{error}</p>}
    <label className="manual-field">Analysis target<select aria-label="Analysis target" disabled={busy} value={targetIndex} onChange={e => { invalidate(); setSteps([]); setTargetIndex(e.target.value); }}><option value="">Select a target</option>{choices.map((c, i) => <option key={JSON.stringify(c.target)} value={i}>{c.label}</option>)}</select></label>
    {!choices.length && !catalogBusy && <p>Import data with New analysis first.</p>}
    <label className="manual-field">Find an operation<input aria-label="Find an operation" value={search} onChange={e => setSearch(e.target.value)}/></label>
    {catalogBusy ? <p role="status">Loading operations…</p> : <details open={steps.length === 0}><summary>{operations.length} operations</summary>{Object.entries(groups).map(([group, items]) => <section key={group}><h3>{group.replace(/_/g, ' ')}</h3><div className="manual-catalog">{items!.map(op => <button type="button" key={op.id} disabled={busy || op.availability.status === "unavailable" || !!dedicatedTargetReason(op,target)} title={dedicatedTargetReason(op,target) ?? `${op.summary}\n${op.availability.reason_code}: ${op.availability.message}`} onClick={() => op.execution.kind === "workflow" ? add(op) : onDedicated(op.id, target)}>{op.name}<small> · {op.id}{op.availability.status === "unavailable" ? ` · ${op.availability.reason_code}` : dedicatedTargetReason(op,target) ? ` · ${dedicatedTargetReason(op,target)}` : op.execution.kind === "dedicated" ? ' · Open workspace' : ''}</small></button>)}</div></section>)}</details>}
    <form ref={form} onChange={invalidate} onSubmit={e => { e.preventDefault(); void submit(); }}><fieldset disabled={busy}>
      {steps.map((step, i) => {
            const op = operations.find(o => o.id === step.operation_id);
            return <article key={step.step_id}><header><h3>{i + 1}. {op?.name ?? step.operation_id}</h3><button type="button" onClick={() => { invalidate(); setSteps(old => old.filter((_, j) => j !== i)); }}>Remove step {i + 1}</button></header><p>{op?.summary}</p><small>Step reference: {step.step_id}</small>
        <SchemaField key={step.step_id} label={`Step ${i + 1}`} schema={(op?.spec_schema ?? { type: 'object' }) as JsonSchema} value={step.spec} onChange={v => changeStep(i, v as Record<string, unknown>)} columns={choice?.columns}/>
        {i > 0 && <details><summary>Use an earlier result</summary><p>Dataset input uses a producer step. Choose a model branch below when an earlier step produces it.</p><label className="manual-field">Dataset producer<select aria-label={`Step ${i + 1} dataset producer`} value={String((step.spec.source as {
                from_step?: string;
            })?.from_step ?? '')} onChange={e => { const next = { ...step.spec }; if (e.target.value)
                next.source = { from_step: e.target.value, output: 'produced_dataset' };
            else
                delete next.source; changeStep(i, next); }}><option value="">Selected target</option>{steps.slice(0, i).map(s => <option key={s.step_id} value={s.step_id}>{s.step_id} · {s.operation_id}</option>)}</select></label>
          {(op?.spec_schema as JsonSchema)?.properties?.model_ref && <label className="manual-field">Model producer<select aria-label={`Step ${i+1} model producer`} value={String(step.spec.model_ref??'').startsWith('step:')?String(step.spec.model_ref):''} onChange={e=>{const next={...step.spec};if(e.target.value){next.model_ref=e.target.value;delete next.model_run_id;}else if(target?.kind==='model_node'){next.model_ref=target.node_id;next.model_run_id=target.run_id;}else{delete next.model_ref;delete next.model_run_id;}changeStep(i,next);}}><option value="">Selected model / explicit reference</option>{steps.slice(0,i).flatMap(producer=>Array.isArray(producer.spec.branches)?producer.spec.branches.flatMap((branch:unknown)=>{const id=(branch as {branch_id?:unknown})?.branch_id;return typeof id==='string'&&id?[<option key={`${producer.step_id}:${id}`} value={`step:${producer.step_id}:${id}`}>{producer.step_id} · {id}</option>]:[];}):[])}</select></label>}
        </details>}
      </article>;
        })}
      <button type="submit" disabled={!steps.length || !target || catalogBusy || busy}>Preview analysis</button>
    </fieldset></form>
    {outcome && <section aria-label="Analysis preview and results"><h3>{outcome.status.replace(/_/g, ' ')}</h3><ul>{[...outcome.expected_effect, ...outcome.risks].map((s, i) => <li key={i}>{s}</li>)}</ul>
      {outcome.error && <pre role="alert">{JSON.stringify(outcome.error, null, 2)}</pre>}
      {outcome.status === 'awaiting_confirmation' && <button type="button" disabled={busy} onClick={() => void submit(true)}>Confirm analysis</button>}
      {outcome.steps.map(s => <article key={s.step_id}><h4>{s.operation_id} · {s.status}</h4>{s.error && <p role="alert">{s.error}</p>}{s.node_refs.map(n => <button type="button" key={`${n.run_id}:${n.node_id}`} onClick={() => onOpenRun(n.run_id)}>Open result run {n.run_id}</button>)}{s.artifact_refs.map(a => <div key={`${a.run_id}:${a.artifact_id}`}><button type="button" onClick={() => void readArtifact(a.run_id, a.artifact_id)}>View {a.artifact_id}</button><a href={manualUrl(projectRoot, `/runs/${encodeURIComponent(a.run_id)}/artifacts/${encodeURIComponent(a.artifact_id)}`)} target="_blank" rel="noreferrer">Download artifact</a></div>)}</article>)}
      {artifact !== undefined && <pre aria-label="Analysis result">{JSON.stringify(artifact, null, 2)}</pre>}
    </section>}{busy && <p role="status">Working…</p>}
  </section>;
}
