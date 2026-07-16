# Workbench v1.6.6 (V) — 正经的后端 viz:角色 + 模型感知 · 设计 spec

> 起草 2026-07-02 · 用户拍板"做成正经的后端 viz 功能"(不再无脑画所有数值列)
> 分支 `workbench-v1.6.6` · 改 `backend/workbench/visualization.py`(+ 调用点传信号)
> 承接 roadmap §3.5 V。前置:v1.6.6 ② 前端 Table figure 画廊已通用(后端出什么 figure 前端零改动显示)。

## 0. 问题
现状 `_create_eda_figures` 对**所有数值列**无脑画 hist/KDE/box/scatter → 会给 `firm_id` 这种 ID 列画分布图,无意义。不认列角色、不认模型类型。用户要求做成"正经的":按**列角色**(y/x/id/time)+**模型类型**决定画什么,跳过无意义的。

## 1. 可用信号(viz step 已在手)
`normalized_y`(结果变量)、`normalized_x`(回归元)、`model_results`(每模型 `model_type`)、`routing["kind"]`(dataset kind: cross_section/time_series/panel/repeated_cross_section)、`time_candidates`、`exposure_col`、`cleaned`(DataFrame)。

## 2. 核心原则
- **只画"进入分析的变量"**:分布/关系图的候选列 = `y ∪ x`(去掉 exposure)。ID/实体/未用列**不在 y/x 里 → 自动排除**(firm_id 问题即解)。time 列单独走时间图。
- **按列类型选图**:对每个候选列判定 continuous vs categorical(用 `nunique`/dtype;阈值 `CAT_MAX_LEVELS=10`)。
  - continuous → histogram + KDE + 进 boxplot/heatmap
  - categorical(低基数)→ bar/count 计数图(不画 KDE)
  - constant / 高基数非数值 → 跳过
- **按模型类型加专属图**(在角色基座之上)。

## 3. 画图矩阵

### 3.1 角色基座(所有 run,只用 y∪x)
| 输入 | 图 | artifact_id |
|---|---|---|
| 连续列(y 及连续 x) | 分布网格(直方图) | `histograms` |
| 连续列 | 密度网格(KDE,跳常数列) | `kde_plots` |
| 连续列 | 合并箱线图 | `boxplots` |
| ≥2 连续列 | 相关性热力图(已存在,改为只用 y∪x) | `correlation_heatmap` |
| 分类 x(低基数) | 计数条形图网格 | `category_counts` |
| y vs 连续 x | 散点网格(线性模型叠回归线) | `scatter_plots` |
| y vs 分类 x | 按类分组的 y 箱线图 | `group_boxplots` |

### 3.2 模型专属(在基座上叠加)
| 模型类型 | 追加图 | 说明 |
|---|---|---|
| 连续/OLS/panel-OLS | residuals_fitted, qq_residuals, coef_plot | 已存在,保留 |
| binary(logit/probit/glm-binomial) | `pred_prob_by_class`(按真实类别的预测概率分布) + coef_plot | 残差意义弱,换预测概率 |
| count(poisson/negbin/glm-poisson) | 结果计数条形 + residuals + coef | |
| time_series | time_trend(已存在) | |
| panel | (基座 + OLS 专属已够) | 实体 spaghetti 图 → 延后 roadmap |
| DID(twfe/cs/sa/dcdh) | 事件研究系数图(若 bundle 有) | 多数 DID 已有诊断卡;图内接线 → 延后 roadmap |
| IV/2SLS | 一阶段:内生 vs 工具变量散点 | → 延后 roadmap |

### 3.3 本轮范围(用户拍板 2026-07-02:基座 + 全部模型专属)
- §3.1 角色基座**全做**。
- §3.2 模型专属**全做**:OLS/binary/count + panel spaghetti + DID 事件研究图 + IV 一阶段散点。
- 前提:harder 图(binary 预测概率、panel 实体列、IV 内生/工具、DID 事件研究 bundle)所需信号须在 viz step 可得;不可得则需把信号透传进 `create_figures`(见 §4)。逐个先验证信号可得性,不可得的诚实标注并最小化透传。

## 4. 契约 & 兼容
- `create_figures` 签名扩展:加 `regressors: list[str]`、`model_type: str | None`、`categorical_levels` 阈值(默认常量)。`outcome_column` 已加。调用点 diagnostics.py 传 `normalized_x` / 主模型 `model_type`。
- 仍注册为普通 `figure` artifact → 前端 Table 画廊零改动自动显示(含未来新图)。
- **Golden 影响**:artifact 集合会变(部分旧 figure 名保留、新增 category_counts/group_boxplots/pred_prob_by_class 视数据/模型出现;histograms 等的**存在条件**变严 → 某些 golden 可能少图/多图)。需重生受影响 golden,并逐一 `git diff` 确认只是 figure 键增减、非其它漂移。

## 5. 健壮性
NaN 丢弃;常数列 KDE 跳过(try/except);网格列数 cap=12;分类基数 cap=10(超了当高基数跳过分布,或截断 top-N 类);空数据不画该 artifact。

## 6. 验收
- TDD:每类图 + 边界(ID 列被排除 / 分类列走 count 不走 KDE / y-vs-分类 x 走 group box / binary 模型出 pred_prob)。
- Gate 全绿(BE + 重生 golden + FE + tsc),`LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh` 在 worktree。
- 浏览器 smoke:OLS run 不再给 ID 列画分布;binary run 出预测概率图。
