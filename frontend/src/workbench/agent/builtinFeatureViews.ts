let registered = false;

/**
 * Idempotent home-shell bootstrap for built-in feature views.
 *
 * C1 intentionally registers nothing: future feature lanes add their own
 * packet renderer here through a mechanical integration declaration.
 */
export function registerBuiltinFeatureViews(): void {
  if (registered) return;

  // Future declarations call registerFeatureView here. C1 intentionally keeps
  // this registry empty and has no user-visible effect.
  registered = true;
}
