# Work Order — v1.8.9 P0 workflow result binding for ARMA/GARCH

work_package: v1-8-9-p0-workflow-result-binding-arma-garch
lane: p0-workflow-result-binding
baseline_commit: 91ee6a05eab2a1892844c8a3057e1e607359a29e
formal_line: v1-8-9-p0-workflow-result-binding-arma-garch
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration
objective_path: docs/superpowers/objectives/2026-08-20-v1.8.9-p0-workflow-result-binding-arma-garch-objective.md

owned_paths:
  - backend/workbench/engine/stages/estimation.py
  - backend/workbench/engine/result_binding.py
  - backend/workbench/engine/registry.py
  - backend/workbench/engine/packs/arma_garch/declaration.py
  - backend/workbench/engine/packs/ets/declaration.py
  - tests/test_v189_workflow_result_binding.py
  - tests/test_v189_evidence_report_boundary.py
  - docs/superpowers/objectives/2026-08-20-v1.8.9-p0-workflow-result-binding-arma-garch-objective.md
  - docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-workflow-result-binding-arma-garch.md
  - docs/superpowers/handoff/2026-08-20-v1.8.9-p0-workflow-result-binding-arma-garch-handoff.md

protected_paths:
  - backend/workbench/evidence
  - backend/workbench/services/results_service.py
  - backend/workbench/report_view_model.py
  - backend/workbench/agent
  - backend/workbench/statistical
  - frontend
  - scripts/gate.sh
  - .agent/devlines
  - other worktrees

focused_tests:
  - cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_workflow_result_binding.py -q
  - cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_evidence_report_boundary.py -q -k arma_garch_report_admission_valid_real_workflow_renders_owner_document
  - PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/engine
  - git diff --check

known_gates:
  - browser, real provider, multi-worker, host identity, full repository gate and release remain NOT VERIFIED
  - no merge, push or tag is authorized
