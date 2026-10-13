// v1.9.0 — line icons for the workspace chrome: 16px grid, 1.5px stroke,
// currentColor, never emoji (design spec §8.5).

import type { ReactNode } from "react";

function Icon({ size = 16, children }: { size?: number; children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export const SidebarIcon = () => (
  <Icon>
    <rect x="1.75" y="2.75" width="12.5" height="10.5" rx="2" />
    <path d="M6 2.75v10.5" />
  </Icon>
);

export const BrandIcon = () => (
  <Icon size={18}>
    <path d="M8 14.5V7" />
    <path d="M8 10 4.5 7" />
    <path d="M8 8.5l3-2.6" />
    <circle cx="8" cy="4.4" r="1.8" />
    <circle cx="4" cy="5.8" r="1.4" />
    <circle cx="11.6" cy="4.9" r="1.4" />
  </Icon>
);

export const ResultsIcon = () => (
  <Icon size={14}>
    <rect x="2" y="2.5" width="12" height="11" rx="2" />
    <path d="M5 10.5V8M8 10.5V5.5M11 10.5V7" />
  </Icon>
);

export const LineageIcon = () => (
  <Icon size={14}>
    <circle cx="3.5" cy="8" r="1.6" />
    <circle cx="12.5" cy="4" r="1.6" />
    <circle cx="12.5" cy="12" r="1.6" />
    <path d="M5 8h3M8 8l3-3.2M8 8l3 3.2" />
  </Icon>
);

export const SearchIcon = () => (
  <Icon size={15}>
    <circle cx="7" cy="7" r="4.75" />
    <path d="M10.5 10.5 14 14" />
  </Icon>
);

export const SettingsIcon = () => (
  <Icon>
    <circle cx="8" cy="8" r="2.1" />
    <path d="M8 1.75v1.6M8 12.65v1.6M14.25 8h-1.6M3.35 8h-1.6M12.42 3.58l-1.13 1.13M4.71 11.29l-1.13 1.13M12.42 12.42l-1.13-1.13M4.71 4.71 3.58 3.58" />
    <circle cx="8" cy="8" r="4.6" />
  </Icon>
);

export const SendIcon = () => (
  <Icon>
    <path d="M8 12.75V3.5" />
    <path d="M4.25 7.25 8 3.5l3.75 3.75" />
  </Icon>
);

export const StopIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
    <rect x="2" y="2" width="8" height="8" rx="1.5" fill="currentColor" />
  </svg>
);

export const ReviewIcon = () => (
  <Icon size={14}>
    <path d="M8 1.75 13 3.5v4c0 3.2-2.1 5.6-5 6.75C5.1 13.1 3 10.7 3 7.5v-4z" />
    <path d="M5.75 8.1 7.3 9.6l3-3.2" />
  </Icon>
);

export const PlusIcon = () => (
  <Icon size={13}>
    <path d="M8 3.25v9.5M3.25 8h9.5" />
  </Icon>
);

export const AgentRailIcon = () => (
  <Icon>
    <path d="M2.75 3.25h10.5v7H7.5L4.5 13v-2.75H2.75z" />
  </Icon>
);

export const FoldRightIcon = () => (
  <Icon>
    <rect x="1.75" y="2.75" width="12.5" height="10.5" rx="2" />
    <path d="M10 2.75v10.5" />
  </Icon>
);

const CHEVRON = {
  up: "M3.5 10 8 5.5l4.5 4.5",
  down: "M3.5 6 8 10.5 12.5 6",
  left: "M10 3.5 5.5 8l4.5 4.5",
  right: "M6 3.5 10.5 8 6 12.5",
};

export const ChevronIcon = ({ direction }: { direction: keyof typeof CHEVRON }) => (
  <Icon size={14}>
    <path d={CHEVRON[direction]} />
  </Icon>
);

export const ExpandIcon = () => (
  <Icon size={14}>
    <path d="M9.5 2.5h4v4" />
    <path d="M6.5 13.5h-4v-4" />
    <path d="M13.5 2.5 9 7" />
    <path d="M2.5 13.5 7 9" />
  </Icon>
);

/** Dock into the right-hand column. */
export const DockIcon = () => (
  <Icon>
    <rect x="1.75" y="2.75" width="12.5" height="10.5" rx="2" />
    <path d="M9.75 2.75v10.5" />
    <path d="M11.5 5.5h1M11.5 7.5h1" />
  </Icon>
);

/** Lift out into a floating window. */
export const FloatIcon = () => (
  <Icon>
    <rect x="1.75" y="4.75" width="9.5" height="8.5" rx="1.75" />
    <path d="M6.5 2.75h5.25a2 2 0 0 1 2 2V10" />
  </Icon>
);

/** Fold down to the bubble. */
export const MinimizeIcon = () => (
  <Icon>
    <path d="M4.5 4.5 11 11" />
    <path d="M11 6.5V11H6.5" />
  </Icon>
);

export const GripIcon = () => (
  <svg width="10" height="16" viewBox="0 0 10 16" fill="currentColor" aria-hidden="true">
    <circle cx="3" cy="4" r="1.1" />
    <circle cx="7" cy="4" r="1.1" />
    <circle cx="3" cy="8" r="1.1" />
    <circle cx="7" cy="8" r="1.1" />
    <circle cx="3" cy="12" r="1.1" />
    <circle cx="7" cy="12" r="1.1" />
  </svg>
);

/** Transform: a wand. */
export const TransformIcon = () => (
  <Icon>
    <path d="M2.5 13.5 9.5 6.5" />
    <path d="M11 2v2M11 6v2M9 4h-2M15 4h-2" />
    <path d="M13 9.5v1.5M12.25 10.25h1.5" />
  </Icon>
);

/** Export: an arrow out of a tray. */
export const ExportIcon = () => (
  <Icon>
    <path d="M8 10V2.5M5 5.5 8 2.5l3 3" />
    <path d="M2.75 9.5v3a1 1 0 0 0 1 1h8.5a1 1 0 0 0 1-1v-3" />
  </Icon>
);

/** Sharing with AI providers: a shield. */
export const ShieldIcon = () => (
  <Icon>
    <path d="M8 1.75 13.25 3.75v4c0 3.1-2.2 5.4-5.25 6.5-3.05-1.1-5.25-3.4-5.25-6.5v-4z" />
    <path d="M5.75 8 7.4 9.6 10.5 6.4" />
  </Icon>
);

export const CloseIcon = () => (
  <Icon size={14}>
    <path d="M4 4l8 8M12 4l-8 8" />
  </Icon>
);
