// v1.6.8 F5 — project_root ↔ URL path-segment slug.
//
// Why not encodeURIComponent: paths contain `/` → `%2F` inside a path
// segment, which vite/react-router normalize inconsistently. base64url over
// UTF-8 bytes yields only [A-Za-z0-9_-], safe in a path segment.

export function rootToSlug(projectRoot: string): string {
  const bytes = new TextEncoder().encode(projectRoot);
  let bin = "";
  bytes.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Decode a slug back to the project root.
 *  Throws (DOMException from atob) on malformed input — callers should catch
 *  and route to the launcher rather than render a garbage path. */
export function slugToRoot(slug: string): string {
  const b64 = slug.replace(/-/g, "+").replace(/_/g, "/");
  const pad = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  const bin = atob(pad);
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}
