# Work Order — v1.8.9 P0 Workflow Truth Remediation 4

work_package: v1-8-9-p0-workflow-truth-remediation-4
lane: p0-workflow-truth-remediation-4
baseline_commit: c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
dependency: v1-8-9-p0-workflow-truth-remediation-3
formal_line: v1-8-9-p0-workflow-truth-remediation-4
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-workflow-truth
objective_path: docs/superpowers/objectives/2026-08-16-v1.8.9-p0-workflow-truth-remediation-4-objective.md

owned_paths:
  - backend/workbench/agent/workflow.py
  - backend/workbench/agent/workflow_runtime.py
  - backend/workbench/providers/builtin/workflow_post_estimation.json
  - tests/test_v189_workflow_truth.py
  - tests/test_workflow_resume.py
  - tests/test_workflow_runtime.py
  - docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-workflow-truth-remediation-4.md
  - docs/superpowers/handoff/2026-08-16-v1.8.9-p0-workflow-truth-remediation-4-handoff.md

protected_paths:
  - backend/workbench/contracts
  - backend/workbench/evidence
  - backend/workbench/services/results_service.py
  - backend/workbench/report_view_model.py
  - backend/workbench/predictive_research
  - frontend
  - scripts/gate.sh
  - .agent/devlines

focused_tests:
  - cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_workflow_truth.py ../tests/test_workflow_resume.py ../tests/test_workflow_runtime.py -q

known_gates:
  - shared Agent/Notebook cutover, provider execution, browser, full gate and release remain NOT VERIFIED
  - FD-only host persistence and protected consumer/report wiring remain outside this line
  - no commit, merge, push or tag is authorized
