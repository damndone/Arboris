# Retrospective — v1-8-7-block1-shared-input-wiring

## Goal

# v1.8.7 块 1 共享入参薄接线 Objective  v1.8.7 块 1。**零行为薄接线**，Integration 性质的机械改动。  A1（设计方差引擎）与 A2（测量级别）都要往 Run API 与 orchestrator 加入参， 因此这两条流不是不相交的工作流。本块先由一次共享提交完成**纯字段透传**， 之后 A1 / A2 才可并行。  **本块不实现任何语义。** 新字段一路透传到 \`ctx.artifacts\`， 到此为止；没有任何 stage 消费它们，没有任何校验，没有任何行为变化。 消费与校验分别属于块 2 及之后。  ## 必须完成  1. 在 \`POST /runs\` 及其对称入口新增以下 Form 字段，默认空串/空值，全部可选：     \`\`\`    survey_strata_col        分层变量    survey_psu_col           初级抽样单元    survey_fpc_col           有限总体校正    survey_replicate_weights 数据自带的重复权重列组（JSON 数组）    survey_replicate_type    brr | jackknife | bootstrap | provided    survey_lonely_psu        fail | remove | adjust | average | certainty    survey_weight_frame      cross_sectional | longitudinal    survey_subpop            子总体表达式    \`\`\`  2. 上述字段沿既有 \`sampling_weight\` 的同一条路径透传：    HTTP → \`run_service\` → \`orchestrator\` → \`ctx.artifacts\`，    使用既有 \`_\` 前缀约定（如 \`_survey_strata_col\`）。  3. \`measurement_level\` 沿既有 \`labels\` 通道承载（不新增顶层 Form 字段）：    \`labels\` JSON 增加可选 \`measurement_level\` 映射，随既有 labels 一同透传到    \`frame.attrs\`。**本块只透传，不校验取值、不影响路由。**  4. 保持 \`POST /runs\` 与 \`/runs/batch\` 的**校验对称**（既有约定，v1.6.9 已清过一次债）。  5. CLI（\`backend/workbench/cli.py\`）同步补齐上述参数，避免重蹈 D3「CLI 缺参数」旧债。  ## 明确不做  - **不实现任何语义**：不建设计对象、不算方差、不做 lonely-PSU 处理、   不推导 degf、不产出 DEFF、不解析子总体表达式。 - **不校验新字段取值**（枚举校验属块 2）。 - 不触碰 \`backend/workbench/engine/**\`（块 2 的 owned scope）。 - 不触碰前端（A1 的 RunForm 工作在其自己的线内）。 - 不改 \`ModelFamilyContract\`（块 2/3）。 - 不改既有 \`sampling_weight\` 的 fail-closed 行为——它在块 2 才解除。 - 不 push / 不建 PR / 不 merge / 不 tag。  ## 可证伪验收  - **透传可见**：一次真实 run 传入全部新字段后，\`ctx.artifacts\` 中出现对应   \`_survey_*\` 键且值与传入一致；用测试断言，不靠阅读代码。 - **零行为**：传入新字段的 run 与不传新字段的同一 run，   产出的 artifact 集合、\`models\` 块与全部统计数值**逐位一致**。   这条是本块的核心约束——若两者有任何差异，说明混进了语义。 - **\`sampling_weight\` 行为不变**：声明 \`sampling_weight\` 仍然 fail-closed，   错误码与消息与 baseline \`9d5e947\` 逐字节一致（解除属块 2）。 - **对称性**：\`/runs\` 与 \`/runs/batch\` 对新字段的接受与校验行为一致。 - **CLI 可达**：CLI 能传入全部新参数并到达同一透传路径。 - **\`measurement_level\` 透传**：\`labels\` 中携带 \`measurement_level\` 时进入   \`frame.attrs\`，且**不影响 y_type 判定与模型路由**（断言路由结果不变）。 - golden 23 逐位 0-drift（本块不应产生任何漂移；若漂移，先当作设计被违反排查）。 - 后端全量 ≥ 4631 passed，\`git diff --check\` 干净。

## Final status

STARTED

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

- #1: `e41d9149-136f-4b1c-b689-8c031f160bc3` | 2026-08-05T17:37:48.989Z | STATE_CHANGE/line_started | incident=`e8bfffa8-a76c-4c09-9bbd-ba0e9fc11502` | lesson_key=`frozen-context-before-start` | event_sha256=`a7e203cb42bba2412e49575a5b8198b593203086abc19e0e1dee75d02e3d1647`
