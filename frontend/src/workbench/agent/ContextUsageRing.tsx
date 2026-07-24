import { useState } from "react";

export interface ContextUsageRingProps {
  used: number;
  remaining: number;
  /** Total capacity in tokens. `null`/0 renders the empty (unknown) state. */
  total: number | null;
  size?: number;
  strokeWidth?: number;
}

/**
 * A hollow context-usage ring (Codex-style), not a filled pie.
 *
 *   used = total - remaining
 *   progress = clamp(used / total, 0, 1)
 *
 * Two overlapping SVG circles: a low-contrast full track (total capacity) and a
 * high-contrast progress arc (used). The progress arc starts at 12 o'clock and
 * grows clockwise via stroke-dashoffset, animated with a ~200ms ease-out so it
 * never jumps. Ring size and stroke width are fixed, so progress never causes
 * layout jitter. The token details live only in the hover tooltip.
 */
export function ContextUsageRing({
  used,
  remaining,
  total,
  size = 20,
  strokeWidth = 2,
}: ContextUsageRingProps) {
  const [hover, setHover] = useState(false);

  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  const hasCapacity = typeof total === "number" && total > 0;
  const progress = hasCapacity ? Math.min(Math.max(used / total, 0), 1) : 0;
  const percentage = progress * 100;
  const dashOffset = circumference * (1 - progress);

  const level = !hasCapacity
    ? "empty"
    : percentage >= 95
      ? "danger"
      : percentage >= 80
        ? "warning"
        : "normal";

  const ariaLabel = hasCapacity
    ? `Context usage: ${Math.round(percentage)}%, ${remaining.toLocaleString()} tokens remaining out of ${total.toLocaleString()}`
    : "Context usage: capacity unknown";

  const center = size / 2;

  return (
    <div
      className="wb-context-ring"
      data-level={level}
      data-testid="agent-context-ring"
      role="img"
      aria-label={ariaLabel}
      tabIndex={0}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle
          className="wb-context-ring-track"
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
        />
        {hasCapacity && (
          <circle
            className="wb-context-ring-progress"
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            transform={`rotate(-90 ${center} ${center})`}
          />
        )}
      </svg>
      {hover && (
        <div className="wb-context-ring-tooltip" role="tooltip" data-testid="agent-context-tooltip">
          {hasCapacity ? (
            <>
              <div className="wb-context-ring-tooltip-head">
                <strong>{Math.round(percentage)}%</strong> of context used
              </div>
              <dl>
                <div><dt>Used</dt><dd>{used.toLocaleString()}</dd></div>
                <div><dt>Remaining</dt><dd>{remaining.toLocaleString()}</dd></div>
                <div><dt>Total</dt><dd>{total.toLocaleString()}</dd></div>
              </dl>
            </>
          ) : (
            <div className="wb-context-ring-tooltip-head">Context capacity unknown</div>
          )}
        </div>
      )}
    </div>
  );
}
