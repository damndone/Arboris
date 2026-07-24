import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useRef, useState, type FocusEvent } from "react";
import type {
  AgentCapability,
  AgentCapabilityCatalog,
  AgentCapabilityBoundaryItem,
} from "./agentTypes";

type CapabilityListItem = AgentCapability | AgentCapabilityBoundaryItem;

function BoundaryList({
  title,
  items,
  testId,
  onPromptSelect,
  actionLabel,
}: {
  title: string;
  items: CapabilityListItem[];
  testId: string;
  onPromptSelect?: (prompt: string) => void;
  actionLabel: string;
}) {
  return (
    <section data-testid={testId} className="wb-agent-capability-section">
      <h4>{title}</h4>
      {items.length === 0 ? (
        <p className="wb-agent-capability-empty">No registered capabilities</p>
      ) : (
        <ul>
          {items.map((item) => {
            const executable = "operation_id" in item;
            const operationId = executable ? item.operation_id : item.id;
            const description = executable ? item.ui_description : item.description;
            const examples = executable ? item.example_prompts : [];
            const prompt = examples[0]
              ?? (executable
                ? `Explain how to use ${item.operation_id} for the current analysis.`
                : `Explain ${item.label} for the current analysis.`);
            return (
              <li key={operationId}>
                <div className="wb-agent-capability-title">
                  <span aria-hidden="true">{executable ? "✓" : "○"}</span>
                  <strong>{executable ? description : item.label}</strong>
                </div>
                <div className="wb-agent-capability-description">{description}</div>
                {executable && (
                  <div className="wb-agent-capability-meta">
                    {item.risk_level} · confirmation: {item.confirmation_policy} · {operationId}
                  </div>
                )}
                {examples.length > 0 && (
                  <div className="wb-agent-capability-example">Example: {examples[0]}</div>
                )}
                {onPromptSelect && (
                  <button
                    type="button"
                    className="wb-agent-capability-action"
                    data-testid={`agent-capability-use-${operationId}`}
                    onClick={() => onPromptSelect(prompt)}
                  >
                    {actionLabel}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function AgentCapabilityPopover({
  catalog,
  onPromptSelect,
}: {
  catalog?: AgentCapabilityCatalog | null;
  onPromptSelect?: (prompt: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const closeTimerRef = useRef<number | null>(null);
  const [popoverPosition, setPopoverPosition] = useState({ left: 16, bottom: 16 });
  const hasCatalog = Boolean(
    catalog
      && Array.isArray(catalog.capabilities)
      && catalog.boundary
      && Array.isArray(catalog.boundary.advisory)
      && Array.isArray(catalog.boundary.unsupported),
  );
  const capabilities = Array.isArray(catalog?.capabilities) ? catalog.capabilities : [];
  const advisory = Array.isArray(catalog?.boundary?.advisory) ? catalog.boundary.advisory : [];
  const unsupported = Array.isArray(catalog?.boundary?.unsupported)
    ? catalog.boundary.unsupported
    : [];
  const executable = capabilities.filter((item) => item.natural_language_enabled);
  const selectPrompt = (prompt: string) => {
    onPromptSelect?.(prompt);
    setOpen(false);
  };

  const cancelClose = () => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  };
  const openFromInteraction = () => {
    cancelClose();
    setOpen(true);
  };
  const scheduleClose = () => {
    cancelClose();
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null;
      setOpen(false);
    }, 100);
  };
  const handleBlur = (event: FocusEvent<HTMLElement>) => {
    const next = event.relatedTarget;
    if (
      next instanceof Node
      && (triggerRef.current?.contains(next) || popoverRef.current?.contains(next))
    ) return;
    scheduleClose();
  };

  useEffect(() => () => cancelClose(), []);

  useLayoutEffect(() => {
    if (!open) return undefined;

    const updatePopoverPosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;

      // Anchor the panel's LEFT edge to the trigger (which lives on the bottom
      // left) and clamp it inside the viewport, so a left-side trigger never
      // pushes the panel off the left edge. Fall back to the CSS max width
      // before the panel has measured itself.
      const width = popoverRef.current?.offsetWidth || Math.min(390, window.innerWidth - 32);
      const left = Math.min(Math.max(16, rect.left), Math.max(16, window.innerWidth - width - 16));
      setPopoverPosition({
        left,
        bottom: Math.max(16, window.innerHeight - rect.top + 8),
      });
    };

    updatePopoverPosition();
    window.addEventListener("resize", updatePopoverPosition);
    window.addEventListener("scroll", updatePopoverPosition, true);
    return () => {
      window.removeEventListener("resize", updatePopoverPosition);
      window.removeEventListener("scroll", updatePopoverPosition, true);
    };
  }, [open]);

  const popover = open ? (
    <div
      role="dialog"
      aria-label="Agent capabilities"
      data-testid="agent-capability-popover"
      className="wb-agent-capability-popover"
      ref={popoverRef}
      onMouseEnter={cancelClose}
      onMouseLeave={scheduleClose}
      onFocus={openFromInteraction}
      onBlur={handleBlur}
      style={{
        position: "fixed",
        left: `${popoverPosition.left}px`,
        right: "auto",
        bottom: `${popoverPosition.bottom}px`,
      }}
    >
      {!hasCatalog ? (
        <div className="wb-agent-capability-unavailable">Capabilities unavailable</div>
      ) : (
        <>
          <p className="wb-agent-capability-help">
            Choose an action to place a prompt in the composer. Nothing runs until you send it and confirm any proposal.
          </p>
          <BoundaryList
            title="Available to run"
            items={executable}
            testId="agent-capability-executable"
            onPromptSelect={selectPrompt}
            actionLabel="Use example"
          />
          <BoundaryList
            title="Ask Agent (read-only)"
            items={advisory}
            testId="agent-capability-advisory"
            onPromptSelect={selectPrompt}
            actionLabel="Ask about this"
          />
          <BoundaryList
            title="Not supported"
            items={unsupported}
            testId="agent-capability-unsupported"
            onPromptSelect={selectPrompt}
            actionLabel="Explain limitation"
          />
        </>
      )}
    </div>
  ) : null;

  return (
    <>
      <div className="wb-agent-capability-control">
        <button
          ref={triggerRef}
          type="button"
          className="wb-agent-capability-trigger"
          aria-haspopup="dialog"
          aria-expanded={open}
          data-testid="agent-capability-trigger"
          onMouseEnter={openFromInteraction}
          onMouseLeave={scheduleClose}
          onFocus={openFromInteraction}
          onBlur={handleBlur}
          onClick={() => setOpen((value) => !value)}
        >
          Capabilities
        </button>
      </div>
      {popover && createPortal(popover, document.body)}
    </>
  );
}
