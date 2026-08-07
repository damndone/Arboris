/**
 * Statistical analysis workbench — Design Tokens (TypeScript)
 *
 * Generated equivalents of styles.css :root variables.
 * Import these constants OR consume the CSS variables directly (`var(--text)`).
 *
 * Both dark (default) and light theme values are exported.
 */

export type Stage =
  | "source" | "eda" | "clean" | "transform"
  | "model" | "diag" | "viz" | "report";

export type TrustLevel = "ok" | "review" | "caution";

export const fonts = {
  serif: `"Iowan Old Style", "Source Serif Pro", "Charter", Georgia, "Songti SC", "Noto Serif CJK SC", serif`,
  sans:  `-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif`,
  mono:  `ui-monospace, "SF Mono", Menlo, Consolas, "Roboto Mono", monospace`,
} as const;

export const fontSize = {
  xs:  "10.5px",
  sm:  "11.5px",
  md:  "13px",
  lg:  "14.5px",
  xl:  "20px",
  "2xl": "28px",
} as const;

export const radius = {
  sm: "4px",
  md: "8px",
  lg: "12px",
  xl: "16px",
} as const;

export const space = {
  0.5: "2px", 1: "4px",  2: "8px",  3: "12px",
  4: "16px",  5: "20px", 6: "24px",
} as const;

export const shadow = {
  sm: "0 1px 2px rgba(0,0,0,0.4)",
  md: "0 12px 28px rgba(0,0,0,0.42), 0 2px 6px rgba(0,0,0,0.3)",
  lg: "0 28px 64px rgba(0,0,0,0.5), 0 4px 12px rgba(0,0,0,0.32)",
} as const;

export const blur = {
  thin:    "blur(16px) saturate(140%)",
  regular: "blur(22px) saturate(150%)",
  thick:   "blur(30px) saturate(160%)",
} as const;

export const colorsDark = {
  bg:       "oklch(0.165 0.006 70)",
  bgDeep:   "oklch(0.135 0.006 70)",
  hairline:        "rgba(255,250,240,0.08)",
  hairlineStrong:  "rgba(255,250,240,0.16)",
  text:        "oklch(0.94 0.008 75)",
  textDim:     "oklch(0.72 0.008 75)",
  textFaint:   "oklch(0.50 0.008 75)",
  textMono:    "oklch(0.82 0.008 75)",
  ink:     "oklch(0.72 0.08 240)",
  indigo:  "oklch(0.62 0.07 260)",
  statusReview:  "oklch(0.74 0.10 65)",
  statusCaution: "oklch(0.62 0.13 25)",
  statusOk:      "oklch(0.70 0.07 155)",
  stage: {
    source:    "oklch(0.58 0.008 75)",
    eda:       "oklch(0.66 0.04 220)",
    clean:     "oklch(0.66 0.04 250)",
    transform: "oklch(0.72 0.10 65)",
    model:     "oklch(0.70 0.06 200)",
    diag:      "oklch(0.62 0.04 280)",
    viz:       "oklch(0.66 0.04 320)",
    report:    "oklch(0.74 0.06 75)",
  } satisfies Record<Stage, string>,
  material: {
    ultrathin: "rgba(255,250,240,0.025)",
    thin:      "rgba(255,250,240,0.045)",
    regular:   "rgba(255,250,240,0.06)",
    thick:     "rgba(22,20,18,0.78)",
    chrome:    "rgba(18,16,14,0.88)",
  },
} as const;

export const colorsLight = {
  bg:       "oklch(0.965 0.012 80)",
  bgDeep:   "oklch(0.94 0.014 78)",
  hairline:       "rgba(20,18,16,0.10)",
  hairlineStrong: "rgba(20,18,16,0.20)",
  text:      "oklch(0.22 0.010 75)",
  textDim:   "oklch(0.40 0.010 75)",
  textFaint: "oklch(0.55 0.008 75)",
  textMono:  "oklch(0.30 0.010 75)",
  ink:    "oklch(0.48 0.10 240)",
  indigo: "oklch(0.46 0.10 260)",
  statusReview:  "oklch(0.62 0.12 65)",
  statusCaution: "oklch(0.55 0.16 25)",
  statusOk:      "oklch(0.55 0.08 155)",
  stage: {
    source:    "oklch(0.50 0.010 75)",
    eda:       "oklch(0.50 0.04 220)",
    clean:     "oklch(0.48 0.05 250)",
    transform: "oklch(0.55 0.13 65)",
    model:     "oklch(0.50 0.06 200)",
    diag:      "oklch(0.48 0.06 280)",
    viz:       "oklch(0.52 0.05 320)",
    report:    "oklch(0.55 0.08 75)",
  } satisfies Record<Stage, string>,
  material: {
    ultrathin: "rgba(255,255,255,0.55)",
    thin:      "rgba(255,255,255,0.65)",
    regular:   "rgba(255,255,255,0.72)",
    thick:     "rgba(255,254,250,0.86)",
    chrome:    "rgba(252,250,245,0.92)",
  },
} as const;

export type ColorPalette = typeof colorsDark;

export const tokens = {
  fonts, fontSize, radius, space, shadow, blur,
  dark:  colorsDark,
  light: colorsLight,
} as const;

export default tokens;
