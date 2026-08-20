# Survey remediation-3 Implementation Plan

> For agentic workers: use executing-plans or subagent-driven-development. Steps use checkbox syntax for tracking.

Goal: Replace nullable/generic Agent projection behavior with closed typed
schemas and close the remediation-2 handoff digest gap on one synchronized
formal line.

Architecture: Keep server-owned artifact verification and existing Survey
projection validators as authorities. Add schema-owned projection helpers at
the Agent seam, attach fields only after source-presence and validator checks,
and use a declared allowlist for committed artifact/Notebook results. Freeze
the handoff before the closing formal event so its digest cannot drift.

Tech Stack: Python 3.14, pytest, Agent context projection, committed Notebook
JSON receipts, formal scripts/devline_control.py.

---

### Task 1: Freeze remediation-3 scope and review evidence

Files:
- Create docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-3-objective.md
- Create the formal line through scripts/devline_control.py start
- Create docs/superpowers/plans/2026-08-20-survey-remediation-3.md

- [x] Verify clean baseline 9328c3f3c1e96845042be735a3ecd789d0ea1496 and absent line.
- [x] Start only v1-8-9-p1-survey-remediation-3 with exact scope and known gates.
- [x] Read and verify Context Pack, global rules, rem2 retrospective/handoff, and supplied review.
- [x] Append a CLI REVIEW/GAP for old rem2 handoff digest ee3cf0551255e0d15567adf5ed210d238d757ec13826e2cfc8834614e02f8760 versus the post-tip handoff digest, without editing old events.

### Task 2: Add RED pure projection probes

Files:
- Modify tests/test_agent_context_tools.py

- [x] Add pure probes for sparse _bounded_persisted_model_facts,
  _bounded_regression_table, and _public_requested_model_coefficients; assert
  absent fields are omitted instead of None or empty placeholders.
- [x] Add invalid-declared-field probes; assert typed unavailable status/reason
  or omission and no raw invalid scalar crosses the boundary.
- [x] Add a direct artifact projection probe with declared statistical fields,
  Survey metadata, coefficients, raw_rows, and unknown_extra; assert only the
  explicit typed allowlist survives.
- [x] Run only new probes and record the expected current failures before
  production changes.

### Task 3: Add RED real Agent/Notebook workflow probes

Files:
- Modify tests/test_agent_reads_v187_results.py
- Modify tests/test_agent_context_tools.py

- [x] Extend a real server-owned model workflow fixture with sparse metadata and
  assert Agent result/diagnostic projections contain no synthetic nullable fields.
- [x] Extend the committed Notebook receipt fixture with typed provenance/design,
  replicate/coefficient fields, unknown extras, and raw rows; assert the
  packet contains only allowlisted typed fields.
- [x] Add invalid declared artifact and invalid Notebook packet probes; assert
  typed unavailable status/reason or omission without passthrough.
- [x] Run the new workflow probes and record RED evidence through the CLI.

### Task 4: Implement the minimum closed-schema repair

Files:
- Modify backend/workbench/agent/context_tools.py

- [x] Add a source-presence/typed-value helper used by low-level projections.
- [x] Remove nullable model/table fields and empty nested placeholders from the
  three named projection functions; retain bounded provenance/design/replicate
  metadata.
- [x] Replace generic artifact recursion at _public_operation_artifact_result
  with explicit per-artifact allowlists, including the existing P7 inference
  contract and typed Survey result metadata.
- [x] Preserve raw-row omission and budget limits while rejecting unknown
  declared extras; keep ordinary Agent/Report/Survey consumers unchanged.

### Task 5: Green and regression verification

- [x] Rerun pure projection and real Agent/Notebook probes until green.
- [x] Run Agent context/reads, Report view and selected Report projection tests;
  record foreign/admitted failures without expanding scope.
- [x] Run full Survey regression covering GLM families, design engine/composition,
  limits, Report visibility, weights, replicate weights, falsey declarations,
  exposure, and FPC.
- [x] Run compileall and git diff --check; append GREEN/GAP/GATE via CLI.

### Task 6: Synchronized exact-tip closeout

Files:
- Create docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-3-handoff.md
- Modify only through CLI: .agent/devlines/v1-8-9-p1-survey-remediation-3/*

- [ ] Commit only product/tests and capture exact product tip.
- [ ] Freeze final handoff, compute exact digest, append final CLI state event
  referencing that digest.
- [ ] Run formal verify and retrospective, then commit handoff and formal
  records in the same final commit; make no post-closeout doc-only commit.
- [ ] Recompute current state-chain mismatch, confirm owned unresolved=0,
  confirm old rem2 events unchanged, and report exact tip/manifest/commands.
