// frontend/src/lineage/statusViews.tsx
//
// Inline UI fragments rendered by LineageRouteContainer for loading and
// error branches (Step 5, T5.4). Pulled out of the container so the
// container file stays under the plan §8 T5.4 LOC budget. Copy preserves
// V1.4.1 LineageTab.tsx wording for the existing three error kinds, plus
// new wording for the V1.5.0 unsupported_schema kind.

import type { GraphError } from "./hooks/useGraphData";

export function Loading() {
  return (
    <div className="lineage-root" style={{ padding: 24 }}>
      Loading lineage…
    </div>
  );
}

const ERROR_TITLE: Record<GraphError["kind"], string> = {
  not_found: "Run not found",
  corrupt: "Lineage data is corrupt",
  network: "Could not load lineage",
  adapter_error: "Could not render this graph",
  unsupported_schema: "Unsupported graph schema version",
};

interface ErrorBannerProps {
  error: GraphError;
  onRetry: () => void;
  onHome?: () => void;
}

export function ErrorBanner({ error, onRetry, onHome }: ErrorBannerProps) {
  const detail =
    error.kind === "unsupported_schema"
      ? `Backend returned schema_version=${error.schemaVersion}, which this UI does not understand.`
      : error.detail ?? "";
  const canRetry = error.kind !== "not_found";

  return (
    <div className="lineage-root" style={{ padding: 24 }}>
      <div className="ln-callout ln-callout--red">
        <div className="ln-callout-title">{ERROR_TITLE[error.kind]}</div>
        {detail && <div className="ln-callout-body">{detail}</div>}
        {canRetry && (
          <button
            className="ln-btn-primary"
            onClick={onRetry}
            style={{ marginTop: 12 }}
          >
            Try again
          </button>
        )}
        {!canRetry && onHome && (
          <button
            className="ln-btn-primary"
            onClick={onHome}
            style={{ marginTop: 12 }}
          >
            Back to Home
          </button>
        )}
      </div>
    </div>
  );
}
