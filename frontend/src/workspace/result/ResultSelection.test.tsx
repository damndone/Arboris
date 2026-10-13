import {fireEvent, render, screen} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import {ResultSelection} from './ResultSelection';
const setPrompt = vi.hoisted(() => vi.fn());
vi.mock('../../workbench/agent/AgentSurfaceContext', () => ({useAgentSurfaceOptional: () => ({prompt:'Existing question',setPrompt})}));
afterEach(()=>vi.restoreAllMocks());
it('stages a bounded source-linked question without sending or overwriting the draft', () => {
  render(<ResultSelection runId="owner" modelId="ols_1"><table><tbody><tr><th>x</th><td>1.998</td></tr></tbody></table></ResultSelection>);
  const number = screen.getByText('1.998');
  vi.spyOn(window,'getSelection').mockReturnValue({isCollapsed:false,anchorNode:number.firstChild,focusNode:number.firstChild,toString:()=> '1.998'} as Selection);
  fireEvent.mouseUp(number);
  fireEvent.click(screen.getByRole('button',{name:'Ask Agent about selection'}));
  expect(setPrompt).toHaveBeenCalledWith(expect.stringContaining('Existing question\n\nExplain this selected result: 1.998'));
  expect(setPrompt).toHaveBeenCalledWith(expect.stringContaining('run owner, model ols_1'));
  expect(setPrompt).toHaveBeenCalledWith(expect.stringContaining('do not execute or change anything'));
});
