# 工具拒绝率根因审计（2026-11-02）

审计对象：最近两轮 55 题 QRData 评测，`075c97e7`（上一轮，41/55）与 `55ce11c1`（本轮，39/55）。原始记录在 `local/agent-eval/candidate-075c97e7-qr55-20261102/` 和 `local/agent-eval/candidate-55ce11c1-qr55-20261102/`（本机，不入库）。审计只读取这些记录、发给模型的原始请求（`provider_tape.jsonl.gz`）和代码，没有修改任何评测记录。提取与分类脚本、全部中间结果在 `local/agent-eval/refusal-audit-20261102/`，可重跑。

## 三个核心问题

**Q1：12.9% 统计的是什么？**
是“返回给模型的工具结果里 `ok: false` 的比例”，按单次工具调用计：本轮 55 题共 225 个工具结果，29 个 `ok: false`；上一轮 241 个里 36 个（14.9%）。它统计的不是模型拒答，也不是按题或按步骤计。被计入的全部是工具在执行前（或读取时）拒绝了这次调用：参数格式不合 JSON Schema、步骤字段不在契约里、以及数据层面的保护性核对。权限拒绝、审批等待、数据外发管控、批准后执行失败、模型文字拒答都不计入。这个数字没有区分合理拒绝和不必要的拒绝。

**Q2：拒绝来自哪一层？**

| 层级 | 本轮 29 次 | 上一轮 36 次 |
|---|---:|---:|
| A 模型自身拒绝 | 0 | 0 |
| B Harness 限制（权限、审批、预算、沙箱） | 0 | 0 |
| C 工具参数与契约校验 | 28（96.6%） | 35（97.2%） |
| D 评测误判 | 0 | 0 |
| E 其他（调用了不存在的工具名、读取不支持的产物） | 1（3.4%） | 1（2.8%）* |

\* 上一轮的 1 次 E 是模型调用了不存在的工具 `statistical_explore`；本轮的 1 次是读取 .csv 产物（`ToolVisibleError`）。按根因再分（两次 E 分别计入 R4 和 R3）：

| 根因 | 本轮 | 上一轮 | 是否不必要的拒绝 |
|---|---:|---:|---|
| R1a 步骤字段不在提示词里，模型没查契约就猜字段名或取值 | 10 | 9 | 拒绝本身正确（未知字段不能执行），可在上游避免 |
| R1b `statistical.derive_numeric` 只有两种运算，模型写成表达式或比值 | 3 | 3 | 同上 |
| R2 产品缺陷：一对列写成 `["a","b"]` 被拒（已在 `7dece443` 修复） | 0 | 11 | **是，不必要** |
| R3 数据完整性保护（步骤没声明来源、列名不存在、声称排除却没过滤等） | 7 | 6 | 否，阻止了错误或空的分析 |
| R4 调用格式错误（JSON 写坏、缺必填项、字段放错层级、编造工具名） | 9 | 7 | 否 |

（上一轮 R4 的 7 次里有 1 次是编造工具名，本轮 R3 的 7 次里有 1 次是读取 .csv 产物，两者在层级表中记为 E。）

**Q3：有没有充分证据证明 Harness 或防护规则过严？**
**在这两轮的 65 次拒绝里，没有。** 两轮都没有权限拒绝、预算拦截、沙箱或网络拦截、超时（第四节）。唯一被证实不必要的拒绝是 R2：一个工具校验把唯一可能含义的 `["a","b"]` 当成错误，上一轮造成 11 次（占 36 次的 31%），已修复，本轮为 0。
不计入指标、但确实影响执行的两条 Harness 规则（第五节）：
1. 评测用的 `proposal_only` 策略让只读分析也要审批（`backend/workbench/agent/orchestration_permissions.py:83-86`），而告诉模型的模式说明却是 “read-only analysis runs at once”（`backend/workbench/http/agent_turn_routes.py:245-247`）。两者矛盾。这不产生拒绝，但每个只读步骤多一轮。
2. 默认数据外发管控不把行数据发给模型（`backend/workbench/agent/context_tools_support/registration.py:533-537`），两轮各 6 次，均为 `ok: true`。这是有意的隐私保护，应保留；它让 403 无法计算，但根因是产品没有网络分析能力，不是规则过严。

## 1. Executive Summary

1. 指标名叫“工具被拒率”，实际是“工具调用未通过校验的比例”。两轮都没有出现模型拒绝调用或 Harness 拦截。
2. 14.9% → 12.9% 的下降完全来自 R2 缺陷修复（−11 次）。去掉这 11 次，上一轮是 25/230 = 10.9%，本轮 12.9% 并不更好；分母也从 241 降到 225。**不能把这次下降当成 Agent 工具使用能力的提升。**
3. 最大的可修根因是 R1：13 次（本轮 45%）。提示词只给 4 个步骤写了完整字段（`backend/workbench/agent/protocol.py:142`，`REFERENCE_STEP_IDS = ("model.genesis", "report.compose", "statistical.explore", "data.subset")`）。`test.*`、`treatment_effects.estimate`、`time_series.*`、`matching.*`、`synthetic_control.*`、`statistical.derive_numeric` 只有一句 “Required: input_mode, column_bindings, options.”，提示词要求模型先调用 `inspect_operation_contract`（`protocol.py:17`）。24 次字段名被拒里只有 3 次在被拒前查过契约；本轮 027 先查契约，一次成功。`run_operation` 的 `changes` 参数 schema 只是 `{"type": "object"}`。
4. 397 与 374 根因不同，与拒绝率的关系也不同（第六节）。397 是一个新增的正确性核对生效了，但信息给了“改描述”这条退路；374 是模型猜错处理单位，前提是分组频数表只给“1 个不同值”不给是哪个值，不是拒绝问题。
5. 我此前对 374 的一个说法是错的：只读查询在逐步询问模式下确实都被批准并执行了（`confirmations` 状态均为 completed），并非“一个结果也没拿到”。结果里缺的是州编号本身。

## 2. Metric Definition

**计算代码。** 12.9% 和 14.9% 来自审计脚本 `local/agent-eval/refusal-audit-20261102/round_tools.py`，它复制了仓库脚本 `scripts/agent_eval/tool_rejections.py:22-33` 的口径：
- 每题读取 `record.json` 的 `conversation.entries`；
- 把 `entry_type == "message"` 且 `role == "tool"` 的内容，与 `entry_type == "tool_receipt"` 的 `tool_result` 按 `tool_call_id` 合并（同一调用只算一次）；
- 分母 = 工具结果个数，分子 = 其中 `ok is False` 的个数。

本轮分子 29 = `OperationValidationError` 19 + `invalid_tool_arguments` 9 + `ToolVisibleError` 1，分母 225。上一轮分子 36 = 29 + 6 + `unknown_tool` 1，分母 241。

**仓库里的正式字段没有覆盖这两轮。** `scripts/agent_eval_grade.py:372-382` 只数 `role == "tool"` 消息（不合并 `tool_receipt`），`:494` 汇总成 `tool_rejection_rate`，只用于开发集；QRData 的 `grades-v2.json` 里这个字段是 `null`。也就是说，报告里的 14.9% / 12.9% 是我用临时脚本算的，口径与仓库脚本一致，但没有进入正式评分。

**计入与不计入：**

| 事件 | 是否计入 | 两轮次数 | 证据 |
|---|---|---|---|
| JSON Schema 参数错误（`invalid_tool_arguments`） | 计入 | 6 / 9 | `backend/workbench/agent/tools.py:929-975` |
| 步骤契约与数据校验（`OperationValidationError`） | 计入 | 29 / 19 | 各题 `tool_receipt` |
| 未注册工具、产物不可读 | 计入 | 1 / 1 | 同上 |
| 审批等待（`requires_confirmation`，`ok: true`） | 不计 | 77 / 72 | 第五节 |
| 批准后执行失败（`confirmations[].status == "failed"`） | 不计 | 5 / 4 | 第三节末 |
| 数据外发管控（`egress_withheld`，`ok: true`） | 不计 | 6 / 6 | 原始请求 |
| 权限规则拒绝（`denied`） | — | 0 / 0 | |
| 超时 | — | 0 / 0 | |
| 模型文字拒答 | 不计 | 只在 403 | 第三节 |
| 免费接口 503 | 不计 | 本轮作废的两次启动 | 轮次目录 README |

**能否反映工具使用能力：** 部分能。它对“模型能不能一次写对调用”敏感，但把保护性拒绝（R3，阻止了错误分析，属于好事）和缺陷拒绝（R2）混在同一个数里，也看不到审批与外发管控造成的阻碍。≤3% 的目标若不区分 R3，会鼓励放松数据保护，这是不应该的。

## 3. Refusal Case Inventory

65 次拒绝逐条列在本节末的表格中，消息原文逐字摘自 `tool_receipt.tool_result.error_details[].message`（每条截断到 260 字符，完整原文在 `refusal-audit-20261102/refusals.json`）。表中的 `tool_call_id` 和时间戳（UTC）可在对应 `record.json` 中直接定位。记录里没有 API Key 或 Token，提取时仍做了掩码。

关于表中的“预期操作”：这些都是统计分析题，模型每次都确实发起了工具调用（65 次全部有 `tool_call_id`），没有一次是“该调工具而没调”。预期的正确调用可从拒绝信息推出（如 `allowed: columns`），逐条写出意义不大，故省略。

**模型文字拒答**（不计入指标）只出现在 403，两轮都有。本轮原文（`qrdata.403` 记录，16:26:54 UTC）：“I cannot finish the analysis because the Workbench's data-sharing policy keeps the actual adjacency matrix values on your computer — they are shown to you in the Workbench UI but not sent to me”。它收到的工具内容是（原始请求中的 tool 消息）：`"egress_withheld": true, "reason": "The call succeeded. This project's data-sharing policy keeps rows content on the user's computer, so it was not sent to the model provider."`。

**批准后执行失败**（不计入指标，原文摘录）：
- 上一轮：103 两次 “test.t_tests has no estimable comparison for the declared columns”；116 “r_t2_radiculopathy has only 1 group; there is nothing to split.”；352 “Sample size is below the configured modeling minimum.”；381 “column chain has no value 'Burger King' … Closest values: burgerking.”
- 本轮：374 “SYNTHETIC_CONTROL_PERIOD_GAPS: pre_periods and post_periods list every period, not a range; 27 period(s) lie between them in neither list”；381 同上一轮的 Burger King，以及 “produced empty group values: centralNJ, shoreNJ”；403 “column family has no value 'guadagni' … Values: ACCIAIUOL, …”。

## 4. Root Cause Classification

各类数量见开头 Q2 表，逐条分类见第三节表格，所有分类的置信度均为“高”（每条都有工具返回的原文和参数）。下面是每类的直接触发与证据。

**R1a 字段名或取值猜错（19 次）。**
- 直接触发：`test.chi_square` 写成 `row`/`column`（027、193）；`test.t_tests`/`test.evidence` 写成 `outcome`/`group`/`outcome_1`、`options.alternative`、`options.test`（070、103、106、108、109）；`input_mode` 写成 `summary`/`node`/`raw`（只允许 `frame`）；`treatment_effects.estimate` 的 `bootstrap_reps`、`att` 小写（316）；`time_series.granger` 写成 `x`/`y`（226）；`model.genesis` 把 `outcome`/`predictors` 放在顶层而非 `branches` 里（354、356）。
- 证据：发给模型的系统提示词中（`provider_tape.jsonl.gz` 首个请求，`messages[0]`），这些步骤只有一句 “Required: input_mode, column_bindings, options.”；完整字段只给 4 个步骤（`protocol.py:142`）。
- 24 次字段类拒绝中 21 次被拒前没有调用 `inspect_operation_contract`（`refusal-audit-20261102/audit_checks.py` 的输出）。
- 拒绝信息本身给出了允许的字段（如 “allowed: columns”）；就全部拒绝而言，两轮合计 52/65 次在随后两次调用内同一工具调用成功。
- 判断：属于工具暴露方式（E）与模型不遵守“先查契约”指令的叠加。至于再加一句提示词能不能让模型照做，**无法从现有记录确认（Unconfirmed）**，需要对照实验。

**R1b derive_numeric 词汇表（6 次）。** 原文：“derive_numeric recipe must contain only operator, input_columns, output_name (got: expression, output, transform); operator is natural_log or multiply”。模型要算比值、差值或表达式；这类运算应使用 `data.feature_recipe`，提示词索引对 `derive_numeric` 只写了 “a small server-defined transform vocabulary”，没有列出两种运算。

**R2 平铺的一对列（11 次，仅上一轮）。** 原文：“invalid workflow capability test.t_tests spec: test.t_tests paired_columns entries must contain exactly two column names”。参数全部是 `["bookstore_new", "amazon_new"]` 或 `["dx90_1948", "dx90_2018"]` 这样的平铺对，只有一种含义。修复 `7dece443`（`backend/workbench/agent/workflow_capability_adapters.py` 中 “One pair written flat … can only mean [["a", "b"]]”）后本轮为 0。

**R3 数据完整性保护（13 次，两轮合计）。**
- 7 次 “workflow step … does not declare a source, so it reads the original table; the dataset(s) produced by … would be ignored”：不拒绝的话，过滤或构造的数据会被静默忽略。
- 380 的列名大小写（`fullAfter` 与实际的 `fullafter`，信息列出了可用列）。
- 368 的三条模型设定错误（`polynomial degree … between 2 and 4`、`a column cannot be both a linear predictor and a categorical expansion`、`frequency_weight must name a count column`）。
- 397 的声称排除（第六节）。
- 403 读取 .csv 产物。
- 全部是应保留的合理拒绝。

**R4 调用格式错误（16 次，两轮合计）。**
- **`changes` 写成字符串（7 次）：** 每一次的字符串都不是合法 JSON，`error_details` 里有 `text_breaks_at` 和 `text_before_break`，例如 349 的 `"selected_columns": ["t", "y"] +`。同样把 `changes` 写成字符串、但 JSON 合法的有 40 次，都被正常解码执行（`tools.py:921-924` 的 `_decode_encoded_fields`）。所以拒绝是正确的。主信息写的是 “expected object, got string”，真正原因（JSON 写坏）只在附加字段里，表述有误导性。
- **把 `target` 放进 `changes`（4 次）：** 033 连续 3 次。拒绝里有路径和现成的移动补丁 `{"from": "/changes/target", "op": "move", "path": "/target"}`，模型仍原样重试，属于模型不遵循。
- **`show_dataset_rows` 缺 `run_id`（3 次）**，以及**顶层多写 `active_head_run_id`（1 次）**。

**参数格式错误每题上限：** 目标中位数 0、最多 2；本轮中位数 0，033 达到 3 次，超标。

## 5. Harness Audit

**一次工具调用的完整链路**（以本轮 027、397、374 的记录核对）：
1. 模型输出 `tool_calls`（记录中 `entry_type: message`，`role: assistant`）。
2. Harness 解码与 JSON Schema 校验：`tools.py:917-975`。R4 在这一层被拒，返回 `invalid_tool_arguments`。
3. 步骤契约校验与提案前预检：`validate_workflow_steps` 和 `orchestration_tools.py` 中的 `_preflight_*`。R1、R2、R3 在这一层被拒，返回 `OperationValidationError`。
4. 权限决定：`orchestration_permissions.py:81-115`。两轮没有一次 DENY。在 `proposal_only` 下，ANALYZE 级别的只读操作也会被改成 ASK（`:83-86`）。
5. 审批：评测驱动在回合结束时批准待定提案（`scripts/agent_eval/runner.py:59-77, 217`）。两轮各约 72 次，原因见下表。
6. 执行：批准后失败的 5 次和 4 次见第三节。
7. 返回给模型前的外发管控：`registration.py:533-537`，两轮各 6 次只给摘要。
8. 评测判定：按最终答案行评分，与工具结果无关。

| 审批原因（原文） | 上一轮 | 本轮 | 来源 |
|---|---:|---:|---|
| “Review before execution was requested for this turn.” | 49 | 44 | `proposal_only` 把只读分析也改成 ASK |
| “every step that changes something is confirmed in Ask every step” | 17 | 15 | 逐步询问模式 |
| “this operation is registered as high risk, which always needs your approval” | 11 | 13 | 高风险操作的审批地板 |

**逐层回答：**
1. 哪一层阻止了调用：65 次全部在第 2、3 层（参数与契约校验），1 次在读取层；第 4 层权限没有阻止任何调用。
2. 哪条规则：R2 对应 `paired_columns` 的形状校验（已修）。其余是 schema 的 `additionalProperties: false`、`required`，以及各步骤的字段白名单和数据核对。
3. 规则防范什么：未知字段拒绝是防止静默忽略参数（例如 `options.alternative` 被忽略却以为做了单侧检验）；来源声明核对是防止过滤后的数据被丢掉。
4. 对当前任务是否合理：除 R2 外都合理。
5. 是否因默认拒绝或审批错误导致正常任务无法执行：没有发现。审批只增加轮次，没有一次让任务失败；但第 6 条所述的说明文字与实际不一致。
6. 是否多重限制叠加：存在一个叠加，但不在拒绝里。外发管控不给行数据，分组频数表只给不同值的个数，两者叠加，使 374 这类“查编号”只能靠带过滤的频数表（上一轮 374 就是这样查到 state 3 的）。
7. 是否有路由或配置错误被误认为安全拒绝：没有。
8. **说明与策略不一致（证据充分，P1）：** 模型被告知 “Workbench: execution mode is now Ask every step. Each step that changes something is shown to the person as a card; read-only analysis runs at once.”（`agent_turn_routes.py:245-247`，374 记录中可见），但 `execution_policy` 为 `proposal_only` 时只读分析也要卡片。评测使用 `proposal_only`（`runner.py:43`，注释称这是 v1.9.0 界面默认；`scripts/agent_eval_run.py:240`）。v1.9.1 界面默认是否仍为 `proposal_only`，本次未核实（Unconfirmed）。

**三类区分：**
- **必须保留：** 审批地板（高风险、改数据）、外发管控、未知字段拒绝、来源声明核对、声称排除核对。
- **误拦截缺陷：** R2（已修）。
- **与安全无关的接口或评测问题：** R1 的契约暴露方式、R4 主信息措辞、模式说明与策略矛盾、拒绝率指标不进正式评分、指标不区分拒绝类型。

## 6. Case 397 / 374 Investigation

### 397（Florida，R²）

- 标准答案 0.851。用题目数据重算：67 个县全部纳入 R² = 0.513，去掉 PalmBeach（1 行）R² = 0.8512。两轮都答 0.513，即都在全部 67 县上拟合。
- **修复前（075c97e7）：** 没有任何拒绝。模型在 `expected_effect` 写 “Fit OLS regression of Buchanan00 on Perot96 excluding Palm Beach county”，步骤里没有过滤，提案被批准执行，最终回答 “was fit on the 67 remaining Florida counties … R² is 0.513”。没有“原始拒绝”；问题是模型声称的处理与实际执行不一致，产品没有核对。
- **修复（`9a22c6ec`）：** 新增 `_preflight_claimed_exclusions`，即本次审计中 R3 的一条。这是正确性核对，不是安全防护。
- **修复后（55ce11c1，16:22:17 起）：**
  1. 拒绝原文：“expected_effect says it excludes 'PalmBeach' (column county), but no step filters anything. Add a data.subset step with filters [...] and fit on its output, or correct expected_effect.”
  2. 模型重交时只改了描述：“Fit OLS regression of Buchanan00 on Perot96 using the cleaned data (67 counties)”，这符合信息给的第二个选项，于是通过。
  3. 最后回答又写 “excluding Palm Beach county, using the 67 remaining counties”。
- **“绕过”的含义：** 模型没有绕过安全机制，走的是信息允许的路径；问题在于这条路径让模型保留了错误信念（第一次提交时它写的是 “already excluded in cleaned data”）。核对生效了，但信息只说“没有过滤步骤”，没说该值仍在数据里。
- **审计期间的改动：** 我已把信息改成写明 “the source still has 1 of 67 rows with county = 'PalmBeach'”，并说明不打算排除就不能在回答里声称排除。尚未重测。回答阶段的“声称与执行不一致”目前没有核对，这是剩余缺口。

### 374（加州 Proposition 99，合成控制）

- **正确的处理单位：** state 3（数据中 `california == True` 的唯一州）。上一轮用 state 3，本轮用 state 16。
- **上一轮：** 模型先提交按 `group_by: california` 的频数查询，然后用 `filters: [{"column": "california", "op": "eq", "value": true}]` 再查 `state`，得到 3。答案 −21.24 错在时期写成了区间端点（只取了两个后期年份），这是另一个错误。
- **本轮：**
  1. 查询 1：`tabulate state, california`。返回两个变量各自的频数表，不是交叉表。
  2. 查询 2：`group_by: california`。加州组只返回 `"state": {"distinct": 1, "missing": 0, "obs": 31, …}`，没有值本身。
  3. 两次查询都被批准执行（`confirmations` 状态 completed），结果随后发给了模型（“The person confirmed proposal … Results …”）。
  4. 模型随后直接用 `treated_unit: "16"`，没有再查。
- **错误发生在哪：** 模型推理（猜编号）。工具输出缺口（分组频数只给个数）和外发管控（行数据不发给模型）叠加，让这一步更难。不是任务理解、数据解析或评测问题。
- **与拒绝率的关系：** 无。本轮 374 没有一次工具拒绝。时期写成区间的那次提案在批准后执行失败（“SYNTHETIC_CONTROL_PERIOD_GAPS …”），属于批准后执行失败，不计入拒绝率；模型随即改成逐年列出。
- **审计期间的改动：** 这条核对已移到提案阶段（`_preflight_pack_steps`），尚未重测。分组频数缺口尚未修。

## 7. Before / After Comparison

| | 075c97e7 | 55ce11c1 |
|---|---:|---:|
| 拒绝 / 工具结果 | 36 / 241（14.9%） | 29 / 225（12.9%） |
| 去掉 R2 后 | 25 / 230（10.9%） | 29 / 225（12.9%） |
| 有拒绝的题 | 20 | 20 |
| 单题最多拒绝 | 3（103、104、106） | 4（368） |
| 拒绝后两次调用内同工具成功 | 28 / 36 | 24 / 29 |
| 有拒绝且最终答错的题 | 6 | 10 |

- **已解决：** R2 的 11 次（103、104、106、108、109、110 等），由 `7dece443` 修复。
- **仍然存在：** R1a（9→10）、R1b（3→3）、R3（6→7）、R4（7→9）。同一题两轮出现同类拒绝的有 6 题：109、193（R1a），349（R4），368（R1b、R3），381、390（R3）；其余是不同题或不同原因。
- **新出现：** 397 的声称排除核对（新加的规则）；033 的 `target` 层级错误 3 次；070 的 test.evidence 字段错误（实际原因是缺少两比例检验）。
- **分母变化：** 241→225。分子不变时，分母这一变化会使比例上升约 0.9 个百分点（29/241 = 12.0%，29/225 = 12.9%），所以下降不是分母造成的；下降来自 R2 的 11 次。
- **拒绝修复是否降低正确率：** 没有发现直接证据。本轮从对变错的 3 题（070、316、354）里：316、354 的拒绝都在下一次调用就纠正了，错因是模型选了不同的方法或设定；070 的拒绝反映的是能力缺口。有拒绝且答错的题从 6 增到 10，但这 10 题的错因各不相同（第六节和候选轮文档已分别核实），而且每题只跑一次，不能归因于拒绝。

## 8. Prioritized Fix Plan

以下不包括放宽任何安全或数据保护规则，也不改变指标口径。

**P0-1 让模型拿到常用步骤的确切字段（预期解决 R1a、R1b：本轮 13/29）**
- 位置：`backend/workbench/agent/protocol.py:142`（`REFERENCE_STEP_IDS`）和步骤索引的渲染。
- 方向：两种方式二选一，先测提示词长度再定。
  1. 按失败频次把 `test.*`（共用一个形状）、`treatment_effects.estimate`、`statistical.derive_numeric` 等加入参考；
  2. 在索引行里写出紧凑字段，例如 `input_mode=frame; column_bindings.columns[]; options: paired_columns, reference_means`。
- 风险：提示词变长（目前 62,676 字符，走缓存），可能降低缓存命中或让模型分心。
- 回归：协议快照测试；在开发集或新题上做对照，不用这 55 题判断效果；最终才跑 held-out。
- 安全：校验强度不变。

**P0-2 分组频数表给出各组的值（预期解决 374 这一类“查编号”）**
- 位置：`statistical.explore` 的 tabulate + `group_by` 结果。
- 方向：值的个数较少时（例如不超过 50），返回组内频数（值和计数）。一维频数表已经把值发给模型，这不扩大外发范围；实现前要核对外发分类器对这类结果的处理。
- 风险：结果变大。
- 回归：外发管控测试、tabulate 契约测试。

**P1-1 模式说明与实际策略一致**
- 位置：`agent_turn_routes.py:245-247`；策略见 `orchestration_permissions.py:83-86`。
- 方向：`proposal_only` 下说明改为“只读分析也会先给卡片”。是否改变评测或界面的默认策略，属于产品决定，需要你确认，本次不改。
- 风险：低。
- 回归：模式说明测试。

**P1-2 JSON 写坏时的主信息直接说明原因**
- 位置：`tools.py:944-952`。
- 方向：主信息写成 “changes is not valid JSON; it breaks at character N near …”，保留现有字段。
- 预期：R4 中的 7 次更快纠正。
- 风险：低。

**P1-3 已完成、待重测的三处修复（在本审计请求之前已开始、已诊断）**
- 397 拒绝信息写明该值仍在数据里；
- 合成控制的时期区间在提案阶段核对（`_preflight_pack_steps` 对所有读原表的分析包步骤运行其数据预检）；
- 新增 `test.proportions`（对应 Stata `prtest`/`csi`，与 statsmodels 相差小于 1e-14），解决 070 的能力缺口。

**P2-1 把拒绝率纳入正式评分并分类**
- 方向：把审计脚本并入 `scripts/agent_eval/`，在外部题评分时输出总数，以及按 R1–R4 与“保护性拒绝”的分项；同时报告审批次数、外发管控次数、批准后执行失败次数。口径不变，只增加分项。
- 另外建议在 ≤3% 目标旁边单列“不必要的拒绝”，防止为了压数字放松保护。

**P2-2 拒绝结果自带类别**
- 方向：在 `error_details` 中加 `refusal_kind`（schema / envelope / contract / data_integrity / policy / defect），由抛出处填写，不靠事后解析文字。

**P2-3 记录模型实际看到的工具内容**
- 方向：`record.json` 中的 `tool_receipt` 保存完整输出，外发管控后的模型视图只在压缩的请求日志里。建议在记录里加 `model_view_sha256` 或外发标记，便于审计。

## 9. Evidence Gaps

1. 模型为什么不先查契约，记录里只能看到“没查”，看不到原因；加一句提示词是否有效需要对照实验（Unconfirmed）。
2. 每题只跑一次，两轮之间的逐题差异（例如 033 的 3 次、368 的 4 次）可能是随机波动，无法区分。
3. 拒绝率计算没有进入正式评分，脚本此前只在我的临时目录，现已复制到 `local/agent-eval/refusal-audit-20261102/`，但仍不在仓库里。
4. 外发管控后的模型视图只能从请求日志还原。本次只对每题最后一个请求做了统计；如果某个工具结果在最后一个请求之前已被上下文压缩丢掉，就会漏计。两轮单次请求最大 69,651 个 prompt token（上一轮 106），远低于 200,000 的压缩阈值，所以不会发生压缩，这一统计不受影响。
5. v1.9.1 界面的默认执行策略是否仍为 `proposal_only` 未核实；模式说明的问题在界面上的影响程度因此未知。
6. 没有用 Stata 或 R 复核 `test.proportions`，参考实现只有 statsmodels。
7. 未查看也不需要模型的隐藏推理；所有结论只基于可观察的输出、工具调用和执行记录。

## 附：65 次拒绝逐条表

列说明：Correct 指该题最终答案是否正确；Root cause 与 Layer 见第四节；Record 为相对 `local/agent-eval/` 的路径。

| # | Round | Case | Correct | Time (UTC) | tool_call_id | Tool | Steps | Error | Original message (verbatim, truncated at 260 chars) | Root cause | Layer | Unnecessary? | Confidence | Record |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 075c97e7 | 027 | yes | 07:11:52.601 | `68b2a04e-09db…` | run_operation | test.chi_square | OperationValidationError | test.chi_square field input_mode must be one of: frame; column_bindings.columns is required; column_bindings.row is not a field here; allowed: columns; column_bindings.column is not a field here; allowed: columns | R1a | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.027/tasks/qrdata.027.r1/record.json` |
| 2 | 075c97e7 | 103 | yes | 07:21:24.265 | `588b622d-0765…` | run_operation | statistical.derive_numeric, statistical.explore, test.t_tests | OperationValidationError | derive_numeric operator must be natural_log or multiply | R1b | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.103/tasks/qrdata.103.r1/record.json` |
| 3 | 075c97e7 | 103 | yes | 07:21:35.160 | `74513dc9-3e90…` | run_operation | statistical.explore, test.t_tests | OperationValidationError | invalid workflow capability test.t_tests spec: test.t_tests paired_columns entries must contain exactly two column names | R2 | C | Yes, unnecessary | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.103/tasks/qrdata.103.r1/record.json` |
| 4 | 075c97e7 | 103 | yes | 07:21:46.440 | `9ee64418-30b5…` | run_operation | statistical.explore, test.t_tests | OperationValidationError | invalid workflow capability test.t_tests spec: test.t_tests paired_columns entries must contain exactly two column names | R2 | C | Yes, unnecessary | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.103/tasks/qrdata.103.r1/record.json` |
| 5 | 075c97e7 | 104 | yes | 07:21:24.003 | `8f375dab-aad4…` | show_dataset_rows | — | invalid_tool_arguments | 'run_id' is a required property | R4 | C | No | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.104/tasks/qrdata.104.r1/record.json` |
| 6 | 075c97e7 | 104 | yes | 07:21:47.717 | `a51b2773-59a3…` | run_operation | test.evidence | OperationValidationError | invalid workflow capability test.evidence spec: test.evidence paired_columns entries must contain exactly two column names | R2 | C | Yes, unnecessary | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.104/tasks/qrdata.104.r1/record.json` |
| 7 | 075c97e7 | 104 | yes | 07:21:58.766 | `31718d46-1081…` | run_operation | test.evidence | OperationValidationError | invalid workflow capability test.evidence spec: test.evidence paired_columns entries must contain exactly two column names | R2 | C | Yes, unnecessary | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.104/tasks/qrdata.104.r1/record.json` |
| 8 | 075c97e7 | 106 | no | 07:23:54.017 | `b5a5192d-adee…` | run_operation | data.subset, statistical.explore | OperationValidationError | workflow step summarize_paired does not declare a source, so it reads the original table; the dataset(s) produced by complete_cases would be ignored. Declare source.from_step to read them. | R3 | C | No, protective | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.106/tasks/qrdata.106.r1/record.json` |
| 9 | 075c97e7 | 106 | no | 07:25:59.186 | `703bb29c-16e4…` | run_operation | data.subset, test.evidence | OperationValidationError | invalid workflow capability test.evidence spec: test.evidence paired_columns entries must contain exactly two column names | R2 | C | Yes, unnecessary | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.106/tasks/qrdata.106.r1/record.json` |
| 10 | 075c97e7 | 106 | no | 07:26:07.452 | `1110079b-2fa9…` | run_operation | data.subset, test.evidence | OperationValidationError | workflow step paired_test does not declare a source, so it reads the original table; the dataset(s) produced by paired_data would be ignored. Declare source.from_step to read them. | R3 | C | No, protective | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.106/tasks/qrdata.106.r1/record.json` |
| 11 | 075c97e7 | 108 | yes | 07:16:34.642 | `f82c9d09-9075…` | run_operation | test.evidence | OperationValidationError | invalid workflow capability test.evidence spec: test.evidence paired_columns entries must contain exactly two column names | R2 | C | Yes, unnecessary | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.108/tasks/qrdata.108.r1/record.json` |
| 12 | 075c97e7 | 109 | yes | 07:13:56.323 | `9f9f8c4e-154c…` | run_operation | — | OperationValidationError | test.t_tests field input_mode must be one of: frame; column_bindings.columns is required; column_bindings.outcome is not a field here; allowed: columns; column_bindings.group is not a field here; allowed: columns; options.alternative is not a field here; allow | R1a | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.109/tasks/qrdata.109.r1/record.json` |
| 13 | 075c97e7 | 109 | yes | 07:14:09.226 | `613836e5-3a60…` | run_operation | — | OperationValidationError | invalid workflow capability test.t_tests spec: test.t_tests paired_columns entries must contain exactly two column names | R2 | C | Yes, unnecessary | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.109/tasks/qrdata.109.r1/record.json` |
| 14 | 075c97e7 | 109 | yes | 07:14:28.411 | `3b45d53f-7f77…` | run_operation | — | OperationValidationError | invalid workflow capability test.evidence spec: test.evidence paired_columns entries must contain exactly two column names | R2 | C | Yes, unnecessary | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.109/tasks/qrdata.109.r1/record.json` |
| 15 | 075c97e7 | 110 | yes | 07:11:34.731 | `6b230567-84c9…` | run_operation | test.t_tests | OperationValidationError | invalid workflow capability test.t_tests spec: test.t_tests paired_columns entries must contain exactly two column names | R2 | C | Yes, unnecessary | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.110/tasks/qrdata.110.r1/record.json` |
| 16 | 075c97e7 | 110 | yes | 07:11:44.351 | `b4106b01-d314…` | run_operation | test.t_tests | OperationValidationError | invalid workflow capability test.t_tests spec: test.t_tests paired_columns entries must contain exactly two column names | R2 | C | Yes, unnecessary | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.110/tasks/qrdata.110.r1/record.json` |
| 17 | 075c97e7 | 110 | yes | 07:12:01.873 | `3ee69ad2-3a2a…` | run_operation | test.evidence | OperationValidationError | invalid workflow capability test.evidence spec: test.evidence paired_columns entries must contain exactly two column names | R2 | C | Yes, unnecessary | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.110/tasks/qrdata.110.r1/record.json` |
| 18 | 075c97e7 | 171 | yes | 07:23:16.604 | `011109e7-b10c…` | run_operation | test.chi_square | OperationValidationError | test.chi_square field input_mode must be one of: frame; column_bindings.columns is required; column_bindings.column_a is not a field here; allowed: columns; column_bindings.column_b is not a field here; allowed: columns | R1a | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.171/tasks/qrdata.171.r1/record.json` |
| 19 | 075c97e7 | 193 | yes | 07:24:04.880 | `a65aa6e2-ad7d…` | run_operation | test.chi_square | OperationValidationError | test.chi_square field input_mode must be one of: frame; column_bindings.columns is required; column_bindings.row is not a field here; allowed: columns; column_bindings.col is not a field here; allowed: columns; options.test is not a field here; allowed: paired | R1a | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.193/tasks/qrdata.193.r1/record.json` |
| 20 | 075c97e7 | 222 | no | 06:58:09.865 | `4fa295d4-939e…` | run_operation | — | OperationValidationError | time_series.granger field input_mode must be one of: frame; column_bindings.time is required; column_bindings.cause is required; column_bindings.effect is required; column_bindings.outcome is not a field here; allowed: cause, effect, time; column_bindings.pred | R1a | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.222/tasks/qrdata.222.r1/record.json` |
| 21 | 075c97e7 | 319 | yes | 07:26:42.217 | `cea9b11c-59f4…` | run_operation | — | OperationValidationError | treatment_effects.estimate field input_mode must be one of: frame; options.method must be one of: aipw, ipw, ra; options.confidence_level is not a field here; allowed: bootstrap_replications, estimand, method, seed, trim | R1a | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.319/tasks/qrdata.319.r1/record.json` |
| 22 | 075c97e7 | 322 | yes | 07:05:32.679 | `5e7dba9a-ce7a…` | run_operation | — | OperationValidationError | treatment_effects.estimate field options.method must be one of: aipw, ipw, ra; options.matching_method is not a field here; allowed: bootstrap_replications, estimand, method, seed, trim; options.n_neighbors is not a field here; allowed: bootstrap_replications, | R1a | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.322/tasks/qrdata.322.r1/record.json` |
| 23 | 075c97e7 | 343 | no | 07:04:53.131 | `c026d147-fdb1…` | statistical_explore | — | unknown_tool | tool is not registered: statistical_explore. Use one of the registered tools: calculate, check_model_claims, export_analysis_script, export_dataset, inspect_analysis_completion, inspect_analysis_loop_context, inspect_artifact_preview, inspect_builtin_skills, i | R4 | E | No | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.343/tasks/qrdata.343.r1/record.json` |
| 24 | 075c97e7 | 343 | no | 07:05:12.196 | `fe740b66-6778…` | run_operation | statistical.explore | invalid_tool_arguments | Additional properties are not allowed ('active_head_run_id' was unexpected) | R4 | C | No | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.343/tasks/qrdata.343.r1/record.json` |
| 25 | 075c97e7 | 343 | no | 07:05:47.388 | `714db26c-edec…` | run_operation | — | invalid_tool_arguments | changes: expected object, got string. The caller supplied the string; the operation was not executed. The server did not convert an object to string. Put a JSON object at arguments.changes; inspect_operation_contract lists fields. | R4 | C | No | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.343/tasks/qrdata.343.r1/record.json` |
| 26 | 075c97e7 | 349 | no | 07:09:40.678 | `771805c8-5eac…` | run_operation | — | OperationValidationError | matching.balance field column_bindings.outcome is not a field here; allowed: covariates, id, treatment | R1a | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.349/tasks/qrdata.349.r1/record.json` |
| 27 | 075c97e7 | 349 | no | 07:10:18.292 | `140607d0-f286…` | run_operation | — | invalid_tool_arguments | changes: expected object, got string. The caller supplied the string; the operation was not executed. The server did not convert an object to string. Put a JSON object at arguments.changes; inspect_operation_contract lists fields. | R4 | C | No | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.349/tasks/qrdata.349.r1/record.json` |
| 28 | 075c97e7 | 349 | no | 07:10:36.927 | `eba24d76-0109…` | run_operation | — | invalid_tool_arguments | changes: expected object, got string. The caller supplied the string; the operation was not executed. The server did not convert an object to string. Put a JSON object at arguments.changes; inspect_operation_contract lists fields. | R4 | C | No | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.349/tasks/qrdata.349.r1/record.json` |
| 29 | 075c97e7 | 352 | yes | 07:07:28.726 | `36188a0e-2824…` | run_operation | data.subset, model.genesis | OperationValidationError | workflow step estimate_ate does not declare a source, so it reads the original table; the dataset(s) produced by filter_data would be ignored. Declare source.from_step to read them. | R3 | C | No, protective | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.352/tasks/qrdata.352.r1/record.json` |
| 30 | 075c97e7 | 356 | yes | 07:06:09.062 | `f6c35623-1b93…` | run_operation | model.genesis | OperationValidationError | model.genesis spec contains unsupported field(s): outcome, predictors. Supported fields: branches, by_group, categorical, cohort_col, context_columns, covariance, did_cohort_col, did_mode, did_post_col, did_status_col, did_treat_col, entity_col, iv_endog, iv_i | R1a | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.356/tasks/qrdata.356.r1/record.json` |
| 31 | 075c97e7 | 368 | yes | 07:32:36.236 | `c993e09c-87a2…` | run_operation | — | OperationValidationError | model branch did_main: polynomial degree for poa must be between 2 and 4; degree 1 is just the linear term, so list the column in predictors instead | R3 | C | No, protective | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.368/tasks/qrdata.368.r1/record.json` |
| 32 | 075c97e7 | 368 | yes | 07:34:06.561 | `c0f8e46a-b70a…` | run_operation | — | OperationValidationError | derive_numeric recipe must contain only operator, input_columns, output_name (got: inputs, output, transform); operator is natural_log or multiply | R1b | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.368/tasks/qrdata.368.r1/record.json` |
| 33 | 075c97e7 | 381 | no | 07:19:55.426 | `8d3ba855-f498…` | run_operation | — | OperationValidationError | derive_numeric recipe must contain only operator, input_columns, output_name (got: denominator, numerator, output, transform); operator is natural_log or multiply | R1b | C/E | No (avoidable upstream) | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.381/tasks/qrdata.381.r1/record.json` |
| 34 | 075c97e7 | 381 | no | 07:20:22.310 | `4caa02be-6704…` | run_operation | — | OperationValidationError | workflow step aggregate_by_location does not declare a source, so it reads the original table; the dataset(s) produced by filter_bk would be ignored. Declare source.from_step to read them. | R3 | C | No, protective | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.381/tasks/qrdata.381.r1/record.json` |
| 35 | 075c97e7 | 390 | yes | 07:16:23.128 | `5b866982-1b12…` | run_operation | data.feature_recipe, statistical.explore | OperationValidationError | workflow step vote_share_diff does not declare a source, so it reads the original table; the dataset(s) produced by total_votes, vote_diff would be ignored. Declare source.from_step to read them. | R3 | C | No, protective | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.390/tasks/qrdata.390.r1/record.json` |
| 36 | 075c97e7 | 403 | no | 07:17:17.286 | `21d4c729-7aa5…` | show_dataset_rows | — | invalid_tool_arguments | 'run_id' is a required property | R4 | C | No | High | `candidate-075c97e7-qr55-20261102/qr55/qrdata40/ask/qrdata.403/tasks/qrdata.403.r1/record.json` |
| 37 | 55ce11c1 | 033 | yes | 16:25:41.842 | `c0c05ddb-4a01…` | run_operation | statistical.explore | invalid_tool_arguments | 'target' is a required property \| Additional properties are not allowed ('target' was unexpected) | R4 | C | No | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.033/tasks/qrdata.033.r1/record.json` |
| 38 | 55ce11c1 | 033 | yes | 16:26:09.393 | `4b79b98c-d170…` | run_operation | statistical.explore | invalid_tool_arguments | 'target' is a required property \| Additional properties are not allowed ('target' was unexpected) | R4 | C | No | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.033/tasks/qrdata.033.r1/record.json` |
| 39 | 55ce11c1 | 033 | yes | 16:27:05.264 | `ccdcf00c-52d3…` | run_operation | statistical.explore | invalid_tool_arguments | 'target' is a required property \| Additional properties are not allowed ('target' was unexpected) | R4 | C | No | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.033/tasks/qrdata.033.r1/record.json` |
| 40 | 55ce11c1 | 070 | no | 16:22:41.566 | `72e63aae-deea…` | run_operation | test.evidence | OperationValidationError | test.evidence field input_mode must be one of: frame; column_bindings.columns is required; column_bindings.outcome is not a field here; allowed: columns; column_bindings.group is not a field here; allowed: columns; options.test is not a field here; allowed: pa | R1a | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.070/tasks/qrdata.070.r1/record.json` |
| 41 | 55ce11c1 | 079 | yes | 16:20:39.282 | `a54359b8-d9cf…` | run_operation | — | invalid_tool_arguments | changes: expected object, got string. The caller supplied the string; the operation was not executed. The server did not convert an object to string. Put a JSON object at arguments.changes; inspect_operation_contract lists fields. | R4 | C | No | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.079/tasks/qrdata.079.r1/record.json` |
| 42 | 55ce11c1 | 103 | yes | 16:27:47.473 | `4a810035-644d…` | run_operation | statistical.explore, test.evidence | OperationValidationError | test.evidence field input_mode must be one of: frame; column_bindings.columns is required; column_bindings.outcome is not a field here; allowed: columns; column_bindings.paired_outcome is not a field here; allowed: columns | R1a | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.103/tasks/qrdata.103.r1/record.json` |
| 43 | 55ce11c1 | 106 | no | 16:28:56.055 | `27e21b1a-3195…` | run_operation | statistical.derive_numeric, statistical.explore | OperationValidationError | derive_numeric recipe must contain only operator, input_columns, output_name (got: expression, output); operator is natural_log or multiply | R1b | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.106/tasks/qrdata.106.r1/record.json` |
| 44 | 55ce11c1 | 106 | no | 16:29:05.441 | `68f46443-3db7…` | run_operation | test.evidence | OperationValidationError | test.evidence field input_mode must be one of: frame; column_bindings.columns is required; column_bindings.paired_columns is not a field here; allowed: columns; options.confidence is not a field here; allowed: paired_columns, reference_means | R1a | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.106/tasks/qrdata.106.r1/record.json` |
| 45 | 55ce11c1 | 108 | yes | 16:23:35.819 | `c61bc7f5-d0f1…` | run_operation | test.evidence | OperationValidationError | test.evidence field input_mode must be one of: frame; column_bindings.columns is required; column_bindings.paired_columns is not a field here; allowed: columns; options.test is not a field here; allowed: paired_columns, reference_means; options.alternative is  | R1a | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.108/tasks/qrdata.108.r1/record.json` |
| 46 | 55ce11c1 | 109 | yes | 16:21:23.928 | `9967e061-4f9d…` | run_operation | test.t_tests | OperationValidationError | test.t_tests field input_mode must be one of: frame; column_bindings.columns is required; column_bindings.outcome_1 is not a field here; allowed: columns; column_bindings.outcome_2 is not a field here; allowed: columns; options.alternative is not a field here; | R1a | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.109/tasks/qrdata.109.r1/record.json` |
| 47 | 55ce11c1 | 109 | yes | 16:21:31.804 | `7e39f1b8-4c95…` | run_operation | test.t_tests | OperationValidationError | test.t_tests field options.alternative is not a field here; allowed: paired_columns, reference_means | R1a | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.109/tasks/qrdata.109.r1/record.json` |
| 48 | 55ce11c1 | 193 | yes | 16:30:01.971 | `b88cf4fb-7581…` | run_operation | test.chi_square | invalid_tool_arguments | Additional properties are not allowed ('target' was unexpected) | R4 | C | No | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.193/tasks/qrdata.193.r1/record.json` |
| 49 | 55ce11c1 | 193 | yes | 16:30:10.269 | `e5ca82b3-5aeb…` | run_operation | test.chi_square | OperationValidationError | test.chi_square field input_mode must be one of: frame; column_bindings.columns is required; column_bindings.column is not a field here; allowed: columns; column_bindings.row is not a field here; allowed: columns | R1a | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.193/tasks/qrdata.193.r1/record.json` |
| 50 | 55ce11c1 | 222 | no | 16:37:23.165 | `bdb0aa60-ddb4…` | show_dataset_rows | — | invalid_tool_arguments | 'run_id' is a required property | R4 | C | No | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.222/tasks/qrdata.222.r1/record.json` |
| 51 | 55ce11c1 | 226 | yes | 16:12:47.841 | `806f5685-04f2…` | run_operation | — | OperationValidationError | time_series.granger field input_mode must be one of: frame; column_bindings.time is required; column_bindings.cause is required; column_bindings.effect is required; column_bindings.x is not a field here; allowed: cause, effect, time; column_bindings.y is not a | R1a | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.226/tasks/qrdata.226.r1/record.json` |
| 52 | 55ce11c1 | 316 | no | 16:16:05.638 | `ff0c4efd-c3bb…` | run_operation | — | OperationValidationError | treatment_effects.estimate field input_mode must be one of: frame; options.estimand must be one of: ATE, ATT, ATC; options.bootstrap_reps is not a field here; allowed: bootstrap_replications, estimand, method, seed, trim | R1a | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.316/tasks/qrdata.316.r1/record.json` |
| 53 | 55ce11c1 | 349 | no | 16:17:24.533 | `4fdf9b00-4a68…` | run_operation | — | invalid_tool_arguments | changes: expected object, got string. The caller supplied the string; the operation was not executed. The server did not convert an object to string. Put a JSON object at arguments.changes; inspect_operation_contract lists fields. | R4 | C | No | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.349/tasks/qrdata.349.r1/record.json` |
| 54 | 55ce11c1 | 352 | yes | 16:15:51.971 | `8c9b8a6e-8128…` | run_operation | — | invalid_tool_arguments | changes: expected object, got string. The caller supplied the string; the operation was not executed. The server did not convert an object to string. Put a JSON object at arguments.changes; inspect_operation_contract lists fields. | R4 | C | No | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.352/tasks/qrdata.352.r1/record.json` |
| 55 | 55ce11c1 | 354 | no | 16:33:11.153 | `f34418b4-b477…` | run_operation | model.genesis, statistical.derive_numeric | OperationValidationError | model.genesis spec contains unsupported field(s): outcome, predictors. Supported fields: branches, by_group, categorical, cohort_col, context_columns, covariance, did_cohort_col, did_mode, did_post_col, did_status_col, did_treat_col, entity_col, iv_endog, iv_i | R1a | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.354/tasks/qrdata.354.r1/record.json` |
| 56 | 55ce11c1 | 368 | yes | 16:17:53.044 | `4afa5a28-ee64…` | run_operation | — | OperationValidationError | invalid statistical.explore spec: frequency_weight must name a count column | R3 | C | No, protective | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.368/tasks/qrdata.368.r1/record.json` |
| 57 | 55ce11c1 | 368 | yes | 16:18:40.012 | `c16828c0-84e7…` | run_operation | — | OperationValidationError | model branch did_interaction: a column cannot be both a linear predictor and a categorical expansion: jul, poa. Listing it in `categorical` alone gives the dummy set; listing it in `predictors` alone gives the linear effect on the code. | R3 | C | No, protective | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.368/tasks/qrdata.368.r1/record.json` |
| 58 | 55ce11c1 | 368 | yes | 16:18:55.362 | `ca795c0b-d81a…` | run_operation | — | invalid_tool_arguments | changes: expected object, got string. The caller supplied the string; the operation was not executed. The server did not convert an object to string. Put a JSON object at arguments.changes; inspect_operation_contract lists fields. | R4 | C | No | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.368/tasks/qrdata.368.r1/record.json` |
| 59 | 55ce11c1 | 368 | yes | 16:19:05.360 | `58047c88-1acd…` | run_operation | model.genesis, statistical.derive_numeric | OperationValidationError | derive_numeric recipe must contain only operator, input_columns, output_name (got: columns, output, transform); operator is natural_log or multiply | R1b | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.368/tasks/qrdata.368.r1/record.json` |
| 60 | 55ce11c1 | 380 | no | 16:34:13.732 | `58558f1e-b997…` | run_operation | statistical.explore | OperationValidationError | workflow step summarize_by_location references missing column(s): fullAfter, fullBefore, partAfter, partBefore. Columns it can read: chain, fullafter, fullbefore, location, partafter, partbefore, wageafter, wagebefore. | R3 | C | No, protective | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.380/tasks/qrdata.380.r1/record.json` |
| 61 | 55ce11c1 | 381 | no | 16:25:55.139 | `15de2080-2188…` | run_operation | — | OperationValidationError | workflow step summarize_nj_pa does not declare a source, so it reads the original table; the dataset(s) produced by filter_bk would be ignored. Declare source.from_step to read them. | R3 | C | No, protective | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.381/tasks/qrdata.381.r1/record.json` |
| 62 | 55ce11c1 | 390 | yes | 16:23:50.756 | `16b03737-ac82…` | run_operation | statistical.derive_numeric, statistical.explore | OperationValidationError | derive_numeric recipe must contain only operator, input_columns, output_name (got: expression, output, transform); operator is natural_log or multiply | R1b | C/E | No (avoidable upstream) | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.390/tasks/qrdata.390.r1/record.json` |
| 63 | 55ce11c1 | 390 | yes | 16:24:23.257 | `0abfb141-a879…` | run_operation | data.feature_recipe, statistical.explore | OperationValidationError | workflow step create_vote_share_diff does not declare a source, so it reads the original table; the dataset(s) produced by create_total_votes, create_vote_diff would be ignored. Declare source.from_step to read them. | R3 | C | No, protective | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.390/tasks/qrdata.390.r1/record.json` |
| 64 | 55ce11c1 | 397 | no | 16:22:37.665 | `e02dc1e7-6a00…` | run_operation | model.genesis | OperationValidationError | expected_effect says it excludes 'PalmBeach' (column county), but no step filters anything. Add a data.subset step with filters [{"column": "county", "op": "ne", "value": "PalmBeach"}] and fit on its output, or correct expected_effect. | R3 | C | No, protective | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.397/tasks/qrdata.397.r1/record.json` |
| 65 | 55ce11c1 | 403 | no | 16:25:21.175 | `4ae3ec65-62e1…` | inspect_operation_artifact | — | ToolVisibleError | OPERATION_ARTIFACT_UNAVAILABLE: this artifact is a .csv file (such as the workflow's report), not a JSON result. Its numbers come from the operation's analysis steps: read their result artifacts (the other artifact ids of this operation) instead. | R3 | E | No, protective | High | `candidate-55ce11c1-qr55-20261102/qr55/qrdata40/ask/qrdata.403/tasks/qrdata.403.r1/record.json` |

## 10. 修复后验证（2026-11-02 晚）

修复分两批提交，每批都跑完整 55 题（同一驱动、同一模型和免费路线、同一评分），拒绝率用第 2 节的同一脚本（`round_tools.py`），根因用 `classify_v2.py`。v2 只为 v1 漏判、落入 R3 默认类的新消息补了规则，用它重算前两轮，数字与 v1 完全相同。

**第一批 `c410f4f7` + `172d65cd`：**
- test.proportions、397 拒绝写明该值仍在数据里、分析包数据预检移到提案阶段；
- 步骤索引给出字段签名，字段被拒时附上该步骤签名；分组频数表把各组的值交给模型；JSON 写坏时先说位置；模式说明与审批策略一致。

**第一批之后的一轮（`candidate-172d65cd-qr55-20261102`）暴露了我引入的问题：**
- 为了省字数，签名里省略了默认的 `input_mode: "frame"`，只在一行总说明里提了一句。模型没有照做，7 次被拒为 “spec is missing required field(s): input_mode”。
- `data.feature_recipe` 的 `parameters` 只显示为 object，模型猜参数名，6 次被拒。
- `show_dataset_rows` 6 次只给了别的读取工具用的 `owner_run_id`，没给 `run_id`。
- 这一轮的拒绝率为 35/221（15.8%），比基线 12.9% 更高；R1a+R1b（猜字段）去掉 input_mode 一项后从 13 降到 2，但上面三类新增 19 次。
- 这一轮耗时大增（单题中位数 243 秒，基线 56 秒）的原因在服务端：请求日志里有 145 次 HTTP 429（基线 7 次），每次重试等待 20–60 秒；成功请求 291 次，与基线 297 次相当。

**第二批 `3724e8b2`：** 签名总是写出 input_mode；有分支的步骤（data.feature_recipe）列出各分支的参数；只读工具要求 `run_id` 而只给了 `owner_run_id` 时，用该值并写一条说明（只给 `active_head_run_id` 时不替换）。

**第二批之后的一轮（`candidate-3724e8b2-qr55-20261102`）：** 42 题时因磁盘低于 5 GB 下限暂停（用户的 Codex 会话和交换文件占满空间，不是这一轮），关机后从同一驱动接着跑完；已完成的题没有重跑。

| | 55ce11c1（基线） | 172d65cd | 3724e8b2 |
|---|---:|---:|---:|
| 答对 / 55 | 39 | 41 | 40 |
| 对基线配对 McNemar | | p = 0.774 | p = 1.000 |
| 工具调用被拒 | 29 / 225（12.9%） | 35 / 221（15.8%） | 23 / 236（9.7%） |
| 猜字段（R1a+R1b+R1c） | 13 | 16 | 4 |
| 数据完整性保护（R3） | 7 | 9 | 11 |
| 调用格式（R4） | 9 | 10 | 8 |
| 参数格式错误：每题中位数 / 最多 | 0 / 3 | 0 / 2 | 0 / 3 |
| 批准后执行失败 | 4 | 2 | 10 |
| 请求的 prompt token 中位数 | 38,823 | 42,112 | 43,796 |

- 猜字段从 13 次降到 4 次，是这批修复的主要效果；R3、R4 没有下降。
- 批准后执行失败升到 10 次，其中两项是产品缺陷：070 的两比例检验在模型手工造出一个只有一个值的分组列后报 “unsupported semantic type”；403 一行数据的描述统计在导出 PDF 时因为标准差为空而整步失败（“unsupported format string passed to NoneType.__format__”）。其余是数据层面的正常拒绝（不存在的取值、比值分母为零等）。
- 安全没有退化：三轮都没有规则拒绝；高风险与改数据的审批、Review every step 的审批、外发管控都照常出现。
- 仍错的 15 题中，109 两轮都错，查实是产品输出问题：配对差值没写明是谁减谁，模型把 1948 减 2018 的负值读成 “2018 年更少”；397 两轮都错，模型因为题目说 68 个县、数据只有 67 行而相信 Palm Beach 已被去掉，方案里不再写 “排除”，所以核对没有触发。其余是之前已归类的模型判断或标准答案问题。

**第三批 `bade061a`：** 配对结果写明方向和两列均值；排除核对也读最新的用户请求；角色列算作已声明的列；没声明来源时给出要写的 source。另外把旧评测轮的大 JSON 记录改为 APFS 透明压缩（同路径、同字节，校验 0 失败），腾出约 10 GB。

**第四批 `3f281a47`：** PDF 导出遇到空统计量写 n/a；两比例检验在计数表恰好两行且没有分组列时，每行就是一组；只有一个允许值的必填字段（如 input_mode）缺失时取该值，给了错误的值照样拒绝。

**没有改的：** `target` 等字段放错层级时，拒绝里已附现成的移动补丁，三次都在下一次调用改对；这是有意的审计设计（原调用保持被拒），自动改写会削弱它，所以保留。403 缺网络分析能力，补这一族操作超出本轮范围，记为能力缺口。

**第四批之后的一轮（`candidate-3f281a47-qr55-20261103`）：** 55 题一次跑完，没有过载重排、没有中断。

| | 55ce11c1（基线） | 172d65cd | 3724e8b2 | 3f281a47 |
|---|---:|---:|---:|---:|
| 答对 / 55 | 39 | 41 | 40 | **43** |
| 对基线配对 McNemar | | p = 0.774 | p = 1.000 | p = 0.289 |
| 工具调用被拒 | 29 / 225（12.9%） | 35 / 221（15.8%） | 23 / 236（9.7%） | 24 / 203（11.8%） |
| 猜字段（R1a+R1b+R1c+R1d） | 13 | 16 | 4 | 4 |
| 数据完整性保护（R3） | 7 | 9 | 11 | 16 |
| 调用格式（R4） | 9 | 10 | 8 | 4 |
| 参数格式错误：每题中位数 / 最多 | 0 / 3 | 0 / 2 | 0 / 3 | 0 / 1 |
| 批准后执行失败 | 4 | 2 | 10 | 0 |
| 请求数（含被拒重试） | 305 | 443 | 450 | 405 |
| 请求的 prompt token 中位数 | 38,823 | 42,112 | 43,796 | 42,631 |

- 答对 43 题是目前最高。对基线：新答对 070、316、354、374、380、397，新答错 226、364；p = 0.289，还不能说统计上显著。
- 仍错 12 题：222、226、364 是模型判断（这三题在各轮之间对错来回变，答案格式无误）；323、343、349、351、355 是之前已核实的标准答案问题；281（答 “无因果”）和 381 是模型判断；106 四轮都答 0.33，用数据重算配对差的 t 区间下限是 0.3341，模型的数对、标准答案 0.32 与数据不符，但产品的数字核对提示 0.33 不是任何工具算出的值：配对 t 检验结果里没有均值差的置信区间，模型只能手算；403 是网络分析能力缺口，这一轮模型如实说 “现有操作算不了”，不再编数。
- 109（配对方向）、397（排除核对读请求）、070（两行计数表）、374（分组频数）都答对，对应修复生效。
- 批准后执行失败从 10 降到 0；参数格式错误每题最多 1 次。
- 被拒率 11.8% 没有继续下降，构成变了：R3 从 11 升到 16，其中 8 次是同一种写法，即步骤在 `depends_on` 里只写了一个产出数据的上游、却没写 `source`（104、106×2、355、368、380、381）。拒绝信息给出的修法就是补这一个 source，模型每次都在下一次调用照做，但每次多花一轮。其余 R3：2 次依赖两个独立上游（380、390，确有歧义）、2 次列名问题（381 大小写 `fullAfter`/`fullafter` 一次，聚合后列已不存在一次）、1 次 397 排除核对、2 次活动 head 的 run id 被模型抄错（中间一段重复了一遍）、1 次配对检验选错操作（103）。
- 安全没有退化：没有规则拒绝；改数据和 Review every step 的审批、外发管控照常出现。

**第五批（本节写完时待提交）：** 针对上面的分布：
- 步骤的 `depends_on` 只列了一个产出数据的上游、自己没写 `source`，而这个上游的结果又无法由运行时重放时，按该上游补上 source，提案里显示补好的值。这正是原来拒绝信息要求写的那一个值；依赖两个上游的仍然拒绝，可重放的上游（derive_numeric/derive_boolean）仍走原来的路径。写在 `spec` 旁边的 `source` 移进 `spec`；两处都写且不同时拒绝。
- 拒绝信息：列名只差大小写时点名对应列；`derived_variable` 说明运算数就是 inputs 的顺序；比值等参数写成表达式（如 `fullbefore + partbefore`）时说明参数只能是列名，要先在前一步算出；范围漏写 `high` 时直接说 `rules[1].from.high is required`，不再是 “does not match its closed schema”；整个提案写进了 `changes`，或在 `changes` 上写 `source` 时，说明它们应放在哪里。
- 活动 head 不一致、而 `target.run_id` 本身就是当前 head 时（054、283 是把 id 抄错了一段），拒绝直接说把 target 的 id 原样抄进 preconditions 再提，不再先绕一次 inspect_node_context；仍然拒绝原调用，重新提交时照常校验新的前置条件。
- 配对 t 检验和单样本 t 检验的结果加上均值（差）的 95% t 区间（n − 1 自由度，与 Stata ttest、R t.test 相同；对 SciPy 相对误差 1e-12 以内），只加字段，已有数字不变。
- 用这一轮的原始参数重放：104、106（两次）、355、368、381 的漏写 source 现在都能通过图校验；390 依赖两个上游的拒绝保持不变。

**第五批之后的一轮（`candidate-6af0a0da-qr55-20261103`）：** 55 题一次跑完，没有中断。

| | 55ce11c1（基线） | 3f281a47 | 6af0a0da |
|---|---:|---:|---:|
| 答对 / 55 | 39 | 43 | 41 |
| 对基线配对 McNemar | | p = 0.289 | p = 0.754 |
| 对上一轮配对 McNemar | | | p = 0.688 |
| 工具调用被拒 | 29 / 225（12.9%） | 24 / 203（11.8%） | **21 / 211（10.0%）** |
| 猜字段（R1a+R1b+R1c+R1d） | 13 | 4 | 7 |
| 数据完整性保护（R3） | 7 | 16 | 9 |
| 调用格式（R4） | 9 | 4 | 5 |
| 参数格式错误：每题中位数 / 最多 | 0 / 3 | 0 / 1 | 0 / 1 |
| 批准后执行失败 | 4 | 0 | 6 |
| 请求数（含被拒重试） | 305 | 405 | 393 |
| 单题耗时中位数（秒） | 56.1 | 224.2 | 175.0 |
| 请求的 prompt token 中位数 | 38,823 | 42,631 | 42,775 |

- 第五批的主要目标达成：上一轮 8 次 “只依赖一个产出数据的上游却没写 source” 这一轮是 0 次，R3 从 16 降到 9；拒绝率 10.0% 是五轮中第二低（最低 9.7%）。大小写、活动 head 抄错这两类本轮没有出现。
- 106 这一轮直接引用了工具算出的配对差 t 区间（下限 0.33406），不再手算；答 0.33 与数据一致，标准答案 0.32 与数据不符，归为标准答案问题。
- 答对 41，比上一轮少 2，对上一轮 p = 0.688，属于波动范围：新答对 222、364；新答错 224、239、309 都是 “哪个变量是原因” 的选择题，模型做了同样的回归后给了不同判断，三题在各轮之间对错来回变；380 先按 “全职 / 兼职” 而不是 “全职 / (全职 + 兼职)” 求比例，分母为零被拒后改用两州均值相除（均值之比不等于比例的均值）。这四题都没有工具被拒或产品出错导致的错误。
- 剩下的 21 次拒绝：R3 9 次中 3 次是依赖两个独立上游（355、380、390），模型都在下一次调用照提示串起来；4 次来自两道 Granger 题（222、239）：数据没有时间列，模型引用不存在的行号列 `obs_index`/`row_index` 各 1 次、想用 feature_recipe 造行号 1 次、给 Granger 写错 input_mode 1 次；1 次 397 排除核对；1 次频数权重只用于频数表（054）。R4 5 次中 3 次把每个步骤自己的 `expected_artifacts` 写在了 `changes` 上（349、352、397），1 次写了 `steps_existing`（381），1 次读行数超过 50 的上限（028）。R1 7 次中 2 次配对数据选了组间 t 检验（拒绝信息直接给出正确操作，下一次就改对）。
- 批准后执行失败 6 次，其中 374 的 3 次是产品缺陷，另外从错答里查出一个不报错的缺陷：
  1. **374 合成控制**：`pre_periods` 写成区间对象 `[{"low": 1970, "high": 1988}]` 时，提案校验只检查 “是数组”，放过了；批准后引擎报 “至少需要两个处理前时期”，第三次还因为把对象放进集合抛出 Python 的 TypeError。三次批准都白费。
  2. **355 教育回报**（没有失败，是静默的错误数字）：模型用 `recode` 把整数列 `educ` 映射为 `{"12": 1, ...}`。JSON 的键只能是字符串，而运行时按原值比对（整数 12 不等于字符串 "12"），一个值都没匹配上，默认值 0 填满整列；随后 OLS 对这个常数列报出系数 0.00、标准误 0，模型据此答 0.00。数据变换和估计都没有报错。
  其余 3 次批准后失败是数据层面的正常拒绝（070 分组只有一个水平、106 输出含缺失、380 分母为零）。
- 安全没有退化：没有规则拒绝；高风险与改数据的审批、Review every step 的审批、外发管控照常出现。

**第六批（全量后端 11501 通过，24 跳过，1 预期失败）：**
- `recode` 映射：一个值不是映射里的键时，再按它在 JSON 里的写法查（12 查 "12"；12.0 查 "12" 和 "12.0"），两种写法映射到不同结果时拒绝；所有值都没匹配上时不再用默认值填满整列，而是拒绝并列出该列的几个实际取值。值本身就是键（字符串列，或 Python 调用方传整数键）时走原来的路径，结果不变。recode 的脚本导出本来就沿用已核验的数据快照，不涉及导出差异。
- OLS 常数列：Agent 读系数时，标准误恰好为 0 的项标 `identified: false`，并说明该项在分析样本上是常数或是其他项的精确组合，估计值不是效应。存储的结果与拟合不变。
  - 先试过让 OLS 遇到不满秩设计直接拒绝：全量测试 16 项失败，图界面、重跑、焦点变量等流程的夹具本来就用常数列或共线列，并期待运行完成；产品里还有 Stata 式的 “变量因零方差或共线被去掉” 显示机制。把 OLS 改成拒绝会改变整个产品默认路径的行为，超出本轮范围，已撤回。
  - 未覆盖：两列精确共线（如 x 与 2x）时伪逆把效应拆到两列、标准误不为 0，这里标不出来。OLS 遇不满秩设计应该按 Stata 那样去掉并注明，还是拒绝，需要单独决定，记入待办。
- 合成控制：提案阶段就检查引擎会拒绝的条件（每个时期是一个标量，不能是区间对象；处理前至少两个时期；前后时期不重叠），不再等批准后才失败。只查引擎本身查的条件：引擎接受的未排序列表、字符串时期标签照常通过。
- 拒绝信息：写在 `changes` 上、其实属于单个步骤的字段（如 `expected_artifacts`），说明应写在 `changes.steps[i]` 上；`changes` 上的未知字段（如 `steps_existing`）说明 `changes` 只含 `steps`，读取先前操作的结果用 `target.node_ref`。仍然拒绝原调用。
- **考虑过但没做：** 两个独立的 `data.feature_recipe` 上游被同一步读取时自动串起来。`feature_recipe` 可以删行（`missing_policy: drop_rows`）、可以按所见的行拟合参数（`fit_scope`），串起来后第二个上游会在更少的行上计算，结果与方案字面不同；现有拒绝信息已给出串法，三次都在下一次调用改对，所以保留拒绝。

**第七批：OLS 不满秩设计按 Stata 的做法省略（用户 2026-11-03 选定 “像 Stata 那样去掉”）：**
- 拟合后若设计矩阵不满秩，从左到右找出 “对前面各列没有新增信息” 的列（无主元 QR 对角元与列长之比 < 1e-9，个数必须等于 statsmodels 报的秩亏，去掉后必须满秩，否则不动）。某个预测变量的全部列都在其中时，该变量从公式中去掉，在原拟合用过的同一批行上重拟合；结果里记 `omitted_terms`（变量、项名、原因：`zero_variance` 常数 / `perfect_collinearity` 共线）。x 与 2x 时去掉排在后面的 2x，与 Stata 一致。`x_columns` 仍是声明的全部变量，`formula` 是实际拟合的公式，脚本导出因此与结果一致。已有的 “变量被去掉” 检查（`_check_dropped_variables`）和图界面的 dropped 节点自然接上。
- 去掉整项后仍不满秩，只剩一种情况：某个分类变量的部分水平被其他项精确决定（如 `fine = 6 水平`、`coarse = fine mod 3`，且 coarse 排在前面）。Stata 会省略个别水平，公式项做不到，所以不省略，而是把这组相互决定的全部系数记入 `not_identified_terms`（按零空间载荷判定：不在这组里的项，如 x，照常可识别）。
- Agent 读取：被省略的项在 `omitted_terms` 里注明 “省略：分析样本上为常数 / 是前面各项的精确组合；没有估计值”；`not_identified_terms` 里的系数标 `identified: false` 并说明它不是效应。标准误恰好为 0 的旧结果仍按第六批标出。
- 满秩设计：只多读一次 statsmodels 已算好的秩，拟合、系数、标准误逐位不变（测试直接与 `smf.ols` 比对）。
- 不满秩设计的结果会变：被省略的项不再有伪逆给出的数字；与它共线的前面那一项（如 x）拿回完整效应；其余可识别的系数数值相同，但来自重拟合，只在浮点末位可能不同。第六批撤回的 16 项测试夹具在这一做法下全部通过。

**第七轮（`candidate-08cfac50-qr55-20261103`，第六、七批之后；驱动、评分、拒绝率口径都与前几轮相同）：**

| 指标 | 基线 55ce11c1 | 6af0a0da | 08cfac50 |
|---|---:|---:|---:|
| 答对 / 55 | 39 | 41 | 42 |
| 精确 McNemar p | — | 0.754（对基线） | 0.453（对基线）；1.000（对 6af0a0da） |
| 工具拒绝率 | 29/225 = 12.9% | 21/211 = 10.0% | **13/204 = 6.4%** |
| 其中调用格式错误 | 9 | 5 | 6（352 一题 3 次） |
| classify_v2：R1 / R3 / R4 | 13 / 7 / 9 | 7 / 9 / 5 | 1 / 6 / 6 |
| 批准后执行失败 | 4 | 6 | 5 |
| 请求数（含被拒重试） | 305 | 393 | 387 |
| 单题耗时中位数（秒） | 56.1 | 175.0 | 214.6 |
| 请求的 prompt token 中位数 | 38,823 | 42,775 | 42,586.5 |

- 09:45–09:46 UTC 断网约一分钟，8 题被中断；驱动按既定规则等连接恢复后从头重跑，不计入重跑次数，55 题最终都跑完。被中断的尝试另存在 `attempt0-stopped-by-429-limit/`。
- 答对 42：对 6af0a0da 新答对 224、239（因果方向选择题，各轮来回变），丢了 222（Granger，同样来回变）。355 回到各轮一贯的 4.44（标准答案问题，见前文），不再是上一轮那个由静默 recode 缺陷造成的 0.00。374 合成控制这一轮没有白费批准。差异仍在波动范围内。
- 13 次拒绝的实际组成（classify_v2 的 R4 规则对这几类消息归得粗，以下按原文逐条核对）：读行数 103 超过 50 行上限 2 次（028、079，隐私边界，保留）；`changes` 写成字符串且 JSON 本身括号写错 3 次（352，提示已要求传对象）；`expected_artifacts` 写在 `changes` 上 1 次（381，第六批的新提示生效，下一次调用就改对）；卡方缺 `options` 1 次（116）；同一列既作线性项又作分类展开 1 次（368）；两个独立上游 2 次（380、390，下一次调用都按提示串起来）；397 排除核对 1 次；403 读 CSV 报告当 JSON 1 次、引用不存在的步骤 1 次。
- 批准后失败 5 次：070 `test.proportions` 的 `group_order` 写成 `["1","2"]`，引擎要的是 `["row 1","row 2"]`，批准后才报（下一次改对，答对）；381 筛选值 'Burger King' 实为 'burgerking.'、403 'guadagni' 实为 'GUADAGNI'（守卫都列出了实际取值）；106 派生列产生缺失；116 卡方用到只有一个取值的列。后四次是数据层面的正常拒绝；070 和第六批修的 374 是同一类：本可在提案阶段检查的条件拖到批准后才失败。
- 安全没有退化：没有规则拒绝；审批与外发管控照常。

**第八批：检验族自己的数据检查前移到提案阶段（用户 2026-11-03 同意）：**
- 检验族契约（`TestFamilyContract`）新增可选的 `preflight`：在源数据上跑该族自己的检查，不计算比较结果。提案时 `_preflight_pack_steps` 对没有 `source` 的 `test.*` 步骤调用它，和第六批对合成控制的做法相同；读其他步骤输出的步骤仍在执行时检查。
- `test.proportions` 是第一个接入的族：`check_groups` 只调用引擎原有的角色、计数、分组检查（`_counts`、`_ordered`），不另写规则。没有 `group_column` 时两行计数的组名是 `row 1`/`row 2`，拒绝信息现在会说明这一点。070 那样的 `group_order` 写错会在提案时被拒，不再浪费一次批准。
- 引擎接受的写法照常通过（组顺序可互换，不写 `group_order` 时按排序）。没有 `preflight` 的族行为不变。

**第九批（`dfe879ed` 及之后）：补两项能力缺口，评测改为“离线回放 + 只真跑受影响的题”：**
- 新能力：`data.row_index` 给数据按当前顺序编 1…n 的行号，没有时间列、行已按时间排列的序列可以把它当时间列交给时间序列操作（222、239）；`network.centrality` 从邻接矩阵或边列表算度、接近中心性、介数、特征向量中心性，与公开的 Padgett 佛罗伦萨婚姻网络数值一致（MEDICI 度 6、介数 47.5，GUADAGNI 介数 23.17）。都没有改受保护的 `contracts/model`，没有新增依赖。
- 拒绝信息：JSON 字符串里括号配错时直接说该写哪个括号（352 连错三次）；`run_operation` 说明写明步骤自身字段（含 `expected_artifacts`）属于 `changes.steps[i]`。
- 离线回放：`scripts/agent_eval/replay_round.py` 把录制轮里模型的成功回复按序喂给当前代码，不发任何请求，55 题约 1 分钟；新运行铸出的 id 按种类与录制对齐。回放 08cfac50、6af0a0da、3f281a47 三轮，所有分歧都能解释：先前被拒、现在通过的 5 处来自第五到第八批；070 的组顺序、374 的区间写法改在提案阶段就拒绝；没有退化。回放还抓到第八批自身的一个缺陷：提案前检查读的是编译前的原始参数，省略 `input_mode` 的步骤被误拒（079），已修并补测试。回放测不到模型看到新提示、新能力后会怎么做，所以这部分只真跑受影响的题。
- 定向真实轮 `candidate-dfe879ed-targeted7-20261103`（与第七轮同模型、同线路、同评分、同拒绝率口径）：

| 7 道受影响的题 | 第七轮 08cfac50 | dfe879ed |
|---|---:|---:|
| 工具拒绝 | 7 | **0**（0/28） |
| 模型请求 | 81 | 49 |
| 耗时合计（秒） | 3,011 | 1,544 |
| 答对 | 3（239、352、397） | 3（同） |

- 403 现在一次就用上 `network.centrality`（请求 23 → 5，耗时 1,005 → 100 秒），答 0.033（只计可达节点：1/30）；标准答案 0.022 来自教材所用的旧版 R igraph，它把不可达节点按距离 n 计入（1/(30+16)）。这是有文档的约定，结果里补了 `closeness_unreachable_at_n` 并在网络不连通时提示各约定不同，不是为某一题调参。222 仍是方向判断题（C/B 来回）；349、381 的错与本批无关。
- 新增 `scripts/lint_rules.py`：每发现一个语法能抓住的缺陷就加一条规则并写明来源（首批：OLS 拟合必须经过省略路径、`.gitignore` 的 `node_modules/` 尾斜杠），`tests/test_lint_rules.py` 在测试里运行；抓不到的写回归测试。
