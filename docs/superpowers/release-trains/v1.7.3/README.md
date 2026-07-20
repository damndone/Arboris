# v1.7.3 Release Train

状态：C1.1 合同锁已存在；Integration 工作树已组装未提交的 LMM 候选，并完成代码、原生前端、完整本地 gate 与浏览器端到端验收。它仍不是可发布候选：没有精确提交的 Integration SHA，且 C2 缺少受支持宿主的冻结隔离 canary；性能、独立候选执行和正式发布签字仍未完成。

当前唯一的发布状态入口是 [`release-ledger.json`](release-ledger.json)。它逐项记录 owner、证据、状态和放行条件；任何单一 Lane 或局部测试通过均不等于 v1.7.3 可发布。

## 基线与职责

- 发布基线：`origin/main` / `v1.7.2` / `4b2e6c1d9ddd289005b84c186255fec2e9cbd86a`。
- Integration：`integration/v1.7.3`，初始提交与发布基线相同。
- C1 只能在 Integration worktree 进行；Feature、Evaluation 和 receipt worktree 必须等待实际 C1 lock。
- 两份 `honest-DiD` adversarial 测试是受保护文件，不得修改。

## 已批准的范围决定

v1.7.3 是一个 release train，包含两个独立工作包，并各自持有完成声明和证据：

1. **Report/Operations closeout**：对 v1.7.2 报告与运行运维能力的收口；其已有证据不证明 LMM 已完成。
2. **Repeated Measures / Linear Mixed Effects**：C1.1 合同锁已存在；Integration 工作树已接入 WO-A/WO-B/WO-C 的受控实现，包括 LMM Pack 声明、公共结果投影、Agent 只读解释、RunForm 与 Genesis 参数入口、PacketPanel 展示。它们尚未形成一个提交的 Integration SHA；WO-D 的冻结隔离执行器也尚未在支持主机上通过 canary。因此不能独立评估或发布。

LMM 的初始 run 是用户通过普通 RunForm / `POST /runs` 创建的显式 run。Agent 不创建初始 LMM run；仅可在一个已完成 LMM run 的确定性事实支持下，提出须用户确认的 child `model.rerun` recovery。该 recovery 扩展既有通用 `model.rerun`，不新增 executable operation type。

## C1 目标

C1 锁定版本化 LMM packet contract、canonical fixtures、真实 MixedLM feasibility 证据、薄的 Integration seams 与 OLS 回归保护。C1 不是 LMM Model Pack、Agent recipe、UI 或独立 Evaluation 的完成声明。

每个后续 lane 必须从同一个 `contract_lock_commit` 创建，且 Work Order 必须记录：发布基线、Integration base、C1、branch start、owned/read-only/forbidden paths、输入输出合同和验收命令。

## Integration foundation record

当前 Integration 已接线 LMM 的版本化结果读取与只读展示地基。`PublicModelResult` 是展示边界的唯一输入；前端不接受裸 `PacketEnvelope`、不计算 digest、不推导结论，也不呈现 recovery 或执行控件。canonical FigureContext 只接受两组、严格递增时间和服务器给出的均值向量。

LMM 已作为一个声明式 Pack 能力出现在受控模型入口中；Agent 只允许基于已验证公共结果提出需用户确认的建议，不能创建初始 LMM run 或绕过 WO-D 执行能力。Genesis 与普通 RunForm 都要求明确的受试者、时间、组别、拟合方法和随机斜率选项。`frontend/src/workbench/repeatedMeasures/` 仍是唯一的结果展示消费者；不创建 `frontend/src/features/repeated-measures` 平行消费者。

上述事实证明“未提交工作树中的组装已通过本地完整 gate 与浏览器端到端流程”：真实 CSV Genesis 可不虚构 sheet 名保存，LMM 参数可保存、验证并完成运行，图和结果正确标识 `linear_mixed_effects (primary)`，报告事实、PDF/XLSX 导出和 Agent 的只读 `inspect_repeated_measures_recipe` 均已实际操作验证。它仍不是精确提交候选、严格 C2 候选执行、独立 Evaluation、性能签字或 release 通过声明。

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
