import { useEffect, useState } from 'react';
import { artifactDownloadUrl, exportAnalysisScript, listScriptExportTargets, type AnalysisScriptExportResult, type ScriptExportTargets } from '../../../api';
import { useProjectRootOptional } from '../../../workbench/ProjectRootContext';
import type { GraphViewNode } from '../../api/graphViewTypes';
import { useResolvedNodeOperationContext } from '../NodeOperationContextProvider';

export function ScriptExportSection({ node }: { node: GraphViewNode }) {
  const projectRoot = useProjectRootOptional();
  const resolved = useResolvedNodeOperationContext();
  if (node.kind !== 'model' || !projectRoot || !resolved?.ok || resolved.context.operation_target.node_state !== 'materialized') return null;
  const owner = resolved.context.operation_target;
  if (!owner.op_node_id.startsWith('model:')) return null;
  return <ResolvedScriptExport key={`${projectRoot}:${owner.owner_run_id}:${owner.op_node_id}:${resolved.context.context_fingerprint}`}
    projectRoot={projectRoot} runId={owner.owner_run_id} target={owner.op_node_id} />;
}

function ResolvedScriptExport({ projectRoot, runId, target }: { projectRoot: string; runId: string; target: string }) {
  const [language, setLanguage] = useState<'stata' | 'r' | 'python'>('stata');
  const [requireNative, setRequireNative] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AnalysisScriptExportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedTarget, setSelectedTarget] = useState(target);
  const [targets, setTargets] = useState<ScriptExportTargets['targets']>([{ target, label: 'Model only' }]);
  useEffect(() => {
    let active = true;
    void listScriptExportTargets(projectRoot, runId, target).then(value => {
      if (active) setTargets(value.targets);
    }).catch(cause => {
      if (active) setError(cause instanceof Error ? cause.message : 'Analysis paths unavailable');
    });
    return () => { active = false; };
  }, [projectRoot, runId, target]);
  async function generate() {
    setBusy(true); setError(null); setResult(null);
    try { setResult(await exportAnalysisScript(projectRoot, runId, selectedTarget, language, requireNative)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Script export unavailable'); }
    finally { setBusy(false); }
  }
  return <section aria-label="Script export" style={{ marginTop: 18, color: 'var(--label)' }}>
    <div className="ln-section-label">Script export</div>
    <p style={{ fontSize: 12, color: 'var(--label-secondary)' }}>Reproduce this completed path. The local bundle includes source data and numeric self-checks.</p>
    <fieldset disabled={busy} style={{ border: 0, padding: 0, display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
      <label>Analysis path <select aria-label="Analysis path" value={selectedTarget} onChange={event => { setSelectedTarget(event.target.value); setResult(null); setError(null); }}>
        {targets.map(item => <option key={item.target} value={item.target}>{item.label}</option>)}
      </select></label>
      <label>Script language <select aria-label="Script language" value={language} onChange={event => { setLanguage(event.target.value as typeof language); setResult(null); setError(null); }}>
        <option value="stata">Stata</option><option value="r">R</option><option value="python">Python</option>
      </select></label>
      <label style={{ fontSize: 12 }}><input type="checkbox" checked={requireNative} onChange={event => { setRequireNative(event.target.checked); setResult(null); setError(null); }} /> Require all steps to run natively</label>
      <button type="button" onClick={() => void generate()}>{busy ? 'Exporting…' : 'Export script'}</button>
    </fieldset>
    {error && <p role="alert" style={{ color: 'var(--status-fails-fg)', overflowWrap: 'anywhere' }}>{error}</p>}
    {result && <div aria-live="polite" style={{ fontSize: 12, overflowWrap: 'anywhere' }}>
      <p>{result.fully_native ? 'All steps run natively.' : 'Includes completed Workbench snapshots.'}</p>
      <ul style={{ paddingLeft: 18 }}>{result.coverage.map(item => <li key={item.step_id}>{item.operation} · {item.status}{item.note && <div>{item.note}</div>}</li>)}</ul>
      {result.required_packages.length > 0 && <p>Required packages: {result.required_packages.join(', ')}</p>}
      <a href={artifactDownloadUrl(projectRoot, runId, result.artifact_id)} download={result.filename}>Download script bundle</a>
    </div>}
  </section>;
}
