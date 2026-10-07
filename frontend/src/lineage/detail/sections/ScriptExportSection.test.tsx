import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { sectionRegistry } from '../../../workbench/registry/sectionRegistry';
import type { GraphViewNode } from '../../api/graphViewTypes';

const mocks = vi.hoisted(() => ({ exportScript: vi.fn(), targets: vi.fn().mockResolvedValue({ targets: [{ target: 'model:ols_1', label: 'Model only' }] }), resolved: { current: null as any } }));
vi.mock('../../../api', async (original) => ({ ...(await original<any>()), exportAnalysisScript: mocks.exportScript, listScriptExportTargets: mocks.targets }));
vi.mock('../../../workbench/ProjectRootContext', () => ({ useProjectRootOptional: () => '/project' }));
vi.mock('../NodeOperationContextProvider', () => ({ useResolvedNodeOperationContext: () => mocks.resolved.current }));

const node = { kind: 'model', isDraft: false } as GraphViewNode;
function mount() {
  const entry = sectionRegistry.find(item => item.id === 'scriptExport');
  expect(entry).toBeDefined();
  const Component = entry!.Component;
  render(<Component node={node} />);
}
function owner(state = 'materialized') {
  mocks.resolved.current = { ok: true, context: { context_fingerprint: 'owner1', operation_target: {
    owner_run_id: 'source-run', op_node_id: 'model:ols_1', node_state: state } } };
}
afterEach(() => { vi.clearAllMocks(); mocks.resolved.current = null; });

describe('Script export', () => {
  it('exports the selected resolved owner and displays explicit snapshot coverage', async () => {
    owner();
    mocks.exportScript.mockResolvedValue({ artifact_id: 'script_export_r_a', fully_native: false,
      coverage: [{ step_id: 'clean', operation: 'data.cleaning', status: 'snapshot', note: 'Recorded normalization snapshot.' }],
      required_packages: ['sandwich'], filename: 'analysis-r.zip' });
    mount();
    fireEvent.change(screen.getByLabelText('Script language'), { target: { value: 'r' } });
    fireEvent.click(screen.getByLabelText('Require all steps to run natively'));
    fireEvent.click(screen.getByRole('button', { name: 'Export script' }));
    await waitFor(() => expect(mocks.exportScript).toHaveBeenCalledWith('/project', 'source-run', 'model:ols_1', 'r', true));
    expect(await screen.findByText('Recorded normalization snapshot.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Download script bundle' })).toHaveAttribute('href', expect.stringContaining('source-run'));
  });
  it('displays a native refusal without a download', async () => {
    owner(); mocks.exportScript.mockRejectedValue(new Error('Native export unavailable: cleaning snapshot required'));
    mount(); fireEvent.click(screen.getByRole('button', { name: 'Export script' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Native export unavailable');
    expect(screen.queryByRole('link', { name: 'Download script bundle' })).toBeNull();
  });
  it('does not export an ambiguous or stale owner', () => {
    mocks.resolved.current = { ok: false, reason: 'ambiguous_owner_run' };
    mount(); expect(screen.queryByRole('button', { name: 'Export script' })).toBeNull();
  });
  it.each(['language', 'path', 'native'])('clears the previous request refusal when changing %s', async (control) => {
    owner();
    mocks.targets.mockResolvedValue({ targets: [{ target: 'model:ols_1', label: 'Model only' },
      { target: 'artifact:post-wald', label: 'Model and Wald test' }] });
    mocks.exportScript.mockRejectedValue(new Error('Stata cohort is outside the supported range'));
    mount();
    await screen.findByRole('option', { name: 'Model and Wald test' });
    fireEvent.click(screen.getByRole('button', { name: 'Export script' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Stata cohort');
    if (control === 'language') fireEvent.change(screen.getByLabelText('Script language'), { target: { value: 'r' } });
    if (control === 'path') fireEvent.change(screen.getByLabelText('Analysis path'), { target: { value: 'artifact:post-wald' } });
    if (control === 'native') fireEvent.click(screen.getByLabelText('Require all steps to run natively'));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByRole('link', { name: 'Download script bundle' })).toBeNull();
    expect(mocks.exportScript).toHaveBeenCalledTimes(1);
  });
});

it('exports the persisted post-estimation target selected from the server owner', async () => {
  owner();
  mocks.targets.mockResolvedValue({ targets: [{ target: 'model:ols_1', label: 'Model only' },
    { target: 'artifact:post-wald', label: 'Model and Wald test' }] });
  mocks.exportScript.mockResolvedValue({ artifact_id: 'script_a', fully_native: true,
    coverage: [], required_packages: [], filename: 'analysis.zip' });
  mount();
  const select = await screen.findByLabelText('Analysis path');
  await screen.findByRole('option', { name: 'Model and Wald test' });
  fireEvent.change(select, { target: { value: 'artifact:post-wald' } });
  fireEvent.click(screen.getByRole('button', { name: 'Export script' }));
  await waitFor(() => expect(mocks.exportScript).toHaveBeenCalledWith('/project', 'source-run', 'artifact:post-wald', 'stata', false));
});
