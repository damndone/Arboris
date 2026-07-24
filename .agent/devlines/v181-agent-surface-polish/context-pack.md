# Frozen Context Pack

Line: `v181-agent-surface-polish`
Baseline SHA: `e0f2094ee62691cbd819131cd5a0c174bd0a1c75`

## Objective
# v1.8.1 Agent Surface Polish and Global Scope Design

## Objective

Improve the Workbench Agent surface to match the supplied Codex composer
reference while preserving the existing typed proposal and fail-closed
execution boundaries.

## Scope

1. Restyle the graph Agent composer as a translucent rounded capsule with a
   textarea-first layout, compact action controls, model selector, context
   indicator, capability affordance, and circular send control.
2. Make context and capability details hover/focus driven: entering the
   control opens the detail surface; leaving both trigger and surface closes
   it; keyboard focus remains supported.
3. Render Agent Markdown tables and lightweight inline/block math without
   exposing Markdown markers. The renderer must remain dependency-free and
   route plain text through the existing cite-chip seam.
4. Clicking graph background clears node selection and switches the Agent to
   a project-scoped Main Agent. The Main Agent receives a bounded project
   overview containing family/run/head/chain summaries, remains advisory, and
   never gains chain mutation tools. Selecting a node continues to use the
   chain-scoped Agent.

## Non-goals and invariants

- No second execution state is introduced; Graph/RunFamily remains the source
  of truth.
- No provider capacity is guessed. If context capacity is not declared by the
  configured provider, the UI says so explicitly.
- The Main Agent is read-only and may not confirm, execute, or invent typed
  operations.
- Project context is bounded to summaries and identifiers; raw datasets and
  full artifacts are not sent as global context.

## Acceptance

- Composer visual regression checks cover the capsule structure, compact
  controls, translucent surface, focus/hover behavior, and reduced-motion
  safe transitions.
- Markdown tests cover GFM-style tables, alignment, inline/block math, Greek
  commands, fenced code, and cite-chip text leaves.
- Graph tests prove pane click clears selection; Agent surface tests prove
  Main role/session creation and bounded project overview; chain selection
  remains chain-scoped.
- Targeted tests, full frontend tests, TypeScript, diff check, and in-app
  browser acceptance all pass.

## Boundary
- Affected paths: `docs/releases/v1.8.1-release-notes.md`
- Allowed paths: `docs/releases/v1.8.1-release-notes.md`
- Protected paths: none
- Dependencies: none
- Tests: `cd frontend && npm test -- --run src/workbench/agent src/report/markdown.test.tsx src/lineage/graph/GraphCanvas.test.tsx`, `cd frontend && npm run typecheck`
- Known gates: `scripts/gate.sh`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
