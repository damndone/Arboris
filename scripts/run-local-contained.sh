#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="${WORKBENCH_PYTHON:-}"

if [[ -z "$python" && -x "$repo_root/.venv/bin/python" ]]; then
  python="$repo_root/.venv/bin/python"
fi

if [[ -z "$python" ]]; then
  common_git_dir="$(git -C "$repo_root" rev-parse --git-common-dir)"
  if [[ "$common_git_dir" != /* ]]; then
    common_git_dir="$repo_root/$common_git_dir"
  fi
  shared_python="$(dirname "$common_git_dir")/.venv/bin/python"
  if [[ -x "$shared_python" ]]; then
    python="$shared_python"
  fi
fi

if [[ -z "$python" || ! -x "$python" ]]; then
  echo "No Workbench Python found. Set WORKBENCH_PYTHON to the project interpreter." >&2
  exit 1
fi

cd "$repo_root"
export WORKBENCH_EXECUTION_PROFILE=local_contained
export PYTHONPATH="$repo_root/backend${PYTHONPATH:+:$PYTHONPATH}"
exec "$python" -m uvicorn workbench.api:app --host 127.0.0.1 --port "${WORKBENCH_PORT:-8000}"
