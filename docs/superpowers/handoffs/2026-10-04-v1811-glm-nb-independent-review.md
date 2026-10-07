# GLM-NB 最终原生参考独立对抗复审

结论：**REQUEST CHANGES**。统计参考与冻结接口通过；公开参考资产保护有一项 P2 阻塞。审查只针对候选 `64ec3d73121c7d8e792942e62d30d0b92c9d8907`，代码/参考提交 `b2f7adec0e1503e11e9b0b7da564a1bfdc1157e1`，统一基线 `01fb0752bce129c8d8848c021eca776dadccb515`。后续审查报告提交仅新增独立证据，不是新的功能 baseline，也不代表已合入或已准入。

## P2：拟公开的原生日志包含本地许可证身份

新增并 tracked 的以下资产包含 `Serial number` 与 `Licensed to` header。报告、测试失败输出与新审查提交均不展示字段值。

| 文件（相对仓库根） | 行号 |
|---|---|
| `tests/fixtures/postestimation/glm_negative_binomial_v1811/native-output.txt` | 185–186 |
| `tests/fixtures/postestimation/glm_negative_binomial_v1811/native-stata/oracle.log` | 14–15 |
| `tests/fixtures/postestimation/glm_negative_binomial_v1811/native-stata-v2/oracle.log` | 14–15 |
| `tests/fixtures/postestimation/glm_negative_binomial_v1811/native-stata-v3/oracle.log` | 14–15 |

独立扫描只读取 `manifest.json` 中的既有资产，输出文件、行号和字段存在性。`tests/eval_v1811/glm_nb_review_public_guard_test.py` 在最终候选上 **1 failed**，精确定位上述 8 处；证据为 `glm_nb_review_public_locations.json` 与 `glm_nb_review_public_guard_final_red.txt`。此 header 与统计复现无关，加入公共参考会随源码传播本地许可证序列号及注册身份。

建议 producer 将完整原始日志原样保存在 ignored local 证据目录并绑定 SHA-256，在新提交中仅脱敏既有新资产的许可证 header，保留版本、原生命令、自身 do-file 输出、失败尝试与所有数值，更新对应 manifest。不要删除原始文件、重写历史、重跑改变数字或修改旧参考。审查者未自行修复任何生产或作者资产。

## 冻结合规与自然来源

审查起始工作树 clean，HEAD 精确匹配候选。统一基线到候选共 26 个新增路径，没有修改任何基线已有文件；24 个作者 manifest 资产 hash 全部吻合，9 个保护路径逐字节对照 `git show <baseline>:<path>` 均一致，包括公开 CSV、旧 oracle、旧 generator、模型 runner、推断核心、后估计与冻结文档。完整列表见 `glm_nb_review_protected.json`。

数据是仓库原有公开合成样本，原生成器固定 seed `20261002`、300 行；没有读取用户 Downloads 或 VIX 数据。输入 SHA-256 为 `2e1b92f07632a8c88d047074f77cd6e5f9552b4f932f7d6ed2499161a0bf3084`，独立原生与 owner 执行前后不变。生成 DGP 使用 size=2，不意味着此次拟合必须估计其 alpha：冻结任务明确验证**显式固定 alpha=1** 的 log GLM，不能把这组结果解释为估计 alpha 的 `nbreg` 对照。

## 独立真实原生与 owner 证据

新脚本 `glm_nb_review_native.R` 与 `glm_nb_review_capture.py` 没有调用作者 capture/test helper，也没有复制 expected 生成新参考。共享独占 runner 下重新执行本机真实 R、Stata 和两个真实持久化 Workbench 工作流。R 原生调用 MASS GLM、car Wald/delta、lmtest LR、marginaleffects average/means；Stata 原生调用固定 alpha GLM ML、EIM、scale(1)、test、lincom、nlcom、lrtest 和 margins，并保留完整 4×4 covariance。新结果有 50 个 Stata 原生字段，full/restricted owner 均 completed。

| 独立复验量 | 结果 |
|---|---:|
| owner/R 最大系数误差 | `5.46229728115577e-14` |
| owner/Stata 最大系数误差 | `5.484501741648273e-14` |
| owner/R 最大 SE 误差 | `4.718447854656915e-16` |
| R/Stata 完整 covariance 最大误差 | `1.214306433183765e-16` |
| owner/R 完整 covariance 最大误差 | `1.5612511283791264e-16` |
| R full / restricted 最大 score | `3.80330328485002e-14` / `7.39408534400354e-14` |
| 独立直接似然优化最终最大 score | `1.06874165347262e-13` |

新 Stata 34 个对应字段复现作者已保留的最终 reference；新 R 重现作者系数、完整 covariance、五类最终量与两种 margins。独立解析 log-link 梯度另行核验 margins 的 estimate/SE，native 数值微分误差最大约 `1.5e-9`，没有照抄 expected。

收敛敏感性单独从 epsilon `1e-8`、`1e-12`、`1e-14`、`1e-16` 拟合，最大 score 分别为 `6.85502306329048e-4`、`6.15955420589426e-6`、`5.87748355815409e-7`、`3.80330328485002e-14`。宽松 deviance stopping 确实遗留大于冻结系数 `1e-8` 门槛的差异。另从零起点直接 BFGS 优化固定-alpha 原始 NB 似然，再使用解析 observed Hessian Newton 求根，beta 与最终 IRLS 在 `1e-12` 内一致、LL 在 `1e-12` 内一致。因此 epsilon 收紧有独立最优条件与优化路径支持。

scale=1 指传入推断的**未乘 Pearson dispersion 的最终 EIM inverse**：`(X' diag(mu/(1+mu)) X)^-1`。MASS family 的默认 `summary(glm)$dispersion` 实际约 `0.748143288211742`，不能直接把其默认 summary covariance 当成本次 scale=1 参考。作者显式构造 final EIM inverse 并交给 car/marginaleffects；独立解析矩阵、真实 Stata `scale(1) vce(eim)` 全块与 owner 均吻合。这里没有通过估计或调整 scale 去贴合数字。

独立 8 个统计/合规断言加作者 10 个相关回归：**18 passed，3 个既有 BIC FutureWarning，3.90s**。系数 abs `1e-8`、SE abs `1e-6`；后估计量 rel `1e-6`、p rel `1e-5`、margins estimate rel `1e-6`/SE rel `1e-5`。独立断言对 p 采用零 absolute floor，没有靠 pytest 默认绝对容差放过微小 p 值。未改变样本、统计默认或作者/旧测试容差。

## LR 解释边界与验收边界

本次 LR 的 full `ynb~x1+x2+x3` 与 restricted `ynb~x1` 均在同一 300 行上、相同显式 alpha=1、log link 与 scale=1 的 NB likelihood 下最大化，仅移除 x2/x3 两个回归参数；因此 df=2，LR 约 `20.922503611121101`，p 约 `2.8624378573147229e-5`。这不是 alpha=0 的过度离散边界检验，也不是估计 alpha 后的 NB2 LR 对照。

不能将这组资产推广到两个不同固定 alpha、不同 link/scale、不同样本、非嵌套参数空间或稳健/抽样权重伪似然的模型对。基线 `postestimation/core.py` 的通用 LR guard 核验模型类型、权重、样本和参数子集，没有由本参考资产额外建立 alpha/link/scale 一致性验证；此次报告仅证明上述冻结模型对，未证明任意 GLM-NB 对都可进行 LR。未修改准入表、调用中心文件、运行完整 gate、浏览器、宿主 LMM 或真实 LLM；最终准入仍由 Integration 的证据登记与 live_eval 等门槛决定。

## 复现与保留

工作树：`/Users/jiayuanren/项目规划/.worktrees/codex-v1811-final-oracles`。所有 R/Stata/owner/pytest 命令使用 `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend` 与主线 `local/v1811-coordination/run_exclusive.py`。完整命令、baseline/tip/path/SHA-256 见 `tests/eval_v1811/glm_nb_review_manifest.json`。

最终原生证据在 `tests/eval_v1811/glm_nb_review_evidence_final/`。提交仅包括 JSON、自己 do-file、TSV、自身 do-file 的输出片段及独立测试/报告；完整原始 Stata 日志与两轮生成的真实项目均保留在本地，不加入新审查提交。初次独立证据目录同样保留。没有删除、安装、合入、push 或重写已有文件。
