# P7 生存分析扩展设计

## 目标

在不修改现有 Cox PH model family 的前提下，新增可组合的 non-parametric survival
analysis pack：Kaplan–Meier、log-rank、RMST。

## 输入边界

- `duration_column`、`event_column` 显式声明；event 必须是 0/1，duration 非负有限。
- 可选 `entry_column` 表示 delayed entry；必须满足 entry ≤ duration，不能把普通缺失
  当作删失。
- 可选 `group_column`；分组标签稳定排序，log-rank 支持两组或多组。
- RMST 必须显式提供 `tau`，不从数据最大时间隐式推断。
- 限制行数、组数和事件时间数；不返回原始生存行。

## 计算与输出

- KM 输出 risk set、events、censored、survival、Greenwood SE、CI、median 和 RMST。
- CI 方法显式选择 `plain` 或 `log_log`；median 不可识别时返回 null 与 reason。
- log-rank 输出 observed/expected、协方差、chi-square、df、p 和 tie policy。
- RMST 输出每组曲线积分、tau、可积分区间及是否受最后观察限制。
- 所有结果带 estimator、policy、nobs、event_count 和 provenance。

## Oracle 与安全

- R `survival::survfit`、`survival::survdiff` 是固定输入 Oracle。
- ties、left truncation、全删失、零事件、组间无重叠等边界必须有明确结果或拒绝。
- 不把 survival curve 当作因果效应，不自动选择分组、tau 或 cut point。
- 运行时禁止调用 R/shell；R 仅存在于测试。

## 非目标

不改 `backend/workbench/engine/packs/v186_model_families/survival_cox.py`，不接 Agent
或前端，不实现 Cox、competing risks 或 frailty。
