# GLM-NB 固定 alpha 最终原生参考完成报告

## 身份、冻结与范围

工作树 `/Users/jiayuanren/项目规划/.worktrees/codex-v1811-final-oracles`，分支 `codex/v1811-final-oracles`，冻结起点 `01fb0752bce129c8d8848c021eca776dadccb515`，起点 HEAD/branch/clean 均已确认。数字资产交付提交 `b2f7adec0e1503e11e9b0b7da564a1bfdc1157e1`；本报告随后独立提交，最终 tip 以交付消息及 `git log -1` 为准。

已读 AGENTS.md、正式 v1-8-11 Context Pack/global_rules、Context Pack 指向的相关历史回顾及 `2026-10-04-v1.8.11-final-oracle-interface-freeze.md`。沿用同一版本正式线，无另开或手改 `.agent/devlines`。使用 TDD、systematic-debugging、verification-before-completion 的证据流程。

仅新增 `tests/fixtures/postestimation/glm_negative_binomial_v1811/**`、`tests/test_glm_nb_v1811_reference.py` 及本专属报告。原始 `postestimation/data.csv`、旧 oracle/generator、生产 owner/kernel/postestimation、冻结接口文件均与冻结起点逐字节相同，9 个受保护文件的 SHA/判据在 `manifest.json`。无中心 registry/admission/Agent/frontend 修改，无旧测试、旧参考、统计默认或容差改动；无删除、安装、Downloads、LLM/provider、push/merge/rebase/tag/full gate。

## 完成状态与统计定义

固定 alpha=1，log link，scale=1，完整模型 `ynb ~ x1 + x2 + x3`，限制模型 `ynb ~ x1`，原始同一 300 行样本。源 SHA256 `2e1b92f07632a8c88d047074f77cd6e5f9552b4f932f7d6ed2499161a0bf3084`。

原生 R `glm` + MASS::negative.binomial(theta=1) 使用 `glm.control(epsilon=1e-16,maxit=1000,trace=TRUE)`；按最终 beta 计算 `X' diag(mu/(1+mu)) X` 的 EIM 及其逆。car::linearHypothesis/deltaMethod 显式使用该最终协方差；lmtest::lrtest 比较同样本的原生 logLik；marginaleffects 使用同一协方差输出 average/at-means。保持既有 family_case 键形状，额外记录 metadata、full_precision 的 17 位数字字符串、完整/限制模型 beta/vcov/information/score/LL/nobs/DF/iterations/warnings。

R 4.6.0，MASS 7.3.65，car 3.1.5，lmtest 0.9.40，marginaleffects 1.0.0，jsonlite 2.0.0；现有安装，无安装或升级。完整/限制模型均 `converged=true`，迭代 19/9，warnings 均为空；最大绝对 beta score `3.80330328485002e-14` / `7.39408534400354e-14`。原始 trace、版本及所有输出保存在 `native-output.txt`，未屏蔽 warning。

本机 Stata 18/MP 通过既有 `tests/stata_oracle.py` 和每次新目录完成独立核对。最终命令为 `glm ..., family(nbinomial 1) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)`；模型同固定 alpha likelihood，显式 EIM 与 R 最终点信息一致。完整 fit `e(converged)=1`，日志显示 scale=1 / EIM，LR 采用原生 e(ll)。原始 import 为 `asdouble clear case(preserve)`。原生 `test`、`lincom`、`nlcom`、`lrtest`、`margins` 全部运行并保留 do/log/17 位 TSV/JSON。Stata 启动 profile.do 的既有 r(199) 诊断原样保留，随后 oracle do 正常执行完毕；不把全日志描述为无诊断。

实际 owner 是 public `run_workflow(... model_type='glm:negative_binomial', model_options={'alpha':1.0})`，读取实际 persisted inference kernel 及 estimation design；五类后估计调用现有核心函数。完整/限制 owner workflow 均 completed，kernel 保留 4/2 个 beta，无固定 alpha 附属参数。完整 kernel nobs=300、df_resid=296、z/nonrobust；direct owner fitted 的 final expected Hessian 逆与 vcov 严格数值一致，最大绝对 score `1.1875833649810374e-11`。owner 参数收敛报告 true/13 iterations/absolute parameter change tolerance=1e-12。

## 数字结果与原容差

54 个逐项 owner/R/Stata 对照均 PASS，全部 17 位数与绝对/相对误差见 `numeric-diff.md` 和 `owner-evidence.json`；不以本表的缩写显示替代原始精度。

| 项目 | R 原生 | Stata 原生 | Owner | 原容差 |
|---|---:|---:|---:|---|
| joint Wald statistic / DF | 43.440653744966909 / 2 | 43.440653744966951 / 2 | 43.440653744956535 / 2 | statistic rel1e-6，DF exact |
| joint Wald p | 3.6896221611486429e-10 | 3.6896221611485643e-10 | 3.6896221611677756e-10 | rel1e-5 |
| shifted Wald statistic / DF | 10.745724600510435 / 1 | 10.745724600510423 / 1 | 10.745724600516064 / 1 | statistic rel1e-6，DF exact |
| shifted Wald p | 0.0010452050791167394 | 0.0010452050791167455 | 0.0010452050791135592 | rel1e-5 |
| lincom estimate | -0.69899651625044146 | -0.69899651625044168 | -0.69899651625038317 | rel1e-6 |
| lincom SE | 0.15076868785670161 | 0.15076868785670161 | 0.15076868785670133 | rel1e-6 |
| nlcom estimate | -1.3113000332857292 | -1.3113000332857292 | -1.3113000332858176 | rel1e-6 |
| nlcom SE | 0.39432819166511462 | 0.39432819168420352 | 0.39432819176154726 | rel1e-6 |
| LR statistic / DF | 20.922503611121101 / 2 | 20.922503611121101 / 2 | 20.922503611121101 / 2 | statistic rel1e-6，DF exact |
| LR p | 2.8624378573147229e-5 | 2.8624378573147212e-5 | 2.8624378573147222e-5 | rel1e-5 |
| LL full | -513.25643356734679 | -513.25643356734668 | -513.25643356734668 | rel1e-6 |
| LL restricted | -523.71768537290734 | -523.71768537290723 | -523.71768537290723 | rel1e-6 |

系数对 R 最大绝对误差 `5.462e-14`、对 Stata `5.485e-14`，原容差 abs1e-8；SE 最大绝对误差 `4.441e-16`，原容差 abs1e-6。margins estimate/SE 原容差分别 rel1e-6/rel1e-5，所有平均与均值点 x1/x2 通过，最大相对 SE 误差 `1.026e-8`。有限差分导致 R/Stata/owner margins/nlcom 末位差异，保留原值，没有对齐数字或放宽阈值。

## TDD、命令与原始输出

所有数值/R/Stata/pytest 使用 Integration 的单一 shared lock；wrapper 强制 pytest tmp retention=all/count1000000。本 agent 没有并行第二个重任务。

以下路径均相对于上述工作树。原始重定向日志保存在新 fixture，未重写或删除。统一前缀为：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py
```

按此前缀顺序运行的尾命令：

```sh
.venv/bin/python -m pytest -q tests/test_glm_nb_v1811_reference.py::test_native_reference_exists_and_has_all_five_operation_shapes > tests/fixtures/postestimation/glm_negative_binomial_v1811/tdd-red.txt 2>&1
.venv/bin/python tests/fixtures/postestimation/glm_negative_binomial_v1811/generate_native.py > tests/fixtures/postestimation/glm_negative_binomial_v1811/native-output.txt 2>&1
.venv/bin/python tests/fixtures/postestimation/glm_negative_binomial_v1811/generate_native.py native-stata-v2 > tests/fixtures/postestimation/glm_negative_binomial_v1811/native-stata-v2-output.txt 2>&1
.venv/bin/python tests/fixtures/postestimation/glm_negative_binomial_v1811/generate_native.py native-stata-v3 > tests/fixtures/postestimation/glm_negative_binomial_v1811/native-stata-v3-output.txt 2>&1
.venv/bin/python -m pytest -q -s tests/test_glm_nb_v1811_reference.py > tests/fixtures/postestimation/glm_negative_binomial_v1811/owner-first-green.txt 2>&1
.venv/bin/python tests/fixtures/postestimation/glm_negative_binomial_v1811/capture_owner.py > tests/fixtures/postestimation/glm_negative_binomial_v1811/owner-capture-output.txt 2>&1
.venv/bin/python -m pytest -q -s tests/test_glm_nb_v1811_reference.py > tests/fixtures/postestimation/glm_negative_binomial_v1811/owner-final-green.txt 2>&1
```

RED 原样末行 `1 failed in 1.81s`，失败原因为所需新 oracle 尚不存在。首轮 owner `1 failed, 8 passed, 3 warnings in 12.91s`；新增逐位 covariance equality 断言误把独立 CSV reader 的末位差异当错误，maxabs `1.38777878e-17`，改为同源 vcov 数值检查 rtol1e-12/atol0，不改变任何统计 oracle 容差。Stata 系数/SE 断言显式 rel=0，保证原 absolute 容差不被 pytest.approx 默认相对容差扩大。

最终原样末行 `10 passed, 3 warnings in 12.52s`，退出码 0。warnings 为 statsmodels 已有 BIC 定义 FutureWarning；fontconfig/matplotlib 不可写缓存与 Arrow sysctl sandbox 诊断也完整保留。capture 原样输出 `54 full-precision comparisons PASS; retained owner projects: /var/folders/n0/0xwbb3jn2vs3lmj2rn6wn2940000gn/T/v1811-glm-nb-owner-uqytzebt`。raw project runs 保留，kernel/结果/score 已另存 owned JSON。未做性能或浏览器验收，未运行全量 gate。

## 原生尝试事故与证据保全

第一次 Stata IRLS 尝试误给 ML 专属 tolerance，退出 r(198)，保留 `native-stata/**`。第二次显式 IRLS ltolerance/EIM 得到正常系数与 Wald/lincom/nlcom/margins，但 IRLS 不保存 e(ll)，lrtest 因缺 LL 退出 r(498)，保留 `native-stata-v2/**`，其中 `.`/缺少后续字段明确属于未完成参考，测试不会消费。

查阅本机 Stata glm.sthlp/glm.ado 后，第三次使用同固定 alpha likelihood 的 ML 优化加显式 vce(eim)/scale1，五操作全部完成，接受参考只为 `native-stata-v3/reference.json`。不同尝试的原始 do 文件完整保存，不伪称当前 generator 代码就是失败时的旧代码。无静默降级、删除或补造原生结果。

## 资产入口、哈希与消费者未决

新 native R JSON：`tests/fixtures/postestimation/glm_negative_binomial_v1811/native-r/oracle.json`，SHA256 `4229ad41f85d5ca0e232a825a8b4fe90057eb8f9ecdc3edb802bc3b71b57b4ca`。生成脚本 `generate_oracle.R` SHA256 `8db6edb91543d73c23e56c5a48e00745a39e8f05c7b55a67cad3477562986eb7`。全部脚本、raw native logs、TSV/JSON、测试、capture/diff/output 的 SHA 在 `manifest.json`；manifest 自身不自引用。

五项数字准备、原生独立复核、actual owner/kernel 数字测试、范围自审均完成；不存在所需生产/中心文件变更请求。消费者 registry/admission/Agent/HTTP/frontend 的 GLM-NB 后估计开放仍由 Integration 完成，本报告不声称消费者已开放、不声称 browser/live/fullgate acceptance。独立统计审查完成后唯一日志 P2 已按以下记录修复，待 root 定向复查；合入必须单独取得用户批准，本 agent 不自行合入。IV 任务属于另一条参考工作树，本交付未触及。

## 独立审查 P2：日志 header 脱敏与完整原始证据

修复前 HEAD `87f964311115117f08b790a6247645ad23e1ff80`。独立审查确认数值通过，但三个 `native-stata*/oracle.log` 及 `native-output.txt` 包含 Stata 许可证编号/姓名 header。遵循 root 授权，仅把这两个 header 字段值替换为 `[REDACTED]`，保留标签、缩进、行尾和全部其余字节，合计 8 行。完整原始日志先复制到 git-ignored `local/v1811-glm-nb-raw-logs/20261004-p2/`，原名/相对目录保持，文件 mode=0600。未删除、未 reset、未改写历史、未在工具输出或报告打印原字段值。

`manifest.json.log_redaction.files` 逐文件记录 ignored 原副本路径、原始 SHA、脱敏 SHA、non-header payload SHA、确切改动行号和 byte-identical/ignored 判据；`asset_sha256` 更新为当前 tracked 脱敏文件哈希。原副本与修复前 Git 字节完全相同，脱敏前后去掉两条 header 行后的 payload 完全相同。因此原生数字、命令、原始错误/警告信息均不变。`redact_native_logs.py` 保存精确处理方法，已存在的 preservation record 拒绝覆盖；`log-redaction-audit.json` 保存扫描/字节检查结论。之前报告中的完整原始日志保全指上述 ignored 副本，tracked 日志只遮蔽许可证 header。

按同一 shared-lock 前缀新增运行：

```sh
.venv/bin/python -m pytest -q tests/test_glm_nb_v1811_reference.py::test_native_log_redaction_preserves_all_non_header_bytes > tests/fixtures/postestimation/glm_negative_binomial_v1811/log-redaction-red.txt 2>&1
.venv/bin/python -m pytest -q -s tests/test_glm_nb_v1811_reference.py > tests/fixtures/postestimation/glm_negative_binomial_v1811/log-redaction-final-green.txt 2>&1
```

脱敏前新增 guard RED 原样末行 `1 failed in 1.35s`，失败为缺少 preservation/redaction record。实际脱敏执行 `.venv/bin/python tests/fixtures/postestimation/glm_negative_binomial_v1811/redact_native_logs.py > tests/fixtures/postestimation/glm_negative_binomial_v1811/log-redaction-validation.txt 2>&1`，只做文件字节/哈希操作，输出 `PASS: 4 private raw copies preserved; only 8 license header lines redacted; all non-header bytes identical`。随后 fresh focused 最终末行 `11 passed, 3 warnings in 12.89s`，退出码 0；warnings 同既有 statsmodels BIC FutureWarning，原统计容差及参考 JSON/TSV/数据全无变化。

另扫描冻结起点之后全部 tracked 新增资产及本次 owned 新资产：不存在未脱敏 header 值或原始字段值。新 guard 不依赖 ignored 私有副本在别的 worktree 可用，通过 manifest payload SHA 对 tracked 日志做便携核对。ignored 完整副本的本地字节/原始 Git 字节验证另外记录；它们未进入提交。仅 stage producer 精确 owned 文件，独立审查测试/报告及其 untracked evidence 保持原状。
