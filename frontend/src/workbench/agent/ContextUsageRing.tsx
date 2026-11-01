import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";

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
  /** The next request by kind, largest first. */
  breakdown?: { label: string; tokens: number }[];
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
const PART_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-axis)", "var(--chart-grid)"];

function partStyle(index: number, widthPercent?: number) {
  return { background: PART_COLORS[index % PART_COLORS.length], ...(widthPercent === undefined ? {} : { width: `${widthPercent}%` }) };
}

function shortTokens(value: number): string {
  if (value >= 1_000_000) return `${+(value / 1_000_000).toFixed(2)}M`;
  return value >= 1_000 ? `${Math.round(value / 1_000)}K` : String(value);
}

export function ContextUsageRing({
  used,
  remaining,
  total,
  size = 20,
  strokeWidth = 3,
  assumed = false,
  compactAt = null,
  breakdown = [],
  onCompact,
  compacting = false,
}: ContextUsageRingProps) {
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const details = useRef<HTMLDivElement>(null);
  const open = hover || pinned;
  const [placement, setPlacement] = useState<CSSProperties>({ visibility: "hidden" });
  // On the page itself, so the Agent column cannot cut it off; above the ring and inside the window.
  useLayoutEffect(() => {
    if (!open) return undefined;
    const place = () => {
      const ring = root.current?.getBoundingClientRect();
      const width = details.current?.offsetWidth ?? 0;
      if (ring) setPlacement({ left: Math.max(8, Math.min(ring.right - width, window.innerWidth - width - 8)), bottom: window.innerHeight - ring.top + 8 });
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open]);
  useEffect(() => {
    if (!pinned) return undefined;
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !root.current?.contains(event.target as Node) && !details.current?.contains(event.target as Node)) setPinned(false);
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
  // The ring fills toward the next automatic summary: that is the limit that acts.
  const limit = compactAt ?? total;
  const progress = hasCapacity && limit ? Math.min(Math.max(used / limit, 0), 1) : 0;
  const percentage = progress * 100;
  const dashOffset = circumference * (1 - progress);

  const level = !hasCapacity ? "empty" : percentage >= 95 ? "danger" : percentage >= 80 ? "warning" : "normal";
  const leftUntilSummary = Math.max(0, Math.round(100 - percentage));

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
      {level !== "normal" && level !== "empty" && (
        <span className="wb-context-ring-left" aria-hidden="true">{leftUntilSummary}%</span>
      )}
      {open && createPortal(
        <div
          ref={details}
          className="wb-context-ring-tooltip"
          style={placement}
          role={pinned ? "dialog" : "tooltip"}
          aria-label={pinned ? "Context" : undefined}
          data-testid="agent-context-tooltip"
          onClick={(event) => event.stopPropagation()}
        >
          {hasCapacity ? (
            <>
              <div className="wb-context-ring-tooltip-head">
                <strong>{Math.round(percentage)}% used</strong>
                <span>{shortTokens(used)} / {shortTokens(limit as number)}</span>
              </div>
              <div className="wb-context-ring-bar" aria-hidden="true">
                {breakdown.map((part, index) => (
                  <span key={part.label} style={partStyle(index, (part.tokens / (limit as number)) * 100)} />
                ))}
              </div>
              {breakdown.length > 0 && (
                <ul className="wb-context-ring-parts">
                  {breakdown.map((part, index) => (
                    <li key={part.label}>
                      <span className="wb-context-ring-swatch" style={partStyle(index)} />
                      <span>{part.label}</span>
                      <span>{shortTokens(part.tokens)}</span>
                      <span>{((part.tokens / (limit as number)) * 100).toFixed(1)}%</span>
                    </li>
                  ))}
                  <li>
                    <span className="wb-context-ring-swatch" />
                    <span>Free</span>
                    <span>{shortTokens(Math.max(0, (limit as number) - used))}</span>
                    <span>{Math.max(0, 100 - percentage).toFixed(1)}%</span>
                  </li>
                </ul>
              )}
              {compactAt ? <p className="wb-context-ring-note">Summarized at {shortTokens(compactAt)}; the model allows {shortTokens(total as number)}.</p> : null}
              {assumed && (
                <p className="wb-context-ring-note">
                  The model declares no context window, so this one is assumed. Set the real one for the model in Settings › LLM providers.
                </p>
              )}
            </>
          ) : (
            <div className="wb-context-ring-tooltip-head">Context capacity unknown</div>
          )}
          {onCompact && (
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
        </div>,
        document.body,
      )}
    </div>
  );
}
