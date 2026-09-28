# stash 存档（2026-09-28）

git stash 只存在于本机、不随推送备份，也不便查阅。每个 stash 都转成了一个普通提交（叠在它原来的基础提交上，未跟踪文件也包含在内），tag 为 `archive/stash/<短哈希>-<说明>`，已推送。stash 本身未删除。

查看：`git show --stat <tag>`；与基础比较：`git diff <tag>^ <tag>`；取回：`git checkout <tag> -- <路径>`。

| 存档 tag | stash 说明 | 改动文件 | 未跟踪文件 | 备注 |
|---|---|---|---|---|
| `archive/stash/b065b0bd-codex-wip-2026-08-19-typed-evidence-tests-set-aside-for-v1.8` | On main: codex-wip-2026-08-19-typed-evidence-tests (set aside for v1.8.9 release merge) | 2 | 0 | Codex 8/19 的两份 typed-evidence 测试；Codex 结论：不恢复原断言，防伪造目标需按现行可信边界重新设计 |
| `archive/stash/3f40afdf-v1.8.9-archived-dirty-worktree-2026-08-21-workbench-v1.8.9-f` | On workbench-v1.8.9-final-acceptance: v1.8.9 archived dirty worktree 2026-08-21 workbench-v1.8.9-final-acceptance | 6 | 0 |  |
| `archive/stash/31993161-v1.8.9-archived-dirty-worktree-2026-08-21-workbench-v1.8.9-w` | On workbench-v1.8.9-wave-a: v1.8.9 archived dirty worktree 2026-08-21 workbench-v1.8.9-wave-a | 126 | 0 |  |
| `archive/stash/f58ac0c5-v1.8.9-archived-dirty-worktree-2026-08-21-workbench-v1.8.9-p` | On workbench-v1.8.9-p1-data-consumer-runtime-port-r1: v1.8.9 archived dirty worktree 2026-08-21 workbench-v1.8.9-p1-data-consumer-runtime-port-r1 | 10 | 0 |  |
| `archive/stash/d9be7fbb-v1.8.9-archived-dirty-worktree-2026-08-21-workbench-v1.8.9-p` | On workbench-v1.8.9-p1-data-consumer-runtime-port: v1.8.9 archived dirty worktree 2026-08-21 workbench-v1.8.9-p1-data-consumer-runtime-port | 8 | 0 |  |
| `archive/stash/d3577b11-v1.8.9-archived-dirty-worktree-2026-08-21-workbench-v1.8.9-p` | On workbench-v1.8.9-p1-data-consumer: v1.8.9 archived dirty worktree 2026-08-21 workbench-v1.8.9-p1-data-consumer | 2 | 0 |  |
| `archive/stash/c3da5835-v1.8.9-archived-dirty-worktree-2026-08-21-workbench-v1.8.9-p` | On workbench-v1.8.9-p1-classification-production: v1.8.9 archived dirty worktree 2026-08-21 workbench-v1.8.9-p1-classification-production | 2 | 0 |  |
| `archive/stash/48b2fb7b-v1.8.9-archived-dirty-worktree-2026-08-21-workbench-v1.8.9-p` | On workbench-v1.8.9-p1-classification-ml: v1.8.9 archived dirty worktree 2026-08-21 workbench-v1.8.9-p1-classification-ml | 46 | 0 |  |
| `archive/stash/806981ec-v1.8.9-archived-dirty-worktree-2026-08-21-workbench-v1.8.9-f` | On workbench-v1.8.9-foundation-integration: v1.8.9 archived dirty worktree 2026-08-21 workbench-v1.8.9-foundation-integration | 14 | 0 |  |
| `archive/stash/ead08b89-v1.8.9-archive-probe-after-staging-2026-08-21` | On workbench-v1.8.9-c1-host-authority: v1.8.9 archive probe after staging 2026-08-21 | 7 | 0 |  |
| `archive/stash/04ef5a52-pre-v1.7.3-realign-2026-07-18` | On workbench-v1.7.3: pre-v1.7.3-realign-2026-07-18 | 53 | 9 |  |
