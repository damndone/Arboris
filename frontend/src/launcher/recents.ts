// v1.6.8 T10 — recent-projects persistence (localStorage).
// Roots are stored verbatim (unicode paths included); the list is
// most-recent-first, deduped by root, capped at 12. All storage access is
// defensive: corrupt JSON or a throwing localStorage degrades to [].

const KEY = "workbench.recentProjects.v1";

export type RecentProject = { root: string; lastOpened: string };

export function listRecents(): RecentProject[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(parsed)
      ? parsed.filter(
          // T11 R3: validate BOTH fields — a corrupt lastOpened would leak
          // into `上次打开 {lastOpened}` rendering as "undefined"/objects.
          (r) => typeof r?.root === "string" && typeof r?.lastOpened === "string"
        )
      : [];
  } catch {
    return [];
  }
}

export function touchRecent(root: string): void {
  const rest = listRecents().filter((r) => r.root !== root);
  const next = [{ root, lastOpened: new Date().toISOString() }, ...rest].slice(
    0,
    12
  );
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // ignore (private mode / quota)
  }
}

export function removeRecent(root: string): void {
  try {
    localStorage.setItem(
      KEY,
      JSON.stringify(listRecents().filter((r) => r.root !== root))
    );
  } catch {
    // ignore
  }
}
