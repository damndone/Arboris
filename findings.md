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

# v1.8.9 Notebook/Graph Agent UI regression findings

## Initial reproduction

- The live Notebook surface renders only a heading, one explanatory sentence,
  a disabled textarea, and one compile button; it currently reports `Not Found`.
- The Graph bottom panel stays on Logs when the Agent tab is invoked through the
  live page, so the current Agent shell is not reliably reachable from the UI.

## Reference comparison

- v1.8.8 used the full Notebook workspace and the shared Agent shell with
  transcript turns, activity/progress, scope, capability prompts, model/context
  controls, proposals, revisions, navigation, confirmation, and audit affordances.
- v1.8.9 replaced those presentation shells with small inline-styled
  `NotebookCutoverView` and `AgentCutoverPanel` components. The cutover itself is
  not the visual regression; coupling the new compiler to replacement UI is.
- Restoration must preserve `cutoverApi` as the only NL compile/confirm/execute
  transport. Reintroducing v1.8.8 Notebook execution API calls is out of scope.
