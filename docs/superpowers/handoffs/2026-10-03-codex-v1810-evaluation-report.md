# 工单 A：v1.8.10 第 5–8 步独立对抗评估报告

完成日期：2026-10-04。分支 `eval/v1810-codex`；worktree `/Users/jiayuanren/项目规划/.worktrees/codex-v1810-evaluation`；精确基线 `65d771b0ceb3898728523d07a9324000b4de4fff`。只执行工单 A；工单 B 未执行。

14 项已执行：通过 10 项，缺陷 4 项（A01、A03、A04、A14），未决 0 项，阻断 0 项。这里“缺陷”按工单规则表示可复现验收断言失败；A01 是很小的数值超差，A04 是空值字段形状，两者不能表述为已证实统计方法错误或数值泄露。

## 事故

2026-10-03 路径替换因 locale 失败后，复制的 R 脚本误写已有 multiple_imputation fixture；内容与基线完全一致，用户已核实结案，无需恢复，按更新规则继续。

## 总表与逐项复现

所有命令从本评估 worktree 运行。前端命令的工作目录为其中的 `frontend`。命令前的 UTF-8 环境变量是本机中文路径所需。

| 编号 | 结果（通过 / 缺陷 / 未决 / 阻断） | 测试文件 | 一句话说明 | 复现命令 |
|---|---|---|---|---|
| A01 | 缺陷 | `tests/eval_v1810/test_a01_pool_extremes.py` | m=20 logit 的 x2 p 值略超 1e-7 相对容差；其余 5 个组合通过 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a01_pool_extremes.py` |
| A02 | 通过 | `tests/eval_v1810/test_a02_categorical_imputation.py` | 完整/缺失字符串分类列均明确拒绝，无静默丢行 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a02_categorical_imputation.py` |
| A03 | 缺陷 | `tests/eval_v1810/test_a03_imputation_by_group.py` | 直接请求两种组合子时只做插补合并，未披露忽略 by_group | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a03_imputation_by_group.py` |
| A04 | 缺陷 | `tests/eval_v1810/test_a04_pooled_projections.py` | 两份投影均保留 r_squared/r_squared_adj 空值字段，违反字段不出现要求 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a04_pooled_projections.py` |
| A05 | 通过 | `tests/eval_v1810/test_a05_hac_lag_zero.py` | HAC 滞后 0 的所有标准误等于 HC1 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a05_hac_lag_zero.py` |
| A06 | 通过 | `tests/eval_v1810/test_a06_hac_dates.py` | 季度通过，缺月拒绝；混合日期写法变为缺失后明确拒绝 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a06_hac_dates.py` |
| A07 | 通过 | `tests/eval_v1810/test_a07_hac_by_group.py` | HAC 按组成功，east 组系数及标准误与 R 一致 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a07_hac_by_group.py` |
| A08 | 通过 | `tests/eval_v1810/test_a08_group_values.py` | 数值、布尔、值+缺失均保留分组与行；全缺失拒绝 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a08_group_values.py` |
| A09 | 通过 | `tests/eval_v1810/test_a09_group_limit.py` | 50 组全部可估计，51 组明确拒绝 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a09_group_limit.py` |
| A10 | 通过 | `tests/eval_v1810/test_a10_logit_separation.py` | 完全分离组无法估计，其他组继续，差异检验仅用 600 行 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a10_logit_separation.py` |
| A11 | 通过 | `tests/eval_v1810/test_a11_survey_intersection.py` | 3 组的原子总体与组交集，与 Stata 系数/标准误一致 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a11_survey_intersection.py` |
| A12 | 通过 | `tests/eval_v1810/test_a12_ttest_single_category.py` | t 检验单类别组无法估计，其他两组继续 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a12_ttest_single_category.py` |
| A13 | 通过 | `tests/eval_v1810/test_a13_ledger_count.py` | 持久化台账在 list/mapping 状态下分别增加 k=2/7/50 | `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810/test_a13_ledger_count.py` |
| A14 | 缺陷 | `frontend/src/workbench/agent/__eval__/focus.eval.test.ts` | 共享节点和找不到的数据集通过；不存在运行没有回退当前链 | `npx --no-install vitest run src/workbench/agent/__eval__` |

独立逐项运行结果（均为退出码 0，标注 failed 的为退出码 1）：

- A01：`1 failed, 5 passed in 48.19s；最终组合重跑仍为同一失败`。
- A02：`2 passed in 1.32s`。
- A03：`1 failed in 9.97s`。
- A04：`1 failed in 10.70s`。
- A05：`1 passed in 10.48s`。
- A06：`3 passed in 9.84s`。
- A07：`1 passed in 9.88s`。
- A08：`7 passed in 10.46s`。
- A09：`2 passed in 10.34s`。
- A10：`1 passed, 2 warnings in 9.60s`。
- A11：`1 passed in 10.34s`。
- A12：`1 passed in 0.82s`。
- A13：`6 passed in 1.29s`。
- A14：`1 failed, 2 passed；Duration 572ms`。

## 缺陷证据与核验边界

### A01：m=20 logit 的小 p 值相对误差超限

Workbench `x2` p 值为 `5.1028874281546085e-05`，R 为 `5.10288669984066e-05`，绝对差约 `7.283139485e-12`，相对差约 `1.42726e-7`。保留 `1e-7` 容差，没有 xfail/skip。区间端点采用纯绝对界限 `1e-7 × 标准误`。

已按规定做三步排查后停止：① 双方读取同一组 R 生成的 20 份 CSV，结局 yb，自变量 x1/x2/x3，N=300；② Workbench 内核为 nonrobust、asymptotic、z，R 为 binomial 默认模型协方差，`glm.control(epsilon=1e-14, maxit=100)`，两边合并 dfcom 都为无穷，Barnard–Rubin 规则一致；③ 前三个合并系数与标准误如下（Workbench / R）：

| 参数 | 系数 Workbench | 系数 R | 标准误 Workbench | 标准误 R |
|---|---|---|---|---|
| Intercept | -0.2986814668339129 | -0.298681466833912 | 0.13024156117656824 | 0.130241560289853 |
| x1 | 1.0589359689045963 | 1.05893596890459 | 0.1796403172055777 | 0.179640314934678 |
| x2 | -0.5902789349025088 | -0.590278934902508 | 0.1451093513698985 | 0.145109350143744 |

猜测：R glm 与 statsmodels 的最终协方差数值精度差异被很小的 p 值放大；这是猜测，未进一步定位根因。Workbench 的优化器精度不改；R 已使用工单参考脚本的严格收敛设置，没有用另一种估计器凑数。m=2 的三种组合及 m=20 两种 OLS 都通过。OLS 对照覆盖 unadjusted 和 robust/HC1；后者也是 Workbench 的默认协方差。

### A03：直接运行静默忽略 by_group

输入同时包含 `imputation={method: mice, m: 2}` 与 `by_group={column: region}`。运行 completed，`imputation_summary.json` 为 multiple_imputation、pooled_estimates=true、pooling_model_ids=[ols_1]、warnings=[]；`model_results/collections/by_group.json` 不存在，errors.json 未说明组合冲突或忽略了按组执行。最终重跑 run id 为 `20261004_102936_465655_0146f158`。这项证据来自直接调用 run_workflow，不借用 Agent 规划阶段已有的拒绝行为。

### A04：投影保留空值 R² 字段

真实 m=2 合并结果通过 `_bounded_persisted_model_facts` 和 `_public_requested_model_coefficients` 后，两份投影都包含 `r_squared: None` 与 `r_squared_adj: None`。测试按工单“不出现 r_squared、残差”要求检查字段缺席，因此失败。两份投影未出现 residuals/fitted_values 字段；没有发现单份数据的 R² 或残差数值被泄露。若产品将 null 视为符合“不报告”，需要由 owner 明确字段合同；本评估不自行放宽断言。

### A14：不存在的运行仍成为 Agent 作用运行

`run:run_absent` 不在森林 heads 或 nodes 中，当前运行是 run_active。按第 8 步文档“森林里找不到的选中项沿用当前运行链，不带节点”写断言，预期 run_active/chain/null；实际为 run_absent/chain/null。失败保留；共享节点选择运行族头部、找不到数据集时不虚构节点的两个边界通过。本测试核验纯 focus 解析，未声称完成浏览器或 Agent 会话端到端验收。

## 通过项的行为记录

- A02：分类列完整时拒绝为 MI_IMPUTATION_FAILED，说明选中的 y/x1 未能全部填充，不持久化部分插补数据；分类列自身有缺失时拒绝并点名 category。证明明确拒绝路径，不表示分类列插补支持成功。
- A05：同一 HAC fixture 分别运行 hac_lags=0 与 covariance=robust，逐项标准误一致（1e-10）。
- A06：季度日期 completed；缺月拒绝 OLS_HAC_TIME_GAPS（不均匀频率/缺口）；混合 `YYYY-MM-DD` 与 `YYYY/MM/DD` 的输入有 50% 日期被转成缺失，HIGH_MISSING_RATE 后以 OLS_HAC_TIME_ORDER_MISSING_VALUES 拒绝。这是实际行为记录，没有声称支持混合格式。
- A07：跨组重复时间、全表打乱行序，每组 independently 排序后可运行；east 组系数/标准误与 R `NeweyWest(lag=4, prewhite=FALSE, adjust=TRUE)` 一致（1e-9）。未将跨组差异检验当成 HAC 的外部对照。
- A08：plan_groups 掩码覆盖及真实流水线都核验数值 1.0/2.0、布尔、单值+缺失；全缺失通过组合子拒绝断言。
- A09：每组 30 行、一个自变量，50 组全部估计，51 组明确拒绝。
- A10：分离组 300 行，其他两组各 300 行；分离组 not_estimable 且有 reason，其余估计，差异结果 N=600，不含被排除组项。statsmodels 分离/不收敛警告是预期对抗输入产生，未屏蔽。
- A11：900 行模拟抽样设计，原条件 eligible==1；三组均与 Stata `svy, subpop(if eligible==1 & region=="x"): regress y x` 的斜率、截距和标准误一致（系数 1e-9、标准误 1e-8）。CSV 用 asdouble。只比较系数和标准误，没有比较 p 值或自由度；额外断言每组子总体行数等于交集。
- A12：单类别组标 not_estimable 且有 reason，两组仍正常检验，不留下无法估计组的结果行。
- A13：真实 `_record_operation_in_ledger` 写入与 analysis_ledger.read 读回；k=2/7/50，workflow_state.steps 的 list 和 mapping 形式均精确增加 k。

## 命令与外部对照

生成脚本运行前先打印 owned 输出目录，再单独运行每条命令（R 内部也打印并检查输出前缀）；不使用 perl/sed 修改脚本、不安装软件。

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 Rscript tests/fixtures/eval_v1810/a01/generate_oracle.R tests/fixtures/eval_v1810/a01/m2 2
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 Rscript tests/fixtures/eval_v1810/a01/generate_oracle.R tests/fixtures/eval_v1810/a01/m20 20
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 Rscript tests/fixtures/eval_v1810/a07/generate_oracle.R tests/fixtures/eval_v1810/a07
```

三条生成命令均退出 0。A01 的大样本警告来自 logit dfcom=Inf，是对齐 z 推断的有意设置。mice::pool 的常规 OLS/logit 与继承脚本中的 mice:::pool.vector 交叉核验，HC1 使用后者，未使用 Workbench 生成 R 真值。

## 本次新增 Python 测试汇总原样输出

命令：`LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/eval_v1810`。退出码 1。仅包含本工单新增测试目录，不是仓库全量测试。

```text
.F......FF.......................                                        [100%]
=================================== FAILURES ===================================
________________ test_pooled_results_match_mice_pool[logit-20] _________________

kernels = <function kernels.<locals>.fitted at 0x11b02b3d0>, case = 'logit'
m = 20

    @pytest.mark.parametrize("m", [2, 20])
    @pytest.mark.parametrize("case", sorted(CASES))
    def test_pooled_results_match_mice_pool(kernels, case: str, m: int) -> None:
        fitted = kernels(case, m)
        require_poolable(fitted[0]["model_type"], fitted[0])
        pooled = pool_kernels(fitted)
        expected = json.loads((FIXTURES / f"m{m}" / "oracle.json").read_text())["cases"][case]
        print("case/data/formula", case, m, str(FIXTURES / f"m{m}"), CASES[case], ["x1", "x2", "x3"])
        print("kernel settings", {key: fitted[0].get(key) for key in (
            "covariance_estimator", "df_method", "reference_distribution", "df_resid", "nobs")})
        print("first three pooled coefficients and standard errors", [
            (term, pooled["terms"][term]["estimate"], reference["estimate"],
             pooled["terms"][term]["std_error"], reference["std_error"])
            for term, reference in list(expected["terms"].items())[:3]])
        tolerance = 1e-7
        dfcom = expected["dfcom"]
        assert pooled["dfcom"] == (None if dfcom == "Inf" else pytest.approx(dfcom))
        assert set(pooled["terms"]) == set(expected["terms"])
        for term, reference in expected["terms"].items():
            ours = pooled["terms"][term]
            for ours_key, ref_key in (
                ("estimate", "estimate"), ("within_variance", "ubar"), ("between_variance", "b"),
                ("total_variance", "t"), ("std_error", "std_error"), ("df", "df"), ("riv", "riv"),
                ("lambda", "lambda"), ("fmi", "fmi"), ("statistic", "statistic"), ("p_value", "p_value"),
                ("ci_lower", "ci_lower"), ("ci_upper", "ci_upper"),
            ):
                # An interval endpoint can sit near zero, where a relative tolerance
                # magnifies the optimiser's last digits; measure it on the scale of
                # its standard error instead.
                absolute = tolerance * reference["std_error"] if ref_key.startswith("ci_") else 1e-12
                relative = 0.0 if ref_key.startswith("ci_") else tolerance
>               assert ours[ours_key] == pytest.approx(reference[ref_key], rel=relative, abs=absolute), (
                    f"{case} {term} {ours_key}"
                )
E               AssertionError: logit x2 p_value
E               assert 5.1028874281546085e-05 == 5.10288669984066e-05 ± 5.1e-12
E                 
E                 comparison failed
E                 Obtained: 5.1028874281546085e-05
E                 Expected: 5.10288669984066e-05 ± 5.1e-12

tests/eval_v1810/test_a01_pool_extremes.py:87: AssertionError
----------------------------- Captured stdout call -----------------------------
case/data/formula logit 20 /Users/jiayuanren/项目规划/.worktrees/codex-v1810-evaluation/tests/fixtures/eval_v1810/a01/m20 ('logit', 'yb', {}) ['x1', 'x2', 'x3']
kernel settings {'covariance_estimator': 'nonrobust', 'df_method': 'asymptotic', 'reference_distribution': 'z', 'df_resid': 296.0, 'nobs': 300}
first three pooled coefficients and standard errors [('Intercept', -0.2986814668339129, -0.298681466833912, 0.13024156117656824, 0.130241560289853), ('x1', 1.0589359689045963, 1.05893596890459, 0.1796403172055777, 0.179640314934678), ('x2', -0.5902789349025088, -0.590278934902508, 0.1451093513698985, 0.145109350143744)]
_____________ test_direct_request_discloses_or_refuses_combination _____________

tmp_path = PosixPath('/private/var/folders/n0/0xwbb3jn2vs3lmj2rn6wn2940000gn/T/pytest-of-jiayuanren/pytest-468/test_direct_request_discloses_0')

    def test_direct_request_discloses_or_refuses_combination(tmp_path):
        frame = pd.read_csv(Path(__file__).parents[1] / "fixtures/multiple_imputation/data.csv")
        frame["region"] = ["east" if i % 2 else "west" for i in range(len(frame))]
        path = tmp_path / "combined.csv"
        frame.to_csv(path, index=False)
        project = create_project(tmp_path, "combined")
        result = run_workflow(project.root, [path], mode="auto", model_type="ols", y="y", x=["x1", "x3"],
                              imputation={"method": "mice", "m": 2}, by_group={"column": "region"})
        root = project.root / "runs" / result["run_id"]
        if result["status"] in {"failed", "blocked"}:
            issues = read_json(root / "errors.json")["issues"]
            assert any("imput" in i["message"].lower() and "group" in i["message"].lower() for i in issues), issues
        else:
            assert result["status"] == "completed"
            evidence = json.dumps(read_json(root / "errors.json"), ensure_ascii=False)
>           assert "imput" in evidence.lower() and "group" in evidence.lower(), (
                "Both requested; completed without disclosing which combinator was omitted", result, evidence)
E           AssertionError: ('Both requested; completed without disclosing which combinator was omitted', {'run_id': '20261004_102936_465655_0146f...s": {}, "recommended_action_key": "", "is_user_action_required": false}], "superseded_by": "diagnostic_summary.json"}')
E           assert ('imput' in '{"schema_version": "legacy", "run_id": "20261004_102936_465655_0146f158", "issues": [{"severity": "info", "code": "ca...ms": {}, "recommended_action_key": "", "is_user_action_required": false}], "superseded_by": "diagnostic_summary.json"}')
E            +  where '{"schema_version": "legacy", "run_id": "20261004_102936_465655_0146f158", "issues": [{"severity": "info", "code": "ca...ms": {}, "recommended_action_key": "", "is_user_action_required": false}], "superseded_by": "diagnostic_summary.json"}' = <built-in method lower of str object at 0x11e037bb0>()
E            +    where <built-in method lower of str object at 0x11e037bb0> = '{"schema_version": "legacy", "run_id": "20261004_102936_465655_0146f158", "issues": [{"severity": "INFO", "code": "CA...ms": {}, "recommended_action_key": "", "is_user_action_required": false}], "superseded_by": "diagnostic_summary.json"}'.lower

tests/eval_v1810/test_a03_imputation_by_group.py:27: AssertionError
----------------------------- Captured stderr call -----------------------------
/Users/runner/work/crossbow/crossbow/arrow/cpp/src/arrow/util/cpu_info.cc:242: IOError: sysctlbyname failed for 'hw.l1dcachesize'. Detail: [errno 1] Operation not permitted
/Users/runner/work/crossbow/crossbow/arrow/cpp/src/arrow/util/cpu_info.cc:242: IOError: sysctlbyname failed for 'hw.l2cachesize'. Detail: [errno 1] Operation not permitted
/Users/runner/work/crossbow/crossbow/arrow/cpp/src/arrow/util/cpu_info.cc:242: IOError: sysctlbyname failed for 'hw.l3cachesize'. Detail: [errno 1] Operation not permitted
/Users/runner/work/crossbow/crossbow/arrow/cpp/src/arrow/util/cpu_info.cc:242: IOError: sysctlbyname failed for 'hw.optional.neon'. Detail: [errno 1] Operation not permitted
_________ test_pooled_projections_have_no_r_squared_or_residual_values _________

tmp_path = PosixPath('/private/var/folders/n0/0xwbb3jn2vs3lmj2rn6wn2940000gn/T/pytest-of-jiayuanren/pytest-468/test_pooled_projections_have_n0')

    def test_pooled_projections_have_no_r_squared_or_residual_values(tmp_path):
        project = create_project(tmp_path, "projection")
        source = Path(__file__).parents[1] / "fixtures/multiple_imputation/data.csv"
        result = run_workflow(project.root, [source], mode="auto", model_type="ols", y="y", x=["x1", "x2", "x3"],
                              imputation={"method": "mice", "m": 2})
        root = project.root / "runs" / result["run_id"]
        assert result["status"] == "completed"
        packet = read_json(root / "model_results/ols_1.json")
        views = [_bounded_persisted_model_facts([packet], run_root=root)[0],
                 _public_requested_model_coefficients(run_id=result["run_id"], result=packet, requested_terms=("x1",))]
        def inspect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    assert key not in {"r_squared", "r_squared_adj", "residuals", "fitted_values"}, (key, child)
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        for view in views:
            assert view["multiple_imputation"]["m"] == 2
>           inspect(view)

tests/eval_v1810/test_a04_pooled_projections.py:30: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

value = {'model_id': 'ols_1', 'nobs': 300, 'nobs_basis': 'rows', 'r_squared': None, ...}

    def inspect(value):
        if isinstance(value, dict):
            for key, child in value.items():
>               assert key not in {"r_squared", "r_squared_adj", "residuals", "fitted_values"}, (key, child)
E               AssertionError: ('r_squared', None)
E               assert 'r_squared' not in {'fitted_values', 'r_squared', 'r_squared_adj', 'residuals'}

tests/eval_v1810/test_a04_pooled_projections.py:23: AssertionError
=============================== warnings summary ===============================
tests/eval_v1810/test_a10_logit_separation.py::test_separated_group_is_not_estimable_and_excluded_from_differences
  /Users/jiayuanren/项目规划/.venv/lib/python3.14/site-packages/statsmodels/discrete/discrete_model.py:227: PerfectSeparationWarning: Perfect separation or prediction detected, parameter may not be identified
    warnings.warn(msg, category=PerfectSeparationWarning)

tests/eval_v1810/test_a10_logit_separation.py::test_separated_group_is_not_estimable_and_excluded_from_differences
  /Users/jiayuanren/项目规划/.venv/lib/python3.14/site-packages/statsmodels/base/model.py:607: ConvergenceWarning: Maximum Likelihood optimization failed to converge. Check mle_retvals
    warnings.warn("Maximum Likelihood optimization failed to "

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/eval_v1810/test_a01_pool_extremes.py::test_pooled_results_match_mice_pool[logit-20]
FAILED tests/eval_v1810/test_a03_imputation_by_group.py::test_direct_request_discloses_or_refuses_combination
FAILED tests/eval_v1810/test_a04_pooled_projections.py::test_pooled_projections_have_no_r_squared_or_residual_values
3 failed, 30 passed, 2 warnings in 54.88s
```

## 前端测试原样输出

命令（frontend 工作目录）：`npx --no-install vitest run src/workbench/agent/__eval__`。退出码 1，使用已有 node_modules，未下载依赖。

```text

 RUN  v2.1.9 /Users/jiayuanren/项目规划/.worktrees/codex-v1810-evaluation/frontend

 ❯ src/workbench/agent/__eval__/focus.eval.test.ts (3 tests | 1 failed) 5ms
   × A14 focus boundaries > uses the unresolved-node fallback for a nonexistent run rail selection 4ms
     → expected { focus: { kind: 'node', …(2) }, …(5) } to match object { runId: 'run_active', …(2) }
(6 matching properties omitted from actual)

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/workbench/agent/__eval__/focus.eval.test.ts > A14 focus boundaries > uses the unresolved-node fallback for a nonexistent run rail selection
AssertionError: expected { focus: { kind: 'node', …(2) }, …(5) } to match object { runId: 'run_active', …(2) }
(6 matching properties omitted from actual)

- Expected
+ Received

  Object {
    "nodeKey": null,
    "role": "chain",
-   "runId": "run_active",
+   "runId": "run_absent",
  }

 ❯ src/workbench/agent/__eval__/focus.eval.test.ts:34:22
     32|     // The step-8 record says a selection absent from the forest stays…
     33|     // the active chain without a node, as for an unresolved draft nod…
     34|     expect(resolved).toMatchObject({ runId: "run_active", role: "chain…
       |                      ^
     35|   });
     36| });

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯

 Test Files  1 failed (1)
      Tests  1 failed | 2 passed (3)
   Start at  06:28:56
   Duration  464ms (transform 25ms, setup 57ms, collect 9ms, tests 5ms, environment 268ms, prepare 37ms)

```

## 精确提交与修改范围（ADR-PD-001 §10.2）

```text
46077c0c test(eval): A01 pool m2 and m20 against mice
7c633969 test(eval): A02 categorical MI refusal and retention
680af966 test(eval): A03 reject silent combinator precedence
fb348698 test(eval): A04 exclude pooled single-dataset projection fields
42789db3 test(eval): A05 HAC lag zero matches HC1
c07998c7 test(eval): A06 quarterly gap and mixed HAC dates
0aad6c6d test(eval): A07 grouped HAC against R NeweyWest
051f8ddd test(eval): A08 numeric boolean and missing groups
99503b82 test(eval): A10 separated logit group isolation
fa64f491 test(eval): A09 fifty-group execution boundary
450a2459 test(eval): A11 survey group subpopulation against Stata
ead3e7a8 test(eval): A12 single-category grouped t-test refusal
5a5f9673 test(eval): A13 persisted inferential counts per group
eb7184dc test(eval): A14 shared missing dataset and nonexistent run focus
```

A01 另有随最终报告提交的脚本来源标注修正与区间端点按标准误绝对尺度的断言，已包含在上述最终汇总测试中。其余项均在独立测试核验后逐项提交，失败也提交保留。

精确文件清单见下；后续只增加本报告及 owned 路径下 pytest-output.txt、vitest-output.txt。没有修改产品代码、合同、已有测试、已有 golden 或容差，没有创建新 contract lock，没有运行 devline CLI。正式台账由 Claude 维护。

```text
frontend/src/workbench/agent/__eval__/focus.eval.test.ts
tests/eval_v1810/test_a01_pool_extremes.py
tests/eval_v1810/test_a02_categorical_imputation.py
tests/eval_v1810/test_a03_imputation_by_group.py
tests/eval_v1810/test_a04_pooled_projections.py
tests/eval_v1810/test_a05_hac_lag_zero.py
tests/eval_v1810/test_a06_hac_dates.py
tests/eval_v1810/test_a07_hac_by_group.py
tests/eval_v1810/test_a08_group_values.py
tests/eval_v1810/test_a09_group_limit.py
tests/eval_v1810/test_a10_logit_separation.py
tests/eval_v1810/test_a11_survey_intersection.py
tests/eval_v1810/test_a12_ttest_single_category.py
tests/eval_v1810/test_a13_ledger_count.py
tests/fixtures/eval_v1810/a01/generate_oracle.R
tests/fixtures/eval_v1810/a01/m2/data.csv
tests/fixtures/eval_v1810/a01/m2/imputed_1.csv
tests/fixtures/eval_v1810/a01/m2/imputed_2.csv
tests/fixtures/eval_v1810/a01/m2/oracle.json
tests/fixtures/eval_v1810/a01/m20/data.csv
tests/fixtures/eval_v1810/a01/m20/imputed_1.csv
tests/fixtures/eval_v1810/a01/m20/imputed_10.csv
tests/fixtures/eval_v1810/a01/m20/imputed_11.csv
tests/fixtures/eval_v1810/a01/m20/imputed_12.csv
tests/fixtures/eval_v1810/a01/m20/imputed_13.csv
tests/fixtures/eval_v1810/a01/m20/imputed_14.csv
tests/fixtures/eval_v1810/a01/m20/imputed_15.csv
tests/fixtures/eval_v1810/a01/m20/imputed_16.csv
tests/fixtures/eval_v1810/a01/m20/imputed_17.csv
tests/fixtures/eval_v1810/a01/m20/imputed_18.csv
tests/fixtures/eval_v1810/a01/m20/imputed_19.csv
tests/fixtures/eval_v1810/a01/m20/imputed_2.csv
tests/fixtures/eval_v1810/a01/m20/imputed_20.csv
tests/fixtures/eval_v1810/a01/m20/imputed_3.csv
tests/fixtures/eval_v1810/a01/m20/imputed_4.csv
tests/fixtures/eval_v1810/a01/m20/imputed_5.csv
tests/fixtures/eval_v1810/a01/m20/imputed_6.csv
tests/fixtures/eval_v1810/a01/m20/imputed_7.csv
tests/fixtures/eval_v1810/a01/m20/imputed_8.csv
tests/fixtures/eval_v1810/a01/m20/imputed_9.csv
tests/fixtures/eval_v1810/a01/m20/oracle.json
tests/fixtures/eval_v1810/a07/data.csv
tests/fixtures/eval_v1810/a07/generate_oracle.R
tests/fixtures/eval_v1810/a07/oracle.json
```

## 限制、集成与回滚

每项均在 30 分钟内完成，没有超时或三步排查之外的数值深挖。最终新增 Python 测试 54.88 秒，前端测试时长见原始输出；未做压力测试、全量 gate、真实 provider 或浏览器验收。沙箱的 Arrow sysctl 警告及独立运行时 Fontconfig cache 警告没有阻断测试，未尝试绕过权限。原始 pytest 输出中的行尾空格原样保留，不作为源代码风格修改。

集成风险：此分支有意包含 4 项失败验收证据；不能作为产品发版通过证明。基线早于 owner 后续修复，owner 应先把这些测试在自己的最新版本上重跑，再处理仍失败项；A01 数值超差和 A04 null 字段应按本报告明确的边界判断。建议先整合测试/fixture，随后由 Claude 修产品；本评估没有做 cherry-pick/merge。回滚仅由集成 owner 撤销对应新增测试/fixture 的提交，不动产品线或已有 fixture。

保护路径核验：相对精确基线的持久化改动均在 owned_files（含 A14 显式授权例外）中；已有 multiple_imputation fixture 与基线仍完全一致。没有 push/merge/rebase/tag、删除分支/worktree/stash、模型服务调用、下载数据、安装软件或访问 Downloads。

范围外观察：无。
