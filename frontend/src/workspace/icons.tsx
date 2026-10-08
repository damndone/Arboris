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
    <path d="M2 4.5h7.5M12.5 4.5H14M2 11.5h1.5M6.5 11.5H14" />
    <circle cx="11" cy="4.5" r="1.5" />
    <circle cx="5" cy="11.5" r="1.5" />
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

export const ChevronIcon = ({ direction }: { direction: "up" | "down" }) => (
  <Icon size={14}>
    <path d={direction === "up" ? "M3.5 10 8 5.5l4.5 4.5" : "M3.5 6 8 10.5 12.5 6"} />
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
