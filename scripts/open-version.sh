#!/usr/bin/env bash
# Open any past version or archived worktree as a worktree you can read and run.
#
#   bash scripts/open-version.sh v1.8.8                    # a release tag
#   bash scripts/open-version.sh workbench-v1.6.5          # an archived worktree, as it stood
#   bash scripts/open-version.sh workbench-v1.7 --leftovers  # ...with its uncommitted/untracked files
#   bash scripts/open-version.sh archive/stash/04ef5a52-pre-v1.7.3-realign-2026-07-18
#
# The worktree is created detached (no branch is moved) under .worktrees/view-<name>
# and linked to the shared dependencies. Remove it when done:
#   git worktree remove .worktrees/view-<name>
# See docs/history/README.md.
set -euo pipefail

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
[ $# -ge 1 ] || usage 1
[ "$1" = "-h" ] || [ "$1" = "--help" ] && usage 0

name=$1
leftovers=${2:-}
root=$(git rev-parse --show-toplevel)
cd "$root"

if git rev-parse -q --verify "refs/tags/$name^{commit}" >/dev/null; then
  ref=$name
elif [ "$leftovers" = "--leftovers" ] && git rev-parse -q --verify "refs/tags/archive/leftovers/$name^{commit}" >/dev/null; then
  ref=archive/leftovers/$name
elif git rev-parse -q --verify "refs/tags/archive/worktree/$name^{commit}" >/dev/null; then
  ref=archive/worktree/$name
else
  echo "no tag named $name, archive/worktree/$name or archive/leftovers/$name" >&2
  echo "list them with: git tag -l 'v*' 'archive/*'" >&2
  exit 1
fi

target=.worktrees/view-$(echo "$name" | tr '/' '-')
if [ -e "$target" ]; then
  echo "$target already exists"; exit 0
fi
git worktree add --detach "$target" "$ref"
if [ -x scripts/link-shared-deps.sh ]; then
  bash scripts/link-shared-deps.sh "$target" || echo "(could not link shared dependencies; the code is still readable)"
fi
echo
echo "opened $ref at $target"
echo "remove when done: git worktree remove $target"
