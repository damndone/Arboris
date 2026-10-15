import {PostEstimationResults} from './PostEstimationResults';
import type {PostEstimationResult} from '../../api';
import {useForest} from '../../workbench/ForestContext';
import {useState} from 'react';
import {OperationsPanel} from '../../manual/OperationsPanel';
import {useWorkbench} from '../../workbench/WorkbenchStateProvider';

export function ResultActions({projectRoot, runId, modelId, label, onRefresh, entries = []}: {
  projectRoot: string; runId: string; modelId: string; label: string; onRefresh: () => void; entries?: PostEstimationResult[];
}) {
  const [search, setSearch] = useState<string | null>(null);
  const {dispatch} = useWorkbench();
  const forest = useForest();
  const openView = (view: "table" | "report", owner = runId) => {forest?.setActiveRunId(owner);dispatch.setView(view);};
  const scroll = (button: HTMLButtonElement, section: string) => {
    const region = Array.from(button.closest('.detail-drawer')?.querySelectorAll('section[aria-label]') ?? [])
      .find(element => element.getAttribute('aria-label') === section);
    region?.scrollIntoView({behavior: 'smooth', block: 'start'});
  };
  return <section aria-label="Post-estimation" className="ws-result__section">
    <h2 className="ws-result__heading">Post-estimation</h2>
    <PostEstimationResults entries={entries}/>
    <p>Choose a test or diagnostic for this model. Availability and input requirements come from its operation contract.</p>
    <div className="manual-actions" role="group" aria-label="Next steps">
      <button type="button" onClick={() => setSearch('postestimation')}>New test</button>
      <button type="button" onClick={() => setSearch('diagnostics')}>Diagnostics</button>
      <button type="button" onClick={e => scroll(e.currentTarget, 'Operation')}>Rerun with changes</button>
      <button type="button" onClick={e => scroll(e.currentTarget, 'Compare nodes')}>Compare</button>
      <button type="button" onClick={() => openView('table')}>Add to table</button>
      <button type="button" onClick={() => openView('report')}>Add to report</button>
      <button type="button" onClick={e => scroll(e.currentTarget, 'Script export')}>Reproduce</button>
    </div>
    {search !== null && <OperationsPanel projectRoot={projectRoot} runId={runId} initialSearch={search}
      models={[{runId, nodeId: `model:${modelId}`, label}]}
      initialTarget={{kind: 'model_node', run_id: runId, node_id: `model:${modelId}`}}
      onClose={() => setSearch(null)} onRefresh={onRefresh}
      onOpenRun={owner => openView('table', owner)}
      onDedicated={() => setSearch(null)}/>}
  </section>;
}
