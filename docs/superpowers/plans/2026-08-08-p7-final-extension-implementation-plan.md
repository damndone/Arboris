# P7 最后一批统计扩展实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 P7 worktree 中实现非参数/稳健推断、GLM 扩展、模型诊断、空间统计、Matching 和 Synthetic Control 的独立内核，完成 Oracle 与安全验收后冻结 P7。

**Architecture:** 先新增一个极小的 P7 extension metadata contract，统一机器可读的 `scope`、`assumptions`、`limitations` 和 `not_claimed`。五个扩展领域随后拆成六个独立 pack（Matching 与 Synthetic Control 分开），各自拥有独立 contract、engine、tests 和 Oracle；不修改 Agent、CapabilityContract、OperationRegistry、orchestrator、frontend、survey 数学内核或既有 DID/IV/OLS/LMM runner。

**Tech Stack:** Python 3.11+、NumPy、pandas、SciPy、statsmodels、pytest；R 只用于测试 Oracle，不进入 runtime。

---

## 共享实施规则

每个任务遵循同一 TDD 顺序：

1. 创建一个最小红测，直接调用尚不存在的 contract/pack API；
2. 运行该测试并确认是“功能不存在/边界不满足”的预期失败；
3. 写最小 production code；
4. 运行 focused suite；
5. 运行外部 Oracle 和 adversarial tests；
6. 由 spec reviewer 审查，再由 quality reviewer 审查；
7. 只提交本任务 allowlist 文件。

所有 runtime 代码必须：

- 只接受 typed/封闭 operation 与 policy；
- 对 NaN/Inf、bool、字符串数值、重复列、规模、自由度和矩阵秩做显式校验；
- 将失败映射为稳定 reason code；
- 不返回原始行、原始矩阵或 replicate payload；
- 不执行 R、shell、eval、exec 或动态 import；
- 不自动选择模型或把诊断翻译成模型评级。

## Task 1: P7 extension metadata contract（顺序前置）

**Files:**

- Create: `backend/workbench/contracts/model/p7_extension.py`
- Create: `backend/workbench/engine/packs/p7_common.py`
- Test: `tests/test_p7_extension_metadata.py`

- [complete] Step 1: 写红测，要求 `P7ScopeMetadata.from_dict` 接受 `estimand`、`input_semantics`、`assumptions`、`limitations`、`not_claimed`、`unsupported_extensions`，拒绝 unknown key、空字符串、过长列表、非字符串成员、原始数据字段和路径/代码字段。
- [complete] Step 2: 运行 `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python -m pytest -q tests/test_p7_extension_metadata.py`，确认导入失败或 contract 尚不存在。
- [complete] Step 3: 实现 frozen dataclass、明确长度上限、JSON-safe `to_dict/from_dict` 和 `make_p7_scope` helper；`limitations` 与 `not_claimed` 不能为空的完成结果必须经过验证。
- [complete] Step 4: 测试 digest 绑定不会包含原始 rows/weights/matrix，只绑定 bounded result 和 scope。
- [complete] Step 5: focused suite 通过后提交 `feat(p7): add bounded extension scope metadata`。

## Task 2: 非参数/稳健推断 pack

**Files:**

- Create: `backend/workbench/contracts/model/nonparametric.py`
- Create: `backend/workbench/engine/packs/nonparametric/__init__.py`
- Create: `backend/workbench/engine/packs/nonparametric/common.py`
- Create: `backend/workbench/engine/packs/nonparametric/rank_tests.py`
- Create: `backend/workbench/engine/packs/nonparametric/robust.py`
- Create: `tests/test_nonparametric_contract.py`
- Create: `tests/test_nonparametric_pack.py`
- Create: `tests/test_nonparametric_oracle.py`
- Create: `tests/fixtures/nonparametric/generate_oracle.R`

- [complete] Step 1: 写 contract 红测，锁定 operation IDs：`nonparametric.mann_whitney`、`nonparametric.wilcoxon_signed_rank`、`nonparametric.kruskal_wallis`、`nonparametric.friedman`、`nonparametric.spearman`、`nonparametric.kendall`、`nonparametric.robust_summary`；exact/asymptotic/permutation 必须显式声明。
- [complete] Step 2: 运行 contract focused test，确认 operation 未声明、ties/zeros policy 缺失和非法 missing policy 失败。
- [complete] Step 3: 实现 finite numeric vector/table preparation、complete-case policy、bounded sample counts 和 stable errors；不接受字符串数值或隐式 drop。
- [complete] Step 4: 实现四类 rank tests，明确 exact 适用边界、tie correction、zero-difference policy、自由度和 effect size；不把 Kruskal/Friedman 显著性自动展开成 pairwise 结论。
- [complete] Step 5: 实现 Spearman/Kendall 与 median/MAD/trimmed/Winsorized summary；robust summary 只输出描述/区间证据。
- [complete] Step 6: 接入已有 resampling combiner 生成显式 bootstrap/permutation CI；不复制 replicate runner。
- [complete] Step 7: 用 base R `wilcox.test`、`kruskal.test`、`friedman.test`、`cor.test` 和直接公式 Oracle 验收；生成固定 fixture 与随机不变量测试。
- [complete] Step 8: focused suite、Oracle、adversarial、scope metadata 和安全扫描通过后提交 `feat(p7): add nonparametric and robust inference pack`。

## Task 3: GLM extensions pack

**Files:**

- Create: `backend/workbench/contracts/model/glm_extensions.py`
- Create: `backend/workbench/engine/packs/glm_extensions/__init__.py`
- Create: `backend/workbench/engine/packs/glm_extensions/common.py`
- Create: `backend/workbench/engine/packs/glm_extensions/zero_inflated.py`
- Create: `backend/workbench/engine/packs/glm_extensions/hurdle.py`
- Create: `backend/workbench/engine/packs/glm_extensions/beta.py`
- Create: `tests/test_glm_extensions_contract.py`
- Create: `tests/test_glm_extensions_pack.py`
- Create: `tests/test_glm_extensions_oracle.py`
- Create: `tests/fixtures/glm_extensions/generate_oracle.R`

- [complete] Step 1: 写 contract 红测，锁定 `glm.zero_inflated_poisson`、`glm.zero_inflated_negative_binomial`、`glm.hurdle_poisson`、`glm.hurdle_negative_binomial`、`glm.beta` 和明确的 count/link/zero-process policies。
- [complete] Step 2: 运行红测确认 zero-inflated、hurdle、beta contract 尚不存在；同时加入“Negative Binomial 本体不在新 pack 中”的防重复测试。
- [complete] Step 3: 实现 design matrix/outcome validation、intercept policy、offset policy、iteration cap、convergence status、non-finite coefficient rejection 和 output bound。
- [complete] Step 4: 用 statsmodels 的 zero-inflated estimators 实现 ZIP/ZINB；结果同时报告 count process、inflation process、conditional mean 和 zero probability 的语义。
- [complete] Step 5: 实现 Hurdle 两阶段估计：零/非零模型与正值截断 count model 分开保存；任一阶段失败即整体拒绝。
- [complete] Step 6: 实现 Beta regression，严格拒绝 `y <= 0` 或 `y >= 1`，不静默 squeeze 到开区间。
- [complete] Step 7: 用 R `pscl`/`glmmTMB`/`betareg`（存在时）和 statsmodels/direct likelihood fixture 做 Oracle；Oracle 不可用时不得把单一 Python 实现称为外部验证。
- [complete] Step 8: focused suite、收敛/分离/边界/adversarial 测试和安全扫描通过后提交 `feat(p7): add zero-inflated hurdle and beta glm pack`。

## Task 4: 独立模型诊断 pack

**Files:**

- Create: `backend/workbench/contracts/model/model_diagnostics.py`
- Create: `backend/workbench/engine/packs/model_diagnostics/__init__.py`
- Create: `backend/workbench/engine/packs/model_diagnostics/common.py`
- Create: `backend/workbench/engine/packs/model_diagnostics/heteroskedasticity.py`
- Create: `backend/workbench/engine/packs/model_diagnostics/serial.py`
- Create: `backend/workbench/engine/packs/model_diagnostics/influence.py`
- Create: `tests/test_model_diagnostics_contract.py`
- Create: `tests/test_model_diagnostics_pack.py`
- Create: `tests/test_model_diagnostics_oracle.py`
- Create: `tests/fixtures/model_diagnostics/generate_oracle.R`

- [complete] Step 1: 写 contract 红测，锁定 `diagnostics.vif`、`diagnostics.breusch_pagan`、`diagnostics.white`、`diagnostics.breusch_godfrey`、`diagnostics.reset`、`diagnostics.influence` 的输入/result shape 和 `not_claimed` 文本。
- [complete] Step 2: 运行红测确认 contract 缺失，并证明奇异 design、残差长度不匹配和不足自由度会拒绝。
- [complete] Step 3: 实现 design/response/residual preparation；公共 result 只返回 bounded statistics、df、p-value、condition evidence 和 scope，不返回 design rows。
- [complete] Step 4: 实现 VIF、BP/White、BG、RESET；每个 operation 独立计算，不共享“模型是否有效”的总判定。
- [complete] Step 5: 实现 Cook’s distance、leverage、DFBETAs，并设置高维输出上限与 deterministic truncation semantics。
- [complete] Step 6: 用 statsmodels diagnostic APIs、R `lmtest`/`car`（可用时）和 direct formula fixture 做 Oracle；验证每个诊断的统计量语义而非只比较 p 值。
- [complete] Step 7: focused suite、adversarial、scope metadata 和安全扫描通过后提交 `feat(p7): add standalone model diagnostics pack`。

## Task 5: 空间统计 pack

**Files:**

- Create: `backend/workbench/contracts/model/spatial_statistics.py`
- Create: `backend/workbench/engine/packs/spatial_statistics/__init__.py`
- Create: `backend/workbench/engine/packs/spatial_statistics/common.py`
- Create: `backend/workbench/engine/packs/spatial_statistics/weights.py`
- Create: `backend/workbench/engine/packs/spatial_statistics/autocorrelation.py`
- Create: `tests/test_spatial_statistics_contract.py`
- Create: `tests/test_spatial_statistics_pack.py`
- Create: `tests/test_spatial_statistics_oracle.py`
- Create: `tests/fixtures/spatial_statistics/generate_oracle.R`

- [complete] Step 1: 写 contract 红测，锁定 `spatial.moran_i`、`spatial.geary_c`、`spatial.getis_ord_g`，并要求 row-standardization、zero-neighbor、permutation policy 显式声明。
- [complete] Step 2: 运行红测确认非法重复边、负权重、非对称语义缺失、孤立节点未声明和矩阵规模越界失败。
- [complete] Step 3: 实现有界权重图输入（边列表或矩阵二选一但不可混用）、明确方向、row-standardized/binary policy、connected-component evidence 和 deterministic seed。
- [complete] Step 4: 实现 Moran’s I、Geary’s C、Getis–Ord global statistics；输出 observed statistic、expected/reference semantics、variance policy 和 scope。
- [complete] Step 5: 接入已有 permutation combiner，使用 plus-one p-value；不执行自动邻接矩阵学习，不返回原始权重矩阵。
- [complete] Step 6: 用 R `spdep`（可用时）和 direct formula Oracle 验收；固定图、孤立节点、非连通图和 row-standardization fixture 必须覆盖。
- [complete] Step 7: focused suite、adversarial、资源上限和安全扫描通过后提交 `feat(p7): add spatial autocorrelation pack`。

## Task 6: Matching pack

**Files:**

- Create: `backend/workbench/contracts/model/matching.py`
- Create: `backend/workbench/engine/packs/matching/__init__.py`
- Create: `backend/workbench/engine/packs/matching/common.py`
- Create: `backend/workbench/engine/packs/matching/propensity.py`
- Create: `backend/workbench/engine/packs/matching/balance.py`
- Create: `tests/test_matching_contract.py`
- Create: `tests/test_matching_pack.py`
- Create: `tests/test_matching_oracle.py`
- Create: `tests/fixtures/matching/generate_oracle.R`

- [complete] Step 1: 写 contract 红测，锁定 `matching.att` 与 `matching.balance`，要求 treatment/outcome/covariates、estimand、propensity policy、caliper、replacement、common-support 和 balance threshold 显式声明。
- [complete] Step 2: 运行红测确认缺少 treatment group、非二元 treatment、common support、极端 propensity 和重复 id 失败。
- [complete] Step 3: 实现 bounded propensity score fitting、deterministic nearest-neighbor matching、caliper/replacement policy 和 common-support filter；不自动改阈值。
- [complete] Step 4: 实现 SMD、variance ratio、matched counts、discarded counts 和 ATT/SE evidence；balance 不达标时保留诊断但不输出无条件因果结论。
- [complete] Step 5: 用 base R / MatchIt（可用时）和独立 nearest-neighbor reference Oracle 验收匹配索引、平衡统计量和 ATT；不只比较最终一位 p 值。
- [complete] Step 6: focused suite、隐藏混杂/无 overlap/极端权重/不可匹配数据的 adversarial 测试通过后提交 `feat(p7): add explicit propensity matching pack`。

## Task 7: Synthetic Control pack

**Files:**

- Create: `backend/workbench/contracts/model/synthetic_control.py`
- Create: `backend/workbench/engine/packs/synthetic_control/__init__.py`
- Create: `backend/workbench/engine/packs/synthetic_control/common.py`
- Create: `backend/workbench/engine/packs/synthetic_control/fit.py`
- Create: `backend/workbench/engine/packs/synthetic_control/placebo.py`
- Create: `tests/test_synthetic_control_contract.py`
- Create: `tests/test_synthetic_control_pack.py`
- Create: `tests/test_synthetic_control_oracle.py`
- Create: `tests/fixtures/synthetic_control/generate_oracle.R`

- [complete] Step 1: 写 contract 红测，锁定 `synthetic_control.fit` 与 `synthetic_control.placebo`，要求 treated unit、donor pool、pre/post periods、outcome matrix、weight constraints 和 placebo policy 显式声明。
- [complete] Step 2: 运行红测确认 donor pool 不足、pre-period 不可识别、时间重复/乱序、post period 缺失和约束冲突失败。
- [complete] Step 3: 实现 bounded simplex-constrained donor weight optimization，记录 objective、pre-fit RMSE、权重和、非零 donor 数以及 solver/convergence status。
- [complete] Step 4: 实现 post-treatment gap、cumulative gap 和显式 placebo re-fit；每次 placebo 都有 bounded count/seed，不把 placebo 排名自动变成显著性结论。
- [complete] Step 5: 用 direct quadratic-program reference、R Synth（可用时）和固定 DGP Oracle 验收 donor weights、pre-fit 与 gap；明确 R package 不可用时只能报告 direct reference，不得宣称 Synth Oracle。
- [complete] Step 6: focused suite、资源上限、权重约束、失败路径和 scope metadata 通过后提交 `feat(p7): add synthetic control evidence pack`。

## Task 8: 跨 pack 审查与冻结

**Files:**

- Modify: `task_plan.md`
- Modify: `progress.md`
- Modify: `findings.md`
- Create: `docs/superpowers/handoffs/2026-08-08-p7-freeze-handoff.md`
- Test/scan only: existing test and scripts; no Agent/frontend registration

- [complete] Step 1: 重新读取三份 planning files 和正式 Context Pack，核对实际改动只在 allowlist。
- [complete] Step 2: 运行五 pack focused suites、R/statsmodels/direct Oracle suites、既有 P7 regression、survey/MI/resampling regression。
- [complete] Step 3: 运行 protected-path comparison，必须确认 `backend/workbench/agent/**`、P0/P1/P2 seam、frontend、`backend/workbench/survey/**` 和既有 DID/IV/OLS/LMM 核心没有未授权改动。
- [complete] Step 4: 运行 runtime shell/R/eval/exec/import-path scan、`py_compile`、`git diff --check`、formal FMS verify。
- [complete] Step 5: 在 `p7-freeze-handoff.md` 写清每个 pack 的 scope、limitations、Oracle、已知未覆盖项、未来 P1/P2 adapter 入口和冻结理由。
- [complete] Step 6: 将 Stage 18 标记完成，并记录“后续新增算法必须另开扩展线；当前优先进入 P1/P2 接入”。
- [complete] Step 7: 只提交 P7 代码与冻结文档；不 merge、push、tag 或 release。

## 计划自审结论

- 设计中的五个 pack 都有独立任务和独立文件边界。
- 每个 production task 都先安排红测，再安排最小实现、Oracle、adversarial 和 review。
- 空间回归、Bayesian、自动模型选择、复杂 survey rank inference 和 Agent reachability 明确留在后续，不会被误报为本批完成。
- `Negative Binomial` 已存在，GLM 扩展任务明确禁止重复实现。
- P1/P2/Agent/前端路径没有出现在任何创建/修改文件列表中。

## 完成记录（2026-08-08）

- Task 1–7 的实际实现均已完成并合并为代码提交 `5df5686`；Task 8 的交接、事件流和冻结验证在同一工作线上完成。
- 代码布局按实际落地收敛为每个 pack 一个 runtime/pack 入口，未为不存在的“common/weights/propensity”文件制造空壳；typed contract 与 runtime 的 operation/政策边界保持不变。
- Matching 的实际 v1 距离几何是 `standardized_covariate_euclidean_v1`，不是名义上的 logit 距离；结果中同时报告 propensity support distance 与 match distance。未来若实现真正 propensity-distance matching，必须新增 typed policy、Oracle 和 target-population trimming 语义。
- Hurdle negative-binomial positive-process 的标准误是近似 BFGS inverse/normal approximation；Synthetic Control placebo 是描述性证据而非自动显著性检验；这些不是实现遗漏，而是冻结时的显式边界。
- 最终定向测试为 48（nonparametric/diagnostics）、44（GLM/spatial，1 optional skip）、51（Matching/Synthetic，2 optional skips）；base-R/direct-formula 与 statsmodels Oracles 均按可用环境执行并留痕。
- P7 已冻结。浏览器、Agent reachability、CapabilityContract/OperationRegistry 注册、P1/P2 adoption、full gate、merge、push、tag、release 不在本计划的完成声明内。
