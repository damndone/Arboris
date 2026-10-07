# 工单 B：v1.8.11 七个模型族准入对照数据报告

执行日期：2026-10-04。分支 `eval/v1811-admission-oracles`；worktree `/Users/jiayuanren/项目规划/.worktrees/codex-v1811-admission-oracles`；精确基线 `65d771b0ceb3898728523d07a9324000b4de4fff`。本工单来自原 v1.8.10 worktree 的只读工单文件，未把产品线后续提交合入评估线。

逐族最终测试合计：9 passed、3 failed、1 error（不是一次仓库全量运行；3 failed 为面板/DID 声明及负二项系数，1 error 为 LMM 准入阻断）。

七族均已执行：一致 3 族（iv_2sls、glm:binomial、glm:poisson）；不一致 1 族（glm:negative_binomial）；未决 2 族（panel_ols、did：系数和标准误一致，但推断核心未声明协方差）；阻断 1 族（linear_mixed_effects：本地隔离执行未准入）。

只生成模拟数据、R 对照、测试和证据，**未修改 admission.py 或任何产品代码、已有测试/golden/容差**。失败保留，不使用 xfail/skip，没有绕过 LMM 执行限制。每族均在 60 分钟内结束，没有超时；负二项数值排查只做了规定的三步。

## 结果总表

比较全部内核系数及协方差对角线平方根，容差采用绝对差：系数 1e-8；标准误 1e-6；LMM 的标准误 1e-4 仅预留给 REML 优化器差异，本次阻断而未执行该数值断言。不比较 p 值、置信区间或统计因果解释。

| 模型族 | 结论 | N | 最大系数绝对差 | 最大标准误绝对差 | R 设定 | Workbench 推断核心（covariance / df_method / distribution / df_resid） |
|---|---|---|---|---|---|---|
| iv_2sls | 一致 | 450 | 2.4424906541753444e-15 | 8.3266726846886741e-17 | fixest::feols IV，hetero，ssc(K.adj=FALSE)：HC0、不作自由度缩放 | robust / asymptotic / z / 447.0 |
| panel_ols | 未决（数值一致，核心声明缺失） | 400 | 5.1070259132757201e-15 | 6.9388939039072284e-17 | lm 双向 sum-to-zero 固定效应；vcovHC(HC1)，含完整固定效应参数数 | None / asymptotic / z / 341.0 |
| did | 未决（数值一致，核心声明缺失） | 400 | 6.106226635438361e-15 | 5.2735593669694936e-16 | 两期 2×2 TWFE 的 lm 显式 sum-to-zero 单位/时期项；HC1 | None / asymptotic / z / 198.0 |
| linear_mixed_effects | 阻断 | 360 | 未执行 | 未执行 | lme4::lmer(y ~ arm*time + x + (1|g), REML=TRUE)，bobyqa；仅 R 侧参考 | 不存在：run_workflow 在创建运行前拒绝 |
| glm:binomial | 一致 | 450 | 3.8857805861880479e-16 | 3.4694469519536142e-16 | glm binomial(logit)，epsilon=1e-14、maxit=100、dispersion=1 | nonrobust / asymptotic / z / 447.0 |
| glm:poisson | 一致 | 450 | 3.3306690738754696e-16 | 2.0906679165655362e-12 | glm poisson(log)，epsilon=1e-14、maxit=100、dispersion=1 | nonrobust / asymptotic / z / 447.0 |
| glm:negative_binomial | 不一致 | 450 | 4.0018355303428343e-06 | 1.5059666634564817e-07 | glm MASS::negative.binomial(theta=1)，dispersion=1；最终 epsilon=1e-8；另留 epsilon=1e-14 参考 | nonrobust / asymptotic / z / 447.0 |

## 未决、阻断与数值不一致

### panel_ols 与 did：数值通过，声明不完整

两族均直接调用 run_workflow，使用模型自身的默认 robust 配置。真实推断核心 `covariance_estimator=null`、`df_method=asymptotic`、`reference_distribution=z`；panel df_resid=341，DID df_resid=198。

按工单要“从推断核心绑定 R 设定”，null 不能支持完整的准入声明。因此分类为未决，保留 `test_inference_kernel_declares_its_covariance_estimator` 失败。没有猜测或填入 Workbench 内核字段。数值对照作为单独证据继续进行：依照实际调用的 PanelOLS robust 拟合及其完整固定效应残差自由度，用 R lm 的 sum-to-zero 固定效应与 HC1 对照，系数和标准误均通过。选择显式 dummy lm 是为了同时核验 PanelOLS 的中心化截距；只用 plm/fixest 的去均值斜率会漏掉该参数。

R oracle 的 covariance_estimator 明确写作 `runtime robust; kernel null`，而非伪称与 null 声明匹配；z/df_method 仅记录当前内核，不表示已经外部验证其 p 值/自由度惯例。owner 应修正/明确声明后再登记准入；本评估没有修复产品代码。

### linear_mixed_effects：真实流水线准入阻断

run_workflow 抛出 ModelOptionsError：`Linear mixed-effects execution is unavailable until explicit local containment is admitted.` 发生在数据拟合、运行创建及内核生成之前。R/lme4 本身成功运行，故不能说 R 不可用，也不能报告 LMM 数值不一致。

生成 360 行、60 个 subject、6 个时点、两组 arm 的 R REML 随机截距参考。按照 Workbench 已有 LMM 输入公式，固定项使用 arm*time+x，不把它替换为工单中仅作起点的 y~x。R 标注 `NOT cross-verified`；oracle 的推断元数据标明 Workbench unavailable。真实流水线测试保留 setup error，无 skip/xfail。没有设置执行 profile、伪造 admission、调用未受隔离保护的产品 runner 或申请沙箱绕过。

LMM 文件是待验证材料，不是可登记为已验证的准入 fixture；当前缺少 Workbench 内核、参数命名映射及数值比较证据。owner 在合法准入环境中接续时，需先核对内核与 R 项名，再完成对照，不应直接登记这份 R-only 参考。

### glm:negative_binomial：三步排查后保留超差

① 同一份 R 写入后读回的 CSV（SHA256 `33bf1067bdf7f7ca7f1bf7fb34c16fc167d9318b482f60aae8febd402b084711`），y 对 x1/x2，N=450。双方含截距、无额外行过滤。Workbench 模型为 glm:negative_binomial，不是会估计 alpha 的独立 negative_binomial 模型族。

② Workbench `GLM.fit` 默认 IRLS、tol=1e-8、maxiter=100、nonrobust；族实例默认 alpha=1.0。R 使用 MASS::negative.binomial(theta=1) 和 dispersion=1，不用会估计 theta 的 glm.nb。初次参考 epsilon=1e-14 时，最大系数差 `1.735462146212896e-07`、标准误差 `6.49303755206887e-09`。随后只把 R 名义 epsilon 对齐为 1e-8（maxit 仍为 100），没有改 Workbench 或测试容差；最终最大系数差 `4.001835530342834e-06`、标准误差 `1.5059666634564817e-07`。两次标准误均在容差内，系数均超差。

③ 最终前三个系数/标准误如下。之后不再深挖。

| 参数 | 系数 Workbench | 系数 R（epsilon=1e-8） | 标准误 Workbench | 标准误 R |
|---|---|---|---|---|
| Intercept | 0.4210052437400521 | 0.421004806491937 | 0.06192390917649085 | 0.0619237585798245 |
| x1 | 0.37898457477130565 | 0.378988576606836 | 0.06423157733626034 | 0.0642314345883351 |
| x2 | -0.22930643303336998 | -0.229305872140697 | 0.06134533797429939 | 0.0613453191328153 |

猜测：两实现的 IRLS 停止准则不同，名义 epsilon/tol 相同不等于实际停止精度相同；epsilon=1e-14 的 R 参考仍与当前产品超差。当前证据不能断言模型公式或方差方法错误。保留 `oracle_high_precision.json` 和 `pytest-high-precision-output.txt` 作为初次证据；最终默认测试使用名义精度对齐后的 oracle.json。生成器 phase=oracle_high_precision 可重建严格收敛参考，没有通过调整容差“凑通过”。

## 生成命令与依赖

全部数据使用 R `set.seed(20261003)`，300–600 行；oracle 使用写入后读回的同一 CSV。每个 R 脚本从 commandArgs 读取 owned 输出目录及 phase，精确检查目录，运行前单独打印输出目录。工单第 0 节 A01 的输出目录示例按工单 B 的 owned_files 适用为 tests/fixtures/admission/<family>/，没有写入其他目录。

对每族执行两步（先 data → 真实 Workbench 探测 → 绑定 R 设定后 oracle）：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 Rscript tests/fixtures/admission/<family>/generate_oracle.R tests/fixtures/admission/<family> data
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 Rscript tests/fixtures/admission/<family>/generate_oracle.R tests/fixtures/admission/<family> oracle
```

所有最终生成命令退出 0。首个 IV oracle 尝试因 AER 缺失退出 1；工单提供的另一 IV 实现 fixest 可用，采用 fixest 完成，没有安装软件。sandwich、jsonlite、lme4、MASS 可用。各 oracle.json 的 meta 保存 R 版本，workbench_probe.json 保存首轮真实请求、结果和完整推断核心或阻断证据。

没有调用 Stata（本工单采用 R 对照）。没有联网下载数据、调用大模型或使用 Downloads。

## 逐族测试命令与原样输出

只运行以下七个新文件，没有运行仓库全量测试或 gate。各命令从本 worktree 执行，标准输出和错误输出合并保存在对应 fixture 的 pytest-output.txt。

### iv_2sls

命令：`LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q -s tests/test_admission_oracle_iv_2sls.py`；退出码 0。

```text

Fontconfig error: No writable cache directories
	/opt/homebrew/var/cache/fontconfig
	/Users/jiayuanren/.cache/fontconfig
	/Users/jiayuanren/.fontconfig
first three coefficients and SE (Workbench / R): [('Intercept', 1.0693412648674825, 1.06934126486748, 0.049217870431445286, 0.0492178704314452), ('x1', 0.5552201253208324, 0.555220125320833, 0.052079051756544974, 0.0520790517565449), ('xe', 0.8041549151923951, 0.804154915192396, 0.05155227948506298, 0.051552279485063)]
kernel settings: {'covariance_estimator': 'robust', 'df_method': 'asymptotic', 'reference_distribution': 'z', 'df_resid': 447.0}
max absolute differences: 2.4424906541753444e-15 8.326672684688674e-17
..
2 passed in 11.17s
```

### panel_ols

命令：`LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q -s tests/test_admission_oracle_panel_ols.py`；退出码 1。

```text

Fontconfig error: No writable cache directories
	/opt/homebrew/var/cache/fontconfig
	/Users/jiayuanren/.cache/fontconfig
	/Users/jiayuanren/.fontconfig
first three coefficients and SE (Workbench / R): [('Intercept', 1.979790765819515, 1.97979076581951, 0.05234658129519699, 0.052346581295197), ('x1', 0.7127667823556812, 0.712766782355681, 0.06332817660704627, 0.0633281766070462), ('x2', -0.3891917163179698, -0.38919171631797, 0.05943168305973262, 0.0594316830597326)]
kernel settings: {'covariance_estimator': None, 'df_method': 'asymptotic', 'reference_distribution': 'z', 'df_resid': 341.0}
max absolute differences: 5.10702591327572e-15 6.938893903907228e-17
.F
=================================== FAILURES ===================================
___________ test_inference_kernel_declares_its_covariance_estimator ____________

fitted = {'contract': 'workbench.inference_kernel.v1', 'model_id': 'panel_ols_1', 'model_type': 'panel_ols', 'param_names': ['Intercept', 'x1', 'x2'], ...}

    def test_inference_kernel_declares_its_covariance_estimator(fitted):
>       assert fitted["covariance_estimator"] is not None, (
            "Admission settings cannot be bound from a null covariance_estimator", fitted)
E       AssertionError: ('Admission settings cannot be bound from a null covariance_estimator', {'contract': 'workbench.inference_kernel.v1', 'model_id': 'panel_ols_1', 'model_type': 'panel_ols', 'param_names': ['Intercept', 'x1', 'x2'], ...})
E       assert None is not None

tests/test_admission_oracle_panel_ols.py:49: AssertionError
=========================== short test summary info ============================
FAILED tests/test_admission_oracle_panel_ols.py::test_inference_kernel_declares_its_covariance_estimator
1 failed, 1 passed in 11.50s
```

### did

命令：`LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q -s tests/test_admission_oracle_did.py`；退出码 1。

```text

Fontconfig error: No writable cache directories
	/opt/homebrew/var/cache/fontconfig
	/Users/jiayuanren/.cache/fontconfig
	/Users/jiayuanren/.fontconfig
first three coefficients and SE (Workbench / R): [('Intercept', 1.2487137902084555, 1.24871379020845, 0.07035461451086605, 0.0703546145108659), ('_did_D', 0.6678496814935979, 0.667849681493604, 0.19899290003359546, 0.198992900033596)]
kernel settings: {'covariance_estimator': None, 'df_method': 'asymptotic', 'reference_distribution': 'z', 'df_resid': 198.0}
max absolute differences: 6.106226635438361e-15 5.273559366969494e-16
.F
=================================== FAILURES ===================================
___________ test_inference_kernel_declares_its_covariance_estimator ____________

fitted = {'contract': 'workbench.inference_kernel.v1', 'model_id': 'did_1', 'model_type': 'did', 'param_names': ['Intercept', '_did_D'], ...}

    def test_inference_kernel_declares_its_covariance_estimator(fitted):
>       assert fitted["covariance_estimator"] is not None, (
            "Admission settings cannot be bound from a null covariance_estimator", fitted)
E       AssertionError: ('Admission settings cannot be bound from a null covariance_estimator', {'contract': 'workbench.inference_kernel.v1', 'model_id': 'did_1', 'model_type': 'did', 'param_names': ['Intercept', '_did_D'], ...})
E       assert None is not None

tests/test_admission_oracle_did.py:49: AssertionError
=========================== short test summary info ============================
FAILED tests/test_admission_oracle_did.py::test_inference_kernel_declares_its_covariance_estimator
1 failed, 1 passed in 10.66s
```

### linear_mixed_effects

命令：`LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q -s tests/test_admission_oracle_linear_mixed_effects.py`；退出码 1。

```text
E
==================================== ERRORS ====================================
_______ ERROR at setup of test_coefficients_and_standard_errors_match_r ________

tmp_path_factory = TempPathFactory(_given_basetemp=None, _trace=<pluggy._tracing.TagTracerSub object at 0x104ac4d60>, _basetemp=PosixPath...ers/n0/0xwbb3jn2vs3lmj2rn6wn2940000gn/T/pytest-of-jiayuanren/pytest-479'), _retention_count=3, _retention_policy='all')

    @pytest.fixture(scope="module")
    def fitted(tmp_path_factory):
        project = create_project(tmp_path_factory.mktemp("oracle-linear_mixed_effects"), "oracle")
>       outcome = run_workflow(project.root, [FIXTURES / "data.csv"], mode="auto",
                               model_type='linear_mixed_effects', y='y', x=['x'], **{'model_options': {'subject_id': 'g', 'time': 'time', 'group': 'arm', 'fit_method': 'reml', 'random_slope': False}})

tests/test_admission_oracle_linear_mixed_effects.py:18: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

project_root = PosixPath('/private/var/folders/n0/0xwbb3jn2vs3lmj2rn6wn2940000gn/T/pytest-of-jiayuanren/pytest-479/oracle-linear_mixed_effects0/oracle')
input_files = [PosixPath('/Users/jiayuanren/项目规划/.worktrees/codex-v1811-admission-oracles/tests/fixtures/admission/linear_mixed_effects/data.csv')]
mode = 'auto', y = 'y', x = ['x'], model_type = 'linear_mixed_effects'
imputation = None, by_group = None, statistical_tests = None, entity_col = ''
time_col = '', covariance = '', prediction_model_type = ''
prediction_cv_folds = 0, prediction_sampling_method = ''
prediction_data_structure = None, prediction_entity_column = ''
prediction_group_column = '', prediction_time_column = ''
prediction_final_holdout_fraction = None, prediction_shuffle = None
iv_endog = None, iv_instruments = None, did_mode = '', did_cohort_col = ''
did_treat_col = '', did_post_col = '', did_status_col = ''
did_treatment_path = '', cs_control_group = '', cs_est_method = ''
cs_base_period = '', cs_anticipation = 0, cs_cluster_var = ''
honest_did = False
model_options = {'subject_id': 'g', 'time': 'time', 'group': 'arm', 'fit_method': 'reml', ...}
frequency_weight = '', analysis_weight = '', sampling_weight = ''
survey_strata_col = '', survey_psu_col = '', survey_fpc_col = ''
survey_replicate_weights = None, survey_replicate_type = ''
survey_lonely_psu = '', survey_weight_frame = '', survey_subpop = ''
labels = None, stop_reason = None

    def run_workflow(
        project_root: Path,
        input_files: list[Path],
        *,
        mode: str,
        y: str,
        x: list[str],
        model_type: str = "auto",
        imputation: dict | None = None,
        by_group: dict | None = None,
        statistical_tests: dict | None = None,
        entity_col: str = "",
        time_col: str = "",
        covariance: str = "",
        prediction_model_type: str = "",
        prediction_cv_folds: int = 0,
        prediction_sampling_method: str = "",
        prediction_data_structure: str | None = None,
        prediction_entity_column: str = "",
        prediction_group_column: str = "",
        prediction_time_column: str = "",
        prediction_final_holdout_fraction: float | None = None,
        prediction_shuffle: bool | None = None,
        iv_endog: list[str] | None = None,
        iv_instruments: list[str] | None = None,
        did_mode: str = "",
        did_cohort_col: str = "",
        did_treat_col: str = "",
        did_post_col: str = "",
        did_status_col: str = "",
        did_treatment_path: str = "",
        cs_control_group: str = "",
        cs_est_method: str = "",
        cs_base_period: str = "",
        cs_anticipation: int = 0,
        cs_cluster_var: str = "",
        honest_did: bool = False,
        model_options: dict[str, object] | None = None,
        frequency_weight: str = "",
        analysis_weight: str = "",
        sampling_weight: str = "",
        survey_strata_col: str = "",
        survey_psu_col: str = "",
        survey_fpc_col: str = "",
        survey_replicate_weights: list[str] | None = None,
        survey_replicate_type: str = "",
        survey_lonely_psu: str = "",
        survey_weight_frame: str = "",
        survey_subpop: str = "",
        labels: dict[str, object] | None = None,
        stop_reason: Callable[[], str | None] | None = None,
    ) -> dict[str, str]:
        from ..lineage.hashing import dag_hash
        from ..lineage.run_inputs import write_run_inputs
        from ..lineage.upload_store import store_upload_bytes
        from ..model_options import ModelOptionsError, bind_new_model_options
        from ..services.run_service import _normalize_labels
    
        project_root = Path(project_root)
        if model_type == "linear_mixed_effects":
            from ..services.execution_profile import (
                ExecutionProfileError,
                current_execution_profile,
            )
    
            try:
                current_execution_profile().require_lmm_admission()
            except ExecutionProfileError as error:
>               raise ModelOptionsError(
                    error.code,
                    "Linear mixed-effects execution is unavailable until explicit "
                    "local containment is admitted.",
                ) from None
E               workbench.model_options.ModelOptionsError: Linear mixed-effects execution is unavailable until explicit local containment is admitted.

backend/workbench/orchestrator/__init__.py:254: ModelOptionsError
=========================== short test summary info ============================
ERROR tests/test_admission_oracle_linear_mixed_effects.py::test_coefficients_and_standard_errors_match_r
1 error in 1.12s
```

### glm_binomial

命令：`LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q -s tests/test_admission_oracle_glm_binomial.py`；退出码 0。

```text

Fontconfig error: No writable cache directories
	/opt/homebrew/var/cache/fontconfig
	/Users/jiayuanren/.cache/fontconfig
	/Users/jiayuanren/.fontconfig
first three coefficients and SE (Workbench / R): [('Intercept', -0.43231444353779813, -0.432314443537798, 0.10342666158071165, 0.103426661580712), ('x1', 0.6946500026337908, 0.694650002633791, 0.11810398511951091, 0.118103985119511), ('x2', -0.4236990319395296, -0.42369903193953, 0.10659864633792678, 0.106598646337927)]
kernel settings: {'covariance_estimator': 'nonrobust', 'df_method': 'asymptotic', 'reference_distribution': 'z', 'df_resid': 447.0}
max absolute differences: 3.885780586188048e-16 3.469446951953614e-16
..
=============================== warnings summary ===============================
tests/test_admission_oracle_glm_binomial.py::test_coefficients_and_standard_errors_match_r
  /Users/jiayuanren/项目规划/.venv/lib/python3.14/site-packages/statsmodels/genmod/generalized_linear_model.py:1923: FutureWarning: The bic value is computed using the deviance formula. After 0.13 this will change to the log-likelihood based formula. This change has no impact on the relative rank of models compared using BIC. You can directly access the log-likelihood version using the `bic_llf` attribute. You can suppress this message by calling statsmodels.genmod.generalized_linear_model.SET_USE_BIC_LLF with True to get the LLF-based version now or False to retainthe deviance version.
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
2 passed, 1 warning in 10.63s
```

### glm_poisson

命令：`LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q -s tests/test_admission_oracle_glm_poisson.py`；退出码 0。

```text

Fontconfig error: No writable cache directories
	/opt/homebrew/var/cache/fontconfig
	/Users/jiayuanren/.cache/fontconfig
	/Users/jiayuanren/.fontconfig
first three coefficients and SE (Workbench / R): [('Intercept', 0.2969880789466367, 0.296988078946637, 0.04215178943815293, 0.0421517894402436), ('x1', 0.4025376328782477, 0.402537632878248, 0.03788760176825526, 0.0378876017691937), ('x2', -0.129016598588151, -0.129016598588151, 0.038646535651253276, 0.0386465356526668)]
kernel settings: {'covariance_estimator': 'nonrobust', 'df_method': 'asymptotic', 'reference_distribution': 'z', 'df_resid': 447.0}
max absolute differences: 3.3306690738754696e-16 2.090667916565536e-12
..
=============================== warnings summary ===============================
tests/test_admission_oracle_glm_poisson.py::test_coefficients_and_standard_errors_match_r
  /Users/jiayuanren/项目规划/.venv/lib/python3.14/site-packages/statsmodels/genmod/generalized_linear_model.py:1923: FutureWarning: The bic value is computed using the deviance formula. After 0.13 this will change to the log-likelihood based formula. This change has no impact on the relative rank of models compared using BIC. You can directly access the log-likelihood version using the `bic_llf` attribute. You can suppress this message by calling statsmodels.genmod.generalized_linear_model.SET_USE_BIC_LLF with True to get the LLF-based version now or False to retainthe deviance version.
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
2 passed, 1 warning in 11.05s
```

### glm_negative_binomial

命令：`LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q -s tests/test_admission_oracle_glm_negative_binomial.py`；退出码 1。

```text

Fontconfig error: No writable cache directories
	/opt/homebrew/var/cache/fontconfig
	/Users/jiayuanren/.cache/fontconfig
	/Users/jiayuanren/.fontconfig
first three coefficients and SE (Workbench / R): [('Intercept', 0.4210052437400521, 0.421004806491937, 0.06192390917649085, 0.0619237585798245), ('x1', 0.37898457477130565, 0.378988576606836, 0.06423157733626034, 0.0642314345883351), ('x2', -0.22930643303336998, -0.229305872140697, 0.06134533797429939, 0.0613453191328153)]
kernel settings: {'covariance_estimator': 'nonrobust', 'df_method': 'asymptotic', 'reference_distribution': 'z', 'df_resid': 447.0}
max absolute differences: 4.001835530342834e-06 1.5059666634564817e-07
F.
=================================== FAILURES ===================================
________________ test_coefficients_and_standard_errors_match_r _________________

fitted = {'contract': 'workbench.inference_kernel.v1', 'model_id': 'glm_1', 'model_type': 'glm', 'param_names': ['Intercept', 'x1', 'x2'], ...}

    def test_coefficients_and_standard_errors_match_r(fitted):
        names = fitted["param_names"]
        assert set(names) == set(ORACLE["coefficients"]), (names, ORACLE["coefficients"])
        assert fitted["nobs"] == ORACLE["meta"]["n"]
        rows = []
        for index, term in enumerate(names):
            rows.append((term, fitted["params"][index], ORACLE["coefficients"][term],
                         math.sqrt(fitted["vcov"][index][index]), ORACLE["std_error"][term]))
        print("first three coefficients and SE (Workbench / R):", rows[:3])
        print("kernel settings:", {key: fitted.get(key) for key in (
            "covariance_estimator", "df_method", "reference_distribution", "df_resid")})
        print("max absolute differences:", max(abs(a-b) for _,a,b,_,_ in rows),
              max(abs(a-b) for _,_,_,a,b in rows))
        errors = []
        for term, estimate, reference, se, reference_se in rows:
            if abs(estimate-reference) > 1e-8:
                errors.append((term, "estimate", estimate, reference, estimate-reference))
            # LMM's 1e-4 allowance is exclusively for REML optimizer differences.
            if abs(se-reference_se) > 1e-06:
                errors.append((term, "std_error", se, reference_se, se-reference_se))
>       assert not errors, errors
E       AssertionError: [('Intercept', 'estimate', 0.4210052437400521, 0.421004806491937, 4.3724811510381656e-07), ('x1', 'estimate', 0.378984...6606836, -4.001835530342834e-06), ('x2', 'estimate', -0.22930643303336998, -0.229305872140697, -5.608926729738783e-07)]
E       assert not [('Intercept', 'estimate', 0.4210052437400521, 0.421004806491937, 4.3724811510381656e-07), ('x1', 'estimate', 0.378984...6606836, -4.001835530342834e-06), ('x2', 'estimate', -0.22930643303336998, -0.229305872140697, -5.608926729738783e-07)]

tests/test_admission_oracle_glm_negative_binomial.py:45: AssertionError
------------------------------ Captured log setup ------------------------------
WARNING  matplotlib:__init__.py:577 /Users/jiayuanren/.matplotlib is not a writable directory
WARNING  matplotlib:__init__.py:593 Matplotlib created a temporary cache directory at /var/folders/n0/0xwbb3jn2vs3lmj2rn6wn2940000gn/T/matplotlib-ktw635zb because there was an issue with the default path ({configdir}); it is highly recommended to set the MPLCONFIGDIR environment variable to a writable directory, in particular to speed up the import of Matplotlib and to better support multiprocessing.
WARNING  matplotlib.font_manager:font_manager.py:1249 Matplotlib is building the font cache; this may take a moment.
=============================== warnings summary ===============================
tests/test_admission_oracle_glm_negative_binomial.py::test_coefficients_and_standard_errors_match_r
  /Users/jiayuanren/项目规划/.venv/lib/python3.14/site-packages/statsmodels/genmod/families/family.py:1367: ValueWarning: Negative binomial dispersion parameter alpha not set. Using default value alpha=1.0.
    warnings.warn("Negative binomial dispersion parameter alpha not "

tests/test_admission_oracle_glm_negative_binomial.py::test_coefficients_and_standard_errors_match_r
  /Users/jiayuanren/项目规划/.venv/lib/python3.14/site-packages/statsmodels/genmod/generalized_linear_model.py:1923: FutureWarning: The bic value is computed using the deviance formula. After 0.13 this will change to the log-likelihood based formula. This change has no impact on the relative rank of models compared using BIC. You can directly access the log-likelihood version using the `bic_llf` attribute. You can suppress this message by calling statsmodels.genmod.generalized_linear_model.SET_USE_BIC_LLF with True to get the LLF-based version now or False to retainthe deviance version.
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_admission_oracle_glm_negative_binomial.py::test_coefficients_and_standard_errors_match_r
1 failed, 1 passed, 2 warnings in 10.40s
```

## 初次高精度负二项对照输出（原样）

此输出来自 R epsilon=1e-14，保留作为三步排查的初次证据，不与最终 oracle.json 混用。

```text

Fontconfig error: No writable cache directories
	/opt/homebrew/var/cache/fontconfig
	/Users/jiayuanren/.cache/fontconfig
	/Users/jiayuanren/.fontconfig
first three coefficients and SE (Workbench / R): [('Intercept', 0.4210052437400521, 0.421005262702078, 0.06192390917649085, 0.0619239156695284), ('x1', 0.37898457477130565, 0.378984401225091, 0.06423157733626034, 0.0642315834973829), ('x2', -0.22930643303336998, -0.229306456886556, 0.06134533797429939, 0.0613453387527558)]
kernel settings: {'covariance_estimator': 'nonrobust', 'df_method': 'asymptotic', 'reference_distribution': 'z', 'df_resid': 447.0}
max absolute differences: 1.735462146212896e-07 6.49303755206887e-09
F.
=================================== FAILURES ===================================
________________ test_coefficients_and_standard_errors_match_r _________________

fitted = {'contract': 'workbench.inference_kernel.v1', 'model_id': 'glm_1', 'model_type': 'glm', 'param_names': ['Intercept', 'x1', 'x2'], ...}

    def test_coefficients_and_standard_errors_match_r(fitted):
        names = fitted["param_names"]
        assert set(names) == set(ORACLE["coefficients"]), (names, ORACLE["coefficients"])
        assert fitted["nobs"] == ORACLE["meta"]["n"]
        rows = []
        for index, term in enumerate(names):
            rows.append((term, fitted["params"][index], ORACLE["coefficients"][term],
                         math.sqrt(fitted["vcov"][index][index]), ORACLE["std_error"][term]))
        print("first three coefficients and SE (Workbench / R):", rows[:3])
        print("kernel settings:", {key: fitted.get(key) for key in (
            "covariance_estimator", "df_method", "reference_distribution", "df_resid")})
        print("max absolute differences:", max(abs(a-b) for _,a,b,_,_ in rows),
              max(abs(a-b) for _,_,_,a,b in rows))
        errors = []
        for term, estimate, reference, se, reference_se in rows:
            if abs(estimate-reference) > 1e-8:
                errors.append((term, "estimate", estimate, reference, estimate-reference))
            # LMM's 1e-4 allowance is exclusively for REML optimizer differences.
            if abs(se-reference_se) > 1e-06:
                errors.append((term, "std_error", se, reference_se, se-reference_se))
>       assert not errors, errors
E       AssertionError: [('Intercept', 'estimate', 0.4210052437400521, 0.421005262702078, -1.8962025893909384e-08), ('x1', 'estimate', 0.37898...01225091, 1.735462146212896e-07), ('x2', 'estimate', -0.22930643303336998, -0.229306456886556, 2.3853186009725746e-08)]
E       assert not [('Intercept', 'estimate', 0.4210052437400521, 0.421005262702078, -1.8962025893909384e-08), ('x1', 'estimate', 0.37898...01225091, 1.735462146212896e-07), ('x2', 'estimate', -0.22930643303336998, -0.229306456886556, 2.3853186009725746e-08)]

tests/test_admission_oracle_glm_negative_binomial.py:45: AssertionError
------------------------------ Captured log setup ------------------------------
WARNING  matplotlib:__init__.py:577 /Users/jiayuanren/.matplotlib is not a writable directory
WARNING  matplotlib:__init__.py:593 Matplotlib created a temporary cache directory at /var/folders/n0/0xwbb3jn2vs3lmj2rn6wn2940000gn/T/matplotlib-8cto8o05 because there was an issue with the default path ({configdir}); it is highly recommended to set the MPLCONFIGDIR environment variable to a writable directory, in particular to speed up the import of Matplotlib and to better support multiprocessing.
WARNING  matplotlib.font_manager:font_manager.py:1249 Matplotlib is building the font cache; this may take a moment.
=============================== warnings summary ===============================
tests/test_admission_oracle_glm_negative_binomial.py::test_coefficients_and_standard_errors_match_r
  /Users/jiayuanren/项目规划/.venv/lib/python3.14/site-packages/statsmodels/genmod/families/family.py:1367: ValueWarning: Negative binomial dispersion parameter alpha not set. Using default value alpha=1.0.
    warnings.warn("Negative binomial dispersion parameter alpha not "

tests/test_admission_oracle_glm_negative_binomial.py::test_coefficients_and_standard_errors_match_r
  /Users/jiayuanren/项目规划/.venv/lib/python3.14/site-packages/statsmodels/genmod/generalized_linear_model.py:1923: FutureWarning: The bic value is computed using the deviance formula. After 0.13 this will change to the log-likelihood based formula. This change has no impact on the relative rank of models compared using BIC. You can directly access the log-likelihood version using the `bic_llf` attribute. You can suppress this message by calling statsmodels.genmod.generalized_linear_model.SET_USE_BIC_LLF with True to get the LLF-based version now or False to retainthe deviance version.
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_admission_oracle_glm_negative_binomial.py::test_coefficients_and_standard_errors_match_r
1 failed, 1 passed, 2 warnings in 11.21s
```

## 提交与精确文件清单（ADR-PD-001 §10.2）

每族完成即单独提交，提交消息均带 Co-Authored-By: Codex；不存在 push/merge/tag。最后报告另作一个提交。

```text
bf49a70b test(eval): IV admission oracle against fixest HC0
6ed7bcbf test(eval): panel TWFE R oracle and missing kernel covariance
21592d50 test(eval): DID TWFE oracle and missing inference declaration
f0f8da21 test(eval): binomial GLM R admission oracle
c2dbc26f test(eval): provisional REML oracle with containment blocker evidence
5e431e18 test(eval): Poisson GLM R admission oracle
4586881b test(eval): fixed-alpha NB oracle and bounded convergence mismatch
```

```text
tests/fixtures/admission/did/data.csv
tests/fixtures/admission/did/generate_oracle.R
tests/fixtures/admission/did/oracle.json
tests/fixtures/admission/did/pytest-output.txt
tests/fixtures/admission/did/workbench_probe.json
tests/fixtures/admission/glm_binomial/data.csv
tests/fixtures/admission/glm_binomial/generate_oracle.R
tests/fixtures/admission/glm_binomial/oracle.json
tests/fixtures/admission/glm_binomial/pytest-output.txt
tests/fixtures/admission/glm_binomial/workbench_probe.json
tests/fixtures/admission/glm_negative_binomial/data.csv
tests/fixtures/admission/glm_negative_binomial/generate_oracle.R
tests/fixtures/admission/glm_negative_binomial/oracle.json
tests/fixtures/admission/glm_negative_binomial/oracle_high_precision.json
tests/fixtures/admission/glm_negative_binomial/pytest-high-precision-output.txt
tests/fixtures/admission/glm_negative_binomial/pytest-output.txt
tests/fixtures/admission/glm_negative_binomial/workbench_probe.json
tests/fixtures/admission/glm_poisson/data.csv
tests/fixtures/admission/glm_poisson/generate_oracle.R
tests/fixtures/admission/glm_poisson/oracle.json
tests/fixtures/admission/glm_poisson/pytest-output.txt
tests/fixtures/admission/glm_poisson/workbench_probe.json
tests/fixtures/admission/iv_2sls/data.csv
tests/fixtures/admission/iv_2sls/generate_oracle.R
tests/fixtures/admission/iv_2sls/oracle.json
tests/fixtures/admission/iv_2sls/pytest-output.txt
tests/fixtures/admission/iv_2sls/workbench_probe.json
tests/fixtures/admission/linear_mixed_effects/data.csv
tests/fixtures/admission/linear_mixed_effects/generate_oracle.R
tests/fixtures/admission/linear_mixed_effects/oracle.json
tests/fixtures/admission/linear_mixed_effects/pytest-output.txt
tests/fixtures/admission/linear_mixed_effects/workbench_probe.json
tests/fixtures/admission/panel_ols/data.csv
tests/fixtures/admission/panel_ols/generate_oracle.R
tests/fixtures/admission/panel_ols/oracle.json
tests/fixtures/admission/panel_ols/pytest-output.txt
tests/fixtures/admission/panel_ols/workbench_probe.json
tests/test_admission_oracle_did.py
tests/test_admission_oracle_glm_binomial.py
tests/test_admission_oracle_glm_negative_binomial.py
tests/test_admission_oracle_glm_poisson.py
tests/test_admission_oracle_iv_2sls.py
tests/test_admission_oracle_linear_mixed_effects.py
tests/test_admission_oracle_panel_ols.py
```

另新增本报告：`docs/superpowers/handoffs/2026-10-04-codex-v1811-admission-oracles-report.md`。所有持久化变更均在工单 B owned_files，产品代码、合同、准入登记、已有测试/golden/容差均无改动；未创建/刷新合同 lock 或正式开发线，台账仍由 Claude 负责。

## 限制、集成风险与接续

每份 fixture 只验证本次显式记录的模型/协方差/参数组合，不代表该模型族所有变体。通过数值对照也不是 provider、浏览器、模型全量或发版 gate 验收。

当前可供 owner 考虑登记的是 IV 的 robust(HC0)、GLM binomial/Poisson 的非稳健协方差三组。面板/DID 的数值材料可用，但核心声明未决；负二项有超差；LMM 无产品侧估计。应先解决后四族的声明/收敛/准入问题并重跑对应新文件，再作 admission.py 登记；本分支不能被描述为七族全部准入通过。

原始输出包含 Fontconfig/Matplotlib 沙箱缓存警告及 GLM BIC FutureWarning，均未抑制或绕过；通过项仍退出 0。原始 traceback 的行尾空格按原样保留，仅在日志/报告内，不是产品代码修改。

建议集成 owner 逐族取对应测试/fixture 提交，最后取报告；失败/阻断测试需保留并按证据处理，不应 skip/xfail 或调整已有容差。回滚由 owner 撤销对应新增文件提交，不修改产品线或已有 golden。正式 devline 记录由 Claude 补充。

事故：无误写产品或已有文件。AER 缺失属于已记录的依赖限制，使用工单允许的 fixest 替代。

范围外观察：无。

## 最后范围核验

验证七组 fixture（每组脚本/data/oracle/首轮探测/测试输出）、七个新增测试文件、300–600 行及 oracle N 一致；基线相对差分中 backend/frontend/scripts/.agent 和点名已有测试均无变化，全部修改在工单 B owned_files。源脚本与测试的 `git diff --check 65d771b0ce -- 'tests/test_admission_oracle_*.py' 'tests/fixtures/admission/*/generate_oracle.R'` 退出 0。全路径 diff-check 的退出 2 仅涉及原样 pytest traceback/log 和本报告代码块中的行尾空格，这些输出为保留精确证据而不清洗；源文件末尾空行已移除，不改变测试或 R 计算。
