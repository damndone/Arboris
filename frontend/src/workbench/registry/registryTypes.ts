// frontend/src/workbench/registry/registryTypes.ts
//
// V1.5.2 — shared base type for the three workbench registries
// (sections, actions, bottom panels). Plan §4: "Do not introduce a
// parallel NodeExtensionRegistry. V1.5.0 sectionRegistry already
// reserved this mechanism — promote it instead of cloning."
//
// All entries share {id, order, shouldRender(ctx)}; each registry
// extends with its own payload (Component / handler / Panel).
// `order` slots are deliberately sparse (10/20/30…) so V1.5.x can
// insert sections without renumbering siblings — same convention
// the original sectionRegistry established.

export interface RegistryEntry<TContext> {
  /** Stable string id. Used for testing, persistence keys, telemetry. */
  id: string;
  /** Sort key (ascending). Sparse 10/20/30 numbering recommended. */
  order: number;
  /** Per-render filter. Return false to hide this entry for the given context. */
  shouldRender: (ctx: TContext) => boolean;
}

/** Stable ascending sort by `order`. Does not mutate the input. */
export function sortByOrder<E extends { order: number }>(entries: E[]): E[] {
  return [...entries].sort((a, b) => a.order - b.order);
}

/**
 * Filter entries by `shouldRender(ctx)`, then sort by `order`.
 * Convenience for consumers that always want both steps.
 */
export function filterAndSort<
  TContext,
  E extends RegistryEntry<TContext>,
>(entries: E[], ctx: TContext): E[] {
  return sortByOrder(entries.filter((e) => e.shouldRender(ctx)));
}
