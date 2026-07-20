# Failure Memory 与 Development Efficiency Control 设计

**状态：** 已授权的 v1.7.3 Integration 控制面设计；实现前必须以此为合同。
**目标：** 让每条开发线留下可机读、可复核的失败经验，并在下一条线开始前自动注入与当前任务有关的历史规则，而不是依赖 Agent 或人记得上一次出错的教训。

## 1. 范围与原则

本机制覆盖 v1.7.3 的 `wo-a-agent`、`wo-b-model-pack`、`wo-c-ui`、`wo-d-evaluation` 和 `integration-v1.7.3`，并是后续开发线的必经启动门。它记录工程过程事实，不记录模型思考过程、用户数据、密钥、完整命令输出或任意源文件内容。

它有三个不可替代的性质：

1. `events.jsonl` 是事实源，只能在尾部新增合法事件；回顾、指标、候选规则都由它确定性派生。
2. 规则提升以可去重的 `lesson_key` 和证据为基础；“同一个失败换一种措辞”不会被误判为新问题。
3. 控制工具只阻止不安全的开始、损坏的日志和已知的无效重复；它不把缺少支持的宿主、浏览器或依赖误报成产品通过。

同 UID 的本地文件系统无法提供对恶意写入者的绝对不可篡改性。因此“append-only”在本项目的可验证含义是：受控工具使用追加打开、单行写入、文件锁和 `fsync`；每行有前序哈希；校验器拒绝截断、重排、改写和不连续链。Git/CI 仍是跨机器、跨时间的审计锚点，不能宣称本地 JSONL 单独等同于安全日志服务。

## 2. 文件布局与所有权

```text
.agent/
  devlines/<line_id>/
    events.jsonl                    # 事实源，受控追加
    RETROSPECTIVE.md                # 可重建派生物，不手工编辑
    context-pack.md                 # 此线启动时冻结的输入包
    context-pack.manifest.json      # 输入哈希、规则版本、历史选择
  development-control/
    global-rules.json               # 已生效的、机器可执行规则
    candidate-rules.jsonl           # 两次出现后的待提升规则
    promotion-ledger.jsonl          # 规则升级的不可覆盖决策记录
    retrospective-index.jsonl       # 每条已完成线的安全元数据索引
    schemas/event-v1.json
    schemas/global-rule-v1.json
```

`line_id` 必须匹配 `^[a-z][a-z0-9-]{1,62}$`，不得含路径分隔符、点段、空白或 NUL。创建线时目录必须尚不存在；所有读写都从仓库根目录的已验证 `.agent/devlines` 锚定，拒绝符号链接和越界解析。控制工具是这些文件的唯一写者；生成器不得修改 `events.jsonl`。

根目录 `AGENTS.md` 是人类可读的入口，不保存可变事件；它只要求在开始开发前运行控制工具并遵守 `global-rules.json`。可自动执行的三次规则进入 `global-rules.json`，并由启动/门禁工具实际读取；只有不能机械执行但措辞已审阅的规则，才同步到 `AGENTS.md` 的受管区块。

## 3. 事件合同

每行 JSON 必须是 UTF-8 单行对象、无重复键、最大 16 KiB。以下字段全部必需，且不得为 `null`：

| 字段 | 合同 |
| --- | --- |
| `schema_version` / `event_id` | `1` 与 UUID；`event_id` 在本线唯一。 |
| `timestamp` | UTC RFC 3339，毫秒精度；只能由控制工具产生。 |
| `type` | `FAILURE`、`ERROR`、`GAP`、`WASTE`、`REVIEW`、`GATE`、`STATE_CHANGE` 之一。 |
| `subtype` / `stage` | 受控短标识；例如 `environment_dependency_missing`、`design`、`implementation`、`review`、`gate`、`integration`、`release`。 |
| `cause_status` / `cause` | `known`、`suspected`、`unknown`、`external`、`not_applicable` 之一；原因是去敏后的事实摘要。 |
| `evidence` | 至少一个结构化引用：`kind`、`ref`、`sha256`、`observed_at`；`ref` 必须是仓库相对路径、测试名、命令摘要或 SHA，不能是原始输出。 |
| `impact` / `preventability` | 影响摘要；`preventability` 为 `preventable`、`partially_preventable`、`not_preventable`、`unknown`。 |
| `resolution` / `lesson` | 解决状态（`open`、`mitigated`、`resolved`、`accepted`、`not_applicable`）及可行动教训。 |
| `incident_id` / `lesson_key` | 稳定 UUID 与规范化问题键；无事故事件可用本事件 UUID。`lesson_key` 用于 1/2/3 计数。 |
| `links` | 可为空数组，指向相关 `event_id`、候选规则或门禁运行。 |
| `prev_event_sha256` / `event_sha256` | 前一合法行的摘要和当前规范化对象摘要；首行前序为固定全零值。 |

可选字段仅限已定义的审计字段：`state_from`、`state_to`、`gate_fingerprint`、`review_round`、`artifact_digest`、`duration_ms`、`resource_usage`、`tags`。`resource_usage` 只能记录平台明确给出的 `input_tokens`、`output_tokens`、`tool_tokens`；未知必须省略，禁止估算。

事件语义：

- `FAILURE` 是已尝试的功能、验证或交付未达到合同；`ERROR` 是工具、环境或程序的异常；`GAP` 是发现但尚未尝试/无法证实的缺口；`WASTE` 是已确认没有产生新证据的工作；`REVIEW` 记录接受、变更要求或撤回；`GATE` 记录运行、跳过、阻塞和结果；`STATE_CHANGE` 记录线或关键门状态变化。
- 一个生命周期中的发现、复现、修复、复验须使用同一 `incident_id`。不确定根因不能为了闭环改写为 `known`。
- 工具在写入前做模式、尺寸、去敏、哈希链和 `lesson_key` 校验；失败时不写半行并返回结构化错误。每次追加以锁保护并 `fsync`，随后重新校验刚写行。
- 任何检测到的非法改写本身成为控制面 `ERROR/log_integrity_violation`，并阻止该线继续进入通过态；不得“修复”历史行，只能恢复经审计的完整副本并追加恢复事件。

## 4. 回顾、指标与知识提升

`RETROSPECTIVE.md` 由 `devline-control retrospective --line <id>` 从通过校验的 JSONL 生成。相同日志、生成器版本和时区必须产生字节稳定的正文（生成时间只写入独立 manifest，不进入正文）。它必须逐项给出：目标、最终状态、所有失败/错误/缺口/浪费、发生次数、重复次数、修复时间、根因、解决方案、新增测试、新增规则、未来指导，以及原始事件索引。

指标只从结构化字段计算，并报告样本不足而非编造数值：

| 指标 | 定义 |
| --- | --- |
| Failure frequency | `FAILURE + ERROR + GAP` 事件数 / 全部事件数；同时给出每 100 事件值。 |
| Repeat rate | 有前序同 `lesson_key` 的失败类事件数 / 全部失败类事件数。 |
| Recurrence rate | 出现至少两次的 `lesson_key` 数 / 有效失败类 `lesson_key` 数。 |
| MTTR | 每个已 `resolved` 事故，从其首个失败类事件到首个 resolved 事件的 UTC 毫秒差；报告中位数、样本数和未闭环数。 |
| Review churn | `REVIEW/changes_required` 数与同一工件的平均 `review_round`；撤回也单列。 |
| Spec / plan churn | 带 `artifact_digest` 变化的 `REVIEW` 或 `STATE_CHANGE` 中，标签为 `spec` / `plan` 的修订次数。 |
| Gate waste rate | 具有相同 `gate_fingerprint`、相同输入摘要且没有新证据的已执行 `GATE` 数 / 已执行 `GATE` 数；受外部环境阻塞的首次门禁不算浪费。 |
| Same-state retry rate | `STATE_CHANGE` 中 `state_from == state_to` 且 `subtype=retry` 的数 / 所有重试数。 |
| Token waste | 仅对明确标注 `WASTE` 的事件求可用 `resource_usage` token 总和；同时给出覆盖率，未知不估算。 |

知识提升按同一 `lesson_key` 的独立发生次数计算；同一个 `incident_id` 的重复写入只计一次。每次提升都必须带现有证据、测试或可复现门禁：

1. **第一次：线路经验。** 写入该线回顾的未来指导和索引。
2. **第二次：全局候选。** 向 `candidate-rules.jsonl` 追加一条含触发事件、建议控制点、误伤风险和验证方法的候选规则；启动 Context Pack 将它标为“候选，不可静默当作硬规则”。
3. **第三次：强制规则。** 若可机械执行，工具生成并启用 `global-rules.json` 条目和对应测试/门禁；若只能是行为规则，生成待审阅的 `AGENTS.md` 受管区块提案，并阻止把它标为生效，直到 Integration owner 以证据接受。两者都要写入 `promotion-ledger.jsonl`。这避免普通同 UID 写入者在未经审阅时修改全局 Agent 行为，同时满足“第三次必须升级为 AGENTS 或自动化规则”的可审计门槛。

当前强制标签：WO-A 用 `filesystem-persistence-capability-bypass` 归并 persistence review churn；WO-C 用 `native-frontend-environment-blocker` 归并依赖/环境门禁；WO-D 用 `containment-c1-c2-boundary` 归并工作包边界澄清。历史回填只能从已有报告、测试或命令证据生成，并带 `tags:["historical-backfill"]`；不得虚构时间、耗时或 token。

## 5. 新线启动与 Context Pack

`devline-control start --line <id> --objective <file> --tags <...>` 是唯一创建开发线的入口。它在创建前依次：

1. 校验仓库、line id、干净的控制面模式和当前全局规则；
2. 解析当前任务 Context Pack（目标、精确基线 SHA、许可/保护路径、依赖、测试和已知门）；
3. 从 retrospective index 按标签、受影响路径和 `lesson_key` 选择最多 10 条、最多 80 KiB 的已完成回顾；选择算法、排序、排除理由和内容哈希写入 manifest；
4. 将已生效规则、候选规则和选中的回顾摘要写入冻结 `context-pack.md`；
5. 写入首个 `STATE_CHANGE/line_started` 事件，其 evidence 指向 Context Pack manifest；只有该事件落盘后才返回可工作的线路目录。

开始、恢复和进入关键 Gate 都重新验证 manifest 中的规则版本。规则更新后，旧线不会悄悄改变上下文：控制工具追加 `STATE_CHANGE/context_refresh_required`，要求显式刷新并记录新旧规则摘要。无法找到相关历史不是错误，但必须记录“无匹配”这一选择结果。

## 6. 安全、失败闭合与验收

日志不得含：API key、Cookie、token、绝对用户目录、数据行、原始堆栈、完整命令行参数、未哈希的私有 URL、模型提示或响应。写入器先执行可配置的密钥模式扫描，并要求 evidence 用摘要/仓库相对引用替代；命中则拒写并产生本地安全诊断（不把敏感原文再记入日志）。生成器以纯读模式运行，不能执行候选代码、网络调用或安装依赖。

控制面本身的完成条件为：事件模式/哈希/敏感信息/并发追加/截断检测有单元测试；回顾 golden 测试证明稳定生成和全部必需章节；1/2/3 promotion 及去重有测试；Context Pack 缺失、超限、规则变更、无历史、恶意 line id、符号链接和无效 JSONL 都 fail closed；WO-A/C/D 的历史回填与各自要求的 lesson key 有证据。它不替代 v1.7.3 的 containment、浏览器、性能或 release gate。
