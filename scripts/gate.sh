#!/usr/bin/env bash
# One-command antifragility gate. Run from a version worktree root.
set -uo pipefail

fail=0
mode="full"

usage() {
  cat <<'EOF'
Usage: bash scripts/gate.sh [--quick|--full]

  --quick  Run the smallest safe check set for current worktree changes.
  --full   Run the complete release gate (default).
  --help   Show this help.

The quick mode is for daily development. Use the default/full mode before
handoff, release, push, merge, or tag.
EOF
}

if [ "$#" -gt 1 ]; then
  usage >&2
  exit 2
fi

case "${1:-}" in
  ""|--full)
    mode="full"
    ;;
  --quick)
    mode="quick"
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

banner() {
  printf '\n========== %s ==========\n' "$1"
}

run_stage() {
  local label="$1"
  shift
  banner "$label"
  "$@" || fail=1
}

run_backend_full() {
  .venv/bin/python -m pytest -q
}

run_golden() {
  .venv/bin/python -m pytest \
    tests/test_engine_golden.py \
    tests/test_lineage_invariants.py \
    tests/test_behavior_snapshot.py \
    -q
}

run_frontend_tests() {
  ( cd frontend && npx vitest run )
}

run_frontend_typecheck() {
  ( cd frontend && npx tsc --noEmit )
}

run_diff_check() {
  git diff --check
  git diff --cached --check
}

run_gate_syntax() {
  bash -n scripts/gate.sh
}

run_gate_script_tests() {
  .venv/bin/python -m pytest tests/test_gate_script.py -q
}

run_backend_agent_llm() {
  .venv/bin/python -m pytest -q \
    tests/test_agent_*.py \
    tests/test_llm_*.py \
    tests/test_rerun_service.py \
    tests/test_rerun_endpoint.py \
    tests/test_lineage_run_inputs.py \
    tests/test_node_write_validation.py \
    tests/test_api_run_params.py
}

collect_changed_files() {
  {
    git diff --name-only
    git diff --cached --name-only
    git ls-files --others --exclude-standard
  } | sort -u
}

run_quick() {
  local changed_count=0
  local has_agent_surface=0
  local has_backend_other=0
  local has_frontend=0
  local has_gate_script=0
  local has_pyproject=0
  local path

  while IFS= read -r path; do
    [ -n "$path" ] || continue
    changed_count=$((changed_count + 1))

    case "$path" in
      backend/workbench/agent/*|backend/workbench/http/agent_routes.py|backend/workbench/http/llm_routes.py|backend/workbench/app.py|backend/workbench/llm/client.py|backend/workbench/llm/provider_store.py|backend/workbench/services/rerun_service.py|backend/workbench/services/run_service.py|backend/workbench/services/results_service.py|backend/workbench/lineage/run_inputs.py|backend/workbench/lineage/node_write_validation.py|tests/test_agent_*.py|tests/test_llm_*.py|tests/test_rerun_service.py|tests/test_rerun_endpoint.py|tests/test_lineage_run_inputs.py|tests/test_node_write_validation.py|tests/test_api_run_params.py)
        has_agent_surface=1
        ;;
      frontend/*)
        has_frontend=1
        ;;
      scripts/gate.sh|tests/test_gate_script.py)
        has_gate_script=1
        ;;
      pyproject.toml)
        has_pyproject=1
        ;;
      docs/*|*.md|*.markdown|*.rst|*.txt)
        ;;
      *)
        has_backend_other=1
        ;;
    esac
  done < <(collect_changed_files)

  # A dependency/configuration-only change is conservative and falls back to
  # the full backend suite. It remains part of the focused slice only when
  # accompanied by the explicitly covered Agent/LLM surface.
  if [ "$has_pyproject" -eq 1 ] && [ "$has_agent_surface" -eq 0 ]; then
    has_backend_other=1
  fi

  # With no local changes, a small smoke suite still gives useful feedback.
  if [ "$changed_count" -eq 0 ]; then
    has_agent_surface=1
  fi

  run_stage "QUICK diff check" run_diff_check

  if [ "$has_backend_other" -eq 1 ]; then
    run_stage "QUICK backend full fallback" run_backend_full
  elif [ "$has_agent_surface" -eq 1 ]; then
    run_stage "QUICK backend Agent/LLM/rerun focused suite" run_backend_agent_llm
  fi

  if [ "$has_frontend" -eq 1 ]; then
    run_stage "QUICK frontend tests" run_frontend_tests
    run_stage "QUICK frontend typecheck" run_frontend_typecheck
  fi

  if [ "$has_gate_script" -eq 1 ]; then
    run_stage "QUICK gate script syntax" run_gate_syntax
    run_stage "QUICK gate contract tests" run_gate_script_tests
  fi

  if [ "$changed_count" -gt 0 ] && [ "$has_backend_other" -eq 0 ] \
    && [ "$has_agent_surface" -eq 0 ] && [ "$has_frontend" -eq 0 ] \
    && [ "$has_gate_script" -eq 0 ]; then
    banner "QUICK docs-only change"
    printf '%s\n' 'No runtime tests required for documentation-only changes.'
  fi
}

if [ "$mode" = "quick" ]; then
  run_quick
else
  run_stage "BACKEND full suite (python -m pytest)" run_backend_full
  run_stage "GOLDEN / invariants / snapshot (0-drift)" run_golden
  run_stage "FRONTEND tests (vitest)" run_frontend_tests
  run_stage "FRONTEND typecheck (tsc --noEmit)" run_frontend_typecheck
fi

if [ "$fail" -ne 0 ]; then
  printf '\n>>> GATE FAILED\n'
  exit 1
fi
printf '\n>>> GATE PASSED\n'
