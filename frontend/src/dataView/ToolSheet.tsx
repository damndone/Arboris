// v1.9.0 — the card a Data view tool opens in: what it is, one line on what
// it does, and a way to close it. Transform, Export and AI sharing all use it.

import type { ReactNode } from "react";
import { CloseIcon } from "../workspace/icons";
import "./dataView.css";

export function ToolSheet({
  title,
  description,
  onClose,
  testId,
  children,
}: {
  title: string;
  description: string;
  onClose?: () => void;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <section className="dv-sheet dv-controls" data-testid={testId} aria-label={title}>
      <header className="dv-sheet__head">
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        {onClose && (
          <button type="button" className="ws-icon-button" aria-label={`Close ${title}`} onClick={onClose}>
            <CloseIcon />
          </button>
        )}
      </header>
      {children}
    </section>
  );
}
