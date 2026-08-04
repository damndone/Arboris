# Frozen Context Pack

Line: `v1-8-6-graph-persistence`
Baseline SHA: `cb08e6f0acaccc5e30c0357d6ed1e2d81611d8c8`

## Objective
# v1.8.6 Graph Identity Persistence Objective

把 predictive-research 的分层 SampleSpec identity 投影到 Graph 节点，并让
GraphStore 读回后仍保留 `node_hash`。旧 graph.json 没有该字段时必须继续可读，
以保持 v1.8.5 运行的兼容性；新 prediction run 的 dataset/split/model/evaluation
链必须可从 Graph 节点取到非空稳定身份。

## 可证伪验收

- GraphRecorder 写入的 node_hash 经 GraphStore 写入/读回保持不变。
- 没有 node_hash 的旧 JSON 仍读回为 `None`，不改变旧节点的其他字段。
- predictive-research Graph chain 的每个节点都有非空稳定 node_hash。
- 相关回归测试与既有 GraphStore/GraphRecorder 测试通过。

## Boundary
- Affected paths: `docs/superpowers/plans/2026-08-03-v1.8.6-graph-persistence-objective.md`, `backend/workbench/graph_store.py`, `backend/workbench/graph_model.py`, `backend/workbench/graph_recorder.py`, `backend/workbench/predictive_research/graph_persistence.py`, `tests/test_node_hash.py`
- Allowed paths: `docs/superpowers/plans/2026-08-03-v1.8.6-graph-persistence-objective.md`, `backend/workbench/graph_store.py`, `backend/workbench/graph_model.py`, `backend/workbench/graph_recorder.py`, `backend/workbench/predictive_research/graph_persistence.py`, `tests/test_node_hash.py`
- Protected paths: none
- Dependencies: `baseline-cb08e6f`, `S0-identity-projection-present-GraphStore-readback-pending`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_node_hash.py tests/predictive_research/test_sample_identity_v186.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_graph_store.py tests/test_graph_recorder.py -q`
- Known gates: `TDD-red-before-GraphStore-code`, `old-graph-json-without-node_hash-remains-readable`, `no-push-PR-merge-or-tag-without-authorization`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
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
