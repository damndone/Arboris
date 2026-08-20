# remediation-5 findings

## Root cause

- `build_report_view_model` treated any caller `Mapping` as a typed Report
  projection and rendered legacy presentation before C0 owner admission.
- `render_legacy_html_report` accepted any Mapping and called
  `write_bytes_durable`/`register_artifact` directly.
- `render_html_report` validated writer type and path but omitted its final
  owner/projection revalidation before template and filesystem IO.

## TDD evidence

- Exact-baseline RED: a forged Mapping returned `available` and reached the
  legacy writer seam; the valid-owner call exposed the missing owner-gated API.
  The default host-dependent probe separately hit Unix authority socket
  `PermissionError` before assertions.
- Controlled GREEN: forged Mapping/render and forged `object.__new__` HTML
  writer probes return typed rejection with zero writer/register calls; the
  real owner-issued projection builds and renders successfully.
- Controlled backend Evidence/Report/event focused suite: `114 passed, 1
  warning`; strict event pair: `17 passed`.

## Boundaries

Typed frontend/raw classification `NON-CITABLE`, strict provenance and
outer/nested tamper handling, and controlled HTTP behavior remain preserved.
Browser/provider/central/live-host/full-gate/release remain `NOT VERIFIED`.
