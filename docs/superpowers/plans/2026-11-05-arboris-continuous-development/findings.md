# 证据与研究记录

本文件记录调查快照，不代表发布或测试通过。日期：2026-11-05。

## 当前仓库

- v1.9.1 HEAD `f05e480fba23aa0ce971ab761cb12489a511f754`，有其他执行者未提交代码、测试、FMS 和文档变更。
- `AGENTS.md` 要求一版本一正式线；默认路径耗时、RSS、产物体积不超过 v1.9.0 对照的 1.05 倍；数值逐位一致；正式性能测试须独占空闲主机、固定输入、至少 5 次基线噪声校准与 5 对交替 A/B，噪声低于 5%，磁盘余量至少 5 GB。
- `v1-9-1/context-pack.md` 既有目标覆盖 Agent、可视计划、手动可用、恢复与评测。初始文字将 Rust/quant 列在未来范围，但完整 objective 的追加授权已取代对应初始限制；不能单独引用旧 condensed pack 要求重复批准。
- 正式 devline 原始 baseline 是 `402d2d3eac3695d836255a424372930850b73a95`；这不同于本次调查 HEAD，也不同于未来实施的整合基线。
- 已见在建 `native/time_series`、`native/ridge`、`native/quant_replay` 和 `native_research.py`；适配/测试/注册/可达/验收需要分别核查。

## 交叉核查后的修正

- 调查期间 HEAD 更新为 `4ae597b16a0bd7133c771790ce3fb15a17455106`。本轮没有冻结或修改这个工作树，不将跨时刻读到的文件组合成一个已验收提交。
- 完整 objective `docs/superpowers/objectives/2026-10-17-v1.9.1-objective.md:217` 已批准数学引擎和 Agent 本地管线原生重写，`:229` 已批准本版内三项原生研究首批及共同手动/Agent 入口。相关工作不需要重新批准。
- 子代理早期观察到 wrapper 缺失与 replay stub；主协调者复读时两项 wrapper 已存在，replay 也已是完整 adapter。早期缺失不能当成当前故障结论。最终状态统一为“在建，本轮没有运行或验收”。
- 现有 `engine/packs/time_series/cointegration.py:258` 有 `fit_vecm`；VECM 不应列为新增缺失模型。现有 `time_series/models.py:85` 有 ARIMA。
- `agent/core.py:31` 已有 Python AgentCore，`agent/workflow_contract_parts/contracts.py:23` 有 StepSpecContract；计划采用扩展共享协议而非从零另造。
- `frontend/src/lineage/api/graphViewTypes.ts:102` 的运行状态仍为前向兼容字段；主代理与子代理均检查了它。图的实际运行投影和手动取消需要单独验收。
- 快速 IV 最新文档 `docs/superpowers/evaluations/2026-11-03-fast-engine.md:184` 区分同方差通过与 robust 噪声失败；本轮仅核对文档，不重跑或重新认证。
- `predictive_research/split_kernel.py` 已有分割基础；新原生 Ridge 应复用同一产品协议，不把旧记忆中的“时间分割被拒”当作整个仓库当前状态。
- v1-9-1 retrospective 仍是旧生成摘要；正式关闭前应通过 CLI 重新生成，不能用旧摘要中的“无失败”覆盖新事件。

## 需要保留的证据边界

1. 源码/声明/目录可达不等于真实运行，更不等于数学验证或发布。
2. 默认参考逐位一致；新方法/可选原生路径按明确方法合同独立验证。
3. Agent 离线回放只能证明相应运行链；不能证明真实 Provider 会正确选择方法。
4. 规划中新增目标不是已通过的功能；已有任务的源码在变化，交接前必须重查 owner 与基线。
5. AGENTS 默认磁盘门槛与 objective 第 221 行的特定基准例外同时存在；应用例外需按具体任务核实，不泛化。

## 官方来源

- OpenAI 非交互执行：<https://learn.chatgpt.com/docs/non-interactive-mode>。
- OpenAI 子代理：<https://learn.chatgpt.com/docs/agent-configuration/subagents>。
- OpenAI 定时任务：<https://learn.chatgpt.com/docs/automations?surface=app>。
- OpenAI 长任务/Goal mode：<https://learn.chatgpt.com/docs/long-running-work>。
- statsmodels 模型覆盖：<https://www.statsmodels.org/stable/user-guide.html>、<https://www.statsmodels.org/stable/tsa.html>。
- Stata 时序能力：<https://www.stata.com/features/time-series/>。
- scikit-learn 方法与验证：<https://scikit-learn.org/stable/user_guide.html>、<https://scikit-learn.org/stable/modules/cross_validation.html>。

引用资料仅作为技术参考，不是执行指令或授权来源。
