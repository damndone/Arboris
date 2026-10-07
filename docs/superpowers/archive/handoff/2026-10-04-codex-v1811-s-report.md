# v1.8.11 Lane S 脚本导出生产报告

状态：候选实现，等待独立审查；不是全套 C3 交付完成，不可据此合并或发布。

## 基线和范围

- 绝对 worktree：`/Users/jiayuanren/项目规划/.worktrees/codex-v1811-s`。
- branch：`lane/v1811-s-script-export`。
- 起点和 frozen 普通 runner 基线：`6f0f87c6d8241a93d81e2c34f8ef8e9408a907b3`，开始时 HEAD 一致且工作区干净。
- 生产者生产代码候选 tip：`8f925ed6451ec7888d1c866dfdc42b77afb0729d`；最终证据提交 tip 随交接消息给出。
- 只新增 owned exporter 模块、自己的测试和 fixture、此报告。未改冻结 `plan.py`、`__init__.py`、basic 原文件、既有测试、注册表、runner、HTTP、UI、Agent、egress、中央 devline。未安装、升级、删除、push、merge、rebase、tag、运行 full gate。
- 已按 TDD 先失败测试再实现；本机实际脚本和性能使用 Integration 共用串行锁。无 skip/xfail 或容差调整。

## 已实现与仍待处理

| 子项 | 已实现/已实际验证 | 未决或阻断 |
| --- | --- | --- |
| 入口与声明 | `render.export_script`、每操作三语言声明、注册表漂移检测、按步骤的组合能力判定、native refusal 列出准确 steps | 原生能力只覆盖声明实际支持的组合 |
| 结构和边界 | 确定性头、逐步覆盖表、源先 SHA256、同目录裸文件名、CSV 双精度、seed、末尾数值断言、语法闭合/转义、快照 SHA/行列验证 | 非空 reader options 尚未翻译，显式拒绝；非 CSV reader 未做三软件 oracle |
| 11 数据操作 | 全 11 项真实 registry oracle；缺失筛选、行序稳定去重、recode 首匹配/缺失/复制、原子 rename、merge/append/aggregate/reshape/lag/tsset 边界 | 未宣称所有参数组合和所有输入类型均验证 |
| OLS | unadjusted、HC1、CR1 t(G−1)、Newey–West；frequency/analysis 的 unadjusted、HC1、CR1；分类基准和独立分支 | 完整 survey design OLS 原生未实现；缺 design 拒绝，有 design 仅声明快照理由，不能称 C3 必须项全部完成 |
| 广义模型 | logit、probit（R 用 OIM）、poisson、GLM binomial/poisson | NB2 frozen runner 优化精度依赖失败；NB1/fixed-alpha/非声明 covariance 明确快照理由 |
| IV | unadjusted、HC0；直接 linearmodels/fixest/Stata，对齐 covariance | weighted/category/其他 covariance 尚未验证，声明快照理由 |
| panel/DID | 新 CR1 within/grand means、非嵌套 FE 的 K、t(G−1)；entity 和更粗 string cluster | frozen runner 旧 covariance 不符新 C3，普通基线仍失败；只有只读 Integration overlay 通过；其他 covariance/weights/categories 未实现 |
| 后估计 | wald/lincom/nlcom/lr/margins 在 registry 已开放族；严格 variance/df/distribution，LR 同响应、同源、嵌套、实际样本验证 | NB2 的开放 wald/lincom 同受 M2 依赖；未开放组合明确 NOT_YET_VALIDATED |
| 其他族快照 | 每族明确理由；空模型数字 expected 的快照可校验数据并继续 | 模型数字不能从现有 dataset-only snapshot 独立重现，明确拒绝并提出合同资产缺口 |

## 已观察的命令原样结果

统一执行前缀：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python \
 /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py \
 .venv/bin/python -m pytest -q <本报告列出的 own tests>
```

1. 原生普通基线（当时版本，排除已知 NB2 三例与旧 panel/DID 六例）：

```text
260 passed, 9 deselected, 6 warnings in 108.89s (0:01:48)
```

2. OLS f/aweights × HC1/CR1 追加 12 例、LR 不同样本故意失败 3 例通过；outer merge indicator 的 3 例先因 CSV 不保留 categorical dtype 发生测试断言失败，三者值已完全一致，改为按导出值比较，保留原数值容差。

3. 合法 basic 意图（显式补 required columns，不改 frozen asset）：

```text
3 passed in 2.96s
```

4. 新 panel/DID entity 和更粗 string cluster 三语言 overlay：

```text
12 passed, 6 deselected in 8.88s
```

5. 未改的 existing contract test：

```text
5 passed in 1.17s
```

完整最终普通基线、软件版本、目标脚本计数、逐数字双方值/最大差/容差和性能将在证据提交中追加；以上不代替最终验收。

## 双基线 overlay 证据

只读 Integration runner tip：`1c938407f42563dd4c4bf8a755a19ea84cccd1d7`。

- `runner.py` SHA256：`1867f36a7acd6b731eda5fb5c70169d51c4642e34ee2f0aca5150f0d4e99548c`。
- `panel_inference.py` SHA256：`c0c10b9fdc1ea8d1d8583c880e6f3e717fb78e8fc89ba6ec3ace798423fd5749`。

真实预期生成与测试命令：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 \
 PYTHONPATH=/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/backend:backend \
 WB_EXPORT_EVIDENCE_RUN=panel-overlay .venv/bin/python \
 /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py \
 .venv/bin/python -c 'import workbench.script_export; workbench.script_export.__path__.insert(0,"/Users/jiayuanren/项目规划/.worktrees/codex-v1811-s/backend/workbench/script_export"); import pytest; raise SystemExit(pytest.main(["-q","tests/test_script_export_iv_panel_oracles.py","-k","panel_clustered"]))'
```

`PYTHONPATH` 先加载只读 Integration 的真实 runner，再将 `script_export.__path__` 首位改为 S 的实现；所有源、脚本、日志、预期/实际数字输出仍在 S 新 fixture 目录。没有复制或合入 Integration 代码。此通过不能写成 frozen `6f0f87c6` 全套通过。NB2/M2 未 overlay 验收。

## 精确集成/合同请求与事故

1. frozen basic 缺 required `subset.columns`：真实 registry validation 报 `columns must be a non-empty string list`，直接执行也拒绝。原 fixture 保持只读；新 `validated_basic/plan.json` 明确给原 CSV 全部六列，按真实 registry/runner/postestimation 生成 expected。`recode.rules` 的 `{from:{low,high},to}` 合法，无须特判。
2. NB2 frozen runner 截距 `0.10852296766580023`；Stata/R 严格估计约 `0.108512923662649`，差约 `1.0044e-5`，大于系数默认 `abs=1e-8, rel=1e-6`。请求集成已独立审查的 M2 修复后，用同一测试重新验收；未改优化器、golden 或容差。
3. frozen panel 旧截距 SE `0.0025027726423520295` 对比新 CR1 约 `0.00236670267206428`；DID 旧截距 SE `0.12556471194223834` 对比新 CR1 约 `0.0853952209972437`。请求集成已审查的新 CR1；保留旧基线失败，独立标识 overlay。
4. C3 dataset-only `ScriptSnapshot` 缺可独立验证模型数字的产物：最小消费者需求为另一个有文件名、SHA256、类型版本的真实数值结果资产，以及 expected 对结果字段的映射。现实现遇非空模型/后估计 expected 报 `SNAPSHOT_CANNOT_REPRODUCE_MODEL_NUMBERS`，不将 expected 常量自比。Integration 已确认将补策略/扩展，原冻结 hash 不变。
5. Stata 18 MP 的 `-b do` 在 `assert`/`exit 9` 失败时 OS process status 仍可为 0；本地 helper 按本次 do-file 独有 `r(n);` 日志标记归一化为非零（保留真实 OS status）。R/Python 是进程实际非零。Integration 执行 Stata 时须同样读新工作目录专属日志，不能只看 OS status。
6. Stata 以执行 cwd 读取裸文件；R/Python 从脚本路径确定目录。Integration 必须把 Stata cwd 设为 export 目录。
7. 开始探测 `shasum` 未设置 locale，macOS Perl 出现 locale panic；无文件修改，随后加 `LC_ALL/LANG` 并用 hashlib 读取 hash。此为生产者命令事故，未影响已留证据。
8. Stata 新 string cluster oracle 先报 `type mismatch r(109)`，以一一编码 cluster 修复，不改变聚类归属或统计方法。其他范围外代码未修改。

受影响 existing tests：只读并执行 `test_script_export_plan_contract.py`；既有 postestimation/model/data tests、golden、容差没有变化；未运行全量或 gate。

## 最终保留证据、逐失败归因和性能
生产代码候选 tip：`8f925ed6451ec7888d1c866dfdc42b77afb0729d`。最终证据提交仅更新 own panel 诊断测试和报告/新 fixture，生产模块没有变化。
最终完整普通基线命令：
```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend WB_EXPORT_EVIDENCE_RUN=frozen-final .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest -q tests/test_script_export_render.py tests/test_script_export_data_oracles.py tests/test_script_export_model_oracles.py tests/test_script_export_postestimation_oracles.py tests/test_script_export_iv_panel_oracles.py tests/test_script_export_integrity.py tests/test_script_export_basic_oracle.py --tb=short
```
```text
21 failed, 287 passed, 6 warnings in 136.35s (0:02:16)
```
重要校正：这次完整运行 9 个 NB2 数值失败；12 个 panel/DID 在 frozen runner 尚不接受 `cluster_col` 的签名处失败，尚无模型预期，delta 必须为 N/A，不能称为 12 个 covariance 数值失败。`acceptance.json.original_308_failures` 保留全部 21 个原失败的每个 case/语言/类型。
追加 focused 诊断使 entity 使用原 runner 调用，仅 coarse string 使用新参数；6 个 entity 此时真实运行到旧 covariance 数值断言，6 个 coarse string 仍在 runner 签名处失败：
```text
12 failed, 6 deselected in 5.31s
```
下表分别列 9 个 NB2 真实数值失败、6 个 entity 真实数值失败、6 个 coarse string 签名失败。所有失败完整数字、最大差、各数字容差和目标原样 command output 均保存在新 [acceptance.json](/Users/jiayuanren/项目规划/.worktrees/codex-v1811-s/tests/fixtures/script_export/evidence/acceptance.json)；不是只按数量归因。未产生 Workbench 预期的签名失败不伪造 delta。
| case | 语言 | 首个违反的指标 | Workbench expected | 目标 actual | abs delta | 允许差 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| model-oracle/negative_binomial/model.negative_binomial | python | results['model']['beta']['Intercept'] | 0.10852296766580023 | 0.1085129236626457 | 1.0044003e-05 | 1.1852297e-07 |
| model-oracle/negative_binomial/model.negative_binomial | r | results[["model"]][["beta"]][["Intercept"]] | 0.10852296766580023 | 0.1085129236626492 | 1.0044003e-05 | 1.1852297e-07 |
| model-oracle/negative_binomial/model.negative_binomial | stata | _b[_cons] | 0.10852296766580023 | 0.10851292284029213 | 1.0044826e-05 | 1.1852297e-07 |
| panel/did_coarse_string/model.did | python | missing cluster_col runner parameter | N/A | N/A | N/A | N/A |
| panel/did_coarse_string/model.did | r | missing cluster_col runner parameter | N/A | N/A | N/A | N/A |
| panel/did_coarse_string/model.did | stata | missing cluster_col runner parameter | N/A | N/A | N/A | N/A |
| panel/did_entity/model.did | python | results['model']['se']['Intercept'] | 0.12556471194223834 | 0.085395220997243823 | 0.040169491 | 1.2656471e-06 |
| panel/did_entity/model.did | r | results[["model"]][["se"]][["Intercept"]] | 0.12556471194223834 | 0.085395220997243657 | 0.040169491 | 1.2656471e-06 |
| panel/did_entity/model.did | stata | _se[_cons] | 0.12556471194223834 | 0.085395220997243781 | 0.040169491 | 1.2656471e-06 |
| panel/panel_ols_coarse_string/model.panel_ols | python | missing cluster_col runner parameter | N/A | N/A | N/A | N/A |
| panel/panel_ols_coarse_string/model.panel_ols | r | missing cluster_col runner parameter | N/A | N/A | N/A | N/A |
| panel/panel_ols_coarse_string/model.panel_ols | stata | missing cluster_col runner parameter | N/A | N/A | N/A | N/A |
| panel/panel_ols_entity/model.panel_ols | python | results['model']['se']['Intercept'] | 0.0025027726423520295 | 0.0023667026720642645 | 0.00013606997 | 3.5027726e-08 |
| panel/panel_ols_entity/model.panel_ols | r | results[["model"]][["se"]][["Intercept"]] | 0.0025027726423520295 | 0.0023667026720642819 | 0.00013606997 | 3.5027726e-08 |
| panel/panel_ols_entity/model.panel_ols | stata | _se[_cons] | 0.0025027726423520295 | 0.002366702672064271 | 0.00013606997 | 3.5027726e-08 |
| postestimation/negative_binomial/postestimation.lincom | python | results['model']['beta']['Intercept'] | 0.10852296766580023 | 0.1085129236626457 | 1.0044003e-05 | 1.1852297e-07 |
| postestimation/negative_binomial/postestimation.lincom | r | results[["model"]][["beta"]][["Intercept"]] | 0.10852296766580023 | 0.1085129236626492 | 1.0044003e-05 | 1.1852297e-07 |
| postestimation/negative_binomial/postestimation.lincom | stata | _b[_cons] | 0.10852296766580023 | 0.10851292284029213 | 1.0044826e-05 | 1.1852297e-07 |
| postestimation/negative_binomial/postestimation.wald | python | results['model']['beta']['Intercept'] | 0.10852296766580023 | 0.1085129236626457 | 1.0044003e-05 | 1.1852297e-07 |
| postestimation/negative_binomial/postestimation.wald | r | results[["model"]][["beta"]][["Intercept"]] | 0.10852296766580023 | 0.1085129236626492 | 1.0044003e-05 | 1.1852297e-07 |
| postestimation/negative_binomial/postestimation.wald | stata | _b[_cons] | 0.10852296766580023 | 0.10851292284029213 | 1.0044826e-05 | 1.1852297e-07 |

最终只读 overlay 重跑相同 12 例，在 Integration tip `fb1a140a25a0173c4d97bc5e8e0592678424f51d` 上通过；runner/panel_inference 的 SHA256 与此前 `1c938407` 相同，已前后验证。命令与前述相同，仅 `WB_EXPORT_EVIDENCE_RUN=panel-overlay-final`；own diagnostic test hash 见 acceptance metadata。
```text
12 passed, 6 deselected in 8.83s
```
实际执行的目标脚本次数（不是 pytest test 数）：
| 留证轮次 | Stata | R | Python |
| --- | ---: | ---: | ---: |
| frozen-final | 86 | 86 | 86 |
| frozen-panel-compat | 2 | 2 | 2 |
| panel-overlay-final | 4 | 4 | 4 |

每个数据 oracle 在 `data_pairs` 中保留完整双方 cell 值、各数值列最大差、rtol/atol；每个模型/后估计 oracle 在 `numeric_pairs` 中保留每项双方值、执行表达式、绝对差、abs/rel/allowed；源 hash、plan、目标脚本 hash、真实与归一化 exit、目标原样输出逐例保留。完整数值资产不会只靠口头最大差证明。

实际软件：Stata 18.0 MP；R 4.6.0 (2026-04-24)；Python 3.14.6. Python packages: statsmodels 0.14.6, linearmodels 7.0, numpy 2.5.0, pandas 3.0.4, scipy 1.18.0, arch 8.0.0. R packages: MASS 7.3.65, sandwich 3.1.1, fixest 0.14.1, dplyr 1.2.1, tidyr 1.3.2。

性能命令（共用串行锁，pure rendering，同一 plan 二次逐字节相等）：
```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest -q -s tests/test_script_export_integrity.py -k fifty
```
```text
stata: 50 steps 0.006006s
r: 50 steps 0.000775s
python: 50 steps 0.000691s
3 passed, 45 deselected in 0.99s
```

数值记录器在测试导出的目标脚本中、closing checks 前写出实际捕获值，用于留证；生产 export_script 不写盘，只纯本地返回字符串。原样日志留在 owned `local_runs/oracle-*`，机器可审查结果及日志另持久化在已提交 evidence，不依赖 ignored 目录。

Git 元数据最初 sandbox 操作出现 `index.lock: Operation not permitted`；按已授权本地提交的范围，经 auto-review escalation 成功暂存和提交，无自动审批拒绝。未绕过文件范围或作远端操作。

## 已通过组的双方数字与最大绝对差

每组跨三种目标语言列最大绝对差所在项；表内允许差按该项原 abs/rel 计算。所有项的双方数字（含精确 df、p）及每种语言明细见 evidence 的 `records` 和 `passing_group_summary`，无调整容差。数据单元值由 CSV 序列化保留，机器资产的完整 data_pairs 可审查原行序、列名、缺失与字符串。

| 通过组 | 最差项语言 | expected | actual | 最大 abs delta | 该项允许差 | 检查数字数 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| categories/branches/model.ols | r | -0.12606025144491617 | -0.12606025144491706 | 8.8817842e-16 | 1.3606025e-07 | 54 |
| data/data.aggregate | python | 3 | 3 | 0 | 0 | 33 |
| data/data.append | r | 4 | 4 | 0 | 0 | 54 |
| data/data.dedupe | stata | 2 | 2 | 0 | 0 | 30 |
| data/data.fill_missing | stata | 3 | 3 | 0 | 0 | 60 |
| data/data.lag | python | 5 | 5 | 0 | 0 | 51 |
| data/data.merge | r | 4 | 4 | 0 | 0 | 87 |
| data/data.recode | r | 3 | 3 | 0 | 0 | 42 |
| data/data.rename | python | 2 | 2 | 0 | 0 | 30 |
| data/data.reshape | python | 4 | 4 | 0 | 0 | 48 |
| data/data.subset | python | 2 | 2 | 0 | 0 | 39 |
| data/data.tsset | r | 3 | 3 | 0 | 0 | 48 |
| fixture-project/fixture-run/postestimation.wald | stata | 54.741006828302886 | 54.741006828301025 | 1.861622e-12 | 0.00054742007 | 63 |
| iv/robust/model.iv_2sls | r | 3.3546148733045418 | 3.3546148733045316 | 1.0214052e-14 | 3.3556149e-05 | 39 |
| iv/unadjusted/model.iv_2sls | r | 3.6701222946055001 | 3.6701222946054877 | 1.2434498e-14 | 3.6711223e-05 | 39 |
| model-oracle/glm_binomial/model.glm | stata | 4.7957789715002477 | 4.7957766571360141 | 2.3143642e-06 | 4.796779e-05 | 39 |
| model-oracle/glm_poisson/model.glm | stata | 7.9485288298835055 | 7.9485288290808365 | 8.0266904e-10 | 7.9495288e-05 | 39 |
| model-oracle/logit/model.logit | r | 4.7957767608932027 | 4.7957789715002486 | 2.210607e-06 | 4.7967768e-05 | 39 |
| model-oracle/ols_analysis/model.ols | r | 21.18114038496309 | 21.181140384963101 | 1.0658141e-14 | 0.0002118214 | 48 |
| model-oracle/ols_clustered/model.ols | r | 23.950661450217702 | 23.950661450217716 | 1.4210855e-14 | 0.00023951661 | 48 |
| model-oracle/ols_frequency/model.ols | stata | 16.467953759315279 | 16.467953759315289 | 1.0658141e-14 | 0.00016468954 | 48 |
| model-oracle/ols_hac/model.ols | r | 22.690606644178427 | 22.690606644178455 | 2.8421709e-14 | 0.00022691607 | 48 |
| model-oracle/ols_robust/model.ols | r | 21.156905500462134 | 21.156905500462141 | 7.1054274e-15 | 0.00021157906 | 48 |
| model-oracle/ols_unadjusted/model.ols | r | 21.176786635601545 | 21.176786635601559 | 1.4210855e-14 | 0.00021177787 | 48 |
| model-oracle/poisson/model.poisson | stata | 1.9731852029611081 | 1.9731852040457334 | 1.0846253e-09 | 1.9741852e-05 | 39 |
| model-oracle/probit/model.probit | stata | 4.9265515262774553 | 4.926551492527798 | 3.3749657e-08 | 4.9275515e-05 | 39 |
| panel/did_coarse_string/model.did | r | 14.812806230760435 | 14.812806230760483 | 4.7961635e-14 | 0.00014813806 | 48 |
| panel/did_entity/model.did | r | 13.93004093086644 | 13.930040930866481 | 4.0856207e-14 | 0.00013931041 | 48 |
| panel/panel_ols_coarse_string/model.panel_ols | r | 605.01802839698087 | 605.01802839697484 | 6.0254024e-12 | 0.0060501903 | 33 |
| panel/panel_ols_entity/model.panel_ols | r | 456.89480894524894 | 456.89480894524598 | 2.9558578e-12 | 0.0045689581 | 33 |
| postestimation/logit/postestimation.lincom | r | 4.7957767608932027 | 4.7957789715002486 | 2.210607e-06 | 4.7967768e-05 | 51 |
| postestimation/logit/postestimation.lr | r | 4.7957767608932027 | 4.7957789715002486 | 2.210607e-06 | 4.7967768e-05 | 48 |
| postestimation/logit/postestimation.margins | r | 5.520277354661248 | 5.5202797926974396 | 2.4380362e-06 | 5.5212774e-05 | 66 |
| postestimation/logit/postestimation.nlcom | r | 8.2289543450241851 | 8.2289572141856713 | 2.8691615e-06 | 8.2299543e-05 | 51 |
| postestimation/logit/postestimation.wald | r | 11.839274195654816 | 11.83928542196754 | 1.1226313e-05 | 0.00011840274 | 48 |
| postestimation/ols_clustered/postestimation.lincom | r | 23.950661450217702 | 23.950661450217716 | 1.4210855e-14 | 0.00023951661 | 63 |
| postestimation/ols_clustered/postestimation.margins | r | 23.950661450217702 | 23.950661450217716 | 1.4210855e-14 | 0.00023951661 | 81 |
| postestimation/ols_clustered/postestimation.nlcom | stata | 18.166247998299283 | 18.166248000042366 | 1.7430821e-09 | 0.00018167248 | 63 |
| postestimation/ols_clustered/postestimation.wald | r | 34.495407752961825 | 34.495407752961867 | 4.2632564e-14 | 0.00034496408 | 60 |
| postestimation/ols_hac/postestimation.lincom | r | 22.690606644178427 | 22.690606644178455 | 2.8421709e-14 | 0.00022691607 | 63 |
| postestimation/ols_hac/postestimation.margins | r | 22.690606644178427 | 22.690606644178455 | 2.8421709e-14 | 0.00022691607 | 81 |
| postestimation/ols_hac/postestimation.nlcom | stata | 20.094357463959511 | 20.094357465326382 | 1.3668711e-09 | 0.00020095357 | 63 |
| postestimation/ols_hac/postestimation.wald | r | 35.951877568477109 | 35.951877568477151 | 4.2632564e-14 | 0.00035952878 | 60 |
| postestimation/ols_robust/postestimation.lincom | r | -2.9343526549493184 | -2.9343526549493095 | 8.8817842e-15 | 2.9353527e-05 | 63 |
| postestimation/ols_robust/postestimation.margins | r | 21.156905500462134 | 21.156905500462141 | 7.1054274e-15 | 0.00021157906 | 81 |
| postestimation/ols_robust/postestimation.nlcom | stata | 20.060213281842703 | 20.060213283671221 | 1.8285178e-09 | 0.00020061213 | 63 |
| postestimation/ols_robust/postestimation.wald | r | 38.374314076258152 | 38.374314076258202 | 4.9737992e-14 | 0.00038375314 | 60 |
| postestimation/ols_unadjusted/postestimation.lincom | r | 21.176786635601545 | 21.176786635601559 | 1.4210855e-14 | 0.00021177787 | 63 |
| postestimation/ols_unadjusted/postestimation.lr | stata | 13.153493043223762 | 13.153493043223875 | 1.1368684e-13 | 0.00013154493 | 57 |
| postestimation/ols_unadjusted/postestimation.margins | r | 21.176786635601545 | 21.176786635601559 | 1.4210855e-14 | 0.00021177787 | 81 |
| postestimation/ols_unadjusted/postestimation.nlcom | stata | 18.951928568999822 | 18.951928570915975 | 1.9161526e-09 | 0.00018952929 | 63 |
| postestimation/ols_unadjusted/postestimation.wald | r | 33.879882421655807 | 33.879882421655857 | 4.9737992e-14 | 0.00033880882 | 60 |
| postestimation/poisson/postestimation.lincom | stata | 1.9731852029611081 | 1.9731852040457334 | 1.0846253e-09 | 1.9741852e-05 | 51 |
| postestimation/poisson/postestimation.lr | stata | 1.9731852029611081 | 1.9731852040457334 | 1.0846253e-09 | 1.9741852e-05 | 48 |
| postestimation/poisson/postestimation.margins | stata | 1.9731852029611081 | 1.9731852040457334 | 1.0846253e-09 | 1.9741852e-05 | 66 |
| postestimation/poisson/postestimation.nlcom | stata | 19.704003115119288 | 19.704003118396553 | 3.2772647e-09 | 0.00019705003 | 51 |
| postestimation/poisson/postestimation.wald | r | 29.377938847301387 | 29.377938849136786 | 1.8353994e-09 | 0.00029378939 | 48 |
| postestimation/probit/postestimation.lincom | stata | 4.9265515262774553 | 4.926551492527798 | 3.3749657e-08 | 4.9275515e-05 | 51 |
| postestimation/probit/postestimation.lr | stata | 4.9265515262774553 | 4.926551492527798 | 3.3749657e-08 | 4.9275515e-05 | 48 |
| postestimation/probit/postestimation.margins | stata | 5.5300400125935445 | 5.5300399658715627 | 4.6721982e-08 | 5.53104e-05 | 66 |
| postestimation/probit/postestimation.nlcom | stata | 4.9265515262774553 | 4.926551492527798 | 3.3749657e-08 | 4.9275515e-05 | 51 |
| postestimation/probit/postestimation.wald | stata | 7.1729642495131216 | 7.1729640651627378 | 1.8435038e-07 | 7.1739642e-05 | 48 |
| weighted/analysis_clustered/model.ols | stata | 11.40223440573598 | 11.402234405735991 | 1.0658141e-14 | 0.00011403234 | 48 |
| weighted/analysis_robust/model.ols | stata | 12.650999955420295 | 12.650999955420311 | 1.5987212e-14 | 0.00012652 | 48 |
| weighted/frequency_clustered/model.ols | python | 23.069819870014971 | 23.069819870014982 | 1.0658141e-14 | 0.0002307082 | 48 |
| weighted/frequency_robust/model.ols | r | 29.282566057094094 | 29.282566057094112 | 1.7763568e-14 | 0.00029283566 | 48 |

## 独立审查后的第一项修复提交（S1–S7 / GLM 身份）

修复起点为独立审查冻结 tip `7cd5ae10be4144d2026e95f4e1bc08e41b160384`，branch/worktree 不变、开始时干净。审查报告/tests/manifest/logs 原文件及首轮作者 evidence 均保持原样。原 36 例重跑只将 `s_review_test_adversarial.EVIDENCE` 指向 S owned 新 `remediation_runs/original_red`，未改审查源码；原样结果 `16 failed, 20 passed in 13.47s`。

S1/R 分类模型使用独立 frame，不修改共享源；S2/R numeric category 项名按实际 factor 水平匹配公开项身份；S3/Stata 分类编码使用每模型独立 tempvar，真实 `wb_cat0` 列保留；S4/Stata ISO HAC 时间转为已验证的规则期间，保留实际间隔而非直接忽略日期；S5/CSV 显式 `varnames(1)`；S6/R 全缺失 min/max 返回 NA；S7/Python tsset 在外部键 frame 排序，原 `__wb_time` 值和列保留。GLM admission 保存 `glm:<family>`，这仅为身份修复，不宣称未开放 GLM 后估计已实际验收。

真实重跑：同原命令引导方式，输出改到 `remediation_runs/s1_s7_confirmed`，pytest 选择 `-k "not selected_excel and not sampling_design"`。原样：

```text
30 passed, 6 deselected in 13.36s
```

其中 27 次三语言 native 运行、3 个 GLM 身份接口观测；逐例 plan/数值向量/cell expected/actual/公开原样日志持久化于新 `tests/fixtures/script_export/evidence/remediation_s1_s7.json`。全部沿用原容差。Stata HAC 最初修复还暴露 replace 时首行被原地改变的实现错误；先保存起点与间隔 scalar 后重跑才取得上述 PASS，原失败日志保留。

剩余 reader、sampling OLS 与 snapshot 数字 sidecar 尚未完成；完整 C3 仍未交付。FPC 只读定位发现既有 WB design engine 记录/校验字段却不施加 FPC，review sampling asset 含 fpc=500 但数字来自未传 FPC 的 R oracle。Root 已要求只对实测无 FPC 线性化提供原生，supplied FPC 必须明确拒绝/快照理由，不许当作等价或调容差，底层问题由 Integration 判断。

## Reader 修复提交

起点 `68b35a6cdeb892286b70a4155fce472a6daa75cf`。CSV 显式翻译 delimiter/sep、UTF-8/Latin1/CP1252、header=0、header=None+names；R 使用本机已装 openxlsx 原生读 XLSX 的指定 sheet_name 或首工作表，不安装依赖。未知选项、冲突 delimiter、无法等价的 transpose/header/列身份明确拒绝。所有源仍先校验 SHA256。

TDD：最初 12 RED；首轮 10 PASS/2 FAIL（Stata tab 及 R readxl 未安装），改用现有 openxlsx 和 Stata 官方本机 help 规定的 `delimiters("\\t")` 后 23 PASS。新增默认首工作表与错误 names 参数形状暴露 4 RED/29 PASS，修复后原样：`44 passed in 5.75s`。最终命令为 shared run_exclusive + `pytest -q tests/test_script_export_read_options.py tests/test_script_export_render.py --tb=short`，环境 `WB_EXPORT_EVIDENCE_RUN=reader_complete_final`、LC_ALL/LANG=en_US.UTF-8、PYTHONPATH=backend；PYTEST_ADDOPTS 追加 `-o tmp_path_retention_count=1000000 -o tmp_path_retention_policy=all`。

最终实际 Stata/R/Python 各 5 个 script（UTF8 semicolon、Latin1 pipe、tab 无表头、指定 XLSX sheet、默认首 sheet）。逐数据单元对照原 reader，浮点 abs/rel=1e-8，数字最大差为 0；self-check 使用原冻结容差。新 evidence `tests/fixtures/script_export/evidence/reader_options_remediation.json` 保存每 plan、实际数据/预期数据、数值检查和公开执行日志；原证据未变。原 reader 及 CSV 导出 tests 均受影响，上述 focused checks 已通过，未跑全量/gate。

## 完整无 FPC sampling OLS 与后估计

Reader 后起点 `bf346c1844b37e51067304d8847808ded5ba5063`。新 `exporters/survey.py` 在声明层选取 native renderer，采样 OLS 支持真实已执行的 strata/PSU、两种 t df、完整设计内子总体与 lonely fail/remove/certainty/adjust/average。Python 使用当前版本 Workbench 的自实现 survey engine，覆盖表明确依赖；R survey::svydesign/svyglm、Stata svy 原生估计。Python oracle 环境绑定 S 绝对 backend；本机默认 editable workbench 指向旧 v1.8.6，未把旧包当本轮 oracle。生成脚本本身没有绝对路径。replicate/nonlinear/longitudinal 未验证组合逐项原因明确，完整 FPC 组合保持阻断。

所有 expected 都由冻结 S `run_ols` +真实 `_apply_survey_design_variance` 生成 primary/kernel，后估计由真实 registry.run_operation。无 FPC 24 RED 后真实 24 PASS；扩展到四种 lonely 政策、FPC 理由/诊断共52 PASS。后估计 24 例首轮3 RED/21 PASS：Python/R缺设计 adjusted F、Stata minusP 默认 adjusted F；修复 Korn-Graubard 和 test,nosvyadjust 后通过。R 额外 RED 证明 svyglm 不应计算伪 likelihood，helper关闭该值后不再出现 logLik warning。

最终原样：`87 passed in 53.41s`。命令 shared run_exclusive + `pytest -q tests/test_script_export_survey_oracles.py tests/test_script_export_render.py --tb=short`，环境 WB_EXPORT_EVIDENCE_RUN=survey_complete_final、LC_ALL/LANG=en_US.UTF-8、PYTHONPATH=backend，retention=1000000/all。72 个实际 scripts：Stata/R/Python 各24，其中48个模型设计组合、24个wald/lincom/nlcom/margins。1302个数字沿用冻结容差，最大abs差9.955147817208854e-11；各组最大cell的 expected/actual/delta/allowed如下，新 `evidence/survey_no_fpc_native.json` 保存全部1302对、真实WB primary/kernel、script和日志。

| design / df / operation | language | expected | actual | delta | allowed |
|---|---|---:|---:|---:|---:|
| lonely_adjust/design/model.ols | stata | -4.6688528115124388 | -4.6688528115123624 | 7.6383344e-14 | 4.6698528e-05 |
| lonely_adjust/design_minus_p/model.ols | stata | -4.6688528115124388 | -4.6688528115123624 | 7.6383344e-14 | 4.6698528e-05 |
| lonely_average/design/model.ols | r | -4.370022859681721 | -4.3700228596816526 | 6.8389738e-14 | 4.3710229e-05 |
| lonely_average/design_minus_p/model.ols | r | -4.370022859681721 | -4.3700228596816526 | 6.8389738e-14 | 4.3710229e-05 |
| lonely_certainty/design/model.ols | r | -4.6717509466568838 | -4.6717509466568101 | 7.3718809e-14 | 4.6727509e-05 |
| lonely_certainty/design_minus_p/model.ols | r | -4.6717509466568838 | -4.6717509466568101 | 7.3718809e-14 | 4.6727509e-05 |
| lonely_remove/design/model.ols | r | -4.6717509466568838 | -4.6717509466568101 | 7.3718809e-14 | 4.6727509e-05 |
| lonely_remove/design_minus_p/model.ols | r | -4.6717509466568838 | -4.6717509466568101 | 7.3718809e-14 | 4.6727509e-05 |
| psu_only/design/model.ols | r | 9.4391677473952598 | 9.439167747395226 | 3.375078e-14 | 9.4401677e-05 |
| psu_only/design_minus_p/model.ols | r | 9.4391677473952598 | 9.439167747395226 | 3.375078e-14 | 9.4401677e-05 |
| strata_only/design/model.ols | r | 18.863018561499416 | 18.863018561499356 | 6.0396133e-14 | 0.00018864019 |
| strata_only/design_minus_p/model.ols | r | 18.863018561499416 | 18.863018561499356 | 6.0396133e-14 | 0.00018864019 |
| strata_psu/design/model.ols | r | 8.3227336945376038 | 8.3227336945375736 | 3.0198066e-14 | 8.3237337e-05 |
| strata_psu/design/postestimation.lincom | r | 8.3227336945376038 | 8.3227336945375736 | 3.0198066e-14 | 8.3237337e-05 |
| strata_psu/design/postestimation.margins | r | 8.3227336945376038 | 8.3227336945375736 | 3.0198066e-14 | 8.3237337e-05 |
| strata_psu/design/postestimation.nlcom | stata | 4.4888223077455569 | 4.4888223078451084 | 9.9551478e-11 | 4.4898223e-05 |
| strata_psu/design/postestimation.wald | r | 88.672824457756704 | 88.672824457757557 | 8.5265128e-13 | 0.00088673824 |
| strata_psu/design_minus_p/model.ols | r | 8.3227336945376038 | 8.3227336945375736 | 3.0198066e-14 | 8.3237337e-05 |
| strata_psu/design_minus_p/postestimation.lincom | r | 8.3227336945376038 | 8.3227336945375736 | 3.0198066e-14 | 8.3237337e-05 |
| strata_psu/design_minus_p/postestimation.margins | r | 8.3227336945376038 | 8.3227336945375736 | 3.0198066e-14 | 8.3237337e-05 |
| strata_psu/design_minus_p/postestimation.nlcom | stata | 4.4888223077455569 | 4.4888223078451084 | 9.9551478e-11 | 4.4898223e-05 |
| strata_psu/design_minus_p/postestimation.wald | r | 101.3403708088648 | 101.34037080886579 | 9.8054898e-13 | 0.0010134137 |
| subpopulation/design/model.ols | r | 8.0447933651646899 | 8.0447933651647183 | 2.8421709e-14 | 8.0457934e-05 |
| subpopulation/design_minus_p/model.ols | r | 8.0447933651646899 | 8.0447933651647183 | 2.8421709e-14 | 8.0457934e-05 |

最小FPC诊断持久化到 `/Users/jiayuanren/项目规划/.worktrees/codex-v1811-s/tests/fixtures/script_export/fpc_diagnostic_20261004`，包括源data、probe.R、R完整sessionInfo日志、pairs、两次真实WB primary及gap.json。传FPC=500与不传，WB完全同值；R的Intercept SE 1.59552414552267→1.59232989978524，x1 .177324041106902→.176969037665532，x2 .0888823446973062→.0887044018868015，差异均超原 abs=1e-8/rel=1e-6。现有公开 DESIGN_FIELDS 含survey_fpc_col，但底层engine未使用；Root准备 scope proposal，S未修改底层。原required sampling review asset含FPC但expected无FPC，三例仍应明确失败，不能宣称全部C3交付。

安全与数据身份补充原样：`9 passed, 76 deselected in 4.74s`，含三语言错误survey expected非零退出、closed domain拒绝代码注入、entity列真名time与真实__wb_time列保留。后者原测试新RED为1 FAIL/2 PASS，Python外部排序键仍把entity名time和内部time别名碰撞；改为外部整数键后真实三语言数据完全一致。新 evidence/survey_safety_and_internal_columns.json保留6次实际脚本，错误值三例真实非零（Stata按日志r(9)归一），不删失败产物。

## 最后 focused 验证与未决边界

普通 OLS/model/postestimation 的受影响既有测试：shared lock `pytest -q tests/test_script_export_postestimation_oracles.py tests/test_script_export_model_oracles.py -k ols --tb=short`，原样 `69 passed, 84 deselected in 38.12s`；Stata/R/Python各23实际 scripts，最大abs差1.9161525699473714e-09，未改容差。全数字/日志见新 evidence/ols_helper_regression.json。

完整性及冻结合同：shared lock `pytest -q -s tests/test_script_export_integrity.py tests/test_script_export_plan_contract.py --tb=short`，原样 `53 passed in 8.99s`。三语言source SHA损坏、expected损坏、snapshot SHA/形状损坏均实际非零；有效snapshot仍可继续（model数字sidecar未有接口）。50步render Stata=0.000692s、R=0.000781s、Python=0.001000s，逐字节确定，均<1秒；性能已通知Root。

原独立36例重新执行，仍不改原test，仅 EVIDENCE 指到 owned `remediation_runs/final_review_rerun`，原样 `3 failed, 33 passed in 12.68s`。每个失败均为 `test_workbench_supported_complete_sampling_design_is_native[stata|r|python]`，NOT_FULLY_NATIVE 理由完整显示 suppliedFPC 与 frozen engine 的真实定义差异，没有脚本/实际数字，delta=N/A；拒绝记录及原样pytest输出保存，原16RED/20PASS证据不改。此结果不能宣称原36全通过。

CSV option oracle 是工作台所用的同一个 pandas reader 的显式参数调用；冻结公开 `_read_frame` 的 CSV入口本身尚无 delimiter/encoding/header 接口，仅默认 pd.read_csv(path,nrows=...)。XLSX指定/默认sheet直接使用真实 `_read_frame` 作expected。常见参数导出已实测，不宣称冻结WB表单已接受自定义CSV字段，Excel datetime与其他统计文件全类型projection尚未新增验证。

用户已批准限定底层 FPC 修复，Root冻结 `3c8679c2`，独立FPCworktree由M1负责。S保留 suppliedFPC 明确拒绝与最小probe，不改engine；FPC合入后仍需新的三语言oracle和独立审查。快照model数字sidecar接口、qualified GLM实际后估计开放/验收等待Root/M2；原NB2与panel frozen依赖失败、原basic缺columns仍如实保留。未执行全量/gate，未安装/升级依赖，未删任何目录/缓存/证据，未读Downloads/调用LLM或真实API，未push/merge/rebase/tag，中央devline只由Root记录重要事件。

当前新增修复测试：read_options、survey_oracles、internal_columns；未修改审查tests/manifest/旧logs或冻结plan/__init__。以上各轮pytest都保留临时目录 retention_count=1000000 / retention_policy=all。原样输出汇总及逐未决case见新 `evidence/remediation_acceptance_summary.json`。完整C3仍非全部交付。

## ResultSnapshot 数字 sidecar 消费者交付

生产起点 `92c90b599206588a999d8ff991d5cd59785f5532`；Root供应的 `result_snapshot.py` 为只读untracked依赖，未编辑/stage/提交/删除。第一次供应 Integration `821ccda5` / SHA `8a0f5729951f327ce23f9d9442e8d26ea6a8a3e01291f3d76e1f77b4b6d11d2c`，45 RED（缺新kwarg）后第一轮consumer45 PASS/13.51s。Root在无活动重负载时替换已独立复审供应为 Integration `511616d5` / SHA `2277b52d3cb9e9f55063a3a33fba44eb06d4af87cd45abd47662ea0380d5eb53`；旧供应保留在Root指定local目录。冻结plan.py、__init__.py与basic资产保持原hash。

`export_script(..., result_snapshots: Mapping[str,ResultSnapshotRef] | None=None)` 在None路径保持旧行为；三种validated_basic脚本与旧tip92c90b59逐字节相同，新baseline文件只用于证明兼容。未知key、错误ref类型、native步骤上的未消费ref及缺失closure资产拒绝；require_native先列model/post闭包并拒绝，无须读取实际资产。model仍需原dataset snapshot；post是只读结果，依Root确认继承已校验前驱dataset。coverage明确表示Workbench已完成、数字从sidecar读取、不是native重估。后续独立数据步骤、OLS模型及真实lincom仍可原生执行。

新 `result_runtime.py` 运行时读取实际asset；Python复用供应API，R/Stata用本机Python桥严格调用同一API，再把实际数字供本语言assert。声明workbench与桥python3，R另声明jsonlite；缺依赖实际失败。生成阶段没有读payload、没有把expected作为actual、没有伪造snapshot模型的fit/estimates/ereturn/r()。R/Stata桥读取源一次bytes，使用Root供应的16MiB/regular-file/O_NOFOLLOW/strict duplicateJSON/SHA/schema/binding验证；expected只作为断言RHS或选择要断言的字段。nullable数值与原样非空distribution字符串保留，不改方法名。

真实统计case先由冻结WB run_ols +估计stage得到完整primary/kernel（供应FPC字段但按冻结执行语义记录），真实 registry Wald产生post artifact；build_result_snapshot从持久化artifact读/project，而非从ScriptStep.expected构造values。真实顺序model snapshot→post sidecar→数据subset→独立native OLS→真实native lincom通过。另用明确标注的synthetic nullable parser probe只检验contract解析，不称新统计oracle。坏model/post expected、源bytes篡改、wrong binding且更新hash、duplicate keys且更新hash、负SE schema、symlink、oversize及缺桥依赖均实际非零。

新供应首轮71 PASS/2 harness FAIL：故意NULL实际值导致原数值trace无法float('.')或R空vector；只在新NULL负例禁用可选trace，保留全部runtime断言，原helper不改。require_native空refMap 3 RED证明应优先NOT_FULLY_NATIVE，最小修复后通过。独立lincom新测试曾漏传必需loglik导致3 setup错误；补真实fit.llf后重跑，无生产代码改动。所有失败目录/日志保留。

最后原样：`82 passed in 21.06s`。完整命令：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend \
PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} -o tmp_path_retention_count=1000000 -o tmp_path_retention_policy=all" \
WB_EXPORT_EVIDENCE_RUN=sidecar_final_verified \
.venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py \
.venv/bin/python -m pytest -q -s tests/test_script_export_result_sidecars.py tests/test_script_export_render.py \
tests/test_script_export_plan_contract.py tests/test_script_export_integrity.py::test_fifty_steps_deterministic_performance --tb=short
```

其中63 sidecar关键例、11既有render、5冻结plan、3性能；只按Root要求复验关键sidecar与新增边界，不重复其他S315。39次真实目标执行，Stata/R/Python各13次：每语言3个exit0有效流程、10个预期非零破坏case。9个有效流程276个数字，最大差为R独立OLS Intercept：expected4.596321816357483，actual4.596321816357473，delta9.769962616701378e-15，allowed4.606321816357482e-6。所有原容差保持。50步 Stata0.001001s / R0.000702s / Python0.000656s，逐字节确定且<1秒，已通知Root。

新 `evidence/result_sidecar_runtime.json` 持久化逐case双供应版本、真实artifact、实际sidecarbytes或oversize长度/hash、plan、script、原样公开日志、276对expected/actual及所有非零exit证明。前章“sidecar消费者未完成”历史状态由本节更新为完成；真实artifactbuilder/供应模块独立审查属于Root，不由S替代。suppliedFPC native仍暂拒绝，等待已授权底层FPC修复合入后的适配；qualified GLM实际后估计仍待M2开放/Root安排验收，冻结NB2/panel依赖旧失败与invalid basic仍如实保留。因此完整C3总交付仍不可称全部完成，下一步为独立复审与Root集成安排，尚无用户merge批准。
