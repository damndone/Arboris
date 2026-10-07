# worktree 存档（2026-09-28）

2026-09-28 把 `.worktrees/` 下全部工作目录存档进 git 后，只保留最近五个版本的工作目录（常驻），其余移除。**分支一个都没删**；每个工作目录当时的提交有一个 `archive/worktree/<名字>` tag；工作目录里未提交、未跟踪或被忽略的文件（缓存除外：`node_modules`、`.venv`、`__pycache__` 等）存成叠在该提交之上的一个提交，tag 为 `archive/leftovers/<名字>`。全部 tag 已推送到 GitHub。存档后逐字节核对过 676 个文件，无差异；推送前扫描过密钥，无。

打开任何一个：`bash scripts/open-version.sh <名字或 tag>`（见 [README](README.md)）。

| 工作目录 | 分支 | 提交 | 发布 tag | 存档 tag | 残留文件存档 | 残留内容说明 | 状态 |
|---|---|---|---|---|---|---|---|
| `codex-c373` | `(detached)` | `90799cd7` | — | `archive/worktree/codex-c373` | — |  | 已移除工作目录 |
| `codex-c3f1` | `(detached)` | `90799cd7` | — | `archive/worktree/codex-c3f1` | — |  | 已移除工作目录 |
| `integration-v1.7.3` | `integration/v1.7.3` | `5b54b112` | — | `archive/worktree/integration-v1.7.3` | — |  | 已移除工作目录 |
| `integration-v1.8.1` | `integration/v1.8.1` | `3f9d7d97` | — | `archive/worktree/integration-v1.8.1` | — |  | 已移除工作目录 |
| `local-econometrics-workbench-v1` | `feature/local-econometrics-workbench-v1` | `1620cafd` | — | `archive/worktree/local-econometrics-workbench-v1` | `archive/leftovers/local-econometrics-workbench-v1`（1 项） | Claude Code 本地命令许可设置；无密钥，无产品价值 | 已移除工作目录 |
| `v173-agent-recipes-recovery` | `feat/v173-agent-recipes-recovery` | `d2e43ec2` | — | `archive/worktree/v173-agent-recipes-recovery` | — |  | 已移除工作目录 |
| `v173-c1.1-contract-receipts` | `release-train/v1.7.3-c1.1-contract-receipts` | `f25ffd11` | — | `archive/worktree/v173-c1.1-contract-receipts` | — |  | 已移除工作目录 |
| `v173-evaluation-harness` | `test/v173-evaluation-harness` | `97c40de7` | — | `archive/worktree/v173-evaluation-harness` | `archive/leftovers/v173-evaluation-harness`（6 项） | 6 处未提交修改（collector / strict runner 加固，+686/−153）；Codex 结论：留作参考，不直接并入主线 | 已移除工作目录 |
| `v173-model-linear-mixed-effects` | `feat/v173-model-linear-mixed-effects` | `1262a7c9` | — | `archive/worktree/v173-model-linear-mixed-effects` | — |  | 已移除工作目录 |
| `v173-ui-agent-inspector-compare` | `feat/v173-ui-agent-inspector-compare` | `cd8716ad` | — | `archive/worktree/v173-ui-agent-inspector-compare` | — |  | 已移除工作目录 |
| `v181-agent-notebook-options` | `feat/v181-agent-notebook-options` | `e71a0dda` | — | `archive/worktree/v181-agent-notebook-options` | — |  | 已移除工作目录 |
| `v181-evaluation-harness` | `test/v181-evaluation-harness` | `fb8680d4` | — | `archive/worktree/v181-evaluation-harness` | — |  | 已移除工作目录 |
| `v181-model-ets` | `feat/v181-model-ets` | `8ff8bf32` | — | `archive/worktree/v181-model-ets` | — |  | 已移除工作目录 |
| `v181-ui-notebook` | `feat/v181-ui-notebook` | `751af144` | — | `archive/worktree/v181-ui-notebook` | — |  | 已移除工作目录 |
| `workbench-frontend-api-enhancements` | `feature/workbench-frontend-api-enhancements` | `be198f7f` | — | `archive/worktree/workbench-frontend-api-enhancements` | — |  | 已移除工作目录 |
| `workbench-v1.2.0-hardening` | `feature/workbench-v1.2.0-hardening` | `4694641c` | — | `archive/worktree/workbench-v1.2.0-hardening` | — |  | 已移除工作目录 |
| `workbench-v1.2.1` | `workbench-v1.2.1` | `5314ecbc` | — | `archive/worktree/workbench-v1.2.1` | — |  | 已移除工作目录 |
| `workbench-v1.2.1-browsing` | `feature/workbench-v1.2.1-browsing` | `95f9e8ef` | — | `archive/worktree/workbench-v1.2.1-browsing` | `archive/leftovers/workbench-v1.2.1-browsing`（1 项） | v1.2.3 交互提交设计的早期草稿；正式版已另行提交（大幅改写） | 已移除工作目录 |
| `workbench-v1.2.2` | `workbench-v1.2.2` | `95f9e8ef` | — | `archive/worktree/workbench-v1.2.2` | `archive/leftovers/workbench-v1.2.2`（2 项） | v1.2.2 异步进度的设计与计划，从未提交；功能已实现（`80527380`）——这是唯一的设计记录 | 已移除工作目录 |
| `workbench-v1.2.3-interactive` | `workbench-v1.2.3-interactive` | `1bab7e52` | — | `archive/worktree/workbench-v1.2.3-interactive` | — |  | 已移除工作目录 |
| `workbench-v1.2.4-patch` | `workbench-v1.2.4-patch` | `0f8028c7` | — | `archive/worktree/workbench-v1.2.4-patch` | — |  | 已移除工作目录 |
| `workbench-v1.2.4-statistical-tests` | `workbench-v1.2.4-statistical-tests` | `edd88b6e` | — | `archive/worktree/workbench-v1.2.4-statistical-tests` | — |  | 已移除工作目录 |
| `workbench-v1.2.5` | `workbench-v1.2.5` | `79c8e8ff` | — | `archive/worktree/workbench-v1.2.5` | `archive/leftovers/workbench-v1.2.5`（3 项） | 删除了已入库的 frontend/dist 构建产物（无价值） | 已移除工作目录 |
| `workbench-v1.3.0` | `workbench-v1.3.0` | `919612a3` | — | `archive/worktree/workbench-v1.3.0` | `archive/leftovers/workbench-v1.3.0`（4 项） | Claude Code 本地设置 + 删除了已入库的 frontend/dist 构建产物 | 已移除工作目录 |
| `workbench-v1.3.1` | `workbench-v1.3.1` | `cd2b6d1c` | — | `archive/worktree/workbench-v1.3.1` | `archive/leftovers/workbench-v1.3.1`（14 项） | 构思讨论示意页；结论见 `docs/superpowers/specs/2026-05-12-v1.4-lineage-graph-design.md`、`2026-05-12-v1.3.2-foundation-refactor-design.md` | 已移除工作目录 |
| `workbench-v1.3.2` | `workbench-v1.3.2` | `8a2e6efa` | — | `archive/worktree/workbench-v1.3.2` | `archive/leftovers/workbench-v1.3.2`（3 项） | 删除了已入库的 frontend/dist 构建产物（无价值） | 已移除工作目录 |
| `workbench-v1.4` | `workbench-v1.4` | `d350704c` | `v1.4.1` | `archive/worktree/workbench-v1.4` | `archive/leftovers/workbench-v1.4`（12 项） | 构思讨论示意页；结论见 `docs/superpowers/specs/2026-05-19-v1.4.1-lineage-ui-design.md` | 已移除工作目录 |
| `workbench-v1.4.0` | `workbench-v1.4.0` | `b265bea2` | — | `archive/worktree/workbench-v1.4.0` | `archive/leftovers/workbench-v1.4.0`（3 项） | 删除了已入库的 frontend/dist 构建产物（无价值） | 已移除工作目录 |
| `workbench-v1.4.1` | `workbench-v1.4.1` | `06dbea9c` | — | `archive/worktree/workbench-v1.4.1` | `archive/leftovers/workbench-v1.4.1`（3 项） | 删除了已入库的 frontend/dist 构建产物（无价值） | 已移除工作目录 |
| `workbench-v1.5.0` | `workbench-v1.5.0` | `6a7bc5ee` | — | `archive/worktree/workbench-v1.5.0` | `archive/leftovers/workbench-v1.5.0`（1 项） | Claude Code 预览服务配置（launch.json）；无密钥 | 已移除工作目录 |
| `workbench-v1.5.0.1` | `workbench-v1.5.0.1` | `6e55fe54` | — | `archive/worktree/workbench-v1.5.0.1` | `archive/leftovers/workbench-v1.5.0.1`（1 项） | Claude Code 预览服务配置（launch.json）；无密钥 | 已移除工作目录 |
| `workbench-v1.5.1` | `workbench-v1.5.1` | `4b320aa4` | — | `archive/worktree/workbench-v1.5.1` | `archive/leftovers/workbench-v1.5.1`（11 项） | 构思讨论示意页（v1.5.2 Workbench Spine）；结论见 `docs/releases/v1.5.2-release-notes.md`，已实现 | 已移除工作目录 |
| `workbench-v1.5.2` | `workbench-v1.5.2` | `3dbaa788` | — | `archive/worktree/workbench-v1.5.2` | — |  | 已移除工作目录 |
| `workbench-v1.5.3` | `workbench-v1.5.3` | `2cc58d17` | — | `archive/worktree/workbench-v1.5.3` | `archive/leftovers/workbench-v1.5.3`（1 项） | Claude Code 预览服务配置（launch.json）；无密钥 | 已移除工作目录 |
| `workbench-v1.5.3.1` | `codex/workbench-v1.5.3.1` | `9d753977` | — | `archive/worktree/workbench-v1.5.3.1` | `archive/leftovers/workbench-v1.5.3.1`（1 项） | 误拖入的 VS Code 终端链接（无价值） | 已移除工作目录 |
| `workbench-v1.5.3.2` | `workbench-v1.5.3.2` | `d9aaec5e` | — | `archive/worktree/workbench-v1.5.3.2` | — |  | 已移除工作目录 |
| `workbench-v1.5.4` | `workbench-v1.5.4` | `abe7fda7` | — | `archive/worktree/workbench-v1.5.4` | — |  | 已移除工作目录 |
| `workbench-v1.5.4.1` | `workbench-v1.5.4.1` | `5ff37a80` | `v1.5.4.1` | `archive/worktree/workbench-v1.5.4.1` | — |  | 已移除工作目录 |
| `workbench-v1.5.4.2` | `workbench-v1.5.4.2` | `66f4899d` | `v1.5.4.2` | `archive/worktree/workbench-v1.5.4.2` | — |  | 已移除工作目录 |
| `workbench-v1.5.4.3` | `workbench-v1.5.4.3` | `62ece57c` | `v1.5.4.3` | `archive/worktree/workbench-v1.5.4.3` | — |  | 已移除工作目录 |
| `workbench-v1.5.4.4` | `workbench-v1.5.4.4` | `f0766789` | `v1.5.4.4` | `archive/worktree/workbench-v1.5.4.4` | — |  | 已移除工作目录 |
| `workbench-v1.5.4.5` | `workbench-v1.5.4.5` | `5ebee2d3` | `v1.5.4.5` | `archive/worktree/workbench-v1.5.4.5` | — |  | 已移除工作目录 |
| `workbench-v1.5.5` | `workbench-v1.5.5` | `c03e3500` | `v1.5.5.1` | `archive/worktree/workbench-v1.5.5` | — |  | 已移除工作目录 |
| `workbench-v1.5.6` | `workbench-v1.5.6` | `66be28b4` | — | `archive/worktree/workbench-v1.5.6` | — |  | 已移除工作目录 |
| `workbench-v1.5.6.1` | `workbench-v1.5.6.1` | `89216b29` | — | `archive/worktree/workbench-v1.5.6.1` | — |  | 已移除工作目录 |
| `workbench-v1.5.7` | `workbench-v1.5.7` | `9ee6a8a5` | `v1.5.7` | `archive/worktree/workbench-v1.5.7` | — |  | 已移除工作目录 |
| `workbench-v1.5.7.1` | `workbench-v1.5.7.1` | `7e3e05e5` | — | `archive/worktree/workbench-v1.5.7.1` | — |  | 已移除工作目录 |
| `workbench-v1.5.8` | `workbench-v1.5.8` | `4bb0718e` | — | `archive/worktree/workbench-v1.5.8` | — |  | 已移除工作目录 |
| `workbench-v1.5.9` | `workbench-v1.5.9` | `277ae734` | — | `archive/worktree/workbench-v1.5.9` | — |  | 已移除工作目录 |
| `workbench-v1.6.0` | `workbench-v1.6.0` | `f67f97ca` | — | `archive/worktree/workbench-v1.6.0` | — |  | 已移除工作目录 |
| `workbench-v1.6.1` | `workbench-v1.6.1` | `a1e3c7a0` | — | `archive/worktree/workbench-v1.6.1` | — |  | 已移除工作目录 |
| `workbench-v1.6.10` | `workbench-v1.6.10` | `344379dd` | — | `archive/worktree/workbench-v1.6.10` | — |  | 已移除工作目录 |
| `workbench-v1.6.10.1` | `workbench-v1.6.10.1` | `fafa0d2a` | — | `archive/worktree/workbench-v1.6.10.1` | — |  | 已移除工作目录 |
| `workbench-v1.6.11` | `workbench-v1.6.11` | `9acfae8b` | — | `archive/worktree/workbench-v1.6.11` | `archive/leftovers/workbench-v1.6.11`（1 项） | Claude Code 预览服务配置（launch.json）；无密钥 | 已移除工作目录 |
| `workbench-v1.6.12` | `workbench-v1.6.12` | `b5d763a7` | — | `archive/worktree/workbench-v1.6.12` | `archive/leftovers/workbench-v1.6.12`（5 项） | 构思讨论示意页；结论见 `docs/superpowers/specs/2026-07-12-v2-v10-ccswitch-settings-home-design.md` | 已移除工作目录 |
| `workbench-v1.6.2` | `codex/workbench-v1.6.2` | `7153dc5f` | — | `archive/worktree/workbench-v1.6.2` | `archive/leftovers/workbench-v1.6.2`（1 项） | npm 自动升级 lockfile 补丁版本（无价值） | 已移除工作目录 |
| `workbench-v1.6.3` | `codex/workbench-v1.6.3` | `bf5de581` | — | `archive/worktree/workbench-v1.6.3` | — |  | 已移除工作目录 |
| `workbench-v1.6.4` | `workbench-v1.6.4` | `ddf58c99` | — | `archive/worktree/workbench-v1.6.4` | `archive/leftovers/workbench-v1.6.4`（7 项） | 构思讨论示意页；结论见 `docs/superpowers/specs/2026-06-30-workbench-v1.6.5-variable-role-layer-design.md` | 已移除工作目录 |
| `workbench-v1.6.5` | `workbench-v1.6.5` | `b481f2cb` | — | `archive/worktree/workbench-v1.6.5` | `archive/leftovers/workbench-v1.6.5`（1 项） | 统一图工作台 roadmap 的 7/01 初稿；git 中有其后 4 次修订 | 已移除工作目录 |
| `workbench-v1.6.6` | `workbench-v1.6.6` | `0958a35d` | — | `archive/worktree/workbench-v1.6.6` | `archive/leftovers/workbench-v1.6.6`（1 项） | Claude Code 预览服务配置（launch.json）；无密钥 | 已移除工作目录 |
| `workbench-v1.6.7` | `workbench-v1.6.7` | `48b87c53` | — | `archive/worktree/workbench-v1.6.7` | — |  | 已移除工作目录 |
| `workbench-v1.6.8` | `workbench-v1.6.8` | `8aa6bba6` | — | `archive/worktree/workbench-v1.6.8` | `archive/leftovers/workbench-v1.6.8`（1 项） | matplotlib 字体缓存（无价值） | 已移除工作目录 |
| `workbench-v1.6.9` | `workbench-v1.6.9` | `c1926972` | — | `archive/worktree/workbench-v1.6.9` | — |  | 已移除工作目录 |
| `workbench-v1.7` | `workbench-v1.7` | `a7d8dccf` | — | `archive/worktree/workbench-v1.7` | `archive/leftovers/workbench-v1.7`（234 项） | v1.7 冒烟测试工作日志（findings 661 行）+ 演示与冒烟项目（含交错 DID 演示数据） | 已移除工作目录 |
| `workbench-v1.7.1` | `workbench-v1.7.1` | `39348a6a` | — | `archive/worktree/workbench-v1.7.1` | — |  | 已移除工作目录 |
| `workbench-v1.7.2` | `workbench-v1.7.2` | `1b8eda06` | — | `archive/worktree/workbench-v1.7.2` | `archive/leftovers/workbench-v1.7.2`（6 项） | v1.7.2 真实 DeepSeek 验收工作日志 + 构建产物 | 已移除工作目录 |
| `workbench-v1.7.3` | `workbench-v1.7.3` | `edfa8557` | — | `archive/worktree/workbench-v1.7.3` | — |  | 已移除工作目录 |
| `workbench-v1.8.1` | `workbench-v1.8.1` | `d86bf301` | — | `archive/worktree/workbench-v1.8.1` | — |  | 已移除工作目录 |
| `workbench-v1.8.2` | `workbench-v1.8.2` | `867dc6e0` | — | `archive/worktree/workbench-v1.8.2` | `archive/leftovers/workbench-v1.8.2`（10 项） | 构思讨论示意页；结论见 `docs/superpowers/archive/specs/2026-07-24-v1.8.2-statistical-variable-picker-design.md` 等 7/24–25 设计 | 已移除工作目录 |
| `workbench-v1.8.3` | `workbench-v1.8.3` | `36fce68b` | — | `archive/worktree/workbench-v1.8.3` | — |  | 已移除工作目录 |
| `workbench-v1.8.4` | `workbench-v1.8.4` | `efbfb7bc` | — | `archive/worktree/workbench-v1.8.4` | `archive/leftovers/workbench-v1.8.4`（13 项） | devline 事件草稿（13 份，均已写入正式日志） | 已移除工作目录 |
| `workbench-v1.8.5` | `workbench-v1.8.5` | `318784a2` | — | `archive/worktree/workbench-v1.8.5` | `archive/leftovers/workbench-v1.8.5`（5 项） | devline 事件草稿（5 份，均已写入正式日志） | 已移除工作目录（2026-10-04 轮换出常驻） |
| `workbench-v1.8.6` | `workbench-v1.8.6` | `ce635370` | — | `archive/worktree/workbench-v1.8.6` | `archive/leftovers/workbench-v1.8.6`（11 项） | 构思讨论示意页；结论见 `docs/superpowers/archive/specs/2026-08-04-v1.8.6-report-review-workspace-design.md`、`2026-08-03-v1.8.6-report-evidence-editing-design.md` | 常驻 |
| `workbench-v1.8.7` | `workbench-v1.8.7` | `2a312d42` | — | `archive/worktree/workbench-v1.8.7` | — |  | 常驻 |
| `workbench-v1.8.8` | `workbench-v1.8.8` | `ebba33f1` | — | `archive/worktree/workbench-v1.8.8` | — |  | 已移除工作目录 |
| `workbench-v1.8.8-final` | `workbench-v1.8.8-final` | `f564de63` | `v1.8.8` | `archive/worktree/workbench-v1.8.8-final` | — |  | 常驻 |
| `workbench-v1.8.8-p4` | `workbench-v1.8.8-p4` | `e0c347b0` | — | `archive/worktree/workbench-v1.8.8-p4` | — |  | 已移除工作目录 |
| `workbench-v1.8.8-p5` | `workbench-v1.8.8-p5` | `d9fdac91` | — | `archive/worktree/workbench-v1.8.8-p5` | — |  | 已移除工作目录 |
| `workbench-v1.8.8-p6` | `workbench-v1.8.8-p6` | `3285bc6d` | — | `archive/worktree/workbench-v1.8.8-p6` | — |  | 已移除工作目录 |
| `workbench-v1.8.8-p7-multivariate` | `workbench-v1.8.8-p7-multivariate` | `0ef1110c` | — | `archive/worktree/workbench-v1.8.8-p7-multivariate` | `archive/leftovers/workbench-v1.8.8-p7-multivariate`（14 项） | P7 扩展的 2 条 devline 与 4 份设计/计划。**分支上 40 个提交未进 main**；Codex 核查结论：有遗漏（契约/数值对照测试、多重插补端到端接线），v1.8.10 选择性移植，见 BACKLOG | 已移除工作目录 |
| `workbench-v1.8.9` | `workbench-v1.8.9` | `03fee6d8` | — | `archive/worktree/workbench-v1.8.9` | — |  | 常驻 |
| `workbench-v1.8.9-hardening-integration` | `workbench-v1.8.9-hardening-integration` | `214dee95` | — | `archive/worktree/workbench-v1.8.9-hardening-integration` | `archive/leftovers/workbench-v1.8.9-hardening-integration`（3 项） | 未跟踪的构建产物；分支本身即 `archive/v1.8.9-codex-wip` | 已移除工作目录 |
| `workbench-v1.8.10` | `workbench-v1.8.10` | `bea7e2a0` | `v1.8.10` | `archive/worktree/workbench-v1.8.10` | — |  | 常驻 |
| `codex-v1810-evaluation` | `eval/v1810-codex` | `9ce17129` | — | `archive/local-only/eval-v1810-codex` | — | Codex 评估线，v1.8.10 工单 A；已并入 v1.8.10 | 保留（可移出） |
| `codex-v1811-admission-oracles` | `eval/v1811-admission-oracles` | `3b43f003` | — | `archive/local-only/eval-v1811-admission-oracles` | — | Codex 评估线，工单 B；v1.8.11 的输入 | 保留 |
| `workbench-v1.8.11` | `workbench-v1.8.11` | `d6675af4` | `v1.8.11`（main 上为 squash `8b1a5390`） | —（只在本机：`refs/private/v1.8.11-full-history`） | — | 逐提交历史早期含 Stata 许可证值，不打存档 tag、不推送 | 常驻 |
| 另 22 个 v1.8.11 Codex lane / 审查工作目录（`codex-v1811-*`） | `lane/v1811-*`、`eval/v1811-codex`、`codex/v1811-*` | 见 `archive-index.json` | — | —（只在本机） | — | 同上；主仓库 `.git/hooks/pre-push` 拒绝推送这些分支 | 常驻（待用户决定是否移除） |

`codex-c373`、`codex-c3f1` 是 Codex 自己的 worktree（`~/.codex/worktrees/`），提交 `90799cd7` 已包含在 `archive/v1.8.9-codex-wip` 中。

## git 已不再登记的目录

| 目录 | 存档 tag | 说明 |
|---|---|---|
| `workbench-v1.8.0` | `archive/leftovers/workbench-v1.8.0`（7 项） | （失效的 worktree 目录，已跟踪内容与 tag v1.8.0 逐字相同）构思讨论示意页；结论见 `docs/superpowers/archive/specs/2026-07-20-time-series-graph-native-workbench-design.md` |
| `workbench-v1.8.3-cf4-notebook-planner-projection-r1` | `archive/leftovers/workbench-v1.8.3-cf4-notebook-planner-projection-r1`（1 项） | （失效目录）一份 devline 事件草稿，已在正式日志 |

## 主目录里 Codex v1.8.9 计划的未跟踪资料

存档 tag：`archive/leftovers/main-codex-v1.8.9-program`（24 个文件，基于 `a653693f`）。内容：三条未关闭的 devline（classification-search、p0-legacy-consumer-gate-migration、report-owner-factory）、三份 objective、`docs/superpowers/release-trains/v1.8.9/` 证据与工单、`.codex/` 事件草稿和规划文件。Codex 核查结论：分类搜索 objective（OOF 选择、holdout 封存、预算与参数校验）供 v1.8.11 分类 ML 参考；三条 devline 只是历史材料，不是完成证据。

文件列表：

- `.agent/devlines/v1-8-9-classification-search/RETROSPECTIVE.md`
- `.agent/devlines/v1-8-9-classification-search/context-pack.manifest.json`
- `.agent/devlines/v1-8-9-classification-search/context-pack.md`
- `.agent/devlines/v1-8-9-classification-search/events.jsonl`
- `.agent/devlines/v1-8-9-classification-search/events.jsonl.anchor`
- `.agent/devlines/v1-8-9-p0-legacy-consumer-gate-migration/RETROSPECTIVE.md`
- `.agent/devlines/v1-8-9-p0-legacy-consumer-gate-migration/context-pack.manifest.json`
- `.agent/devlines/v1-8-9-p0-legacy-consumer-gate-migration/context-pack.md`
- `.agent/devlines/v1-8-9-p0-legacy-consumer-gate-migration/events.jsonl`
- `.agent/devlines/v1-8-9-p0-legacy-consumer-gate-migration/events.jsonl.anchor`
- `.agent/devlines/v1-8-9-report-owner-factory/RETROSPECTIVE.md`
- `.agent/devlines/v1-8-9-report-owner-factory/context-pack.manifest.json`
- `.agent/devlines/v1-8-9-report-owner-factory/context-pack.md`
- `.agent/devlines/v1-8-9-report-owner-factory/events.jsonl`
- `.agent/devlines/v1-8-9-report-owner-factory/events.jsonl.anchor`
- `.codex/p0-report-owner-factory-event.json`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-objective.md`
- `docs/superpowers/objectives/2026-08-21-v1.8.9-classification-search-objective.md`
- `docs/superpowers/objectives/2026-08-21-v1.8.9-report-owner-factory-objective.md`
- `docs/superpowers/release-trains/v1.8.9/evidence/consumer-gap-event.json`
- `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-legacy-consumer-gate-migration.md`
- `findings.md`
- `progress.md`
- `task_plan.md`
