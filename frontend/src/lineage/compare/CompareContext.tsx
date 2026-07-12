// v1.6.11 slice B-2 — arbitrary two-node comparison state.
//
// One provider owns the pick flow: a drawer section starts a pick from the
// anchor node, the canvas routes its next node click here instead of changing
// the selection, and the resulting pair renders through CompareDiffView from
// either node's drawer. Pure state — context resolution and diffing stay in
// api/nodeOperationContext + api/compareNodes.
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

export interface ComparePair {
  anchorKey: string;
  targetKey: string;
}

export interface CompareState {
  /** Set while waiting for the user to click the second node on the canvas. */
  pickingFromKey: string | null;
  /** Completed pair; drives the diff view in the drawer. */
  pair: ComparePair | null;
  startPick: (anchorKey: string) => void;
  cancelPick: () => void;
  /** Route a canvas node click. Returns true when the click was consumed
   *  (a pick was pending), false when normal selection should proceed. */
  handleCanvasSelect: (nodeKey: string) => boolean;
  swap: () => void;
  clear: () => void;
}

const Context = createContext<CompareState | null>(null);

export function CompareProvider({ children }: { children: ReactNode }) {
  const [pickingFromKey, setPickingFromKey] = useState<string | null>(null);
  const [pair, setPair] = useState<ComparePair | null>(null);

  const startPick = useCallback((anchorKey: string) => {
    setPickingFromKey(anchorKey);
    setPair(null);
  }, []);

  const cancelPick = useCallback(() => setPickingFromKey(null), []);

  const handleCanvasSelect = useCallback(
    (nodeKey: string): boolean => {
      if (pickingFromKey === null) return false;
      if (nodeKey === pickingFromKey) return true; // ignore self-click, keep picking
      setPair({ anchorKey: pickingFromKey, targetKey: nodeKey });
      setPickingFromKey(null);
      return true;
    },
    [pickingFromKey],
  );

  const swap = useCallback(() => {
    setPair((current) =>
      current === null
        ? null
        : { anchorKey: current.targetKey, targetKey: current.anchorKey },
    );
  }, []);

  const clear = useCallback(() => {
    setPair(null);
    setPickingFromKey(null);
  }, []);

  const value = useMemo<CompareState>(
    () => ({ pickingFromKey, pair, startPick, cancelPick, handleCanvasSelect, swap, clear }),
    [pickingFromKey, pair, startPick, cancelPick, handleCanvasSelect, swap, clear],
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** Null outside the provider (bare-mount tests, legacy consumers) — callers
 *  treat that as "compare unavailable" and render nothing. */
export function useCompareOptional(): CompareState | null {
  return useContext(Context);
}
