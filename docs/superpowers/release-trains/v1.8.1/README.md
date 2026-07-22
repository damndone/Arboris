# v1.8.1 Release Train — Notebook 波次（ADR-PD-001 首次用于 v1.8.x）

## 这一波是什么

v1.8.1 = 一个 Notebook 产品功能 + 三项正确性基础设施，六个 Gate。
**Gate 1/2/3 已在 `workbench-v1.8.1` 串行完成**（RunFamily / Context Compiler /
Core Trace）。**Gate 4/5/6 + 可见切片按 ADR-PD-001 的 3+1 并行协议执行**，
即本 release train。

## 与 ADR-PD-001 的两处记录在案的偏离

1. **§4.1 要求 integration 从「已发布的 release 基线」建立。**
   本波次从 `d86bf30`（`workbench-v1.8.1` tip，**未合并、未发版**）建立，
   因为 Gate 4/5/6 在语义上依赖 Gate 1/2/3 的 RunFamily 身份、编译上下文与
   trace。用户于 2026-07-22 明确拍板接受此偏离。
   **后果**：本波次的 `release_baseline_commit` 不是发布快照，
   release ledger 必须同时记录 Gate 1/2/3 与 Gate 4/5/6 的证据。
2. **Model Pack Lane 的模型是新增的**（`time_series.ets`）。
   用户选择"严格按 ADR，补一个模型"而非改写 Lane 结构。ETS 不是随意挑的：
   Notebook 的前提是 Agent 给出多条可辩护路径，而这只有在**同一份数据上存在
   至少两个可比模型**时才可验证。ETS 与既有 ARMA-GARCH 构成真正的备选关系。
   用 `statsmodels.tsa.exponential_smoothing.ets`，**不引入新依赖**（§8.3）。

## 拓扑

```
workbench-v1.8.1 @ d86bf30 (Gate 1/2/3，未发布)
        │
        ▼
integration/v1.8.1
        ├── contract-only commits
        ▼
contract_lock_commit C1
        ├── feat/v181-agent-notebook-options     (Lane A)
        ├── feat/v181-model-ets                  (Lane B)
        ├── feat/v181-ui-notebook                (Lane C)
        └── test/v181-evaluation-harness         (Lane D)
        ▼
independent evaluation evidence → merge queue → integration gate
```

## Lane 与 Gate 的对应

| Lane | 分支 | Gate | 一句话职责 |
|---|---|---|---|
| A Agent | `feat/v181-agent-notebook-options` | Gate 4 | 生成 ≤3 条 typed option、生命周期、stale 判定 |
| B Model Pack | `feat/v181-model-ets` | 新模型 | ETS pack：估计、诊断、compare adapter、known-truth |
| C UI/UX | `feat/v181-ui-notebook` | Gate 6 + 可见切片 | Notebook 渲染、option 卡片、选中文本、上下文/trace 可见 |
| D Evaluation | `test/v181-evaluation-harness` | 全部 | 独立 fixture、known truth、故障注入、过度主张检查 |

Gate 5（执行与 Artifact Contract）由 Lane A 产出 proposal、Lane B 产出 artifact，
**契约在 C1 已锁**（`ArtifactContract@1.0`），两条 Lane 不直接互相依赖实现。

## 发布权限

按 ADR §13：不 push、不建 PR、不 merge、不 tag，除非用户对该动作明确授权。
