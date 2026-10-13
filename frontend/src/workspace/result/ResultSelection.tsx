import {useRef, useState, type ReactNode} from 'react';
import {useAgentSurfaceOptional} from '../../workbench/agent/AgentSurfaceContext';

export function resultQuestion(text: string, context: string, runId: string, modelId: string): string {
  return `Explain this selected result: ${text}\nDisplayed context: ${context}\nSource: run ${runId}, model ${modelId}. Verify the persisted source before interpreting; do not execute or change anything.`;
}
export function ResultSelection({runId, modelId, children}: {runId: string; modelId: string; children: ReactNode}) {
  const agent = useAgentSurfaceOptional();
  const surface = useRef<HTMLDivElement>(null);
  const [selection, setSelection] = useState<{text: string; context: string} | null>(null);
  const capture = () => {
    const range = window.getSelection();
    if (!range || range.isCollapsed || !surface.current?.contains(range.anchorNode) || !surface.current.contains(range.focusNode)) return;
    const text = range.toString().trim().slice(0, 1500);
    const element = range.anchorNode instanceof Element ? range.anchorNode : range.anchorNode?.parentElement;
    const block = element?.closest('tr, .ws-result__number, section');
    const context = block ? Array.from(block.children).map(child => child.textContent?.trim()).join(' | ').slice(0, 2000) : '';
    if (text) setSelection({text, context});
  };
  return <div ref={surface} className="ws-result-selection" onMouseUp={capture} onKeyUp={capture}>
    {selection && agent && <button type="button" className="ws-result-selection__ask" onClick={() => {
      const question = resultQuestion(selection.text, selection.context, runId, modelId);
      agent.setPrompt(agent.prompt.trim() ? `${agent.prompt}\n\n${question}` : question);
      window.dispatchEvent(new Event('workbench:show-agent'));
      setSelection(null);
    }}>Ask Agent about selection</button>}
    {children}
  </div>;
}
