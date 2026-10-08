// Run list formatting shared by the run history rail and the workspace Runs tab.

export function formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const delta = Date.now() - t;
  const s = Math.round(delta / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

export function shortRunId(id: string): string {
  // Workbench run ids look like: 20260525_210044_142101_055d5cbd
  // The last 8-char hex segment is the unique tail; render that.
  const tail = id.split("_").pop() ?? id;
  return tail.slice(0, 8);
}

export function statusClass(status: string | null): string {
  switch (status) {
    case "completed":
    case "ok":
      return "run-rail__pill run-rail__pill--ok";
    case "failed":
    case "error":
      return "run-rail__pill run-rail__pill--red";
    case "blocked":
      return "run-rail__pill run-rail__pill--warn";
    case "running":
      return "run-rail__pill run-rail__pill--info";
    default:
      return "run-rail__pill run-rail__pill--neutral";
  }
}
