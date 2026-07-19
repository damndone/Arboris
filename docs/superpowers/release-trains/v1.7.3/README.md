# v1.7.3 Release Train

状态：C1.1 owner-binding 已锁定；未发布。

## 不可变起点

- 发布基线：`v1.7.2` / `4b2e6c1d9ddd289005b84c186255fec2e9cbd86a`。
- C1.1 合同锁：`0251f0a30d984bdbb2cfab404e6c646deab60cae`。
- receipt 分支：`release-train/v1.7.3-c1.1-contract-receipts`，仅保存治理文本，不是任何功能 Lane 的祖先。
- 两份 `honest-DiD` adversarial 测试是受保护文件，不得修改。

四条 Lane 必须用 Work Order 中的固定 `branch_start_commit` 创建：

```text
git worktree add -b <lane> <path> 0251f0a30d984bdbb2cfab404e6c646deab60cae
```

不得使用执行时的 `git rev-parse integration/v1.7.3`，也不得从 receipt commit 创建功能分支。后者两个引用都会破坏同一 wave 共享不可变起点的要求。

## C1.1 锁定范围

C1.1 是 Integration/Contract 修复，不是 LMM Model Pack、Agent recipe、UI 或 Evaluation 的完成声明。它为非空 `model_options` 建立服务端 owner binding，且要求：

- 同一已验证 owner 才能进行一层 merge；
- public `model_type`、resolved `model_id` 或合同身份变化时，必须给出完整目标 replacement，且不读取 source payload；
- hash 在 source payload 被实际复用前验证；
- Draft、executable、confirmed、successful executed audit 使用同一服务端 binding；
- 调用方不得写入 `model_options_binding`；
- 由于 `run_inputs` 会 redact secret-bearing keys，generic `model_options` 拒绝这类嵌套键，避免持久化后 hash 失真。该规则是审计一致性约束，不把 hash 表述为安全签名。

生产环境仍没有 LMM runtime/pack/声明、Agent recipe 或 UI 注册。测试中的临时 handler/mapping 只用于验证 generic seam，不能解释为功能已经接入。

## Receipt 与 Lane 治理

本 receipt 的两步提交语义为：

1. R1 为 docs-only payload，记录精确 C1.1 lock 和四个 Work Order；
2. R2 是 R1 的直接子提交，只把 R1 SHA 写入 `receipt_commit` 字段。

`receipt_commit` 是治理引用，不改变 `contract_lock_commit` 或 `branch_start_commit`。每条 Lane 的唯一非 owned metadata 输出是其 `metadata_output` 指定的 Completion Report；Lane 不得修改 README、lock manifest、Work Order 或其他 Lane 的 receipt。

## 不可做的动作

- 不调用真实 provider、不读取真实 API key；
- 不安装、卸载或修改共享依赖，也不创建 worktree-local `.venv`；
- 不 push、PR、merge、tag 或发布；
- 不在 Feature/Evaluation Lane 中修改受保护测试、公共 C1.1 contract 或中央 receipt。

## 依据

- `docs/superpowers/specs/2026-07-18-adr-pd-001-parallel-development-protocol.md`
- `docs/superpowers/plans/2026-07-18-v1.7.3-repeated-measures-implementation-plan.md`
- `docs/superpowers/plans/2026-07-18-v1.7.3-report-ops-closeout.md`
- `docs/superpowers/handoffs/v1.7.3/verified-path-manifest.md`
- `docs/superpowers/handoffs/v1.7.3/verified-command-manifest.md`
