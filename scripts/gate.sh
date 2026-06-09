#!/usr/bin/env bash
# V1.5.4.3 one-command antifragility gate. Run from a version worktree root.
set -uo pipefail
fail=0
banner() { printf '\n========== %s ==========\n' "$1"; }

banner "BACKEND full suite (python -m pytest)"
.venv/bin/python -m pytest -q || fail=1

banner "GOLDEN / invariants / snapshot (0-drift)"
.venv/bin/python -m pytest tests/test_engine_golden.py tests/test_lineage_invariants.py tests/test_behavior_snapshot.py -q || fail=1

banner "FRONTEND tests (vitest)"
( cd frontend && npx vitest run ) || fail=1

banner "FRONTEND typecheck (tsc --noEmit)"
( cd frontend && npx tsc --noEmit ) || fail=1

if [ "$fail" -ne 0 ]; then
  printf '\n>>> GATE FAILED\n'; exit 1
fi
printf '\n>>> GATE PASSED\n'
