# v1.8.11 FPC / GLM-NB 三语言统计适配完成报告

## 独立审查 P2 收敛修复补充

本补充对应独立审查 `80bafa06e7781b725be60bca65388bf54a8f476e` 对原候选 `678d9cc46d155a50aed47b210e2e6a6e82a12882` 的两项真实 RED。修复仍在原 owned worktree，未 merge/rebase/push，也未修改审查测试、旧 oracle、容差或统计默认。修复代码、回归与证据提交为 **`adaa3b586891bf7b1a2a07173c712583c648ba5e`**；包含本补充报告的最终 SHA 由 parent 交付消息记录，避免自身提交哈希的循环引用。正式 v1-8-11 事件由 IntegrationCLI 登记。

原因是 R `glm.control(epsilon=1e-16)` 仍按 deviance 变化终止；大 alpha 下 deviance 的量级使错误 beta 被判收敛。现在仍用 MASS 的固定 theta 原生 GLM 初始化，随后调用原生 `glm.fit` 的单步 IRLS，在参数相对变化 <=1e-12 **且**按样本数、设计列尺度归一的 scaled score <=1e-10 后才发布结果。alpha>=1 时使用等价的 alpha×score 残差 `(y/mu-1)/(1+1/(alpha*mu))`，避免小 score 的量级掩盖未收敛；alpha<1 使用原 score。每次仅对单步迭代的 warning 做局部抑制，最终是否收敛由上述证书决定；无默认替换或 sequential 降级。

最终 EIM 仍为 `inverse(X' diag(mu/(1+alpha*mu)) X)`，scale=1、z，独立 negative_binomial 的 OIM 不变。合法有限 alpha 没有新上界；当实际原生 mean/variance 非有限时 `GLM_NB_NUMERIC_FAILURE` 明确退出，未满足收敛证书时 `GLM_NB_NOT_CONVERGED` 明确退出，不发布部分数字。

| 真机案例 | 原 RED | 修复复验 |
|---|---|---|
| alpha=1e20，240行公开合成数据，completed owner 26iterations | R截距 -1.0171957731642591 vs owner 0.41984161711405155 | R截距 0.4198416171140387；x1 0.5438671026125138 vs 0.5438671026124017；x2 -0.3225180098448674 vs -0.3225180098449096；max coefficient abs差 1.1213252548714081e-13 < 原1e-8 |
| 同组最终 EIM SE | 原截距自检失败，未到SE | max SE abs差 1.1920928955078125e-7 < 原1e-6；三个SE依次 649372365.6740237、672946964.1387975、610975975.1537546 |
| 同组 R 收敛证书 | deviance早停 | 28次单步 refinement；parameter_change 5.67434987885918e-13；scaled_score 1.78420241544093e-13 |
| alpha=1e308，owner真实拒绝 | 旧R一次迭代exit0 | R exit1，`GLM_NB_NUMERIC_FAILURE: non-finite native mean or variance`，numeric_actual.tsv不存在；Stata/Python同组原样拒绝仍通过 |
| 独立alpha=2新R精确参考 | 审查普通组原通过 | Stata/R/Python coefficient/SE、全3×3 covariance和LL全部原容差通过 |

原样独立测试通过 `replay_review_convergence.py` 执行，审查测试文件只读，所有输出重定向到本线 owned 新目录。首轮 RED 为2 failed/2 passed；首次 GREEN尝试仍误取审查树冻结 renderer（pytest配置改变模块搜索路径），输出完整保留，不计修复验收；随后入口预加载生产 renderer并断言绝对路径，4 passed/24 deselected/2.30s。作者加入两个 portable native R 回归，并验证极端案例 owner 真实拒绝；2 passed/111 deselected/1.32s。

本次完整相关测试为 **113 passed（原111+新增2），36.63s**；独立 alpha=2 三语言为 **3 passed/25 deselected，2.42s**；`tsc --noEmit` exit0（stdout/stderr空）。已知 statsmodels BIC FutureWarning 与1e308实际overflow RuntimeWarning原样保留，未通过 suppress/skip/xfail 隐藏失败。

完整命令保存在 `tests/fixtures/script_export/v1811_statistical_adapters/convergence_commands.txt`。原始输出分别为 `convergence_review_red01.txt`、`convergence_review_green01.txt`（误取旧renderer）、`convergence_review_green02.txt`、`convergence_author_green01.txt`、`convergence_focused_green01.txt`、`convergence_alpha_two01.txt`、`convergence_tsc01.txt`。双方全精度数字见 `review_convergence_replay/producer_green02_large_alpha_completed_owner_r/numeric_pairs.json`；所有脚本、输入、plan、失败/成功运行目录和本机raw日志均保留。

保护审计输出为 `convergence_asset_audit01.txt`，manifest为 `convergence_asset_protection_manifest.json`：**2799 个冻结资产逐字节不变、108 份 ignored raw日志0600 与原/脱敏SHA及header之外bytes一致、3559 份文本扫描、0 未脱敏header发现**。新增证据提交824个owned文件；完整 `git diff --cached --check` 因保留的原生日志/生成文本尾部空格退出2，未为满足whitespace检查改写证据；生产代码和作者测试专门的 `git diff HEAD^ HEAD --check -- backend/workbench/script_export/exporters/models.py tests/test_script_export_v1811_statistical_adapters.py` exit0。没有新的中央接线或合同变更请求；本补充只完成 producer 本地复验，等待同一 reviewer 独立复验与用户合入批准。

生产候选已完成本线验证，公开 GLM-NB 后估计 consumer 在冻结基线仍未准入，必须由 Integration 在真实中央开放后执行补验。本报告不把局部原生探针算作 consumer、浏览器、Agent 或 release 验收。

## 身份与范围

- 分支：`codex/v1811-script-statistical-adapters`。
- 绝对工作树：`/Users/jiayuanren/项目规划/.worktrees/codex-v1811-script-adapters`。
- 精确冻结基线：`04d84b6d8f027ff8a45921bd9a5f4aeec28398c5`；开工 status 干净、HEAD 匹配。
- 实现与测试证据提交：`95a93009dd7eec4b7afe1380116a15975c7cfaf9`。包含本报告的最终提交通过 parent 交付消息和 `git rev-parse HEAD` 给出；本报告不能在自身提交内容中循环记录自身 SHA。
- 唯一生产改动：`backend/workbench/script_export/exporters/{survey,models,__init__}.py`；其余新增仅 `tests/test_script_export_v1811_statistical_adapters.py`、`tests/fixtures/script_export/v1811_statistical_adapters/**` 与本报告。
- 已读本树 AGENTS、objective、lane-contracts、交接 §6、正式 context/global/历史教训及波次冻结设计。沿用 `v1-8-11`，未手改正式记录；物料事件由 IntegrationCLI 记账。

## 子项状态

| 子项 | 状态 | 证据与边界 |
|---|---|---|
| FPC counts/fractions/domain/certainty | 完成 | 7 场景 × Stata/R/Python = 21 原生成功；包括 no-PSU、no-strata、fraction=0 |
| 完整设计 n_h / domain | 完成 | 在 domain 前验证层内 FPC 与 full PSU 数，真实 subpopulation 方差对已批准参考 |
| 非法 FPC | 完成 | mixed/missing/层内不一致/N<n/非整数 counts/负值/布尔数据，7×3 原生非零退出，未到数字自检 |
| replicate+FPC | 完成 | 三语言明确 native refusal，保留现有边界 |
| GLM-NB 显式 alpha、log、final EIM、scale1 | 完成 | alpha=1 与不同 alpha=.5 真实 R/Stata/Python；generic/direct 两种模型声明 |
| 五后估计局部原生探针 | 完成 | 2 alpha ×3语言，完整4×4 covariance、两模型LL、联合/平移Wald、lincom、nlcom、LR、平均/均值点margins自检 |
| 五后估计完整 export_script consumer | 冻结基线阻断，集成待验 | 7具体场景×2alpha×3语言=42 个真实 NOT_YET_VALIDATED，均保存完整plan；未 mock VALIDATED，未跳过 |
| 独立 negative_binomial 固定alpha OIM边界 | 完成 | 保留原 renderer 和 refusal；当前原生仅 estimated NB2，固定alpha仍须明确sidecar，未错误开放为GLM EIM |
| 无FPC与旧GLM/独立NB回归 | 完成 | 无FPC18通过；模型/声明/合同37通过，旧断言7失败逐项列下 |
| TypeScript | 完成 | tsc --noEmit exit0，未改frontend |
| 资产保护 | 完成 | 68旧参考逐字节不变；85完整原日志ignored local0600，公开仅header值遮蔽 |

## 实现口径与接线

`survey.py:21` 解除过时 FPC 拒绝但仍检查字段类型；`:34` 输出 R/Stata 数据校验；`:111` 之后给真实 `survey::svydesign(fpc=~...)` 和 `svyset ..., fpc(...)`。Python 原有 `build_design_from_artifacts` / `estimate_with_design` 消费已批准 FPC 引擎。全球 all<=1 为fraction，否则 all>1 为整数counts；每层值一致，counts>=完整抽样PSU数。noPSU按每行、noStrata按单层；domain零贡献PSU仍计入 n_h；certainty 是批准的 f=1 口径，不新增 lonely 默认或统计实现。

`models.py:247` 严格拒绝缺省/布尔/字符串/非正/非有限与超大整型 alpha，统一 `GLM_NB_ALPHA_REQUIRED`；`:259` 为专属 GLM-NB renderer。Python 使用 statsmodels 现有严格IRLS，随后在最终beta求 `inv(-hessian(observed=False))` 并清理原缓存；R 使用固定 theta=1/alpha 的 MASS glm，最终 EIM `inverse(X' diag(mu/(1+alpha*mu)) X)`；Stata `glm ..., family(nbinomial alpha) link(log) ml vce(eim) scale(1)`。均显式检验收敛与有限性，按z推断。没有改变独立负二项的 OIM 或原估计默认。

`exporters/__init__.py:62/70/99` 同时声明 generic family 和直接 `model.glm:negative_binomial` native；FPC coverage 带明确等价说明。沿用既有闭合模型与后估计 renderer，不改 plan/runtime、中心 registry/admission 或公有消费者。

## TDD、命令与原始输出

所有数值/native/pytest都通过共享绝对runner串行，当前worktree绑定 `PYTHONPATH=backend`，执行后释放锁。原始失败与成功目录全保留，未删旧测试、fixture、golden或放宽容差。使用 test-driven-development 与 verification-before-completion 技能。

下列命令的共同前缀为（以下完整命令文件也保留在 `commands.txt`）：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py
```

| 精确后续命令 | 原样输出文件 | 结果 |
|---|---|---|
| `.venv/bin/python -m pytest -q tests/test_script_export_v1811_statistical_adapters.py -k 'executed_natively or final_eim_model' --tb=short` | `tdd_red_01.txt` | 27 failed,8 deselected,1.97s，生产实现前RED |
| `.venv/bin/python -m pytest -q tests/test_script_export_v1811_statistical_adapters.py --tb=short -s` | `tdd_green_01.txt` | 2 failed,33 passed,21.20s，Python finite pandas shape故障 |
| 同上 | `tdd_green_02.txt` | 12 failed,65 passed,22.84s，测试p需转普通float |
| 同上 | `tdd_green_03.txt` | 83 passed,26.69s |
| 同上 | `tdd_green_04.txt` | 3 failed,107 passed,38.14s，N=2=n_h是合法certainty，修探针数据 |
| `.venv/bin/python -m pytest -q tests/test_script_export_v1811_statistical_adapters.py -k overflow_integer --tb=short` | `overflow_alpha_red.txt` | 1 failed,110 deselected,1.19s，alpha溢出RED |
| `.venv/bin/python -m pytest -q tests/test_script_export_v1811_statistical_adapters.py --tb=short -s` | `final_focused_01.txt` | **111 passed,36.54s** |
| `.venv/bin/python -m pytest -q tests/test_script_export_v1811_statistical_adapters.py -k local_native_inference_primitives --tb=short -s` | `final_primitives_02.txt` | **6 passed,105 deselected,5.33s**，新增两模型LL自检后仅重跑相关组 |
| `Rscript tests/fixtures/script_export/v1811_statistical_adapters/generate_alpha_half_oracle.R tests/fixtures/postestimation/data.csv 2e1b92f07632a8c88d047074f77cd6e5f9552b4f932f7d6ed2499161a0bf3084 tests/fixtures/script_export/v1811_statistical_adapters/native-r-alpha-half` | `native-r-alpha-half-command.txt` | exit0；R4.6.0/MASS7.3.65/car3.1.5/lmtest0.9.40/marginaleffects1.0.0 |
| `.venv/bin/python tests/fixtures/script_export/v1811_statistical_adapters/run_related.py -q tests/test_script_export_survey_oracles.py -k 'complete_no_fpc and (strata_psu or subpopulation or lonely_average)' --tb=short -s` | `no_fpc_regression_01.txt` | 18 passed,64 deselected,15.18s |
| `.venv/bin/python tests/fixtures/script_export/v1811_statistical_adapters/run_related.py -q tests/test_script_export_render.py tests/test_script_export_plan_contract.py tests/test_script_export_model_oracles.py -k 'not test_native_model_engine_oracle or glm_binomial or glm_poisson or negative_binomial' --tb=short -s` | `related_regression_01.txt` | 37 passed,3 failed,27 deselected,15.16s |
| `.venv/bin/python tests/fixtures/script_export/v1811_statistical_adapters/run_related.py -q tests/test_script_export_survey_oracles.py -k 'supplied_fpc or fpc_frozen' --tb=short -s` | `affected_existing_fpc_01.txt` | 4 failed,78 deselected,1.20s，旧断言列下 |
| `.venv/bin/python tests/fixtures/script_export/v1811_statistical_adapters/audit_assets.py` | `asset_audit_02.txt` | 68 refs,85 rawlogs,2737 texts,0 unredacted header findings,36 final positive native runs |

Frontend命令（cwd=`/Users/jiayuanren/项目规划/.worktrees/codex-v1811-script-adapters/frontend`）：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=../backend ../.venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py ./node_modules/.bin/tsc --noEmit
```

原样stdout/stderr为 `tsc_01.txt`（空），exit0。`run_related.py`只把已有测试输出目录绑定到新owned目录并保护日志，不改测试代码、准入或容差；其负二项/GLM6条 statsmodels BIC FutureWarning 按原样保留。

## 数字证据、容差与性能

每个目录均含完整 `plan.json`、`analysis.{do,R,py}`、`numeric_pairs.json`（双方全精度数字、差与allowed）、`numeric_actual.tsv`、原生stdout/stderr、exit。`numeric_summary.json`列36组最大差；完整R alpha=.5 oracle另外包含 covariance/LL/五后估计以及收敛信息。alpha=1完全复用冻结的真实R参考，既有参考未改。

模型系数 abs1e-8、SE abs1e-6；FPC t abs1e-8+rel1e-6、p rel1e-5。五后估计保留原reference capture口径：estimate/stat/lincom/nlcom SE/LL rel1e-6、p rel1e-5、margins SE rel1e-5；新矩阵自检 abs1e-8+rel1e-6。没有改变任何旧oracle容差。marginaleffects数值导数与闭合log-link/delta原语的最大微小差见下，仍远低于原容差。

下表展示每组最大绝对差所在数字，及该组所有数字的最大相对差；其余完整双方数字以目录内numeric_pairs为准。时间包含进程启动、读CSV、拟合、原生检查和保留证据；不是冷机/大样本性能承诺。

| 原生组/语言 | 参考 | 实际 | max abs差 | max rel差 | 秒 |
|---|---:|---:|---:|---:|---:|
| [fpc_population_stata_8918741e38](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_population_stata_8918741e38/numeric_pairs.json) | 9.2440478844246634 | 9.2440478844246741 | 1.06581e-14 | 9.68618e-15 | 0.998 |
| [fpc_population_r_be0c89e286](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_population_r_be0c89e286/numeric_pairs.json) | 4.6527115739431109 | 4.6527115739431109 | 0 | 0 | 0.650 |
| [fpc_population_python_1f259a6cbe](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_population_python_1f259a6cbe/numeric_pairs.json) | 9.2440478844246634 | 9.2440478844246972 | 3.37508e-14 | 3.34763e-14 | 0.874 |
| [fpc_fraction_stata_71e2b6567c](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_fraction_stata_71e2b6567c/numeric_pairs.json) | 9.2440478844246634 | 9.2440478844246741 | 1.06581e-14 | 9.68618e-15 | 0.764 |
| [fpc_fraction_r_cfaad33862](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_fraction_r_cfaad33862/numeric_pairs.json) | 4.6527115739431109 | 4.6527115739431109 | 0 | 0 | 0.589 |
| [fpc_fraction_python_a6ea592194](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_fraction_python_a6ea592194/numeric_pairs.json) | 9.2440478844246634 | 9.2440478844246972 | 3.37508e-14 | 3.34763e-14 | 0.810 |
| [fpc_subpopulation_stata_34de94c359](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_subpopulation_stata_34de94c359/numeric_pairs.json) | 9.1333498594925668 | 9.1333498594925473 | 1.95399e-14 | 2.13999e-14 | 0.765 |
| [fpc_subpopulation_r_2f08a5f373](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_subpopulation_r_2f08a5f373/numeric_pairs.json) | 5.4816705044520218 | 5.4816705044520218 | 0 | 0 | 0.593 |
| [fpc_subpopulation_python_27eea9b04a](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_subpopulation_python_27eea9b04a/numeric_pairs.json) | 9.1333498594925668 | 9.1333498594925366 | 3.01981e-14 | 3.40606e-14 | 0.816 |
| [fpc_lonely_census_stata_8a7becaf56](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_lonely_census_stata_8a7becaf56/numeric_pairs.json) | 7.6144180117336635 | 7.6144180117336475 | 1.59872e-14 | 1.17304e-14 | 0.765 |
| [fpc_lonely_census_r_dc2e6bbd20](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_lonely_census_r_dc2e6bbd20/numeric_pairs.json) | 4.767273406190168 | 4.767273406190168 | 0 | 0 | 0.600 |
| [fpc_lonely_census_python_1f0f304d9f](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_lonely_census_python_1f0f304d9f/numeric_pairs.json) | -5.0870034320644235 | -5.0870034320645008 | 7.72715e-14 | 8.58257e-14 | 0.825 |
| [fpc_no_psu_stata_9cc0962491](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_no_psu_stata_9cc0962491/numeric_pairs.json) | 26.676336676967825 | 26.676336676967864 | 3.90799e-14 | 1.14889e-13 | 0.770 |
| [fpc_no_psu_r_f1fac38a16](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_no_psu_r_f1fac38a16/numeric_pairs.json) | 4.6527115739431109 | 4.6527115739431109 | 0 | 0 | 0.597 |
| [fpc_no_psu_python_d60550d445](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_no_psu_python_d60550d445/numeric_pairs.json) | 26.676336676967825 | 26.67633667696791 | 8.52651e-14 | 2.19267e-13 | 0.823 |
| [fpc_no_strata_stata_8ba1f70db8](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_no_strata_stata_8ba1f70db8/numeric_pairs.json) | -6.1889486715045621 | -6.1889486715045869 | 2.4869e-14 | 4.10448e-14 | 0.773 |
| [fpc_no_strata_r_3acd67086d](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_no_strata_r_3acd67086d/numeric_pairs.json) | 4.6527115739431109 | 4.6527115739431109 | 0 | 0 | 0.598 |
| [fpc_no_strata_python_b69f6c8b53](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_no_strata_python_b69f6c8b53/numeric_pairs.json) | 13.348999045881026 | 13.348999045881072 | 4.61853e-14 | 6.55915e-14 | 0.816 |
| [fpc_zero_fraction_stata_f86ad9af4c](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_zero_fraction_stata_f86ad9af4c/numeric_pairs.json) | 8.3227336945375736 | 8.3227336945375825 | 8.88178e-15 | 6.43589e-15 | 0.779 |
| [fpc_zero_fraction_r_7edbc0ef85](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_zero_fraction_r_7edbc0ef85/numeric_pairs.json) | 4.6527115739431109 | 4.6527115739431109 | 0 | 0 | 0.588 |
| [fpc_zero_fraction_python_7af37ab6f3](../../../tests/fixtures/script_export/v1811_statistical_adapters/fpc_zero_fraction_python_7af37ab6f3/numeric_pairs.json) | 8.3227336945375736 | 8.3227336945376038 | 3.01981e-14 | 2.94978e-14 | 0.815 |
| [glm_nb_stata_False_6fd09395e0](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_stata_False_6fd09395e0/numeric_pairs.json) | 0.16986251046239487 | 0.1698625104623952 | 3.33067e-16 | 1.9608e-15 | 0.924 |
| [glm_nb_r_False_2149fad610](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_r_False_2149fad610/numeric_pairs.json) | 0.52403339827555395 | 0.52403339827555395 | 0 | 0 | 0.182 |
| [glm_nb_python_False_1b0134f7bd](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_python_False_1b0134f7bd/numeric_pairs.json) | 0.52403339827555395 | 0.52403339827549933 | 5.4623e-14 | 5.23478e-13 | 0.790 |
| [glm_nb_stata_True_0fba41a98a](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_stata_True_0fba41a98a/numeric_pairs.json) | 0.16986251046239487 | 0.1698625104623952 | 3.33067e-16 | 1.9608e-15 | 0.976 |
| [glm_nb_r_True_3c23d1c826](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_r_True_3c23d1c826/numeric_pairs.json) | 0.52403339827555395 | 0.52403339827555395 | 0 | 0 | 0.185 |
| [glm_nb_python_True_db8e350b41](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_python_True_db8e350b41/numeric_pairs.json) | 0.52403339827555395 | 0.52403339827549933 | 5.4623e-14 | 5.23478e-13 | 0.690 |
| [glm_nb_alpha_half_stata_e0441bf97a](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_alpha_half_stata_e0441bf97a/numeric_pairs.json) | 0.38084532291716122 | 0.38084532291714684 | 1.43774e-14 | 3.77513e-14 | 0.906 |
| [glm_nb_alpha_half_r_35c61b52bd](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_alpha_half_r_35c61b52bd/numeric_pairs.json) | 0.52941907662749654 | 0.52941907662749654 | 0 | 0 | 0.171 |
| [glm_nb_alpha_half_python_4ab4a51206](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_alpha_half_python_4ab4a51206/numeric_pairs.json) | -0.10833250363412572 | -0.10833250363416436 | 3.86358e-14 | 3.56641e-13 | 0.657 |
| [glm_nb_primitives_1.0_stata_0a4bd82d47](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_primitives_1.0_stata_0a4bd82d47/numeric_pairs.json) | 0.65174411412307309 | 0.65174411293709811 | 1.18597e-09 | 5.81131e-09 | 1.235 |
| [glm_nb_primitives_1.0_r_4df5e45214](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_primitives_1.0_r_4df5e45214/numeric_pairs.json) | 0.65174411412307309 | 0.65174411263864518 | 1.48443e-09 | 6.44027e-09 | 0.239 |
| [glm_nb_primitives_1.0_python_0e97e8b48e](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_primitives_1.0_python_0e97e8b48e/numeric_pairs.json) | 0.65174411412307309 | 0.65174411263856158 | 1.48451e-09 | 6.44027e-09 | 0.697 |
| [glm_nb_primitives_0.5_stata_c56785b09c](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_primitives_0.5_stata_c56785b09c/numeric_pairs.json) | 0.6563673408291717 | 0.65636733962552318 | 1.20365e-09 | 1.03408e-08 | 1.001 |
| [glm_nb_primitives_0.5_r_f1a309cb06](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_primitives_0.5_r_f1a309cb06/numeric_pairs.json) | 0.6563673408291717 | 0.65636733931877578 | 1.5104e-09 | 6.56167e-09 | 0.207 |
| [glm_nb_primitives_0.5_python_2450d94d00](../../../tests/fixtures/script_export/v1811_statistical_adapters/glm_nb_primitives_0.5_python_2450d94d00/numeric_pairs.json) | 0.6563673408291717 | 0.6563673393188334 | 1.51034e-09 | 6.56167e-09 | 0.688 |

## 资产保护、事故与范围外观察

`protected_assets.json`绑定68个既有fixture/旧tests的冻结SHA与当前SHA，全部一致。`asset_protection_manifest.json`记录85份Stata raw/new SHA、ignored raw相对路径、0600、去header值后的payload SHA。原始log完整保留，本线不重写已有历史。公开log只替换 Serial number / Licensed to 的header值，命令、数字与其余bytes相同；审计不打印字段值。最终 `asset_audit_03.txt` 连同本报告扫描2740个新/owned文本，无未遮蔽header。保护路径仅local不外发。

可恢复的失败全保留：Python cov_params 是DataFrame的有限性断言需先np.asarray；numpy float64不能成为frozen JSON叶子，测试转普通float；非法N<n探针最初N=2且n_h=2，实际合法certainty，测试改完整PSU结构令n_h>N，不改变生产定义；超大整数alpha真实RED泄漏OverflowError，严格转换后统一Refusal。没有scope外写、删除、安装或真实LLM调用。

未覆盖范围：全量gate、浏览器/HTTP/Agent正式导出链、私有数据、离开本机的依赖安装、自助集成、replicate设计与GLM权重/稳健协方差。Python survey导出显式依赖Workbench批准的设计引擎。独立negative_binomial固定alpha的原生导出仍保留既有sidecar边界；本任务仅新增GLM-NB native，不能以此声称全部NB高级选项原生可用。

## 既有受影响测试与精确集成请求

1. `tests/test_script_export_survey_oracles.py::test_supplied_fpc_cannot_be_silently_dropped[stata]`、`[r]`、`[python]`：旧期待 supplied FPC `NOT_FULLY_NATIVE`，批准FPC后不再抛此拒绝。
2. 同文件 `test_fpc_frozen_engine_difference_is_persisted`：旧期待 `plain==with_fpc`，已批准引擎真实乘(1-f)，冻结基线就已不成立。
3. `tests/test_script_export_render.py::test_unopened_postestimation_pair_is_explicitly_rejected[stata]`、`[r]`、`[python]`：旧期待glm:poisson Wald未准入，冻结中央已开放。本线未改该renderer/registry定义。

以上7项完整RED保留；由Root改中央owned旧断言为已批准行为的真实检查，或选择真实未准入组合。本线未代改、未skip/xfail。

Root已通知中央67088c98开放GLM-NB，生产者未自行merge/rebase。Integration移植候选后，请只运行完整消费者组（同一实际数据与容差）：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest -q tests/test_script_export_v1811_statistical_adapters.py -k five_operation_consumer_gate --tb=short -s
```

测试直接查询真实 `VALIDATED`：缺少pair时生成 `actual_refusal/unvalidated` metadata与完整plan，开放时生成 `actual_native_execution/validated` metadata并真正 `export_script(require_native=True)` / native execute；没有永远期待冻结拒绝、没有mock准入或静默skip。具体42例：联合Wald、平移Wald、lincom、nlcom、嵌套LR、average margins、means margins，alpha1/.5，三语言。集成需保留已执行model_options.alpha/family/covariance与输入SHA；FPC的设计字段与sampling weight应来自真实已执行输入，不能省略。后估计无需本线新增模块外改，现有封闭renderer在真实中央准入后消费最终EIM矩阵。

合同变更请求：无新增统计默认或字段请求；中央旧断言更新与consumer准入/生产链复验是既已授权Integration职责。独立审查与用户批准合入仍未发生，分支和worktree保留。
