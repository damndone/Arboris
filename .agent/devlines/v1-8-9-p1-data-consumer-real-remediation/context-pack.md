# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer-real-remediation`
Baseline SHA: `dff7c6d9f0dcdc8f243a83a6f0f048e90ba3c4bb`

## Objective
# Workbench v1.8.9 P1 Data Consumer real remediation objective

修复独立规格复审确认的真实 P1 缺口，不以 formal closeout 替代产品
验证。本 line 从当前 Data Consumer worktree 精确 HEAD
`dff7c6d9f0dcdc8f243a83a6f0f048e90ba3c4bb` 开始；产品实现历史基线
`73a09151aa3ab4eb1cdb2e3c94fca2df93df92b3` 只作为上下文引用。旧的
`v1-8-9-p1-data-consumer` 与 `v1-8-9-p1-data-consumer-formal-closeout`
formal lines 保持不变。

## Required remediation

- 给 CSV/XLSX/Parquet 建立真实 writer/read-back interchange contract：能力声明
  必须与可用 optional dependency 一致；缺失 `pyarrow`/`fastparquet` 时返回稳定的
  typed `optional_dependency`/`unavailable`，不能假装支持；`.sav`/`.zsav`/`.dta`
  在缺失 `pyreadstat` 时继续 typed unavailable；metadata loss 与 schema/dtype
  边界必须可解释。
- 将已有 `DataOperationsSection` 接入 canonical
  `frontend/src/workbench/registry/sectionRegistry.ts`。用户路径必须从服务端
  manifest 的 typed descriptor 生成 preview，并且 confirm 只能携带服务端 preview
  fingerprint/descriptor ref；不得在前端重算结果或绕过服务端 confirmation。
- 维持 package-local 边界。Agent/Notebook/Report central integration、provider、
  host、browser、full gate、merge/release 均不在本 line 内，不得被测试或文档写成已完成。

## Boundary

- formal files are generated or updated only through `scripts/devline_control.py`;
- product scope is limited to interchange capability/writer/read-back and the
  canonical Data Operations UI adapter plus their focused tests;
- no dependency installation and no changes to central Agent/Notebook/Report
  integration, provider catalog, host gate, release scripts, or old formal lines;
- all optional dependency outcomes and unverified gates remain explicit.

## Verification

- focused backend interchange/ingestion tests;
- focused frontend Data Operations/registry tests;
- `PYTHONPATH=backend .venv/bin/python -m compileall -q backend`;
- `git diff --check`;
- formal `verify` and regenerated `RETROSPECTIVE.md` through the CLI.

## Known gates

`agent-central-integration-not-verified`, `notebook-central-integration-not-verified`,
`report-central-integration-not-verified`, `browser-acceptance-not-verified`,
`provider-full-gate-not-verified`, `host-full-gate-not-verified`,
`full-gate-not-verified`, `merge-not-authorized`, `release-not-verified`.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-data-consumer-remediation-objective.md`, `docs/superpowers/specs/2026-08-19-v1.8.9-p1-data-consumer-remediation-design.md`, `docs/superpowers/plans/2026-08-19-v1.8.9-p1-data-consumer-remediation-plan.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-data-consumer-remediation-handoff.md`, `backend/workbench/data_interchange.py`, `backend/workbench/ingestion.py`, `tests/test_v189_data_interchange.py`, `tests/test_ingestion_metadata.py`, `frontend/src/lineage/dataOperations.ts`, `frontend/src/lineage/dataOperations.test.ts`, `frontend/src/workbench/registry/sectionRegistry.ts`, `frontend/src/workbench/registry/sectionRegistry.v189.test.ts`, `frontend/src/lineage/detail/sections/sectionRegistry.test.ts`, `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`
- Allowed paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-data-consumer-remediation-objective.md`, `docs/superpowers/specs/2026-08-19-v1.8.9-p1-data-consumer-remediation-design.md`, `docs/superpowers/plans/2026-08-19-v1.8.9-p1-data-consumer-remediation-plan.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-data-consumer-remediation-handoff.md`, `backend/workbench/data_interchange.py`, `backend/workbench/ingestion.py`, `tests/test_v189_data_interchange.py`, `tests/test_ingestion_metadata.py`, `frontend/src/lineage/dataOperations.ts`, `frontend/src/lineage/dataOperations.test.ts`, `frontend/src/workbench/registry/sectionRegistry.ts`, `frontend/src/workbench/registry/sectionRegistry.v189.test.ts`, `frontend/src/lineage/detail/sections/sectionRegistry.test.ts`, `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`
- Protected paths: `.agent/devlines/v1-8-9-p1-data-consumer`, `.agent/devlines/v1-8-9-p1-data-consumer-formal-closeout`, `backend/workbench/agent`, `backend/workbench/providers`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `frontend/src/agent`, `frontend/src/notebook`, `frontend/src/report`, `scripts/gate.sh`
- Dependencies: `v1-8-9-p1-data-consumer`, `v1-8-9-p1-data-consumer-formal-closeout`
- Tests: `focused backend interchange/ingestion pytest`, `focused frontend Data Operations and canonical registry vitest`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend`, `git diff --check`
- Known gates: `agent-central-integration-not-verified`, `notebook-central-integration-not-verified`, `report-central-integration-not-verified`, `browser-acceptance-not-verified`, `provider-full-gate-not-verified`, `host-full-gate-not-verified`, `full-gate-not-verified`, `merge-not-authorized`, `release-not-verified`

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
