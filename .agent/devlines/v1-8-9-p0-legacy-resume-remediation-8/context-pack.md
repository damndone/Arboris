# Frozen Context Pack

Line: `v1-8-9-p0-legacy-resume-remediation-8`
Baseline SHA: `69b5b0079f0532ea7be7b6d8bd2a352dfa9f4294`

## Objective
# Workbench v1.8.9 P0 Legacy/Resume Remediation-8 Objective

## Objective

Close the remaining P0 proposal authority bypass at exact baseline
`69b5b0079f0532ea7be7b6d8bd2a352dfa9f4294`: a caller can directly construct
`_ProposalStoreServerAuthorityV1`, call `issue()`, and pass the self-consistent
issuer/service entry to `ProposalStore._issue_server_capability`, reaching real
proposal side effects.

## Required outcomes

- The module owns exactly one live server authority object. Direct constructor
  calls fail closed permanently; `object.__new__` instances and field-forged,
  copied, or serialized authority/entry objects cannot issue or admit anything.
- `authority.issue()` succeeds only on the module-initialized singleton and
  only creates entries admitted by that authority's registry and secret.
- `ProposalStore._issue_server_capability` and `_issue` validate unique
  authority object identity plus registry, secret, owner identity, issuer and
  entry nonce, PID, generation, and exact root identity before any proposal,
  repository, or event side effect. `entry_nonce` equality is explicit.
- Add real adversarial RED/GREEN regressions for direct construction,
  `object.__new__` forgery, caller `issue()`, forged entry/issuer bindings, and
  zero side effects before and after the attempted path.
- Preserve route-owned issuance and compiler/orchestrator positive proposal
  paths.
- Keep predecessor remediation-7 `.agent/devlines` records immutable. The new
  handoff records its predecessor's corrected final exact HEAD/tree digest:
  `97c82f5e59e8e3cd104170152f7b53da8eda416a` /
  `d15da557e1a704e4333fc685a9bfa30beaba1fb8`.

## Boundary

Affected paths:

- `backend/workbench/agent/proposals.py`
- `tests/test_v189_legacy_resume_remediation8.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8-objective.md`
- `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8-handoff.md`

Protected paths include all predecessor `.agent/devlines/*` records, the root
checkout, other worktrees, unrelated route/compiler/orchestrator source,
Report/data/classification/survey/provider paths, and predecessor source/tests.

Baseline: `69b5b0079f0532ea7be7b6d8bd2a352dfa9f4294`.

Dependencies: `v1-8-9-p0-legacy-resume-remediation-7`, its corrected handoff
digest, legacy/resume authority hardening, route authority, Agent compiler
cutover, workflow truth, and contract-lock evidence.

## Tests and gates

- TDD RED then GREEN: `tests/test_v189_legacy_resume_remediation8.py`.
- Focused remediation-8 adversarial suite plus remediation-7, remediation-6,
  remediation-5, remediation-2, route authority, Agent Notebook compiler,
  workflow-resume, and relevant workflow seam positive-path suites.
- `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`.
- `git diff --check` and scoped diff/path verification.
- Formal line verify, final GATE, retrospective, and exact HEAD/tree digest
  handoff.

Known external gates remain `NOT VERIFIED` unless run here: browser acceptance,
external provider runtime, host restart, true multi-worker deployment, full
repository gate, integration, release, merge, tag, and push. No dependency
installation, destructive cleanup, root write, other-worktree write, push,
merge, tag, or release operation is authorized.

## Boundary
- Affected paths: `backend/workbench/agent/proposals.py`, `tests/test_v189_legacy_resume_remediation8.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8-handoff.md`
- Allowed paths: `backend/workbench/agent/proposals.py`, `tests/test_v189_legacy_resume_remediation8.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8-handoff.md`
- Protected paths: `root-checkout`, `other-worktrees`, `predecessor-formal-lines`, `Report`, `data`, `classification`, `survey`, `providers`
- Dependencies: `v1-8-9-p0-legacy-resume-remediation-7`, `v1-8-9-p0-legacy-resume-remediation-6`, `v1-8-9-p0-legacy-resume-authority-rehardening`, `v1-8-9-p0-legacy-resume-hardening`, `v1-8-9-p0-agent-compiler-core`, `v1-8-9-contract-lock`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation8.py -q --disable-warnings --maxfail=1`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation7.py tests/test_v189_legacy_resume_remediation6.py tests/test_v189_legacy_resume_remediation5.py tests/test_v189_legacy_resume_remediation2.py tests/test_v189_legacy_route_authority.py tests/test_v189_agent_notebook_cutover.py tests/test_workflow_resume.py -q --disable-warnings --maxfail=1`, `PYTHONPYCACHEPREFIX=/private/tmp/workbench-v189-remediation8-pycache PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `git diff --check`
- Known gates: `browser_acceptance_NOT_VERIFIED`, `external_provider_runtime_NOT_VERIFIED`, `host_restart_NOT_VERIFIED`, `true_multi_worker_NOT_VERIFIED`, `full_repository_gate_NOT_VERIFIED`, `integration_release_merge_tag_push_NOT_VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
