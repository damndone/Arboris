# Work Order — v1.8.9 P0 Agent Compiler

work_package: v1-8-9-p0-agent-compiler-core
lane: p0-agent-compiler
baseline_commit: c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
dependency: v1-8-9-contract-lock
branch: workbench-v1.8.9-p0-agent-compiler
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-agent-compiler
formal_line: v1-8-9-p0-agent-compiler-core

owned_paths:
  - backend/workbench/agent/planning_contracts.py
  - backend/workbench/agent/port_types.py
  - backend/workbench/agent/failure_contract.py
  - backend/workbench/agent/capability_manifest.py
  - backend/workbench/agent/capability_discovery.py
  - backend/workbench/agent/plan_compiler.py
  - backend/workbench/agent/compilation_store.py
  - backend/workbench/agent/context_compiler.py
  - backend/workbench/providers/builtin/agent_compiler.json
  - tests/test_v189_agent_compiler.py
  - tests/test_v189_capability_manifest.py
  - docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-compiler-core.md
  - docs/superpowers/handoff/2026-08-15-v1.8.9-p0-agent-compiler-core-handoff.md

focused_tests:
  - cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_agent_compiler.py ../tests/test_v189_capability_manifest.py -q

protected_paths:
  - backend/workbench/agent/workflow_runtime.py
  - backend/workbench/agent/workflow.py
  - backend/workbench/agent/workflow_contracts.py
  - backend/workbench/agent/operations.py
  - backend/workbench/agent/orchestrator.py
  - backend/workbench/agent/notebook
  - backend/workbench/http/agent_routes.py
  - backend/workbench/data_operations.py
  - backend/workbench/predictive_research
  - frontend
  - scripts/gate.sh
  - .agent/devlines

known_gates:
  - core/shadow evidence does not prove Agent/Notebook/runtime cutover, provider benchmark, browser, full gate or release
  - merge, push, tag and release are not authorized

Acceptance: draft input compiles only through known typed capabilities and compatible ports; compilation is server-owned, deterministic, persisted and replay-safe; unsafe requests fail closed.
