// v1.9.0 — "Ask Agent" from anywhere in the workspace (a node's context menu,
// selected text). The question goes into the composer and the Agent comes
// forward with the cursor at the end; nothing is sent until the person sends
// it, so they can edit the question and no turn is spent by a right-click.

import { useMemo } from "react";
import type { GraphViewNode } from "../../lineage/api/graphViewTypes";
import { useAgentSurfaceOptional } from "../../workbench/agent/AgentSurfaceContext";
import { useWorkspaceCommands } from "../workspaceCommands";

const SELECTION_LIMIT = 1500;
const CONTEXT_LIMIT = 2000;

/** Appends to what is already being written instead of replacing it. */
export function appendToPrompt(existing: string, addition: string): string {
  return existing.trim() ? `${existing.trimEnd()}\n\n${addition}` : addition;
}

export function nodeQuestion(title: string, kind: string): string {
  return `About ${kind ? `the ${kind} ` : ""}"${title}": what does it show, how was it produced, and what should I check next?`;
}

export function selectionQuestion(text: string, context: string, where: string): string {
  const lines = [`Explain this: "${text.slice(0, SELECTION_LIMIT)}"`];
  const bare = (value: string) => value.replace(/[^\p{L}\p{N}.,<>%-]+/gu, "");
  if (context && bare(context) !== bare(text)) lines.push(`Shown with: ${context.slice(0, CONTEXT_LIMIT)}`);
  if (where) lines.push(`Where: ${where}`);
  lines.push("Check it against the saved results before interpreting.");
  return lines.join("\n");
}

/** The selection as a quotation the person can write around. */
export function quoteSelection(text: string): string {
  return text
    .slice(0, SELECTION_LIMIT)
    .split("\n")
    .map((line) => `> ${line}`)
    .join("\n") + "\n\n";
}

function focusComposer(): void {
  requestAnimationFrame(() => {
    const field = document.getElementById("ws-composer-text");
    if (!(field instanceof HTMLTextAreaElement)) return;
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
  });
}

export interface AskAgent {
  /** Put text into the composer (after anything already there) and show the Agent. */
  put(text: string): void;
}

/** Null where there is no Agent column (classic shell, tests without one). */
export function useAskAgent(): AskAgent | null {
  const agent = useAgentSurfaceOptional();
  const commands = useWorkspaceCommands();
  return useMemo(() => {
    if (!agent || !commands) return null;
    return {
      put(text: string) {
        agent.setPrompt(appendToPrompt(agent.prompt, text));
        commands.showAgent();
        focusComposer();
      },
    };
  }, [agent, commands]);
}

/** "Ask Agent about this node": select it (so it becomes the Agent's focus),
 * then ask. Undefined where there is no Agent column. */
export function useAskAgentAboutNode(select: (nodeKey: string) => void): ((node: GraphViewNode) => void) | undefined {
  const ask = useAskAgent();
  return useMemo(() => {
    if (!ask) return undefined;
    return (node: GraphViewNode) => {
      select(node.nodeKey);
      ask.put(nodeQuestion(node.title, node.kind.replace(/_/g, " ")));
    };
  }, [ask, select]);
}
