// frontend/src/workbench/panels/PlaceholderPanel.tsx
//
// V1.5.2 P4 — shared empty-state body for Shell / Pending / Timeline.
// Each disabled panel registers with `disabled: () => ({reason})` so
// it appears in the tab strip greyed out — but if the user URL-forces
// `?panel=shell&panelOpen=1`, the panel body still renders. That body
// is this placeholder, which makes the deferral copy explicit.

interface PlaceholderPanelProps {
  title: string;
  comingIn: string;
  description: string;
}

export function PlaceholderPanel({
  title,
  comingIn,
  description,
}: PlaceholderPanelProps) {
  return (
    <div
      data-testid={`bottom-panel-placeholder-${title.toLowerCase()}`}
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        gap: 6,
        color: "var(--label-secondary)",
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 14, color: "var(--label)", fontWeight: 600 }}>
        {title} — coming in {comingIn}
      </div>
      <div style={{ fontSize: 12, maxWidth: 480 }}>{description}</div>
    </div>
  );
}
