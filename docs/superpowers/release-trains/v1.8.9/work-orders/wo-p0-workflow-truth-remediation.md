# Work Order — v1.8.9 P0 Workflow Truth Remediation

work_package: v1-8-9-p0-workflow-truth-remediation
lane: p0-workflow-truth-remediation
baseline_commit: c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
dependency: v1-8-9-p0-workflow-truth-core
formal_line: v1-8-9-p0-workflow-truth-remediation
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-workflow-truth

owned_paths:
  - backend/workbench/agent/workflow.py
  - backend/workbench/agent/workflow_runtime.py
  - backend/workbench/agent/post_estimation_registry.py
  - backend/workbench/providers/builtin/workflow_post_estimation.json
  - tests/test_v189_workflow_truth.py
  - tests/test_workflow_resume.py
  - tests/test_workflow_runtime.py
  - docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-workflow-truth-remediation.md
  - docs/superpowers/handoff/2026-08-16-v1.8.9-p0-workflow-truth-remediation-handoff.md

protected_paths:
  - frontend
  - backend/workbench/predictive_research
  - backend/workbench/data_operations.py
  - backend/workbench/agent/workflow_contracts.py
  - backend/workbench/agent/notebook
  - scripts/gate.sh
  - .agent/devlines

focused_tests:
  - cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_workflow_truth.py ../tests/test_workflow_resume.py ../tests/test_workflow_runtime.py -q

known_gates:
  - shared compiler cutover, browser, provider, full gate and release remain NOT VERIFIED
  - no commit, merge, push or tag is authorized
