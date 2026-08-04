import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type CSSProperties,
} from "react";
import { ReportComposer } from "./ReportComposer";
import "./report.css";

interface PreviewPoint {
  x: number;
  y: number;
}

interface PreviewSize {
  width: number;
  height: number;
}

export interface ReportPreviewPanelProps {
  children: ReactNode;
  value: string;
  onChange: (value: string) => void;
  onRevise: () => void;
  busy: boolean;
  contextLines?: readonly string[];
  contextDetails?: readonly string[];
  contextUsedTokens?: number;
  contextWindowTokens?: number | null;
}

/**
 * A report-only draft window. The panel owns presentation state (dock/float,
 * pin, collapse, drag) while ReportView owns the immutable evidence and the
 * revision request. Children are deliberately rendered as opaque prose content.
 */
export function ReportPreviewPanel({
  children,
  value,
  onChange,
  onRevise,
  busy,
  contextLines = [],
  contextDetails = [],
  contextUsedTokens = 1,
  contextWindowTokens = null,
}: ReportPreviewPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [layout, setLayout] = useState<"docked" | "floating">("docked");
  const [pinned, setPinned] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [position, setPosition] = useState<PreviewPoint>({ x: 36, y: 116 });
  const [panelSize, setPanelSize] = useState<PreviewSize | null>(null);
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ offsetX: number; offsetY: number } | null>(null);

  const handlePointerMove = useCallback((event: PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    setPosition({
      x: Math.max(8, event.clientX - drag.offsetX),
      y: Math.max(56, event.clientY - drag.offsetY),
    });
  }, []);

  const stopDragging = useCallback(() => {
    dragRef.current = null;
    setDragging(false);
  }, []);

  useEffect(() => {
    if (!dragging) return undefined;
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
    };
  }, [dragging, handlePointerMove, stopDragging]);

  const beginDragging = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (layout !== "floating") return;
    const rect = panelRef.current?.getBoundingClientRect();
    if (!rect) return;
    event.preventDefault();
    dragRef.current = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    setDragging(true);
  };

  const moveWithKeyboard = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (layout !== "floating") return;
    const step = event.shiftKey ? 64 : 16;
    const deltas: Record<string, PreviewPoint> = {
      ArrowLeft: { x: -step, y: 0 },
      ArrowRight: { x: step, y: 0 },
      ArrowUp: { x: 0, y: -step },
      ArrowDown: { x: 0, y: step },
    };
    const delta = deltas[event.key];
    if (!delta) return;
    event.preventDefault();
    setPosition((current) => ({
      x: Math.max(8, current.x + delta.x),
      y: Math.max(56, current.y + delta.y),
    }));
  };

  const resizePreview = (direction: "larger" | "smaller") => {
    const base = panelSize ?? { width: 680, height: 720 };
    const delta = direction === "larger" ? 80 : -80;
    setPanelSize({
      width: Math.min(960, Math.max(360, base.width + delta)),
      height: Math.min(900, Math.max(280, base.height + delta)),
    });
  };

  const togglePinned = () => {
    const nextPinned = !pinned;
    setPinned(nextPinned);
    if (nextPinned && layout === "docked") {
      setLayout("floating");
      const width = Math.min(720, Math.max(360, window.innerWidth - 32));
      setPosition({
        x: Math.max(8, window.innerWidth - width - 16),
        y: 96,
      });
    }
  };

  return (
    <section
      ref={panelRef}
      data-testid="report-preview-panel"
      data-layout={layout}
      data-pinned={pinned ? "true" : "false"}
      data-collapsed={collapsed ? "true" : "false"}
      className={`report-preview-panel report-preview-panel--${layout}${pinned ? " report-preview-panel--pinned" : ""}${dragging ? " report-preview-panel--dragging" : ""}`}
      style={layout === "floating" ? {
        "--report-preview-left": `${position.x}px`,
        "--report-preview-top": `${position.y}px`,
        ...(panelSize ? { width: `${panelSize.width}px`, height: `${panelSize.height}px` } : {}),
      } as CSSProperties : undefined}
    >
      <header className="report-preview-panel__header">
        <button
          type="button"
          className="report-preview-panel__drag-handle"
          aria-label="Drag report preview"
          aria-pressed={dragging}
          aria-keyshortcuts="ArrowUp ArrowDown ArrowLeft ArrowRight"
          title={layout === "floating" ? "Drag preview" : "Switch to floating to drag"}
          onPointerDown={beginDragging}
          onKeyDown={moveWithKeyboard}
        >
          <span aria-hidden="true">⋮⋮</span>
        </button>
        <div className="report-preview-panel__title">
          <strong>Report preview</strong>
          <span>Draft · source evidence is immutable</span>
        </div>
        <div className="report-preview-panel__controls">
          <button
            type="button"
            aria-label={layout === "floating" ? "Dock preview" : "Float preview"}
            onClick={() => setLayout((current) => current === "docked" ? "floating" : "docked")}
          >
            {layout === "floating" ? "Dock" : "Float"}
          </button>
          <button
            type="button"
            aria-label={pinned ? "Unpin preview" : "Pin preview"}
            onClick={togglePinned}
          >
            {pinned ? "Unpin" : "Pin"}
          </button>
          <button
            type="button"
            aria-label={collapsed ? "Expand preview" : "Collapse preview"}
            onClick={() => setCollapsed((current) => !current)}
          >
            {collapsed ? "Expand" : "Collapse"}
          </button>
          {layout === "floating" && (
            <>
              <button
                type="button"
                aria-label="Make preview smaller"
                title="Make preview smaller"
                onClick={() => resizePreview("smaller")}
              >
                −
              </button>
              <button
                type="button"
                aria-label="Make preview larger"
                title="Make preview larger"
                onClick={() => resizePreview("larger")}
              >
                ＋
              </button>
            </>
          )}
        </div>
      </header>
      {!collapsed && (
        <>
          <div data-testid="report-preview-content" className="report-preview-panel__content">
            {children}
          </div>
          <div className="report-preview-panel__footer">
            <div className="report-preview-panel__guardrail">
              Agent may revise prose only. Source facts, results, and lineage remain read-only.
            </div>
            <ReportComposer
              value={value}
              onChange={onChange}
              onSubmit={onRevise}
              submitLabel="Revise draft"
              placeholder="告诉 Agent 如何修改这份报告…"
              ariaLabel="Report revision instruction"
              contextLines={contextLines}
              contextDetails={contextDetails}
              contextUsedTokens={contextUsedTokens}
              contextWindowTokens={contextWindowTokens}
              busy={busy}
            />
          </div>
        </>
      )}
    </section>
  );
}
