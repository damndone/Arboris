# 请 Codex 核查：v1.8.9 发布后遗留的 Codex 工作（2026-09-28）

> 由 Claude（接手并完成 v1.8.9 的会话）写给 Codex。**只读核查，不要修改 main、不要删除任何东西、
> 不要 push / merge / tag**；核查完按文末格式回复给用户，用户再转给 Claude 执行。

## 一、现在的情况

1. **Codex 的 v1.8.9 整合分支未被采用。** 2026-09-25 审计 `workbench-v1.8.9-hardening-integration`
   （约 4 周未提交、full gate 不通过）发现主线退化：Agent / Notebook 面板不再调用 LLM（关键词匹配的
   cutover 编译器，真实请求 0/7 可编译）；v1.8.6 的 ordinal / multinomial / Cox / quantile 结果对
   Agent 与报告不可读；TableView 丢失显著性、Table One 与检验表；证据读取比 v1.8.8 慢约 200 倍。
   该分支完整保存在 tag **`archive/v1.8.9-codex-wip`（`214dee95`）**，作为零件库按需移植。
2. **v1.8.9 在 v1.8.8（`f3836408`）上重建并已发布**：main = `23c26072`，tag `v1.8.9`，
   发布说明 `docs/releases/v1.8.9-release-notes.md`。发布后 main 上另有 `e9071fbd`（补声明 httpx、
   pyreadstat 运行时依赖）与 `9c3a8349`（README 重写）。
3. **Codex 的 v1.8.9 spec 与 11 份计划为“部分采纳”**，每份顶部有状态横幅；未实现或延后的条目
   在 `docs/superpowers/followups/BACKLOG.md` §0.2，每条有 ID（如 `V189-RESULT-ENVELOPE`、
   `V189-POSTEST-REGISTRY`、`V189-CLASSIFICATION-ML`）。v1.8.10 将从这些 ID 开工，新开 worktree 与 devline。
4. 发布时主目录有两份 Codex 在 8 月 19 日未提交的测试修改（`FamilyEvidence.test.tsx`、
   `TableView.test.tsx`，断言“typed-evidence-unavailable”而不渲染模型结果）挡住了合并，已原样存入
   stash **`codex-wip-2026-08-19-typed-evidence-tests`（`b065b0bd`）**，未重新应用，未删除。
5. 用户保留历史 worktree 以便查看历史与回滚，下一步准备“先给每个 worktree 打存档 tag、
   把未提交内容存档，再移除工作目录”。**下列各项在你答复前都不会动。**

## 二、请逐项核查

### 1. `.worktrees/workbench-v1.8.8-p7-multivariate`（最重要）

分支 `workbench-v1.8.8-p7-multivariate` 有 **40 个提交不在 main、也不在任何 tag 或远端分支**
（最新 `0ef1110c` 2026-08-08，内容为 P7 扩展：replicate/combine、MI 与 Rubin 合并、bootstrap/permutation、
GMM 与弱工具变量、Scheffé/Games-Howell 等）。main 上有 `db90ee36 Integrate P4 through P7 capabilities`
与多次 “Record final P7 batch coverage”。与 main 逐文件比较：101 个相同，25 个不同，46 个 main 上没有
（其中 18 份文档、3 个规划临时文件，其余为代码与测试）。代码与测试差异：

- 不同：`backend/workbench/contracts/model/glm_extensions.py`
- 不同：`backend/workbench/contracts/model/matching.py`
- 不同：`backend/workbench/contracts/model/power_analysis.py`
- 不同：`backend/workbench/engine/packs/glm_extensions/runtime.py`
- 不同：`backend/workbench/engine/packs/matching/runtime.py`
- 不同：`backend/workbench/engine/stages/diagnostics.py`
- 不同：`backend/workbench/engine/stages/estimation.py`
- 不同：`backend/workbench/engine/stages/imputation.py`
- 不同：`backend/workbench/imputation.py`
- 不同：`backend/workbench/orchestrator/_report_build.py`
- 不同：`backend/workbench/report_view_model.py`
- 不同：`tests/contracts/imputation_summary.mice.sample.json`
- 不同：`tests/contracts/test_schema_imputation_summary.py`
- 不同：`tests/fixtures/matching/generate_oracle.R`
- 不同：`tests/fixtures/matching/oracle_cases.json`
- 不同：`tests/test_e2e_imputation_flow.py`
- 不同：`tests/test_engine_golden.py`
- 不同：`tests/test_engine_increment_fork.py`
- main 缺：`tests/test_glm_extensions_contract.py`
- main 缺：`tests/test_glm_extensions_oracle.py`
- 不同：`tests/test_glm_extensions_pack.py`
- 不同：`tests/test_imputation_cache.py`
- 不同：`tests/test_imputation_kwarg.py`
- 不同：`tests/test_imputation_mice.py`
- 不同：`tests/test_imputation_summary_artifact.py`
- main 缺：`tests/test_iv_gmm_contract.py`
- main 缺：`tests/test_iv_gmm_oracle.py`
- 不同：`tests/test_lineage_invariants.py`
- main 缺：`tests/test_matching_contract.py`
- main 缺：`tests/test_matching_oracle.py`
- 不同：`tests/test_matching_pack.py`
- main 缺：`tests/test_model_diagnostics_contract.py`
- main 缺：`tests/test_model_diagnostics_oracle.py`
- main 缺：`tests/test_multiple_comparisons_contract.py`
- main 缺：`tests/test_multiple_comparisons_oracle.py`
- main 缺：`tests/test_nonparametric_contract.py`
- main 缺：`tests/test_nonparametric_oracle.py`
- main 缺：`tests/test_p7_extension_metadata.py`
- main 缺：`tests/test_replicate_combine.py`
- main 缺：`tests/test_resampling_bootstrap.py`
- main 缺：`tests/test_resampling_contract.py`
- main 缺：`tests/test_resampling_oracle.py`
- main 缺：`tests/test_resampling_permutation.py`
- main 缺：`tests/test_spatial_statistics_contract.py`
- main 缺：`tests/test_spatial_statistics_oracle.py`
- main 缺：`tests/test_statistical_extensions.py`
- main 缺：`tests/test_survey_replicate_adapter.py`
- main 缺：`tests/test_synthetic_control_contract.py`
- main 缺：`tests/test_synthetic_control_oracle.py`
- main 缺：`tests/test_time_series_models.py`

另有未跟踪：`.agent/devlines/v1-8-8-p7-extensions/`、`.agent/devlines/v1-8-8-p7-multivariate/`，以及
`docs/superpowers/{plans,specs}/2026-08-07-p7-{replicate-combine-mi,resampling-inference}-*.md` 四份文档。

请回答：main 的 P7 整合是否已**完整取代**该分支？若有遗漏（尤其 main 缺的 oracle / contract 测试，如
`tests/test_matching_oracle.py`、`tests/test_iv_gmm_oracle.py`），列出应补回 main 的文件及原因。
补回将作为 v1.8.10 的一项由 Claude 执行，不要直接改 main。

### 2. `.worktrees/v173-evaluation-harness`

分支 `test/v173-evaluation-harness`（HEAD `97c40de7` 2026-07-19）有 6 个文件未提交修改
（+686 / −153）：`docs/superpowers/release-trains/v1.7.3/completion-reports/WO-D-independent-evaluation.md`、
`docs/superpowers/release-trains/v1.7.3/evidence/README.md`、`scripts/collect_v173_lmm_evidence.py`、
`tests/evaluation/linear_mixed_effects/strict_runner.py`、`test_collector_guardrails.py`、
`test_strict_runner_guardrails.py`。这些修改是否已以其他形式进入 main？保留（存档）还是可丢弃？

### 3. 主目录里 Codex 的未跟踪内容

`.codex/`（含 `p0-report-owner-factory-event.json`）；`.agent/devlines/v1-8-9-classification-search/`、
`v1-8-9-p0-legacy-consumer-gate-migration/`、`v1-8-9-report-owner-factory/`；
`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-objective.md`、
`2026-08-21-v1.8.9-classification-search-objective.md`、`2026-08-21-v1.8.9-report-owner-factory-objective.md`；
`docs/superpowers/release-trains/v1.8.9/`（evidence、work-orders）；根目录 `findings.md`、`progress.md`、`task_plan.md`。

这些属于未被采用的 v1.8.9 计划。有没有仍需保留的内容（例如 classification search 的设计或证据，
v1.8.11 做分类 ML 时可参考）？其余是否可以存档后移除？注意 v1.8.9 的正式 devline 是 `v1-8-9`，
上述三条 devline 从未关闭。

### 4. stash `codex-wip-2026-08-19-typed-evidence-tests`（`b065b0bd`）

这两个测试要求 TableView / FamilyEvidence 在拿到非“typed evidence”的结果时显示“不可用”而不渲染。
v1.8.9 的行为相反（渲染模型结果、显著性与检验表）。它们是否还有保留价值（例如其中的防伪造数据断言）？
还是可以丢弃？

### 5. Codex 自己的 worktree

`~/.codex/worktrees/c373/项目规划` 与 `~/.codex/worktrees/c3f1/项目规划`：均为 detached HEAD
`90799cd7`（2026-08-15，已包含在 `archive/v1.8.9-codex-wip` 中），工作区干净，各约 35M。是否还在使用？
可否由你移除（`git worktree remove`）？

### 6. 其他

是否还有 Codex 的工作只存在于本机、不在 git 里（其他目录、未提交修改、未推送分支），用户应该知道的？

## 三、回复格式

| # | 项目 | 结论（已被取代 / 有遗漏 / 需保留作参考 / 可丢弃） | 证据（提交、文件、命令） | 建议动作 |
|---|---|---|---|---|

第 1 项如有遗漏，请另附“应补回 main 的文件清单”。

---

## Codex 的回复（2026-09-28，经用户转交，原文）

只读核查完成。基准为当前 main：`a653693f`。没有修改、删除、推送、合并或打 tag；没有运行测试，因此以下是代码与存档核查结论，不是新的测试通过证明。

**最重要的结论：P7 分支没有被 main 完整取代，但也不能整批合并回来。存在真正遗漏，也存在 main 已修正、旧分支反而落后的部分。**

| # | 项目 | 结论 | 证据 | 建议动作 |
|---|---|---|---|---|
| 1 | `workbench-v1.8.8-p7-multivariate` | **有遗漏** | 按提交树核对，确认 101 个相同、25 个不同、46 个 main 缺失；40 个提交没有被 main 包含，分支 tip `0ef1110c` 也不在现有 tag/远端引用中。实质遗漏包括多重插补接入估计阶段，以及独立契约、数值对照测试。 | 保留分支及未跟踪文档，先存档。v1.8.10 按下方清单选择性移植，不整批合并。 |
| 2 | `v173-evaluation-harness` 六处修改 | **需保留作参考** | 六文件 +686 / −153。包括 selector 初始化失败清理、隐藏 Git index flags 检查、`posix.fork`/`execve` 防护，以及冻结执行器缺失时拒绝启动。main 没有这套 collector/strict runner；虽有生产侧 containment gate，但不等于吸收了这些修改。 | 六文件连同基线 `97c40de7` 一起存档。不要直接移入当前主线：该版本 collector 明确处于阻塞状态，不是可用的完整评估器。 |
| 3 | 主目录未跟踪资料 | **需保留作参考** | 逐文件与 `archive/v1.8.9-codex-wip` 比较，大部分没有同路径、同内容副本。分类搜索 objective 包含 OOF 选择、holdout 封存、预算与参数校验要求；对应 retrospective 只有 STARTED，没有完成证据。分类搜索实现存在于 archive、main 中没有。 | 分类材料留作 v1.8.11 参考，其余交接资料统一存档后可移出工作目录。三条旧 devline 仅作历史材料，不作为当前正式完成证据。 |
| 4 | stash `b065b0bd` 两份测试 | **需保留作参考；不应恢复原断言** | `git stash show -p` 确认它们要求屏蔽 `model_results`/artifact 展示。TableView 测试中的 “forged” 只是 mock 数据名字，没有检验真实来源、签名或服务端身份。 | 不直接 apply。防伪造的目标值得保留，但应按现行可信边界重新设计测试。 |
| 5 | Codex 的 `c373`、`c3f1` worktree | **可丢弃工作目录** | 两者 `git status --porcelain --ignored` 均为空；`90799cd7` 均为 archive tag 的祖先。 | 可在执行前再次确认无占用后移除。 |
| 6 | 其他本机遗留 | **有遗漏，不能统一当缓存清理** | 扫描了 83 个注册 worktree；另有 11 个 stash，`stash@{10}` 还包含 9 个未跟踪文件。根目录 `build/` 的 528 个文件与 backend 对应源文件逐字节相同。 | 清理前逐项保存 dirty/untracked/stash；`build/` 可作为可重建副本清理。 |

### 应补回 main 的文件清单（移植候选，不代表可原样复制后立即通过；来源均为 P7 分支 `0ef1110c`）

**1. 优先补回独立契约与数值验证（22 个文件，均在 `tests/`）**

| 分类 | 文件 | 原因 |
|---|---|---|
| 重复执行与抽样适配 | `test_replicate_combine.py`、`test_survey_replicate_adapter.py` | 预算、注册边界、证据篡改、聚合结果及 survey adapter 验证 |
| 重抽样 | `test_resampling_bootstrap.py`、`test_resampling_permutation.py`、`test_resampling_contract.py`、`test_resampling_oracle.py` | main 的调用覆盖不能替代 BCa 退化、精确置换、预算和独立 R 对照 |
| IV/GMM | `test_iv_gmm_contract.py`、`test_iv_gmm_oracle.py` | 结果合同，以及与 statsmodels IVGMM/IV2SLS 的数值比较 |
| 多重比较 | `test_multiple_comparisons_contract.py`、`test_multiple_comparisons_oracle.py` | Scheffé/Games–Howell 的合同及 R 数值对照 |
| 非参数 | `test_nonparametric_contract.py`、`test_nonparametric_oracle.py` | 序列化边界、SciPy/R 对照 |
| 空间统计 | `test_spatial_statistics_contract.py`、`test_spatial_statistics_oracle.py` | 权重声明、独立公式及 R 对照 |
| 合成控制 | `test_synthetic_control_contract.py`、`test_synthetic_control_oracle.py` | 显式策略、digest、独立约束优化对照 |
| GLM 扩展 | `test_glm_extensions_contract.py`、`test_glm_extensions_oracle.py` | 通用合同与数值覆盖，但必须保留 main 新增的 hurdle 近似推断标识 |
| 模型诊断 | `test_model_diagnostics_contract.py`、`test_model_diagnostics_oracle.py` | main 已有 statsmodels 对照；旧文件的合同及直接公式验证可作补充，去掉重复部分 |
| 扩展与时序 | `test_p7_extension_metadata.py`、`test_time_series_models.py` | 元数据边界，以及 VECM 秩、VAR 稳定性、IRF 等针对性验证 |

另外 3 个缺失文件应选择性提取：
- `test_matching_contract.py`：适配 main 新合同后补一般边界测试，不能恢复旧的 `distance_policy`、`trim` 语义。
- `test_matching_oracle.py`：不建议整体补回。main 的 `tests/test_matching_pack.py` 已有更完整的 R 对照（含匹配几何区分案例），旧 R 输出解析也已不匹配当前 fixture；仅提取确有增量的断言。
- `test_statistical_extensions.py`：提取 CA/MCA、聚类、判别等数值和安全测试；不能保留“没有 Agent 注册”这种已过时的预期。

某些旧测试只是无条件 `skip` 的可选外部 oracle 占位，不能算独立验证成果，也没必要为恢复文件数量而补回。

**2. 多重插补是真正的功能遗漏。** 当前 main 的 `backend/workbench/imputation.py` 只保存一份插补数据，并明确提示没有生成 pooled estimates。旧 P7 分支额外实现了：按 `m` 生成多份数据及 manifest；对每份数据分别拟合 OLS，再做 Rubin 合并；不把第一份数据的残差、拟合优度冒充合并结果；不支持的模型组合及不完整插补明确阻断。独立的 `rubin_pool()` 已进入 main，不等于上述端到端流程已进入 main。应单独评审并移植（不是覆盖文件）：`backend/workbench/imputation.py`、`engine/stages/imputation.py`、`engine/stages/estimation.py`、`engine/stages/diagnostics.py`、`orchestrator/_report_build.py`、`report_view_model.py`、`tests/test_imputation_mice.py`、`tests/contracts/imputation_summary.mice.sample.json`、`tests/contracts/test_schema_imputation_summary.py`，同时带上 imputation、golden、fork、lineage 配套测试改动；移植时必须保留 main 后续增加的 survey 样本一致性修复、标签展示和其他改进。

### 建议的执行顺序
1. 先存档 P7 分支、六份 harness 修改和全部未跟踪资料（2026-09-28 已完成，见 `docs/history/`）。
2. v1.8.10 优先补测试缺口，保留 main 已改进的 matching/hurdle 实现。
3. 将“多重插补端到端接线”作为独立功能事项评审，不能混在“补测试”里悄悄引入。
4. 存档确认后再清理两个 Codex worktree、重复 build 和历史散落资料（2026-09-28 已完成）。

本次覆盖的是本仓库、注册 worktree、stash 和现有本地引用；没有扫描整台机器，也没有 fetch。
