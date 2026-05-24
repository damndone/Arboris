// frontend/src/lineage/detail/sections/TrustBanner.tsx
//
// V1.5.0 trust banner (Step 6, T6.4). Replaces the V1.4.1 Inspector
// callout logic (Inspector.tsx lines 31-49).
//
// Three variants (spec §8.1 needsTrust + plan T6.4 step 2):
//   1. Any decision has reviewStatus = "needed" | "failed" → orange
//      "Review required" with decisionRegistry-derived titles in the body
//   2. Else trust === "review" → orange "Review suggested"
//   3. Else trust === "caution" → red "Caution"
//   4. Else: do not render (registry's needsTrust gate suppresses mount)
//
// aria-live="polite" so screen readers announce the banner when it
// appears after a refetch flips trust state.

import { getDPDisplay } from "../../decisions/decisionRegistry";
import type { GraphViewNode } from "../../api/graphViewTypes";

type Variant = "review-required" | "review-suggested" | "caution";

interface BannerCopy {
  variant: Variant;
  /** Color token name without the "--" prefix (review | caution). */
  token: "review" | "caution";
  title: string;
  body: string;
}

export function _deriveCopy(node: GraphViewNode): BannerCopy | null {
  const needsReview = node.decisions.filter(
    (d) => d.reviewStatus === "needed" || d.reviewStatus === "failed",
  );
  if (needsReview.length > 0) {
    const titles = needsReview
      .map((d) => getDPDisplay(d.id).title.toLowerCase())
      .join(" and ");
    return {
      variant: "review-required",
      token: "review",
      title: "Review required",
      body: `${needsReview.length} ${needsReview.length === 1 ? "choice needs" : "choices need"} confirmation: ${titles}.`,
    };
  }
  if (node.trust === "review") {
    return {
      variant: "review-suggested",
      token: "review",
      title: "Review suggested",
      body:
        node.trustReason ??
        "Default value was chosen automatically. Confirm before relying on results.",
    };
  }
  if (node.trust === "caution") {
    return {
      variant: "caution",
      token: "caution",
      title: "Caution",
      body:
        node.trustReason ??
        "Manual confirmation of the transform's semantics is required.",
    };
  }
  return null;
}

export function TrustBanner({ node }: { node: GraphViewNode }) {
  const copy = _deriveCopy(node);
  // Defensive: registry's shouldRender suppresses mount when copy is null,
  // but render a no-op rather than throw if the registry is bypassed.
  if (copy === null) return null;

  const tokenVar = `var(--${copy.token})`;
  // Tinted background derived from the same token so dark + light themes
  // stay coherent. color-mix is supported in modern Safari/Chrome/Firefox.
  const background = `color-mix(in oklch, ${tokenVar} 5%, var(--bg-elev))`;

  return (
    <div
      className={`dp-trust ${copy.variant}`}
      role="status"
      aria-live="polite"
      data-testid={`trust-banner-${copy.variant}`}
      style={{
        margin: "12px 0 6px",
        padding: "12px 14px 14px 18px",
        borderRadius: 4,
        border: "1px solid var(--separator)",
        borderLeft: `4px solid ${tokenVar}`,
        background,
      }}
    >
      <div
        style={{
          fontWeight: 600,
          fontSize: 9.5,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          marginBottom: 4,
          fontFamily: "var(--font-mono)",
          color: tokenVar,
        }}
      >
        {copy.title}
      </div>
      <div
        style={{
          color: "var(--label)",
          fontSize: 13,
          lineHeight: 1.5,
        }}
      >
        {copy.body}
      </div>
    </div>
  );
}
