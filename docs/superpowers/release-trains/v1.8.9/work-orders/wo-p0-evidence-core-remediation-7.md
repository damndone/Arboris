# Work Order — v1.8.9 P0 Evidence Core Remediation 7

work_package: v1-8-9-p0-evidence-core-remediation-7
lane: p0-evidence-core-remediation-7
baseline_commit: c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
dependency: v1-8-9-p0-evidence-core-remediation-6
formal_line: v1-8-9-p0-evidence-core-remediation-7
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core
objective_path: docs/superpowers/objectives/2026-08-16-v1.8.9-p0-evidence-core-remediation-7-objective.md

owned_paths:
  - backend/workbench/evidence/authority.py
  - backend/workbench/evidence/__init__.py
  - tests/test_v189_evidence_envelope.py
  - docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core-remediation-7.md
  - docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-core-remediation-7-handoff.md

protected_paths:
  - backend/workbench/contracts
  - backend/workbench/agent
  - backend/workbench/data_operations.py
  - backend/workbench/services/results_service.py
  - backend/workbench/report_view_model.py
  - backend/workbench/predictive_research
  - frontend
  - scripts/gate.sh
  - .agent/devlines

focused_tests:
  - cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_evidence_envelope.py -q

known_gates:
  - production host resolver/deployment wiring and downstream runtime cutover remain NOT VERIFIED
  - provider execution, browser, full gate and release remain NOT VERIFIED
  - no commit, merge, push or tag is authorized

