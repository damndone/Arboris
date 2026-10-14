import { useEffect, useRef, useState } from "react";

export interface ContextUsageRingProps {
  used: number;
  remaining: number;
  /** Total capacity in tokens. `null`/0 renders the empty (unknown) state. */
  total: number | null;
  size?: number;
  strokeWidth?: number;
  /** The model declares no window; ``total`` is the Workbench's assumption. */
  assumed?: boolean;
  /** Above this the earlier conversation is summarized automatically. */
  compactAt?: number | null;
  /** Clicking the ring pins its details with a "summarize now" action. */
  onCompact?: () => void;
  compacting?: boolean;
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
  assumed = false,
  compactAt = null,
  onCompact,
  compacting = false,
}: ContextUsageRingProps) {
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!pinned) return undefined;
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !root.current?.contains(event.target as Node)) setPinned(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, [pinned]);

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
      ref={root}
      className="wb-context-ring"
      data-level={level}
      data-testid="agent-context-ring"
      role={onCompact ? "button" : "img"}
      aria-label={onCompact ? `${ariaLabel}. Show details` : ariaLabel}
      aria-expanded={onCompact ? pinned : undefined}
      tabIndex={0}
      onClick={onCompact ? () => setPinned((open) => !open) : undefined}
      onKeyDown={onCompact ? (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          setPinned((open) => !open);
        }
      } : undefined}
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
      {(hover || pinned) && (
        <div
          className="wb-context-ring-tooltip"
          role={pinned ? "dialog" : "tooltip"}
          aria-label={pinned ? "Context" : undefined}
          data-testid="agent-context-tooltip"
          onClick={(event) => event.stopPropagation()}
        >
          {hasCapacity ? (
            <>
              <div className="wb-context-ring-tooltip-head">
                <strong>{Math.round(percentage)}%</strong> of context used
              </div>
              <dl>
                <div><dt>Used</dt><dd>{used.toLocaleString()}</dd></div>
                <div><dt>Remaining</dt><dd>{remaining.toLocaleString()}</dd></div>
                <div><dt>Total</dt><dd>{total.toLocaleString()}{assumed ? " (assumed)" : ""}</dd></div>
                {compactAt ? <div><dt>Summarized at</dt><dd>{compactAt.toLocaleString()}</dd></div> : null}
              </dl>
              {assumed && (
                <p className="wb-context-ring-note">
                  The model declares no context window, so this one is assumed. Set the real one for the model in Settings › LLM providers.
                </p>
              )}
            </>
          ) : (
            <div className="wb-context-ring-tooltip-head">Context capacity unknown</div>
          )}
          {pinned && onCompact && (
            <button
              type="button"
              className="wb-context-ring-action"
              disabled={compacting}
              onClick={() => {
                onCompact();
                setPinned(false);
              }}
            >
              {compacting ? "Summarizing…" : "Summarize earlier conversation"}
            </button>
          )}
          {pinned && onCompact && (
            <p className="wb-context-ring-note">
              Earlier messages are replaced by a checked summary in what the Agent reads; the full conversation stays here.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
