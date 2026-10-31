// v1.9.1 — a button in the composer bar that opens a small sheet above it,
// the way Claude Code's mode and model pickers do. Escape and a click outside
// close it; focus returns to the button.

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

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
/** A setting with ordered levels: drag or use the arrow keys; the choice saves as it moves. */
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
  const [shown, setShown] = useState(value);
  useEffect(() => setShown(value), [value]);
  const index = Math.max(0, options.findIndex((option) => option.value === shown));
  return (
    <label className="ws-menu__slider" title={title}>
      <span className="ws-menu__slider-head">
        <span>{label}</span>
        <span className="ws-menu__slider-value">{options[index]?.label}</span>
      </span>
      <input
        type="range"
        min={0}
        max={options.length - 1}
        step={1}
        value={index}
        aria-label={label}
        aria-valuetext={options[index]?.label}
        onChange={(event) => {
          const next = options[Number(event.target.value)];
          if (!next) return;
          setShown(next.value);
          onChange(next.value);
        }}
      />
    </label>
  );
}
