#!/usr/bin/env bash
# One-command antifragility gate. Run from a version worktree root.
set -uo pipefail

fail=0
mode="full"
PYTHON=""
python_resolution_attempted=0

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

# A full gate runs the whole backend suite plus a multi-worker jsdom pool. Two
# of them at once, or one alongside a dev server, exhausted a 24 GB machine and
# the suite was killed mid-run -- which surfaced as a truncated log and a bare
# exit 1, i.e. it looked like a test failure rather than memory exhaustion.
# Refuse to start instead of stacking, and say exactly what to stop.
GATE_LOCK="${TMPDIR:-/tmp}/workbench-gate-$(cd "$(dirname "$0")/.." && basename "$PWD").lock"

preflight_exclusive() {
  local conflict=0

  if [ -e "$GATE_LOCK" ]; then
    local holder
    holder="$(cat "$GATE_LOCK" 2>/dev/null || echo unknown)"
    if [ "$holder" != "unknown" ] && kill -0 "$holder" 2>/dev/null; then
      echo "REFUSING: another gate is already running (pid $holder)." >&2
      echo "  Wait for it, or: kill $holder && rm -f $GATE_LOCK" >&2
      exit 3
    fi
    rm -f "$GATE_LOCK"
  fi

  # Match how a real vitest run actually appears in the process table --
  # `node (vitest)` and `node (vitest N)` for its workers -- rather than any
  # command line that mentions the word. A looser pattern matched its own
  # monitoring `grep -E "vitest|..."` and refused a perfectly clean gate; a
  # preflight that cries wolf gets switched off, which is worse than none.
  local stray
  stray="$(pgrep -f "node \([v]itest" 2>/dev/null | tr '\n' ' ' || true)"
  if [ -n "${stray// /}" ]; then
    echo "REFUSING: vitest is already running (pids: $stray)." >&2
    echo "  A previous run may not have exited. Stop it first: kill $stray" >&2
    conflict=1
  fi

  local dev
  dev="$(pgrep -f "[v]ite.*--port" 2>/dev/null | tr '\n' ' ' || true)"
  if [ -n "${dev// /}" ]; then
    echo "REFUSING: a vite dev server is running (pids: $dev)." >&2
    echo "  Stop the preview before gating; they contend for memory and the" >&2
    echo "  same build cache. Then re-run this script." >&2
    conflict=1
  fi

  [ "$conflict" -eq 0 ] || exit 3

  echo $$ > "$GATE_LOCK"
  trap 'rm -f "$GATE_LOCK"' EXIT INT TERM
}

# A worktree must borrow the main checkout's frontend/node_modules, never
# install its own.
#
# scripts/link-shared-deps.sh has existed for this since v1.6.6, but nothing
# enforced it, so three worktrees quietly ran `npm install` and carried a full
# 137-159 MB copy each -- 431 MB of byte-identical duplication, on a disk with
# 8.8 GB free. All three had the same package-lock hash as the main checkout,
# so not one of those copies was buying anything.
#
# Checked here because the gate is the one command nobody skips before a
# handoff, a merge or a release.
#
# Scope is deliberately narrow. `.venv` is NOT checked: this script resolves a
# Python in a documented order (WORKBENCH_PYTHON, then a local .venv, then the
# common checkout's), and tests cover a worktree that carries its own -- and it
# was never the waste anyway, since the duplicated trees had no .venv at all.
# The main checkout is skipped because it owns the authoritative directory, and
# the repo root is derived from git rather than hardcoded so a scratch
# repository built in a temp directory is simply not our concern.
preflight_shared_deps() {
  local here common_git repo_root
  here="$(cd "$(dirname "$0")/.." && pwd)"

  # Invoked from inside the worktree rather than with `-C`, matching how the
  # rest of this script calls git.
  common_git="$(cd "$here" && git rev-parse --git-common-dir 2>/dev/null)" || return 0
  [ -n "$common_git" ] || return 0
  case "$common_git" in
    /*) ;;
    *) common_git="$here/$common_git" ;;
  esac
  # Derived textually: the parent of the common .git directory is the main
  # checkout. Resolving it by `cd` would depend on that directory existing,
  # which makes the check silently skip itself rather than fail loudly.
  repo_root="$(dirname "$common_git")"

  # The main checkout owns the real directory; nothing to enforce there.
  [ "$here" = "$repo_root" ] && return 0
  # Without a shared install to borrow, there is nothing to point at.
  [ -d "$repo_root/frontend/node_modules" ] || return 0

  local modules="$here/frontend/node_modules"
  if [ -d "$modules" ] && [ ! -L "$modules" ]; then
    local size
    size="$(du -sh "$modules" 2>/dev/null | cut -f1)"
    echo "REFUSING: $modules is a real directory (${size:-?}), not a link to" >&2
    echo "  the shared install. Worktrees must not install their own." >&2
    echo "" >&2
    echo "  Reclaim it, then re-run this script:" >&2
    echo "    rm -rf \"$modules\"" >&2
    echo "    bash \"$repo_root/scripts/link-shared-deps.sh\" \"$here\"" >&2
    echo "" >&2
    echo "  If this worktree genuinely needs different dependency versions, say" >&2
    echo "  so in its handoff and install them in the main checkout instead --" >&2
    echo "  every worktree shares one authoritative install by design." >&2
    exit 3
  fi

  if [ ! -e "$modules" ]; then
    echo "NOTE: this worktree has no frontend/node_modules. Link the shared one:" >&2
    echo "    bash \"$repo_root/scripts/link-shared-deps.sh\" \"$here\"" >&2
  fi
}

run_stage() {
  local label="$1"
  shift
  banner "$label"
  "$@" || fail=1
}

resolve_pytest_python() {
  local common_git_dir=""
  local common_python=""
  local candidate
  local -a candidates=()

  if [ -n "$PYTHON" ]; then
    return 0
  fi
  if [ "$python_resolution_attempted" -eq 1 ]; then
    return 1
  fi
  python_resolution_attempted=1

  if [ -n "${WORKBENCH_PYTHON:-}" ]; then
    candidates+=("$WORKBENCH_PYTHON")
  fi
  candidates+=("$PWD/.venv/bin/python")

  if common_git_dir="$(git rev-parse --git-common-dir 2>/dev/null)" \
    && [ -n "$common_git_dir" ]; then
    case "$common_git_dir" in
      /*) ;;
      *) common_git_dir="$PWD/$common_git_dir" ;;
    esac
    common_python="$(dirname "$common_git_dir")/.venv/bin/python"
    if [ "$common_python" != "$PWD/.venv/bin/python" ]; then
      candidates+=("$common_python")
    fi
  fi

  for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import pytest' >/dev/null 2>&1; then
      PYTHON="$candidate"
      return 0
    fi
  done

  printf '\nERROR: No pytest-capable Python interpreter found.\n' >&2
  printf 'Checked candidates (in order):\n' >&2
  for candidate in "${candidates[@]}"; do
    printf '  - %s\n' "$candidate" >&2
  done
  return 1
}

run_pytest() {
  resolve_pytest_python || return 1
  "$PYTHON" -m pytest "$@"
}

run_backend_full() {
  run_pytest -q
}

run_golden() {
  run_pytest \
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
  run_pytest tests/test_gate_script.py -q
}

run_devline_control_verify() {
  resolve_pytest_python || return 1
  PYTHONPATH="backend${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" scripts/devline_control.py verify --all
}

run_backend_agent_llm() {
  run_pytest -q \
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
  local has_dev_control_surface=0
  local devline_directory
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
      backend/workbench/development_control/*|tests/test_devline_control_*.py|scripts/devline_control.py|AGENTS.md|.agent/development-control/*)
        has_dev_control_surface=1
        ;;
      .agent/devlines/*/context-pack.md|.agent/devlines/*/context-pack.manifest.json|.agent/devlines/*/events.jsonl.anchor)
        has_dev_control_surface=1
        ;;
      .agent/devlines/*/events.jsonl|.agent/devlines/*/RETROSPECTIVE.md)
        devline_directory="${path%/*}"
        if [ -f "$devline_directory/events.jsonl.anchor" ]; then
          has_dev_control_surface=1
        else
          has_backend_other=1
        fi
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

  # Formal development-control artifacts are the only change surface that
  # replays all existing FMS history in quick mode.  The verifier is read-only
  # and fail-closed; product-only work must not pay this historical-gate cost.
  if [ "$has_dev_control_surface" -eq 1 ]; then
    run_stage "QUICK formal development-control verification" run_devline_control_verify
  fi

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

preflight_shared_deps
preflight_exclusive

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
