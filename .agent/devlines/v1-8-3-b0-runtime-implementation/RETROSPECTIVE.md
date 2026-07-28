# Retrospective — v1-8-3-b0-runtime-implementation

## Goal

# B0 通用自定义能力运行时基础  **状态**：设计已批准，等待实现计划  **基线设计**：\`docs/superpowers/specs/2026-07-25-model-custom-contract-design.md\`  ## 目标  为 Agent 后续补齐 Workbench 缺失算法建立通用、隔离、可验证的执行基础。该基础不以单方程、系数表、经典标准误、p-value、某个示例模型或逐字节结果相等为根契约。  本开发线只交付三个切片：  1. **通用契约与身份**    - \`custom_capability_contract_v1\`    - 类型化输入角色    - observation identity    - \`parameter_table\`、\`metric_set\`、\`indexed_series\`、\`structured_artifact\`    - 全面有界的输出校验    - 作者字段与服务端保留字段隔离    - 覆盖代码、运行时、依赖 manifest、harness、契约和策略的 \`handler_bundle_sha256\` 2. **可复现性与证据**    - \`exact | numeric | statistical\` profile    - 分字段 comparator    - 作者自测与独立 evidence packet 分离    - 服务端派生的 E0/E1/E2/E3    - E1 强制 \`experimental\`、\`source_eligible=false\` 3. **严格运行边界**    - 独立 \`untrusted_capability_v1\` profile    - deny-by-default 宿主文件读取    - 无网络    - 密封解释器、依赖、输入、harness 和输出    - host-read canary    - 进程树级资源策略与 fail-closed admission    - 有界 stdout、stderr、JSON 和输出文件  ## 架构约束  - 通用运行时只执行密封 \`input bundle -> output bundle\`，不理解具体模型。 - \`model.custom\` 是后续第一个可信适配器；Agent 代码本身不是进程内 \`ModelHandler\`。 - 当前全局 \`MODEL_REGISTRY\` 不动态注册 Agent 代码，也不允许覆盖原生 model type。 - 报告、诊断、图表、Compare 和 rerun 支持必须由后续适配器显式声明，不能因 bundle 可运行而自动继承。 - 服务端独占 lineage、result/source/artifact 身份、样本指纹、授权、信任等级与 \`source_eligible\`。 - \`code_sha256\` 仅为源码证据；历史 rerun 必须绑定完整 bundle identity。 - 双跑不是统一字节等值闸门；验证按 exact、numeric 或 statistical 语义执行。 - 作者自带 fixture、expected 和 authority 只能获得 E1，不能单独产生 verified 或 promotion 资格。 - 现有 \`code.execute\` G3 行为不在本开发线中被静默修改；新能力使用独立且更严格的 profile。 - 无法提供所声明隔离和资源保证的宿主必须拒绝执行。  ## 本开发线不实现  - \`dependency.request\` - chain-scoped handler registry - \`model.custom\` Agent operation 或自然语言入口 - UI - 报告、诊断、图表或 Compare 适配 - \`pack.promote\` - \`WORKFLOW_STEP_SPEC_CONTRACTS\` 变更 - 任一具体新模型的产品能力  ## 完成边界  - 多种互不等价的 fixture 证明根契约不强迫所有算法伪装成 OLS。 - NaN/Inf、服务端字段伪造、样本错位、未知 facet、输出超限全部 fail closed。 - exact、numeric、statistical profile 都有正反测试。 - E1 无法越权为 verified 或 source-eligible。 - bundle 任一身份成分改变都会改变 digest。 - 宿主 sentinel 不可读、不可枚举；网络和越界写入不可用。 - 子进程树、CPU、内存、PID、墙钟与输出总量受策略约束；保证不足时拒绝。 - 不接 Agent、dependency、registry、workflow 或 promotion。 - \`tests/test_no_exercise_specific_naming.py\` 和相关 sandbox、\`code.execute\` 回归测试通过。

## Final status

CLOSED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `6e1e4dae-e3e5-4649-a477-72ae83e88e6d` | 2026-07-25T23:13:44.544Z | STATE_CHANGE/line_started | incident=`49470795-e0c4-4611-a077-c199480a3c5e` | lesson_key=`frozen-context-before-start` | event_sha256=`9105ef7a0c908ed0de8354084035fbc7c0c0a5277599607137200c89c192fc93`
- #2: `c2df7933-12db-42ec-8ac7-9801d9191683` | 2026-07-26T03:36:00.000Z | STATE_CHANGE/superseded_by_new_baseline | incident=`9ddc7945-2e13-48a8-8af4-9d54576102c0` | lesson_key=`superseded-line-needs-explicit-closeout` | event_sha256=`3f4955fcf4c4d2857d2ead9850a84c155995115b8a3b838a1e8d9bfee46f449c`
