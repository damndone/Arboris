/**
 * Public surface of the v1.8.1 Notebook lane.
 *
 * Integration mounts `NotebookSurface` with a `NotebookView` built by the data
 * adapter; every component below is pure and takes its data as props, so
 * swapping the mock source for the real endpoints is an adapter change, not a
 * component change (ADR-PD-001 §7C).
 */

export { NotebookSurface, type NotebookSurfaceProps } from "./NotebookSurface";
export { OptionCard, type OptionCardProps } from "./OptionCard";
export { ContextSlicePanel, type ContextSlicePanelProps } from "./ContextSlicePanel";
export { PlanDiffConfirmation, type PlanDiffConfirmationProps } from "./PlanDiffConfirmation";
export { SelectionActions, type SelectionActionsProps } from "./SelectionActions";
export {
  executability,
  axisNote,
  rankLabel,
  recommendationLabel,
  type Executability,
} from "./statusAxes";
export * from "./contracts";
