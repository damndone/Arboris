/**
 * What the Agent is about: one FocusRef (kind + id), resolved by a registry of
 * context providers (v1.8.10 design §8.4).
 *
 * There is one Agent whose scope follows the focus, not an Agent per page:
 * the Data page focuses the dataset it shows, a graph selection focuses that
 * node -- in the run that owns it, never silently the active run's head --
 * and a blank canvas focuses the project. Each kind has one provider; a new
 * focus kind adds a provider here and nothing else.
 */

import type { ForestViewModel, HeadSetNode as ForestNode } from "../../lineage/api/graphViewTypes";

export type FocusKind = "project" | "dataset" | "node" | "plan" | "report";

export interface FocusRef {
  kind: FocusKind;
  /** project: the project root; dataset: the dataset node id in its run
   * ("stage:raw"); node: the forest node key; plan: the option id; report:
   * the run id. */
  id: string;
  runId?: string;
}

export interface FocusEnv {
  projectRoot: string;
  activeRunId: string;
  forest: ForestViewModel | null;
}

export interface ResolvedFocus {
  focus: FocusRef;
  /** "main" is the project Agent (overview across runs); "chain" can act on
   * one run's nodes, including read-only analyses without a confirmation. */
  role: "main" | "chain";
  runId: string;
  /** The forest node the Agent acts on, when the focus has one. */
  nodeKey: string | null;
  /** Whether the node's owner run is not the active run (shown in the label). */
  ownerIsNotActive: boolean;
  label: string;
}

type FocusProvider = (focus: FocusRef, env: FocusEnv) => ResolvedFocus | null;

function shortRun(runId: string): string {
  return (runId.split("_").pop() ?? runId).slice(0, 8);
}

/** The run that owns a node: the active run when it contains the node, else
 * the head (latest) run among the node's runs. */
export function ownerRunOf(node: ForestNode, forest: ForestViewModel, activeRunId: string): string | null {
  const runs = node.runs ?? [];
  if (runs.length === 0) return null;
  if (runs.includes(activeRunId)) return activeRunId;
  const head = forest.heads.find((item) => runs.includes(item.runId));
  return head?.runId ?? runs[runs.length - 1];
}

const projectProvider: FocusProvider = (focus, env) => ({
  focus,
  role: env.forest ? "main" : "chain",
  runId: env.activeRunId,
  nodeKey: null,
  ownerIsNotActive: false,
  label: env.forest
    ? `Project · ${env.forest.heads.length} runs`
    : `Run · ${shortRun(env.activeRunId)}`,
});

/** A run's head model node: what a run (not a node) focus acts on. */
function headModelNode(forest: ForestViewModel, runId: string): ForestNode | undefined {
  const head = forest.heads.find((item) => item.runId === runId);
  return (head
    ? forest.nodes.find((node) => node.nodeHash === head.headNodeHash && (node.kind === "model" || node.stage === "model"))
    : undefined)
    ?? forest.nodes.find((node) => node.runs.includes(runId) && (node.kind === "model" || node.stage === "model"));
}

const nodeProvider: FocusProvider = (focus, env) => {
  if (!env.forest) return null;
  // An empty id is a run focus (the run rail): the run's head model node.
  const node = focus.id
    ? env.forest.nodes.find((item) => item.nodeKey === focus.id)
    : focus.runId ? headModelNode(env.forest, focus.runId) : undefined;
  if (!node) return null;
  const owner = focus.runId && node.runs.includes(focus.runId)
    ? focus.runId
    : ownerRunOf(node, env.forest, env.activeRunId);
  if (!owner) return null;
  const ownerIsNotActive = owner !== env.activeRunId;
  return {
    focus,
    role: "chain",
    runId: owner,
    nodeKey: node.nodeKey,
    ownerIsNotActive,
    label: ownerIsNotActive ? `Run ${shortRun(owner)} · ${node.title}` : `Current chain · ${node.title}`,
  };
};

const datasetProvider: FocusProvider = (focus, env) => {
  const runId = focus.runId ?? env.activeRunId;
  if (!env.forest) {
    return { focus, role: "chain", runId, nodeKey: null, ownerIsNotActive: false, label: `Dataset · ${focus.id}` };
  }
  const node = env.forest.nodes.find(
    (item) => item.opNodeId === focus.id && (item.runs ?? []).includes(runId),
  );
  if (!node) {
    return { focus, role: "chain", runId, nodeKey: null, ownerIsNotActive: runId !== env.activeRunId,
             label: `Dataset · ${focus.id}` };
  }
  const resolved = nodeProvider({ kind: "node", id: node.nodeKey, runId }, env);
  return resolved ? { ...resolved, focus, label: `Dataset · ${node.title}` } : null;
};

const reportProvider: FocusProvider = (focus, env) => ({
  focus,
  role: "chain",
  runId: focus.id || env.activeRunId,
  nodeKey: null,
  ownerIsNotActive: (focus.id || env.activeRunId) !== env.activeRunId,
  label: `Report · run ${shortRun(focus.id || env.activeRunId)}`,
});

const planProvider: FocusProvider = (focus, env) => ({
  ...projectProvider(focus, env)!,
  focus,
  label: `Plan · ${focus.id}`,
});

export const FOCUS_PROVIDERS: Readonly<Record<FocusKind, FocusProvider>> = {
  project: projectProvider,
  dataset: datasetProvider,
  node: nodeProvider,
  plan: planProvider,
  report: reportProvider,
};

/** The focus a workbench state implies: a page's declared focus wins, then a
 * graph selection, then the project. A `run:<id>` rail selection is the run's
 * focus, not a node. */
export function focusFromWorkbench(input: {
  projectRoot: string;
  declared: FocusRef | null;
  selectedKey: string | null;
  /** Set when the active run was switched after the node was selected: a
   * detail tab left over from another run must not outrank the switch. */
  staleSelectionRunId?: string | null;
}): FocusRef {
  if (input.declared) return input.declared;
  if (input.staleSelectionRunId) return { kind: "node", id: "", runId: input.staleSelectionRunId };
  if (input.selectedKey && input.selectedKey.startsWith("run:")) {
    return { kind: "node", id: "", runId: input.selectedKey.slice("run:".length) };
  }
  if (input.selectedKey) return { kind: "node", id: input.selectedKey };
  return { kind: "project", id: input.projectRoot };
}

/** Resolve through the registry; an unresolvable focus falls back to the project. */
export function resolveFocus(focus: FocusRef, env: FocusEnv): ResolvedFocus {
  const resolved = FOCUS_PROVIDERS[focus.kind](focus, env);
  if (resolved) return resolved;
  if (focus.kind === "node") {
    // A selection the forest does not hold (a draft node): the active run's
    // chain, without a node, as before focus existed.
    return { focus, role: "chain", runId: focus.runId ?? env.activeRunId, nodeKey: null,
             ownerIsNotActive: false, label: `Run · ${shortRun(focus.runId ?? env.activeRunId)}` };
  }
  return projectProvider({ kind: "project", id: env.projectRoot }, env)!;
}
