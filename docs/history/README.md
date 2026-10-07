# 历史与存档

Arboris 每个版本、每个开发工作目录、每份没提交的草稿和每个 stash 都保存在 git 里，并已推送到
GitHub。本目录告诉你去哪里找、怎么打开。

| 想知道 | 看这里 |
|---|---|
| 每个版本是什么时候发布的、做了什么 | [versions.md](versions.md)（含发布说明、GitHub Release、当时的代码链接） |
| 某个开发工作目录当时的样子，以及里面没提交的东西 | [worktrees.md](worktrees.md) |
| 各个 stash 里存了什么 | [stashes.md](stashes.md) |
| 以上全部，机器可读 | [archive-index.json](archive-index.json) |

## 例外：v1.8.11 的逐提交历史只在本机

v1.8.11 开发中，有些 Stata 日志在脱敏前就被提交了，早期提交里留有许可证序列号与持有人。
因此本版以一个 squash 提交合入 main（`8b1a5390`，文件树与集成分支末端完全一致），**逐提交历史不推送**：

- 本机保存：集成分支与 23 个 lane / 审查分支，加 `refs/private/v1.8.11-full-history`（不是 tag，`git push --tags` 不会带走）；
- 入库文件里原始日志的 SHA-256 已换成带密钥的占位符（`withheld-raw-sha256-*`），真实值只在本机 `local/v1811-license-raw/`；
- 主仓库 `.git/hooks/pre-push` 拒绝推送私有 ref、这些分支、新增的许可证值和被隐去的哈希。

## 查询

```bash
git tag -l 'v*'                          # 所有发布版本
git tag -l 'archive/*'                   # 所有存档
git log --oneline v1.8.7..v1.8.8         # 两个版本之间做了什么
git diff --stat v1.8.7 v1.8.8            # 两个版本之间改了哪些文件
git show v1.6.5:README.md                # 某个版本里的某个文件
git show --stat archive/leftovers/workbench-v1.7     # 某个工作目录里没提交的文件
git show archive/leftovers/workbench-v1.7:findings.md
```

不用命令行：在 GitHub 上打开 `https://github.com/damndone/Arboris/tree/<tag>`，例如
[v1.8.8](https://github.com/damndone/Arboris/tree/v1.8.8)、
[archive/leftovers/workbench-v1.7](https://github.com/damndone/Arboris/tree/archive/leftovers/workbench-v1.7)。

## 打开一个旧版本来运行或回滚重建

```bash
bash scripts/open-version.sh v1.8.8                      # 发布版本
bash scripts/open-version.sh workbench-v1.6.5            # 某个工作目录存档时的状态
bash scripts/open-version.sh workbench-v1.7 --leftovers  # 连同它没提交的文件
git worktree remove .worktrees/view-v1.8.8               # 用完移除
```

打开的是一个独立的只读式工作目录（detached，不移动任何分支）。要在旧版本上继续开发，
从它新建分支：`git worktree add -b <新分支> .worktrees/<目录> v1.8.8`——v1.8.9 就是这样
从 v1.8.8 重建的。

## 各类存档

- **发布版本**：`v*` tag，v1.4.1 起每版都有；发布说明在 `docs/releases/`。
- **开发工作目录**：`archive/worktree/<名字>`——2026-09-28 存档时每个 worktree 的提交，共 82 个，
  包括没有发布 tag 的早期版本（v1.0–v1.4.0）和各条并行开发线（v1.7.3 的 wo-*、v1.8.1、v1.8.8 的 P4–P7 等）。
- **没提交的文件**：`archive/leftovers/<名字>`——叠在上面那个提交之上的一个提交（缓存除外）。
- **stash**：`archive/stash/<短哈希>-<说明>`——转成普通提交，含未跟踪文件。
- **合并前的分支**：`archive/branch-tip/*`——分支合并删除时保留的最后一个提交。
- **未采用的整合分支**：`archive/v1.8.9-codex-wip`——Codex 的 v1.8.9 整合分支（未采用，作零件库）。

## 设计与过程文档在哪

- 每版目标与完成状态：`docs/superpowers/objectives/`
- 设计与计划：`docs/superpowers/specs/`、`docs/superpowers/plans/`（旧的在 `docs/superpowers/archive/`）
- 并行开发的设计与证据：`docs/superpowers/release-trains/`（v1.7.3），并行开发协议 ADR-PD-001 在 `docs/superpowers/specs/2026-07-18-adr-pd-001-parallel-development-protocol.md`
- 评测与发版 gate 日志：`docs/superpowers/evaluations/`
- 每条开发线的事件与复盘：`.agent/devlines/<线>/`（`RETROSPECTIVE.md`）
- 长期路线与待办：`docs/superpowers/roadmap/`、`docs/superpowers/followups/BACKLOG.md`

## 本地保留

最近五个版本保留常驻工作目录：`workbench-v1.8.6`、`-v1.8.7`、`-v1.8.8-final`
（即 v1.8.8 发布状态）、`-v1.8.9`、`-v1.8.10`。`workbench-v1.8.5` 于 2026-10-04 轮换移出（分支保留）。
2026-10-07 发布 v1.8.11 后新增常驻 `workbench-v1.8.11`；按五个版本的规矩应轮换移出 `workbench-v1.8.6`，**等用户确认后再移除**（不自动删）。
其余可随时用上面的脚本重建。
