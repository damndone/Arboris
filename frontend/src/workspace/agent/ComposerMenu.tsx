// v1.9.1 — a button in the composer bar that opens a small sheet above it,
// the way Claude Code's mode and model pickers do. Escape and a click outside
// close it; focus returns to the button.

import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";

const THUMB = 16;

/** Positions computed while dragging; everything static lives in the stylesheet. */
function geometry(property: "left" | "width", value: string, opacity?: number): CSSProperties {
  return { [property]: value, ...(opacity === undefined ? {} : { opacity }) };
}

export function ComposerMenu({
  label,
  title,
  disabled,
  className,
  children,
}: {
  /** What the button shows: the current choice. */
  label: ReactNode;
  /** The button's accessible name and tooltip. */
  title: string;
  disabled?: boolean;
  className?: string;
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const sheetId = useId();

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape, true);
    };
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const close = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };

  return (
    <div ref={rootRef} className={`ws-menu ${className ?? ""}`}>
      <button
        ref={buttonRef}
        type="button"
        className="ws-menu__button"
        aria-label={title}
        title={title}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? sheetId : undefined}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
      >
        {label}
        <svg className="ws-menu__chevron" viewBox="0 0 10 10" width="8" height="8" aria-hidden="true">
          <path d="M2 6.5 5 3.5 8 6.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div id={sheetId} role="dialog" aria-label={title} className="ws-menu__sheet">
          {children(close)}
        </div>
      )}
    </div>
  );
}

/** A row of equal choices (Off / Low / High / Max), one selected. */
/** A setting with ordered levels: every level is a visible stop, and the bar deepens as it rises.
 *  The thumb follows the pointer and settles on the nearest stop; the choice saves on release. */
export function StepSlider<T extends string>({
  label,
  title,
  options,
  value,
  onChange,
}: {
  label: string;
  title?: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  const track = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const [chosen, setChosen] = useState(value);
  useEffect(() => setChosen(value), [value]);
  const last = options.length - 1;
  const index = Math.max(0, options.findIndex((option) => option.value === chosen));
  const position = drag ?? (last > 0 ? index / last : 0);
  const shown = last > 0 ? Math.round(position * last) : 0;
  const choose = (next: number) => {
    const option = options[Math.min(last, Math.max(0, next))];
    if (!option) return;
    setChosen(option.value);
    if (option.value !== chosen) onChange(option.value);
  };
  const fraction = (clientX: number) => {
    const box = track.current?.getBoundingClientRect();
    if (!box || box.width <= THUMB) return position;
    return Math.min(1, Math.max(0, (clientX - box.left - THUMB / 2) / (box.width - THUMB)));
  };
  const at = (share: number) => `calc(${THUMB / 2}px + ${share} * (100% - ${THUMB}px))`;
  return (
    <div className="ws-menu__slider" title={title}>
      <div className="ws-menu__slider-head">
        <span>{label}</span>
        <span className="ws-menu__slider-value">{options[shown]?.label}</span>
      </div>
      <div
        ref={track}
        className="ws-menu__slider-track"
        data-dragging={drag !== null || undefined}
        role="slider"
        tabIndex={0}
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={last}
        aria-valuenow={shown}
        aria-valuetext={options[shown]?.label}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture?.(event.pointerId);
          setDrag(fraction(event.clientX));
        }}
        onPointerMove={(event) => { if (drag !== null) setDrag(fraction(event.clientX)); }}
        onPointerUp={(event) => {
          if (drag === null) return;
          setDrag(null);
          choose(Math.round(fraction(event.clientX) * last));
        }}
        onPointerCancel={() => setDrag(null)}
        onKeyDown={(event) => {
          const next = { ArrowLeft: index - 1, ArrowDown: index - 1, ArrowRight: index + 1, ArrowUp: index + 1, Home: 0, End: last }[event.key];
          if (next === undefined) return;
          event.preventDefault();
          choose(next);
        }}
      >
        <span className="ws-menu__slider-rail" />
        <span className="ws-menu__slider-fill" style={geometry("width", at(position), 0.35 + 0.65 * position)} />
        {options.map((option, stop) => (
          <span
            key={option.value}
            className="ws-menu__slider-stop"
            data-passed={stop <= shown || undefined}
            style={geometry("left", at(last > 0 ? stop / last : 0))}
          />
        ))}
        <span className="ws-menu__slider-thumb" style={geometry("left", at(position))} />
      </div>
    </div>
  );
}
