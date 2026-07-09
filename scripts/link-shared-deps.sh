#!/usr/bin/env bash
# link-shared-deps.sh — 让新 worktree 共用主仓库的依赖，免去重复安装。
#
# 主仓库(REPO_ROOT)保留唯一一份权威的 .venv + frontend/node_modules；
# 每个新 worktree 只建符号链接指过去，不再 pip install / npm install。
#
# 用法:
#   scripts/link-shared-deps.sh <worktree路径>
#   例: scripts/link-shared-deps.sh .worktrees/workbench-v1.6.6
#
# 依赖漂移(重要):
#   如果某个新版本改了 requirements / package.json(新增了包),
#   在主仓库根跑一次安装即可,所有 worktree 因共享自动生效:
#     (cd "$REPO_ROOT" && .venv/bin/pip install -r backend/requirements.txt)
#     (cd "$REPO_ROOT/frontend" && npm install)
set -euo pipefail

REPO_ROOT="/Users/jiayuanren/项目规划"
WT="${1:?用法: link-shared-deps.sh <worktree路径>}"

# 规范成绝对路径
WT="$(cd "$WT" && pwd)"

if [ ! -d "$REPO_ROOT/.venv" ]; then
  echo "错误: 主仓库缺少 .venv ($REPO_ROOT/.venv)。先在主仓库装一次依赖。" >&2
  exit 1
fi
if [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
  echo "错误: 主仓库缺少 frontend/node_modules。先在主仓库 npm install 一次。" >&2
  exit 1
fi

# 安全: 若 worktree 里已有*实体*依赖目录(非链接),提示先删,避免误覆盖。
for p in "$WT/.venv" "$WT/frontend/node_modules"; do
  if [ -e "$p" ] && [ ! -L "$p" ]; then
    echo "警告: $p 是实体目录(非链接)。删掉它以回收空间后再重跑:" >&2
    echo "  rm -rf \"$p\"" >&2
    exit 1
  fi
done

# -s 符号链接  -f 覆盖旧链接  -n 不要链接进已存在目录内部
ln -sfn "$REPO_ROOT/.venv" "$WT/.venv"
mkdir -p "$WT/frontend"
ln -sfn "$REPO_ROOT/frontend/node_modules" "$WT/frontend/node_modules"

echo "已链接共享依赖到 $WT :"
echo "  .venv                 -> $REPO_ROOT/.venv"
echo "  frontend/node_modules -> $REPO_ROOT/frontend/node_modules"
