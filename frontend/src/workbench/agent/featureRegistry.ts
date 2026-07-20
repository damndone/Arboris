import type { ReactElement } from "react";

/** A packet-only view contribution from a future Workbench feature lane. */
export interface AgentFeatureView {
  contractKey: string;
  render: (packet: unknown) => ReactElement;
}

const featureViews = new Map<string, AgentFeatureView>();

/**
 * Register exactly one renderer per versioned packet contract.
 *
 * A collision is a release-integration error, not an invitation to choose an
 * arbitrary view. This makes multi-lane additions fail closed.
 */
export function registerFeatureView(view: AgentFeatureView): void {
  if (featureViews.has(view.contractKey)) {
    throw new Error(`duplicate agent feature view: ${view.contractKey}`);
  }
  featureViews.set(view.contractKey, view);
}

/** Return no view for unknown packets so generic surfaces remain safe. */
export function resolveFeatureView(contractKey: string): AgentFeatureView | null {
  return featureViews.get(contractKey) ?? null;
}
