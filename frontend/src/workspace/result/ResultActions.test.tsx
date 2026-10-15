import {render, screen, fireEvent} from '@testing-library/react';
import {it, expect, vi} from 'vitest';
import {ResultActions} from './ResultActions';
vi.mock('../../workbench/WorkbenchStateProvider', () => ({useWorkbench: () => ({dispatch: {setView: vi.fn()}})}));
vi.mock('../../manual/OperationsPanel', () => ({OperationsPanel: (p: any) => <div role="region" aria-label="Bound operation">{JSON.stringify(p.initialTarget)}</div>}));
it('opens a manual test bound to the displayed model owner', () => {
  render(<ResultActions projectRoot="/p" runId="source" modelId="ols_1" label="OLS" onRefresh={() => {}}/>);
  fireEvent.click(screen.getByRole('button', {name:'New test'}));
  expect(screen.getByRole('region',{name:'Bound operation'})).toHaveTextContent('"run_id":"source"');
  expect(screen.getByRole('region',{name:'Bound operation'})).toHaveTextContent('"node_id":"model:ols_1"');
});
