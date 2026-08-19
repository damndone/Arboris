# Work Order — v1.8.9 P0 Evidence Core

work_package: v1-8-9-p0-evidence-core
lane: p0-evidence-core
baseline_commit: c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
dependency: v1-8-9-contract-lock
branch: workbench-v1.8.9-p0-evidence-core
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core
formal_line: v1-8-9-p0-evidence-core

owned_paths:
  - backend/workbench/evidence/__init__.py
  - backend/workbench/evidence/contracts.py
  - backend/workbench/evidence/registry.py
  - backend/workbench/evidence/projection.py
  - backend/workbench/evidence/persistence.py
  - backend/workbench/providers/builtin/evidence_core.json
  - tests/test_v189_evidence_envelope.py
  - docs/superpowers/objectives/2026-08-16-v1.8.9-p0-evidence-core-objective.md
  - docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core.md

read_only_contracts:
  - backend/workbench/contracts/evidence/**
  - backend/workbench/contracts/common/**
  - backend/workbench/canonical.py
  - backend/workbench/agent/capability_contract.py

forbidden_paths:
  - backend/workbench/agent/workflow_runtime.py
  - backend/workbench/agent/workflow.py
  - backend/workbench/results_service.py
  - backend/workbench/agent/**
  - backend/workbench/predictive_research/**
  - frontend/**
  - scripts/gate.sh
  - .agent/devlines/**

focused_tests:
  - cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_evidence_envelope.py -q

known_gates:
  - consumer/UI wiring is intentionally deferred to later integration lines
  - browser, real provider, full gate and release evidence are NOT VERIFIED
  - merge, push, tag and release are not authorized

rollback: abandon only this isolated worktree/branch; do not rewrite C0 or main

## Acceptance

- Valid envelopes round-trip canonically with stable semantic status.
- Missing, corrupt, unavailable, blocked, tampered and cross-scope artifacts fail closed.
- Projection never fabricates values or silently re-runs analysis.
- Formal events, verification and retrospective are produced by the control CLI.
