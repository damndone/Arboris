// Classic shell: shows or hides the run history rail (moved out of
// WorkbenchRouteContainer in v1.9.0).

export function RunHistoryToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      data-testid="run-history-toggle"
      aria-label={open ? "Hide run history" : "Show run history"}
      title={open ? "Hide runs" : "Show runs"}
      onClick={onToggle}
      style={{
        alignItems: "center",
        display: "inline-flex",
        height: 28,
        justifyContent: "center",
        padding: 4,
        width: 28,
        border: 0,
        borderRadius: 6,
        background: "transparent",
        color: "var(--label-secondary)",
        cursor: "pointer",
        fontSize: 12,
      }}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="3" y="4" width="18" height="16" rx="2.5" stroke="currentColor" strokeWidth="1.6" />
        <line x1="9" y1="4" x2="9" y2="20" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    </button>
  );
}
