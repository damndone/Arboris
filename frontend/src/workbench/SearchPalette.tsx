// frontend/src/workbench/SearchPalette.tsx
//
// V1.5.2 P7 — ⌘K search palette. Plan §10.
//
// Contract:
//   - ⌘K opens the palette (toggle if already open)
//   - Escape closes; does NOT commit any state changes
//   - Up/Down arrow keys move the result cursor
//   - Typing in the input filters live; the query is NOT written
//     to URL until Enter/click commits
//   - Hover over a result also sets the cursor (transient, Tier 3)
//   - Enter or click on a result → dispatch.selectBySearchCommit
//     which writes ?q= to URL, opens the tab, sets focus, unpins
//
// Search backend: RunSnapshotAdapter.searchIndex (built once per
// model, projects node/variable/model/decision into hit items
// that resolve to a nodeKey). Cap displayed results at 25 to
// keep the palette snappy; users can refine the query.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useLineage } from "../lineage/LineageContext";
import { buildRunSnapshot, type SearchItem } from "./RunSnapshotAdapter";
import { useWorkbench } from "./WorkbenchStateProvider";
import { isEditableTarget } from "./keyboard";

const MAX_RESULTS = 25;

export function SearchPalette() {
  const { model } = useLineage();
  const { state, dispatch } = useWorkbench();
  const [open, setOpen] = useState(false);
  // Local input — divorced from URL state.searchQuery on purpose so
  // typing doesn't churn the URL. URL only updates on commit.
  const [input, setInput] = useState(state.searchQuery);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Build snapshot once per model. Cheap re-build; cached by useMemo.
  const snapshot = useMemo(() => buildRunSnapshot(model), [model]);

  // Filter + cap. Memoised on input change.
  const results = useMemo<SearchItem[]>(() => {
    const q = input.trim().toLowerCase();
    if (!q) return [];
    const hits: SearchItem[] = [];
    for (const item of snapshot.searchIndex) {
      if (item.haystack.includes(q)) {
        hits.push(item);
        if (hits.length >= MAX_RESULTS) break;
      }
    }
    return hits;
  }, [input, snapshot]);

  // Keep cursor in range when results shrink.
  useEffect(() => {
    if (cursor >= results.length) setCursor(Math.max(0, results.length - 1));
  }, [results, cursor]);

  // Mirror cursor into Tier 3 so the graph search-hit overlay (P6)
  // can highlight the cursor's nodeKey separately if it wants. Today
  // it just highlights all hits; cursor is reserved for future use.
  useEffect(() => {
    if (open && results.length > 0) {
      dispatch.setSearchCursor(cursor);
    } else {
      dispatch.setSearchCursor(null);
    }
  }, [open, cursor, results.length, dispatch]);

  // ⌘K / Ctrl+K toggle. Listener owned here (not in
  // WorkbenchRouteContainer) so the palette is self-contained.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        // F4: don't hijack ⌘K while the user is typing into an
        // input/textarea/contenteditable (e.g. editing text in the
        // detail drawer). Exception: when the palette is already open
        // the focused element is the palette's own input, and ⌘K
        // should still toggle it closed.
        if (!open && isEditableTarget(document.activeElement)) return;
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape" && open) {
        // Plan §7: Escape only closes transient UI; never touches
        // selected/focus. Just close the palette.
        e.stopPropagation();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // When opening, seed input with the current committed query (so the
  // palette feels like an editor of URL state, not a separate one) and
  // focus the input.
  useEffect(() => {
    if (open) {
      setInput(state.searchQuery);
      setCursor(0);
      // Defer focus to after the portal mounts.
      queueMicrotask(() => inputRef.current?.focus());
    }
  }, [open, state.searchQuery]);

  const commitHit = useCallback(
    (item: SearchItem) => {
      dispatch.selectBySearchCommit(item.nodeKey, input.trim());
      setOpen(false);
    },
    [dispatch, input],
  );

  const onInputKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, Math.max(0, results.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = results[cursor];
      if (item) commitHit(item);
    }
  };

  if (!open) return null;

  return createPortal(
    <div
      data-testid="search-palette-backdrop"
      onMouseDown={(e) => {
        // Click outside the panel closes (mousedown to beat the
        // browser focus shift). Inner panel stops propagation.
        if (e.target === e.currentTarget) setOpen(false);
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        paddingTop: "12vh",
        zIndex: 1100,
      }}
    >
      <div
        data-testid="search-palette"
        onMouseDown={(e) => e.stopPropagation()}
        style={{
          width: "min(640px, 92vw)",
          maxHeight: "60vh",
          background: "var(--bg-card-2, #1c1c1e)",
          borderRadius: 12,
          boxShadow: "0 24px 60px rgba(0,0,0,0.6)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <input
          ref={inputRef}
          data-testid="search-palette-input"
          type="text"
          value={input}
          placeholder="Search nodes, variables, models, decisions…"
          onChange={(e) => {
            setInput(e.target.value);
            setCursor(0);
          }}
          onKeyDown={onInputKey}
          style={{
            padding: "14px 16px",
            border: 0,
            borderBottom: "1px solid var(--separator)",
            background: "transparent",
            color: "var(--label)",
            font: "inherit",
            fontSize: 15,
            outline: "none",
          }}
        />
        <div
          data-testid="search-palette-results"
          style={{ overflow: "auto", flex: 1 }}
        >
          {results.length === 0 && input.trim() !== "" && (
            <div
              style={{
                padding: 16,
                color: "var(--label-tertiary)",
                fontSize: 13,
              }}
            >
              No matches for "{input}"
            </div>
          )}
          {results.length === 0 && input.trim() === "" && (
            <div
              style={{
                padding: 16,
                color: "var(--label-tertiary)",
                fontSize: 13,
              }}
            >
              Type to search the run. ↑/↓ to navigate, Enter to open.
            </div>
          )}
          {results.map((item, i) => (
            <button
              key={`${item.kind}:${item.nodeKey}:${i}`}
              type="button"
              data-testid={`search-palette-hit-${i}`}
              data-active={i === cursor ? "true" : undefined}
              onMouseEnter={() => setCursor(i)}
              onClick={() => commitHit(item)}
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 10,
                padding: "10px 16px",
                border: 0,
                width: "100%",
                background:
                  i === cursor
                    ? "var(--tint-bg, rgba(10,132,255,0.15))"
                    : "transparent",
                color: "var(--label)",
                cursor: "pointer",
                textAlign: "left",
                font: "inherit",
                fontSize: 13,
              }}
            >
              <span
                style={{
                  minWidth: 64,
                  fontSize: 11,
                  color: "var(--label-tertiary)",
                  fontFamily: "var(--font-mono, monospace)",
                  textTransform: "uppercase",
                }}
              >
                {item.kind}
              </span>
              <span style={{ flex: 1 }}>{item.label}</span>
              {item.detail && (
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--label-tertiary)",
                    fontFamily: "var(--font-mono, monospace)",
                  }}
                >
                  {item.detail}
                </span>
              )}
            </button>
          ))}
        </div>
        <div
          style={{
            borderTop: "1px solid var(--separator)",
            padding: "6px 12px",
            display: "flex",
            justifyContent: "space-between",
            fontSize: 11,
            color: "var(--label-tertiary)",
          }}
        >
          <span>↑↓ navigate · Enter open · Esc close</span>
          <span>⌘K</span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
