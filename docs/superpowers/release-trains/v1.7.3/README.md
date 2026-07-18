# v1.7.3 Release Train

状态：C1 Contract Sprint 进行中；未发布。

## 基线与职责

- 发布基线：`origin/main` / `v1.7.2` / `4b2e6c1d9ddd289005b84c186255fec2e9cbd86a`。
- Integration：`integration/v1.7.3`，初始提交与发布基线相同。
- C1 只能在 Integration worktree 进行；Feature、Evaluation 和 receipt worktree 必须等待实际 C1 lock。
- 两份 `honest-DiD` adversarial 测试是受保护文件，不得修改。

## 已批准的范围决定

v1.7.3 是一个 release train，包含两个独立工作包，并各自持有完成声明和证据：

1. **Report/Operations closeout**：对 v1.7.2 报告与运行运维能力的收口；其已有证据不证明 LMM 已完成。
2. **Repeated Measures / Linear Mixed Effects**：当前仅进入 C1 Contract Sprint；尚未实现、独立评估或发布。

LMM 的初始 run 是用户通过普通 RunForm / `POST /runs` 创建的显式 run。Agent 不创建初始 LMM run；仅可在一个已完成 LMM run 的确定性事实支持下，提出须用户确认的 child `model.rerun` recovery。该 recovery 扩展既有通用 `model.rerun`，不新增 executable operation type。

## C1 目标

C1 锁定版本化 LMM packet contract、canonical fixtures、真实 MixedLM feasibility 证据、薄的 Integration seams 与 OLS 回归保护。C1 不是 LMM Model Pack、Agent recipe、UI 或独立 Evaluation 的完成声明。

每个后续 lane 必须从同一个 `contract_lock_commit` 创建，且 Work Order 必须记录：发布基线、Integration base、C1、branch start、owned/read-only/forbidden paths、输入输出合同和验收命令。

## 不可做的动作

- 不调用真实 DeepSeek 或其他真实 provider；
- 不读取真实 API key；
- 不安装、卸载或修改共享依赖，也不创建 worktree-local `.venv`；
- 不创建 Feature/Evaluation lane，直到 C1 receipt 已完成；
- 不 push、PR、merge、tag 或发布，除非另获明确授权。

## 依据

- `docs/superpowers/specs/2026-07-18-adr-pd-001-parallel-development-protocol.md`
- `docs/superpowers/plans/2026-07-18-v1.7.3-repeated-measures-implementation-plan.md`
- `docs/superpowers/plans/2026-07-18-v1.7.3-report-ops-closeout.md`
- `docs/superpowers/handoffs/v1.7.3/verified-path-manifest.md`
- `docs/superpowers/handoffs/v1.7.3/verified-command-manifest.md`
