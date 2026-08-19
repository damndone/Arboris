# Work Order — v1.8.9 P0 Legacy Compilation Authority Cutover

work_package: v1-8-9-p0-legacy-compilation-authority-cutover
lane: p0-legacy-compilation-authority-cutover
baseline_commit: c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
dependency: v1-8-9-p0-agent-compiler-remediation-5
formal_line: v1-8-9-p0-legacy-compilation-authority-cutover
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-legacy-cutover
objective_path: docs/superpowers/objectives/2026-08-16-v1.8.9-p0-legacy-compilation-authority-cutover-objective.md

owned_paths:
  - backend/workbench/contracts/agent/planning.py
  - backend/workbench/agent/plan_compiler.py
  - backend/workbench/agent/planning_contracts.py
  - backend/workbench/agent/compilation_store.py
  - tests/contracts/test_v189_contract_lock.py
  - tests/test_v189_legacy_compilation_authority.py
  - docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-legacy-compilation-authority-cutover.md
  - docs/superpowers/handoff/2026-08-16-v1.8.9-p0-legacy-compilation-authority-cutover-handoff.md

protected_paths:
  - backend/workbench/agent/workflow.py
  - backend/workbench/agent/workflow_runtime.py
  - backend/workbench/agent/notebook
  - backend/workbench/evidence
  - backend/workbench/services/results_service.py
  - backend/workbench/report_view_model.py
  - backend/workbench/predictive_research
  - frontend
  - scripts/gate.sh
  - .agent/devlines

focused_tests:
  - cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/contracts/test_v189_contract_lock.py ../tests/test_v189_legacy_compilation_authority.py -q

known_gates:
  - trusted host/supervisor wiring and integration with the accepted Compiler-5 implementation remain NOT VERIFIED
  - Agent/Notebook route cutover, provider, browser, full gate and release remain NOT VERIFIED
  - no commit, merge, push or tag is authorized

