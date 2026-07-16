// frontend/src/lineage/graph/NodeActionMenu.tsx
//
// V1.5.2 P6 — refactored to consume actionRegistry (plan §11).
//
// Renders the actions registered for the `drawer-header-menu` surface.
// V1.5.0 hardcoded 4 items inline; that's replaced with a registry
// loop so new actions (or disabled placeholders for AI / rerun /
// mark-review) appear automatically.
//
// When mounted outside WorkbenchStateProvider (legacy test harness),
// the menu degrades to V1.5.0's read-only invokes — copyNodeId,
// copyAsJson, copyLineagePath, plus the "View Raw JSON" item that
// is NOT in the registry (it's drawer-internal — owned by the
// drawer, not a node-scoped action). This keeps the existing
// RawJsonModal flow intact.
//
// Popup is rendered via createPortal into document.body and positioned
// against the trigger's getBoundingClientRect() with `position: fixed`.
// Closes on outside-click + Escape + scroll (V1.4.1 MoreMenu pattern
// hardened in V1.5.0 REV-3 F1+F2).

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../api/graphViewTypes";
import { createPipelineDraftFromNode } from "../../api";
import type { PipelineDraftResponse } from "../../api";
import {
  actionsForSurface,
  type ActionContext,
} from "../../workbench/registry/actionRegistry";
import { useWorkbenchOptional } from "../../workbench/WorkbenchStateProvider";
import { useResolvedNodeOperationContext } from "../detail/NodeOperationContextProvider";
import { useDraftActions } from "../drafts/DraftActionsContext";
import { useProjectRootOptional } from "../../workbench/ProjectRootContext";
import { useAgentNavigationOptional } from "../../workbench/agent/agentNavigation";
import {
  createAgentForkProposal,
  getAgentGraphNavigation,
} from "../../workbench/agent/agentApi";
import type { AgentNavigationRef } from "../../workbench/agent/agentTypes";
import "../tokens/lineage.css";

export interface NodeActionMenuProps {
  node: GraphViewNode;
  /** Needed by "Copy lineage path"; pass the same model the workbench owns. */
  model: GraphViewModel;
  /** Caller wires this to open the RawJsonModal. View Raw JSON stays
   *  drawer-local (not a registry action) because it controls a
   *  drawer-owned modal, not a node-scoped imperative. */
  onShowJson: () => void;
  projectRoot?: string;
  /** v1.6.7: forking a draft keeps it IN the main forest — the parent
   *  registers the created draft so it renders on the graph, instead of
   *  navigating to the standalone /pipeline-drafts route. */
  onForkDraft?: (created: PipelineDraftResponse) => void;
}

interface PopupCoords {
  top: number;
  right: number;
}

const GAP_PX = 6;

export function NodeActionMenu({
  node,
  model,
  onShowJson,
  projectRoot,
  onForkDraft,
}: NodeActionMenuProps) {
  const wb = useWorkbenchOptional();
  const resolvedContext = useResolvedNodeOperationContext();
  const draftActions = useDraftActions();
  const contextProjectRoot = useProjectRootOptional();
  const openAgentNavigation = useAgentNavigationOptional();
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<PopupCoords | null>(null);
  // Visible failure state for actions that settle after the menu closes
  // (e.g. fork draft hitting a 409 context_stale). Cleared on re-open.
  const [forkError, setForkError] = useState<string | null>(null);
  const [agentForkBusy, setAgentForkBusy] = useState(false);
  const [agentForkError, setAgentForkError] = useState<string | null>(null);
  const [agentNavigationLinks, setAgentNavigationLinks] = useState<AgentNavigationRef[]>([]);
  const [agentNavigationBusy, setAgentNavigationBusy] = useState(false);
  const [agentNavigationError, setAgentNavigationError] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popupRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    if (!open) {
      setCoords(null);
      return undefined;
    }
    const compute = () => {
      const btn = triggerRef.current;
      if (!btn) return;
      const rect = btn.getBoundingClientRect();
      setCoords({
        top: rect.bottom + GAP_PX,
        right: window.innerWidth - rect.right,
      });
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onDocMouseDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t)) return;
      if (popupRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onScroll = () => setOpen(false);
    document.addEventListener("mousedown", onDocMouseDown, true);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown, true);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  // Build the action context. When the provider is absent the
  // registry's dispatch-dependent actions (openDetail, pinTab,
  // pinUpstream, focusUpstream) gracefully no-op via the stub
  // dispatch below — V1.5.0/1.5.1 test harnesses keep working.
  const ctx: ActionContext = {
    node,
    model,
    selectedKey: wb?.state.selectedKey ?? null,
    focusKey: wb?.state.focusKey ?? null,
    pinned: wb?.state.pinned ?? false,
    dispatch: {
      openDetail: wb?.dispatch.selectByCanvasClick ?? (() => {}),
      pinTab: wb?.dispatch.selectByCanvasClick ?? (() => {}),
      pinUpstream: wb?.dispatch.pinFocus ?? (() => {}),
      // F1: focus-only (see ContextMenu) — don't move selection.
      focusUpstream: wb?.dispatch.setFocusOnly ?? (() => {}),
    },
  };
  const registryActions = actionsForSurface("drawer-header-menu", ctx);
  const context = resolvedContext?.ok ? resolvedContext.context : null;
  const contextFailure =
    resolvedContext && !resolvedContext.ok ? resolvedContext : null;
  const capabilities = resolvedContext?.ok
    ? resolvedContext.context.capabilities
    : null;
  const effectiveProjectRoot =
    projectRoot ??
    contextProjectRoot ??
    new URLSearchParams(window.location.search).get("project_root") ??
    "";
  const navigationRunId =
    context?.operation_target.owner_run_id ?? model.runId;
  const navigationNodeRef =
    context?.operation_target.op_node_id ?? node.nodeKey;
  const navigationForestNodeKey = context?.selection.forest_node_key ?? node.nodeKey;

  useEffect(() => {
    if (!open || !openAgentNavigation || !effectiveProjectRoot) return undefined;
    let cancelled = false;
    setAgentNavigationBusy(true);
    setAgentNavigationError(null);
    getAgentGraphNavigation(effectiveProjectRoot, {
      runId: navigationRunId,
      nodeRef: navigationNodeRef,
      forestNodeKey: navigationForestNodeKey,
    })
      .then((result) => {
        if (cancelled) return;
        const links = result?.projection?.links;
        setAgentNavigationLinks(Array.isArray(links) ? links : []);
      })
      .catch((error) => {
        if (cancelled) return;
        setAgentNavigationLinks([]);
        setAgentNavigationError(
          error instanceof Error ? error.message : "Agent lineage unavailable",
        );
      })
      .finally(() => {
        if (!cancelled) setAgentNavigationBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    effectiveProjectRoot,
    navigationForestNodeKey,
    navigationNodeRef,
    navigationRunId,
    open,
    openAgentNavigation,
  ]);
  const canOpenDraft = Boolean(
    resolvedContext?.ok &&
      effectiveProjectRoot &&
      resolvedContext.context.node_payload.editable_schema?.length,
  );

  async function onForkDraftHere() {
    if (!canOpenDraft || !resolvedContext?.ok) return;
    const context = resolvedContext.context;
    setForkError(null);
    try {
      const result = await createPipelineDraftFromNode(effectiveProjectRoot, {
        source_run_id: context.operation_target.owner_run_id,
        source_model_node_id: context.operation_target.op_node_id,
        source_op_node_id: context.operation_target.op_node_id,
        source_node_hash: context.operation_target.node_hash,
        source_forest_node_key: context.selection.forest_node_key,
        source_context_fingerprint: context.context_fingerprint,
      });
      (onForkDraft ?? draftActions?.onForkDraft)?.(result);
    } catch (e) {
      // Fail closed AND visibly: the menu has already closed by the time the
      // request settles, so a console-only failure looks like a silent no-op.
      setForkError(e instanceof Error ? e.message : String(e));
      console.error("fork draft failed", e);
    }
  }

  const canForkAgent = Boolean(
    openAgentNavigation &&
      effectiveProjectRoot &&
      resolvedContext?.ok &&
      !agentForkBusy,
  );

  async function onForkAgentHere() {
    if (!canForkAgent || !resolvedContext?.ok || !openAgentNavigation) return;
    const context = resolvedContext.context;
    const activeHeadRunId = context.ownership.active_head_run_id ?? navigationRunId;
    setAgentForkBusy(true);
    setAgentForkError(null);
    try {
      const result = await createAgentForkProposal(effectiveProjectRoot, {
        source_run_id: context.operation_target.owner_run_id,
        source_node_ref: context.operation_target.op_node_id,
        active_head_run_id: activeHeadRunId,
      });
      openAgentNavigation(result.navigation);
    } catch (error) {
      setAgentForkError(error instanceof Error ? error.message : String(error));
    } finally {
      setAgentForkBusy(false);
    }
  }

  const closeAfter = (fn: () => void) => () => {
    fn();
    setOpen(false);
  };

  const disabledFromContext = (actionId: string): string | undefined => {
    if (contextFailure) {
      if (actionId === "askAiAboutNode" || actionId === "rerunFromNode") {
        return `Node context resolution failed: ${contextFailure.reason}`;
      }
      return undefined;
    }
    if (!capabilities) return undefined;
    const reason =
      capabilities.disabled_reasons[0] ?? "Node context capability disabled";
    if (actionId === "askAiAboutNode" && !capabilities.can_ask_ai) return reason;
    if (actionId === "rerunFromNode" && !capabilities.can_rerun) return reason;
    return undefined;
  };

  const popup =
    open && coords !== null ? (
      <div
        ref={popupRef}
        role="menu"
        data-testid="node-action-menu-popup"
        style={{
          position: "fixed",
          top: coords.top,
          right: coords.right,
          background: "var(--bg-card-2)",
          borderRadius: 12,
          padding: 6,
          minWidth: 240,
          boxShadow:
            "0 16px 40px rgba(0,0,0,0.75), 0 0 0 1px var(--separator)",
          zIndex: 1000,
        }}
      >
        {/* View Raw JSON is drawer-owned (not registry) — stays at top. */}
        <MenuItem
          label="View Raw JSON"
          shortcut="⌘J"
          onClick={closeAfter(onShowJson)}
          testId="drawer-menu-item-view-raw-json"
        />
        {contextFailure?.reason === "ambiguous_owner_run" && (
          <MenuItem
            label="Choose operation owner"
            disabled="Choose an operation owner before running context-bound actions."
            onClick={() => {}}
            testId="drawer-menu-item-choose-operation-owner"
          />
        )}
        {openAgentNavigation && (
          <>
            <MenuItem
              label={agentNavigationBusy ? "Loading Agent lineage…" : "Agent lineage"}
              disabled={agentNavigationBusy ? "Loading Agent lineage" : agentNavigationError ?? undefined}
              onClick={() => {}}
              testId="drawer-menu-item-agent-lineage"
            />
            {agentNavigationLinks.map((link) => (
              <MenuItem
                key={`agent-navigation:${link.kind}:${link.id}`}
                label={`Open ${link.label}`}
                disabled={!link.available ? link.reason ?? "Unavailable" : undefined}
                onClick={closeAfter(() => {
                  if (link.available) openAgentNavigation(link);
                })}
                testId={`drawer-menu-item-agent-navigation-${link.kind}-${link.id}`}
              />
            ))}
          </>
        )}
        {canForkAgent && (
          <MenuItem
            label="Fork Agent context"
            onClick={closeAfter(onForkAgentHere)}
            testId="drawer-menu-item-fork-agent-context"
          />
        )}
        {canOpenDraft && !node.isDraft && (
          <MenuItem
            label="Fork draft here"
            onClick={closeAfter(onForkDraftHere)}
            testId="drawer-menu-item-fork-draft-here"
          />
        )}
        {registryActions.map((action) => {
          const contextDisabled = disabledFromContext(action.id);
          const registryDisabled = action.disabled?.(ctx);
          const disabled = contextDisabled ?? (registryDisabled || undefined);
          return (
            <MenuItem
              key={action.id}
              label={action.label}
              shortcut={action.shortcut}
              disabled={
                typeof disabled === "string" ? disabled : disabled?.reason
              }
              onClick={closeAfter(() => action.invoke(ctx))}
              testId={`drawer-menu-item-${action.id}`}
            />
          );
        })}
      </div>
    ) : null;

  return (
    <div
      style={{ display: "inline-block" }}
      data-testid="node-action-menu"
    >
      <button
        ref={triggerRef}
        type="button"
        className="ln-btn-secondary"
        onClick={() => {
          setForkError(null);
          setAgentForkError(null);
          setOpen((o) => !o);
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Node actions"
      >
        Actions ⌄
      </button>
      {forkError !== null && (
        <div
          role="alert"
          style={{
            marginTop: 6,
            maxWidth: 320,
            fontSize: 12,
            color: "var(--red)",
            whiteSpace: "normal",
          }}
        >
          Fork draft failed: {forkError}
        </div>
      )}
      {agentForkError !== null && (
        <div
          role="alert"
          style={{
            marginTop: 6,
            maxWidth: 320,
            fontSize: 12,
            color: "var(--red)",
            whiteSpace: "normal",
          }}
        >
          Agent fork failed: {agentForkError}
        </div>
      )}
      {popup !== null && createPortal(popup, document.body)}
    </div>
  );
}

function MenuItem({
  label,
  shortcut,
  onClick,
  disabled,
  testId,
}: {
  label: string;
  shortcut?: string;
  onClick: () => void;
  disabled?: string;
  testId: string;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      data-testid={testId}
      data-disabled={disabled ? "true" : undefined}
      title={disabled}
      disabled={!!disabled}
      onClick={() => {
        if (disabled) return;
        onClick();
      }}
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "9px 12px",
        borderRadius: 8,
        background: "transparent",
        border: 0,
        color: disabled ? "var(--label-tertiary)" : "var(--label)",
        cursor: disabled ? "not-allowed" : "pointer",
        textAlign: "left",
        font: "inherit",
        fontSize: 13.5,
        width: "100%",
        opacity: disabled ? 0.55 : 1,
      }}
    >
      <span>{label}</span>
      {shortcut && (
        <span
          style={{
            color: "var(--label-tertiary)",
            fontSize: 12,
            fontFamily: "var(--font-mono)",
          }}
        >
          {shortcut}
        </span>
      )}
    </button>
  );
}
