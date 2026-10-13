import {render, screen} from '@testing-library/react';
import {it, expect} from 'vitest';
import {TimelinePanel, timelineSummary} from './TimelinePanel';

it('shows persisted actions and disclosure counts without inventing a plan', () => {
  const value = {entries: [{at: '2026-10-13T01:00:00Z', who: 'ui', what: 'model.rerun', status: 'completed', summary: 'Changed quantiles', categories: []}],
    counts: {inferential_tests: 2, models: 1, data_changes: 3}, entries_omitted: 4} as never;
  render(<TimelinePanel value={value} error={null} onRefresh={() => {}}/>);
  expect(screen.getByText('Changed quantiles', {selector:'p'})).toBeInTheDocument();
  expect(screen.getByText(/4 earlier entries/)).toBeInTheDocument();
  expect(timelineSummary(value)).toContain('2 tests');
  expect(screen.getByText('model.rerun')).not.toBeVisible();
});

it('refreshes persisted history after an Agent operation completes', async () => {
  const {renderHook, waitFor} = await import('@testing-library/react');
  const {vi} = await import('vitest');
  const {AgentSurfaceContext} = await import('../workbench/agent/AgentSurfaceContext');
  const {useTimeline} = await import('./TimelinePanel');
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({entries: [], counts: {inferential_tests: 1, models: 1, data_changes: 0}, entries_omitted: 0}))));
  vi.stubGlobal('fetch', fetchMock);
  let operation = {record_id: 'op-1', status: 'running'};
  const hook = renderHook(() => useTimeline('/project', 'run-1'), {wrapper: ({children}) => <AgentSurfaceContext.Provider value={{activeOperation: operation} as never}>{children}</AgentSurfaceContext.Provider>});
  await waitFor(() => expect(hook.result.current.value).not.toBeNull());
  expect(fetchMock).toHaveBeenCalledTimes(1);
  operation = {...operation, status: 'completed'};
  hook.rerender();
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  hook.rerender();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  vi.unstubAllGlobals();
});
