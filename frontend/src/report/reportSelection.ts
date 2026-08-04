import type { CitableFact, FigureFactInput } from "./factTable";

/**
 * Keep a report readable by default. The full figure inventory remains in the
 * report provenance; this is only the default set sent to the writer.
 */
export const DEFAULT_REPORT_FIGURE_LIMIT = 4;

const FIGURE_PRIORITY_PATTERNS: readonly RegExp[] = [
  /coef|coefficient|estimate|effect/i,
  /resid|residual|qq|diagnostic|acf|pacf/i,
  /forecast|prediction|fitted/i,
  /scatter|correlation|heatmap/i,
  /hist|kde|box/i,
];

function figurePriority(figure: FigureFactInput): number {
  const identity = `${figure.artifact_id} ${figure.chart_type}`;
  const index = FIGURE_PRIORITY_PATTERNS.findIndex((pattern) => pattern.test(identity));
  return index < 0 ? 0 : FIGURE_PRIORITY_PATTERNS.length - index;
}

/** Return figure IDs omitted from the default report packet, in inventory order. */
export function defaultExcludedFigureIds(
  figures: readonly FigureFactInput[],
  limit = DEFAULT_REPORT_FIGURE_LIMIT,
): string[] {
  if (figures.length <= limit) return [];
  const selected = new Set(
    figures
      .map((figure, index) => ({ figure, index, priority: figurePriority(figure) }))
      .sort((left, right) => right.priority - left.priority || left.index - right.index)
      .slice(0, Math.max(0, limit))
      .map(({ figure }) => figure.artifact_id),
  );
  return figures
    .map((figure) => figure.artifact_id)
    .filter((artifactId) => !selected.has(artifactId));
}

export function includedReportFigures<T extends FigureFactInput>(
  figures: readonly T[],
  excludedFigureIds: readonly string[],
): T[] {
  const excluded = new Set(excludedFigureIds);
  return figures.filter((figure) => !excluded.has(figure.artifact_id));
}

/** Resolve the owning figure for a figure-derived fact, if this is one. */
export function figureIdForFact(fact: Pick<CitableFact, "field" | "node_key">): string | null {
  const source = fact.field.startsWith("figure:")
    ? fact.field.slice("figure:".length)
    : fact.node_key.startsWith("figure:")
      ? fact.node_key.slice("figure:".length)
      : "";
  if (!source) return null;
  const separator = source.indexOf(":");
  return separator < 0 ? source : source.slice(0, separator);
}

export function includedReportFacts(
  facts: readonly CitableFact[],
  excludedFactIds: readonly string[],
  excludedFigureIds: readonly string[],
): CitableFact[] {
  const excludedFacts = new Set(excludedFactIds);
  const excludedFigures = new Set(excludedFigureIds);
  return facts.filter((fact) => {
    if (excludedFacts.has(fact.id)) return false;
    const figureId = figureIdForFact(fact);
    return figureId === null || !excludedFigures.has(figureId);
  });
}
