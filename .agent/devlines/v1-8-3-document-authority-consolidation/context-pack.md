# Frozen Context Pack

Line: `v1-8-3-document-authority-consolidation`
Baseline SHA: `90eec270dc47590705dca48c71f55f1e55843301`

## Objective
# v1.8.3 文档权威收敛

## 目标

把 v1.8.3 规格与计划恢复为仓库既有的扁平目录惯例，消除重复 scope、已完成使命的 objective、双重权威和失效引用，同时完整保留已批准的运行时、Capability Factory、领域记忆与执行边界。

## 交付

- 三份扁平规格：custom capability runtime、Capability Factory、domain memory；
- 三份扁平计划：execution control、Capability lane、Memory lane；
- 零份保留 objective，零份重定向壳文件；
- execution-control plan 是唯一开工入口；
- 全部实时文档引用指向新权威路径；
- 已冻结 `.agent/devlines` 历史证据保持不变。

## 不做

- 不修改产品代码、测试代码、正式 FMS 历史记录或发布状态；
- 不删除有独立语义职责的运行时、Capability Factory 或领域记忆契约；
- 不新增设计功能、实现范围、review 文档或计划分片；
- 不 push、PR、merge、tag 或 release。

## 完成标准

- `docs/superpowers/specs` 和 `docs/superpowers/plans` 不再存在唯一的 v1.8.3 子目录例外；
- v1.8.3 只保留三份规格与三份计划，文件名均含日期和版本；
- objectives、重复 README 和旧实时引用清零；
- 命名 gate、引用检查、diff check 与正式 FMS verify 通过。

## Boundary
- Affected paths: `docs/superpowers/specs`, `docs/superpowers/plans`, `docs/releases/v1.8.2-release-notes.md`
- Allowed paths: `docs/superpowers/specs`, `docs/superpowers/plans`, `docs/releases/v1.8.2-release-notes.md`
- Protected paths: `backend`, `frontend`, `tests`, `scripts`, `docs/superpowers/handoff`, `.agent/devlines/v1-8-3-implementation-planning-review`, `.agent/devlines/v1-8-3-design-review-corrections`
- Dependencies: `docs/superpowers/specs/2026-07-25-model-custom-contract-design.md`, `docs/superpowers/specs/v1.8.3/capability-factory-design.md`, `docs/superpowers/specs/v1.8.3/domain-memory-design.md`, `docs/superpowers/plans/v1.8.3/2026-07-25-v1.8.3-execution-control.md`
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/test_no_exercise_specific_naming.py`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python scripts/devline_control.py verify --line v1-8-3-document-authority-consolidation`
- Known gates: `Preserve approved runtime, capability, memory, isolation, evidence, admission, authorization, and consumer boundaries while removing duplicate documentation.`, `Do not edit frozen historical Context Packs or prior development-line event streams.`, `The final live documentation convention is flat dated versioned Markdown files with one execution-control entry point and no retained objectives.`, `Do not push, open a PR, merge, tag, promote, or release without explicit user authorization.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none
