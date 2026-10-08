// v1.9.0 — the new workspace runs behind a switch until it is accepted
// (design spec §8.8). Settings › Appearance flips it; `?workspace=new` or
// `?workspace=classic` on any project URL flips it too and is remembered, so a
// test or a screenshot can pin a shell without touching settings.

import { useSyncExternalStore } from "react";

export type WorkspaceMode = "new" | "classic";

const KEY = "workbench:workspace";
const EVENT = "workbench:workspace-change";
const DEFAULT_MODE: WorkspaceMode = "classic";

function isMode(value: string | null): value is WorkspaceMode {
  return value === "new" || value === "classic";
}

export function resolveWorkspaceMode(search: string, stored: string | null): WorkspaceMode {
  const fromUrl = new URLSearchParams(search).get("workspace");
  if (isMode(fromUrl)) return fromUrl;
  return isMode(stored) ? stored : DEFAULT_MODE;
}

function readStored(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setWorkspaceMode(mode: WorkspaceMode): void {
  try {
    localStorage.setItem(KEY, mode);
  } catch {
    // Storage may be unavailable; the event still switches this session.
  }
  window.dispatchEvent(new Event(EVENT));
}

function currentMode(): WorkspaceMode {
  const search = typeof window === "undefined" ? "" : window.location.search;
  const mode = resolveWorkspaceMode(search, readStored());
  if (isMode(new URLSearchParams(search).get("workspace")) && readStored() !== mode) {
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      // ignore
    }
  }
  return mode;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  window.addEventListener("popstate", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
    window.removeEventListener("popstate", onChange);
  };
}

export function useWorkspaceMode(): WorkspaceMode {
  return useSyncExternalStore(subscribe, currentMode, () => DEFAULT_MODE);
}
