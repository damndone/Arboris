# docs/superpowers — 文档地图与生命周期约定

> 目的:这几类文档生命周期不同,混在一起会烂账。本文件定义约定,新对话/收尾时照此维护。
> 2026-07-15 修订:补上 specs/plans/根目录会话文件的定位(此前缺失,导致"不知道看哪")。

## 🧭 看这里(人类 owner 只需要这 3 个)

| 想知道什么 | 看哪个 |
|---|---|
| **产品方向、下个版本做什么** | `roadmap/2026-07-01-unified-graph-workbench-roadmap.md`(北极星)+ 同目录其他方向文档 |
| **还欠什么债 / 开放问题** | `followups/BACKLOG.md`(唯一滚动清单,§1 一处看全) |
| **现在做到哪、新会话怎么接手** | `handoffs/` 里唯一的最新一份 |

其余全部是 agent 的工作产物或已冻结历史,不需要主动读。

## 全部七类(给维护者)

| 位置 | 是什么 | 给谁看 | 生命周期 | 维护规则 |
|---|---|---|---|---|
| `roadmap/` | 长期产品/技术方向 + `architecture-debt.md` 架构债台账 | **人** | 长活 | 就地更新,不归档 |
| `followups/BACKLOG.md` | **唯一** live 滚动欠账清单(2026-07-15 定名,不再随版本改名) | **人** | 长活滚动 | 做完就删(git 留痕);版本收尾时复制快照进 `archive/followups/`,本体继续滚 |
| `handoffs/` | 会话交接快照(现状+下一步+恢复协议) | **人+agent** | 最新即权威 | **只留最新一份**,旧的移 `archive/handoff/` |
| `specs/` | 每个 feature 一份设计文档(做什么/为什么/契约) | agent(实现者) | 写完即历史 | 只留**当前未发版**版本的;发版收尾移 `archive/specs/` |
| `plans/` | 对应 spec 的任务清单(TDD 勾选框) | agent(实现者) | 写完即历史 | 同上,发版收尾移 `archive/plans/` |
| 仓库根 `task_plan.md` / `findings.md` / `progress.md` | 当前开发线的会话草稿(计划/发现/流水账),跨会话恢复用 | agent | 随开发线 | 不是正式文档;开发线收尾**整份冻结进 `archive/session-scratch/`**(命名 `<日期>-<版本>-<原名>.md`),根目录不留过期草稿 |
| `archive/` | 已冻结历史(handoff/followups/specs/plans/复盘) | 考古 | immutable | 只读留痕,不再维护 |

## 核心约定

1. **只有"带开放状态"的文档需要维护**:handoff(只留最新)和 BACKLOG(做完就删)。
   specs/plans/progress 是一次性写完的历史,不需要读也不需要清,只在版本收尾时批量归档。
2. **开着的债只放一个地方** = `followups/BACKLOG.md`。§1 是跨文档扁平总索引
   (架构债/roadmap 主线只放 pointer 行,正文在各自文档就地更新)。
   做完就删,git 历史留痕,不靠 `[x]` 勾(实践证明没人回去勾)。
3. **worktree 一律共用主 checkout 的依赖,不得自己安装**(2026-07-22 定,机器强制)。

   新建 worktree 后**第一件事**:
   ```
   bash scripts/link-shared-deps.sh <worktree路径>
   ```
   它把 `.venv` 和 `frontend/node_modules` 建成指向主 checkout 的符号链接。
   **不要在 worktree 里跑 `npm install`。**

   - **强制点**:`scripts/gate.sh` 的 preflight 会检查。worktree 里若有*实体*
     `frontend/node_modules`,gate 直接 `exit 3` 并给出可复制的修复命令;
     没有链接则只提示不拦。主 checkout 自身豁免(它持有权威副本)。
     契约测试见 `tests/test_gate_script.py`。
   - **只管 `node_modules`,不管 `.venv`**:gate 支持 worktree 自带 venv
     (解析顺序 `WORKBENCH_PYTHON` → 本地 `.venv` → 主 checkout `.venv`),
     那是受支持的配置;而且实测浪费的从来只有 `node_modules`。
   - **依赖漂移**:某版本新增了包,**在主 checkout 装一次**即可,所有 worktree
     因共享自动生效。不要为此在 worktree 里单独装。
   - **为什么定这条**:曾有三个 worktree 各自 `npm install`,每个 137–159 MB,
     合计 **431 MB 逐字节重复**(三者 `package-lock.json` 与主 checkout 同一 hash,
     一份都没多买到东西),而当时磁盘只剩 8.8 GB。脚本 v1.6.6 就有了,
     但没有强制点,所以没人被拦住。

4. **版本收尾仪式**(发版 merge+tag 后,一次做完):
   - 本版 spec/plan → `archive/specs/`、`archive/plans/`;
   - 旧 handoff → `archive/handoff/`,新 handoff 成为唯一 live;
   - BACKLOG:清掉本版做完的项(§3 留一行痕),复制快照进 `archive/followups/`;
   - 根目录会话草稿 → `archive/session-scratch/`;
   - **删掉已合并的分支**(本地+远端),见下条 §5 的 tag 规矩;
   - 检查 `docs/superpowers/` 顶层没有裸放文件(除本 README)。

5. **分支合并后即删,但先用 tag 保住名字**(2026-07-22 定)。

   合并进 main 的分支一律删除(本地和远端),否则分支列表会涨到没人看得懂——
   曾一次性积到 42 条已合并分支。删之前**必须**给分支尖端打 tag:
   ```
   git tag -a archive/branch-tip/<名字> <分支> -m "..."
   git push origin <tag>        # 确认远端有了,再删分支
   ```
   - **为什么不能只靠版本 tag**:`v1.6.11` 这类发版 tag 指向的是 main 上的
     **merge commit**,不是分支尖端。"有同名 tag"≠"尖端被覆盖"。实测 34 条版本
     分支里,只有 8 条的尖端恰好被某个 tag 指到。判断标准只有一个:
     `git tag --points-at <分支>` 非空。
   - **只存在于本机的分支**(远端没有、也不在 main 里)同样用 tag 备份,
     命名 `archive/local-only/<名字>`。这类分支磁盘一坏就没了。
     自检:`git rev-list --count <分支> --not --remotes --tags` 必须为 0。
   - 未合并的分支不要动。
6. **新建文档前先问**:是不是该写进已有的七类之一?顶层裸放和自创目录是烂账的开始。
7. **`docs/` 顶层(superpowers 之外)的归属**(2026-07-15 整理定版):
   - `docs/releases/` = 各版 release notes,发版时写一份进这里,write-once 历史;
   - `docs/architecture/` = 长活技术参考(含被 estimator 源码注释引用的 `v1.5.8/v1.5.9/v1.6.0-IMPL-NOTES.md`
     实现配方——**是活参考不是历史,移动必须同步改代码注释里的路径**);
   - `docs/api-contracts/`、`docs/*-howto.md`、`docs/dev-browser-smoke.md`、`docs/extensions.md` = 活文档,就地更新;
   - `docs/` 顶层不再裸放版本号文件;release notes 之外的版本产物一律走 superpowers 七类。

> 反面教材(2026-07-08 与 2026-07-15 两次整理前的状态):根目录躺着 v1.5.4.3 的 HANDOFF、
> superpowers 顶层裸放两份 HANDOFF、plans/ 混进 progress 文件、五份 followups 各自 14+ 个
> 没人勾的 checkbox、specs/plans 积了 47 份跨 15 个版本的历史无人能辨认哪份现役。
