# Frozen Context Pack

Line: `v1-8-9-p0-legacy-resume-remediation-9`
Baseline SHA: `621ee442084c4f34b9d42413a7140a39506df988`

## Objective
# Workbench v1.8.9 P0 Legacy/Resume Remediation-9 Objective

## Objective

Close the independent P2 handoff/evidence gap at exact baseline
`621ee442084c4f34b9d42413a7140a39506df988`: remediation-8's handoff records
only its formal parent closeout tip/tree (`e6c21cb2` / `ab1efd9b2`), while the
current final implementation/docs tip is `621ee442` / `07856f3`. Add an
explicit real authority copy/pickle regression to the focused evidence; the
existing product fail-closed behavior is already present and product code is
out of scope.

## Required outcomes

- Add a real regression that exercises the module-owned live proposal authority
  through both `copy` and `pickle` paths and proves the authority cannot be
  cloned or serialized across its trust boundary.
- Keep the regression side-effect aware: proposal bytes, repository branch
  entries, and agent event entries must remain unchanged when the authority
  boundary rejects the operation.
- Preserve all remediation-8 security behavior and route-owned positive paths;
  do not modify product code.
- Record the accurate implementation/docs baseline tip and final exact
  HEAD/tree digests in this line's handoff, including the corrected remediation-8
  formal closeout tip/tree and the later docs tip/tree.
- Preserve remediation-8's known GAP classifications and every
  `NOT VERIFIED` boundary; do not reopen or edit predecessor records.

## Boundary

Affected paths:

- `tests/test_v189_legacy_resume_remediation8.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-9-objective.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-9-handoff.md`

Protected paths include all predecessor `.agent/devlines/*` records,
remediation-8 objective/plan/handoff files, `backend/workbench/**`, the root
checkout, other worktrees, and unrelated source/tests/docs. Product code is
explicitly out of scope.

Baseline: `621ee442084c4f34b9d42413a7140a39506df988`.

Dependencies: `v1-8-9-p0-legacy-resume-remediation-8`, its formal closeout
`e6c21cb2a8f42cf7d8f5d50b0f0c49f24b8cb9e2` /
`ab1efd9b8b34032069c77a6eef920cf52030c005`, current docs tip
`621ee442084c4f34b9d42413a7140a39506df988` /
`07856f3002e2381dd4a4f8d39e0f5e26b814ae4e`, and the legacy/resume authority,
route, compiler, workflow-truth, and contract-lock evidence.

## Tests and gates

- TDD/coverage regression: `tests/test_v189_legacy_resume_remediation8.py`.
- Focused remediation-8 adversarial suite plus remediation-7, remediation-6,
  remediation-5, remediation-2, route authority, Agent Notebook compiler,
  workflow-resume, and relevant workflow seam positive-path suites.
- `PYTHONPYCACHEPREFIX=/private/tmp/workbench-v189-remediation9-pycache PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`.
- `git diff --check` and frozen-scope/path verification.
- Formal line verify, final GATE, retrospective, and exact HEAD/tree digest
  handoff through `scripts/devline_control.py`.

Known GAPs remain open and must be carried forward: the historical direct
service suite's stale 19 fixtures and the inherited workflow seam fixtures
that omit `active_head_run_id`. Browser acceptance, external provider/runtime,
host restart, true multi-worker deployment, full repository gate, integration,
release, merge, tag, and push remain `NOT VERIFIED` unless directly run and
evidenced here. No dependency installation, reset, checkout, destructive
cleanup, root write, other-worktree write, product-code edit, push, merge, tag,
or release operation is authorized.

## Boundary
- Affected paths: `tests/test_v189_legacy_resume_remediation8.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-9-objective.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-9-handoff.md`
- Allowed paths: `tests/test_v189_legacy_resume_remediation8.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-9-objective.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-9-handoff.md`
- Protected paths: `predecessor-formal-lines`, `remediation8-records`, `backend/workbench`, `root-checkout`, `other-worktrees`
- Dependencies: `v1-8-9-p0-legacy-resume-remediation-8`, `e6c21cb2a8f42cf7d8f5d50b0f0c49f24b8cb9e2`, `ab1efd9b8b34032069c77a6eef920cf52030c005`, `621ee442084c4f34b9d42413a7140a39506df988`, `07856f3002e2381dd4a4f8d39e0f5e26b814ae4e`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation8.py -q --disable-warnings --maxfail=1`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation7.py tests/test_v189_legacy_resume_remediation6.py tests/test_v189_legacy_resume_remediation5.py tests/test_v189_legacy_resume_remediation2.py tests/test_v189_legacy_route_authority.py tests/test_v189_agent_notebook_cutover.py tests/test_workflow_resume.py -q --disable-warnings --maxfail=1`, `PYTHONPYCACHEPREFIX=/private/tmp/workbench-v189-remediation9-pycache PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `git diff --check`
- Known gates: `browser-acceptance-not-verified`, `external-provider-runtime-not-verified`, `host-restart-not-verified`, `true-multi-worker-not-verified`, `full-repository-gate-not-verified`, `integration-release-merge-tag-push-not-verified`, `historical-direct-service-19-failures-gap`, `inherited-workflow-seam-scope-gap`

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
