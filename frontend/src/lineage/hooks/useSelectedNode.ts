// frontend/src/lineage/hooks/useSelectedNode.ts
//
// V1.5.0 selected-node URL state (Step 5, T5.2).
//
// Wraps react-router's `useSearchParams` so that the rest of the lineage UI
// reads/writes the selected node through one symbolic API instead of
// manually constructing `URLSearchParams` everywhere.
//
// Contract (plan §8 T5.2):
//   - `selectedKey: string | null` — the current `?node=` value, or null
//   - `select(key)`      writes `?node=key` (replace: false → push entry)
//   - `select(null)`     removes the `?node=` param entirely
//   - All mutations are immutable (a fresh URLSearchParams is built each time)

import { useCallback, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import type { GraphViewNode } from "../api/graphViewTypes";

export interface UseSelectedNodeResult {
  selectedKey: string | null;
  select: (key: string | null) => void;
}

export function useSelectedNode(
  nodes?: GraphViewNode[] | null,
  autoSelectScope?: string | null,
): UseSelectedNodeResult {
  const [params, setParams] = useSearchParams();
  const didAutoSelectRef = useRef(false);
  const autoSelectScopeRef = useRef<string | null>(autoSelectScope ?? null);
  // URLSearchParams.get("node") on `?node=` returns "" (not null). Treat
  // empty string as "no selection" so a stale URL like `?node=` doesn't
  // wedge the UI into rendering an empty drawer for a non-existent node.
  // [REV-3 #2 — Step 5 adversarial review]
  const raw = params.get("node");
  const selectedKey = raw === "" ? null : raw;

  useEffect(() => {
    const scope = autoSelectScope ?? null;
    if (autoSelectScopeRef.current === scope) return;
    autoSelectScopeRef.current = scope;
    didAutoSelectRef.current = false;
  }, [autoSelectScope]);

  useEffect(() => {
    if (didAutoSelectRef.current) return;
    if (!nodes || nodes.length === 0) return;
    didAutoSelectRef.current = true;

    const currentRaw = params.get("node");
    const currentSelectedKey = currentRaw === "" ? null : currentRaw;
    if (currentSelectedKey !== null) return;

    const pick =
      nodes.find((node) => node.trust === "review") ??
      nodes.find((node) => node.trust === "caution");
    if (!pick) return;

    const next = new URLSearchParams(params);
    next.set("node", pick.nodeKey);
    setParams(next, { replace: true });
  }, [nodes, params, setParams]);

  const select = useCallback(
    (key: string | null) => {
      const next = new URLSearchParams(params);
      if (key === null) next.delete("node");
      else next.set("node", key);
      setParams(next, { replace: false });
    },
    [params, setParams],
  );

  return { selectedKey, select };
}
