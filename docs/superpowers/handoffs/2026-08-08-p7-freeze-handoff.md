# P7 最终扩展冻结交接书

## 交接结论

P7 的最后一批独立统计内核已经完成并冻结：五个扩展领域、六个 pack——非参数/稳健推断、GLM 扩展、模型诊断、全局空间统计、Matching、Synthetic Control。代码提交为 `5df5686`：

`feat(p7): add final standalone statistical extension packs`

本交接书只证明 P7 内核层已完成定向实现、契约、Oracle 和边界留痕；它不证明 Agent 已经能发现/调用这些能力，也不证明前端、浏览器、P1/P2 接入或发布已经完成。

## 工作边界与安全结论

- 工作目录：`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.8-p7-multivariate`
- 分支：`workbench-v1.8.8-p7-multivariate`
- 保护范围：Claude 的 Agent/P0/P1/P2、CapabilityContract、OperationRegistry、orchestrator seam、frontend、`backend/workbench/survey/**` 数学内核、既有 DID/IV/OLS/LMM runner 均未修改。
- 运行时不执行 R、shell、`eval`、`exec` 或动态 import；不接收任意公式字符串、callback、文件路径或 Agent 生成代码。
- 所有结果都包含机器可读的 `scope`、`assumptions`、`limitations`、`not_claimed`、`unsupported_extensions`；原始行、原始矩阵、原始权重和 replicate payload 不进入公共结果。
- 没有 merge、push、tag 或 release。与 Claude 的对接必须在 P1/P2 接口层完成，不要把这些 pack 直接注册进本冻结线。

## 已交付 operation

### 1. 非参数 / 稳健推断

- `nonparametric.mann_whitney`
- `nonparametric.wilcoxon_signed_rank`
- `nonparametric.kruskal_wallis`
- `nonparametric.friedman`
- `nonparametric.spearman`
- `nonparametric.kendall`
- `nonparametric.robust_summary`

边界：exact/asymptotic/permutation、缺失、ties、zero-difference 和随机种子均由请求明确指定；稳健 summary 是 median/MAD/trimmed/Winsorized 等描述证据，不是结构模型估计量。秩检验不自动等同于均值检验，Kruskal/Friedman 也不自动生成 pairwise 结论；复杂 survey rank variance 和自动 post-hoc 不在本版。

### 2. GLM 扩展

- `glm.zero_inflated_poisson`
- `glm.zero_inflated_negative_binomial`
- `glm.hurdle_poisson`
- `glm.hurdle_negative_binomial`
- `glm.beta`

边界：零过程、count process、positive process、均值和 precision 是不同 estimand；Beta 响应严格要求 `(0,1)`，不会静默 squeeze 边界值；不会根据零比例自动选择 zero-inflated 或 hurdle。公式、随机效应、自动模型比较、unsafe linear predictor、分离和不收敛均拒绝。Hurdle negative-binomial positive process 的标准误是近似 BFGS inverse/normal approximation，后续报告层必须保留这个标签，不能包装成一般 sandwich 推断。

### 3. 独立模型诊断

- `diagnostics.vif`
- `diagnostics.breusch_pagan`
- `diagnostics.white`
- `diagnostics.breusch_godfrey`
- `diagnostics.reset`
- `diagnostics.influence`

边界：当前是显式 OLS-shaped typed request；只返回每个诊断自己的 statistic/df/p-value/影响证据，不返回 `model_valid` 总判定。高维设计、cluster/survey covariance、非线性模型和 post-selection inference 需要新 contract。Agent 接入必须使用 typed `run_model_diagnostics(request)`；raw operation string 入口会 fail closed。

### 4. 全局空间统计

- `spatial.moran_i`
- `spatial.geary_c`
- `spatial.getis_ord_g`

边界：只做显式图/权重下的全局统计量和 seeded permutation inference；row normalization、对称性、零对角、孤立点、负权重、连通分量和 permutation policy 都显式记录。它描述的是给定图下的空间聚集/离散证据，不是因果效应或空间回归系数。空间 lag/error regression、local Moran/hotspot、学习邻接矩阵均未做。

### 5. Matching

- `matching.att`
- `matching.balance`

关键限制必须原样保留：v1 的 `distance_policy="logit"` 控制 propensity 拟合和支持域报告，但实际 nearest-neighbour 配对几何是 `standardized_covariate_euclidean_v1`。结果同时写出 `support_distance` 和 `match_distance`，不能把它误报成真正的 propensity-score distance matching。

`common_support_policy="trim"` 在 v1 是显式声明的边界政策，不代表可以静默删行；不相交支持域会拒绝，尚未实现带 target-population estimand 的真正 trim。未来若扩展，必须新增独立的 distance geometry policy、`trim_applied`/目标人群语义、Oracle 和回归测试。当前也不提供 ATE、weighting、full matching、Mahalanobis 或自动方法选择；ATT 仍是识别假设下的证据，不是无条件因果事实。

### 6. Synthetic Control

- `synthetic_control.fit`
- `synthetic_control.placebo`

边界：显式 donor pool、排序后的时间、pre/post 分界、非负 simplex 权重、pre-fit RMSE、post gap 和有界 placebo refit。v1 拒绝 `predictor_matrix`，不偷偷改用另一种输入；不做 augmented SCM、ridge/elastic-net 权重、自动 donor 选择、interference 调整，也不输出 placebo 显著性 p 值。Placebo 排名只是描述性 evidence，不能自动变成“显著”。

## 数值验收

- nonparametric + diagnostics：48 passed。
- GLM + spatial：44 passed，1 个可选 `spdep` skip。
- Matching + Synthetic Control：51 passed，2 个可选包 skip（`MatchIt`、`Synth`/`quadprog`）。
- Base-R/direct-formula Oracle：非参数、空间、Matching、Synthetic Control 已执行并通过。
- statsmodels Oracle：GLM、模型诊断已执行并通过。
- 可选 R 包未安装不是正确性证据；skip 被明确留痕，没有被当作通过。
- `py_compile`、`git diff --check`、运行时安全扫描和 protected-path comparison 作为冻结验收的一部分执行；正式事件流通过 `scripts/devline_control.py` 维护。

## 给后续 P1/P2/Agent 的对接方式

1. P1 先为每个 operation 建 CapabilityContract/adapter：输入字段、列语义、缺失策略、资源上限、结果 projection 和允许的失败 reason 必须来自各自 typed contract；不要让 Agent 直接拼 runtime kwargs。
2. Agent 自然语言只负责生成候选 typed request 和解释性 proposal；模型选择、distance geometry、spatial weights、zero-process/hurdle 语义、exact/permutation 和 causal estimand 都必须显式展示并经过确认。
3. P0 负责把数据版本、列来源、依赖和 fingerprint 接到请求；P2 负责 reachability、豁免/缺口检查和 stale 拒绝。P7 不应反过来修改 P0/P1/P2 seam。
4. 执行后报告层只消费 bounded result 和 scope metadata；尤其不要把 Matching 的 ATT、Synthetic Control 的 gap、诊断 p 值或空间聚集统计自动写成无条件结论。
5. 后续接入必须增加 capability-level tests、proposal/confirmation/audit tests、browser/E2E tests 和真实数据 Oracle；当前这些 reachability/browser/E2E 证据均为 `NOT VERIFIED`。

## P7 冻结后的下一步

P7 到达边界：继续增加新统计家族的边际收益已经低于把现有能力接入 P1/P2、Agent、报告和浏览器。下一步应是 Claude 完成 P0/P1/P2 对接，再以本交接书的 operation/限制为输入做 capability admission、自然语言 proposal、确认、执行、证据和端到端验收。

以下事项明确留给新的批准扩展线，而不是继续堆入 P7：真正 propensity-distance matching 与 target-population trimming、复杂 survey rank/causal variance、augmented/regularized SCM、空间回归与局部热点、Bayesian/automatic model selection、GLM 随机效应、非参数多重比较扩展，以及任何新的统计家族。

未授权事项：本线不 merge、不 push、不 tag、不 release；full gate、Agent reachability、浏览器验收和真机自然语言工作流均不在本次完成声明内。
