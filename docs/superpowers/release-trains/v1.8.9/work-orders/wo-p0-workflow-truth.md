# Work Order — v1.8.9 P0 Workflow Truth

work_package: v1-8-9-p0-workflow-truth-core
lane: p0-workflow-truth
baseline_commit: c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
dependency: v1-8-9-contract-lock
branch: workbench-v1.8.9-p0-workflow-truth
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-workflow-truth
formal_line: v1-8-9-p0-workflow-truth-core

owned_paths:
  - backend/workbench/agent/workflow.py
  - backend/workbench/agent/workflow_runtime.py
  - backend/workbench/agent/post_estimation_registry.py
  - backend/workbench/providers/builtin/workflow_post_estimation.json
  - tests/test_v189_workflow_truth.py
  - tests/test_workflow_resume.py
  - tests/test_workflow_runtime.py
  - docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-workflow-truth.md
  - docs/superpowers/handoff/2026-08-15-v1.8.9-p0-workflow-truth-handoff.md

focused_tests:
  - cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_workflow_truth.py ../tests/test_workflow_resume.py ../tests/test_workflow_runtime.py -q

protected_paths:
  - frontend
  - backend/workbench/predictive_research
  - backend/workbench/data_operations.py
  - backend/workbench/agent/workflow_contracts.py
  - backend/workbench/agent/notebook
  - scripts/gate.sh
  - .agent/devlines

known_gates:
  - lane-local evidence does not prove shared compiler cutover, browser, provider, final full gate or release
  - merge, push, tag and release are not authorized

Acceptance: typed outputs and resume are lossless; post-estimation is family-aware with no OLS fallback; unique admission and evidence completion are idempotent and scope-bound; formal state is managed through the control CLI.
