# Failure Memory 与 Development Efficiency Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每条 Workbench 开发线建立受控追加事件、确定性回顾、1/2/3 规则提升和强制 Context Pack 启动门，减少同类失败、无效 Gate 和重复上下文搜索。

**Architecture:** 新增一个不依赖产品运行时的本地 Python CLI `scripts/devline_control.py` 及小型 `backend/workbench/development_control/` 纯函数模块。CLI 是唯一文件写者；事件文件是源，回顾、索引和规则是可验证派生物。启动线先冻结 Context Pack，然后才允许产生开发状态事件。

**Tech Stack:** Python 标准库（`json`、`hashlib`、`fcntl`、`os`、`pathlib`、`re`、`datetime`）、pytest、现有 `scripts/gate.sh`。

---

## 文件映射

| 路径 | 职责 |
| --- | --- |
| `backend/workbench/development_control/events.py` | 模式、去敏、规范 JSON、哈希链、追加和校验。 |
| `backend/workbench/development_control/retrospective.py` | 纯读确定性聚合、指标和 Markdown 渲染。 |
| `backend/workbench/development_control/promotion.py` | `lesson_key` 去重计数、candidate/enforced promotion 计算。 |
| `backend/workbench/development_control/context_pack.py` | 历史选择、规则快照、manifest 和刷新判断。 |
| `scripts/devline_control.py` | `start`、`append`、`verify`、`retrospective`、`promote`、`refresh-context` 子命令。 |
| `tests/test_devline_control_events.py` | 事件契约、追加与完整性攻击回归。 |
| `tests/test_devline_control_retrospective.py` | 生成、指标和稳定性 golden 测试。 |
| `tests/test_devline_control_promotion.py` | 1/2/3、incident 去重和规则门禁。 |
| `tests/test_devline_control_context_pack.py` | 启动、选择、规则变更、路径与限额攻击。 |
| `AGENTS.md` | 极短入口规则；不存事件或可变事实。 |
| `.agent/development-control/schemas/*.json` | 版本化模式；测试样本和 CLI 共享。 |

## Task 1: 锁定事件合同与安全追加器

**Files:** Create `events.py`, schema, `tests/test_devline_control_events.py`.

- [ ] 写失败测试：合法七种事件能通过；缺少用户规定字段、未知枚举、16 KiB 超限、秘密字样、恶意 line id、符号链接目录、重复 `event_id`、断裂前序哈希、截断和重排均被拒绝。
- [ ] 运行：`PYTHONPATH=backend .venv/bin/python -m pytest tests/test_devline_control_events.py -q`；预期缺少模块失败。
- [ ] 实现纯 `canonical_event_bytes`、`validate_event`、`verify_log` 和带排他锁/O_APPEND/fsync 的 `append_event`；追加后重新从末尾验证摘要，绝不重写历史行。
- [ ] 再跑同一命令；预期通过。用两进程/线程测试确认并发写入产生完整的两行而非交错 JSON。

## Task 2: 实现确定性回顾和效率指标

**Files:** Create `retrospective.py`, `tests/test_devline_control_retrospective.py`.

- [ ] 用固定时间、固定事件 ID 的 fixture 写失败测试，断言报告包含目标、最终状态、所有用户要求章节、事件索引和每个指标的公式结果；同一输入连跑两次字节完全相同。
- [ ] 覆盖：unknown 根因、未解决事故、没有 token、首次外部环境 gate、相同指纹无新证据 gate、同 incident 重复事件、review/spec/plan churn。
- [ ] 实现只读聚合：先调用 `verify_log`，再按行号处理；MTTR 仅对应同一 `incident_id` 的首个 resolved 事件；所有零样本以 `N/A (sample=0)` 输出。
- [ ] 生成 `RETROSPECTIVE.md` 时用原子临时文件替换派生物，并在测试中确认它不会改动 `events.jsonl`。

## Task 3: 实现 1/2/3 Knowledge Promotion

**Files:** Create `promotion.py`, `tests/test_devline_control_promotion.py`, default `global-rules.json`.

- [ ] 写失败测试：同一 incident 的多次记录只计一次；第一次只出现在回顾；第二次只追加一个 candidate；第三次可机械规则产生 enabled global rule 和 ledger；不可机械规则只能产生 `AGENTS.md` 提案而不是偷偷生效。
- [ ] 为 `candidate-rules.jsonl`、`promotion-ledger.jsonl` 和 `global-rules.json` 加模式与哈希/来源引用验证；重复执行 `promote` 必须幂等。
- [ ] 实现触发标签和三个当前 lesson key：`filesystem-persistence-capability-bypass`、`native-frontend-environment-blocker`、`containment-c1-c2-boundary`。规则记录要有 `rule_id`、状态、触发 event IDs、范围、执行点、测试引用和误伤说明。
- [ ] 运行 promotion 测试；预期同类不同字面事件被同一 `lesson_key` 归并，未提供证据的候选不能升级。

## Task 4: 强制 Context Pack 启动和历史选择

**Files:** Create `context_pack.py`, extend CLI, `tests/test_devline_control_context_pack.py`, create root `AGENTS.md` managed entry.

- [ ] 写失败测试：`start` 会创建五个 required files、生成 line_started 事件；无 objective/基线、恶意 ID、过大历史、损坏 retrospective index、规则版本漂移、符号链接和未刷新 Context Pack 均 fail closed。
- [ ] 实现确定性选择：按任务标签、受影响路径、`lesson_key`，按相关度/完成时间/line id 排序，最多 10 条和 80 KiB；把未选原因、所有摘要哈希和规则版本写 manifest。
- [ ] 写入最小 `AGENTS.md`：任何新线必须以 `devline-control start` 生成并阅读 Context Pack、已生效规则和相关回顾；不允许手工创建 `.agent/devlines`。保留既有项目规则，不覆盖用户内容。
- [ ] 为 `refresh-context` 写测试：规则更改先追加 refresh-required 事件，再显式生成新版 pack；旧 pack 不得被静默覆盖。

## Task 5: CLI、门禁接线和现有线路的证据回填

**Files:** Create `scripts/devline_control.py`; modify `scripts/gate.sh` and its contract tests only after review; create `.agent/devlines/{wo-a-agent,wo-b-model-pack,wo-c-ui,wo-d-evaluation,integration-v1.7.3}/` through CLI.

- [ ] 先写 CLI 测试，覆盖 `start`、`append --event-file`、`verify`、`retrospective`、`promote` 和 `refresh-context` 的退出码及 stdout JSON；任何写命令失败不得留下半文件。
- [ ] 将快速 gate 只接入“改动 `.agent` 或 control 模块时验证日志/规则模式”；完整 release gate 增加所有活跃线日志可校验、已完成线回顾已生成、Context Pack manifest 未漂移。不要让普通产品测试因为没有新线而重跑历史 Gate。
- [ ] 仅根据当前已验证的 ledger、测试命令和审阅报告，用 CLI 追加历史回填事件。WO-A 必须记录 persistence review churn；WO-C 必须记录依赖环境 blocker 与离线恢复；WO-D 必须记录 C1/C2 boundary。每条回填都有 `historical-backfill` 标签、真实 evidence 引用，并禁止伪造时长/token。
- [ ] 对五条线分别运行 `verify` 和 `retrospective`，并将完成线写入 retrospective index；未完成线的回顾标记 `IN_PROGRESS`，不得冒充最终收口。

## Task 6: 最终验证与操作交接

**Files:** Modify release ledger / integration completion plan only to加入真实控制面证据；tests above; generated `.agent` artifacts.

- [ ] 运行：`PYTHONPATH=backend .venv/bin/python -m pytest tests/test_devline_control_events.py tests/test_devline_control_retrospective.py tests/test_devline_control_promotion.py tests/test_devline_control_context_pack.py -q`；预期全部通过。
- [ ] 运行控制面静态检查：`PYTHONPATH=backend .venv/bin/python scripts/devline_control.py verify --all`；预期每条线的行数、链、模式和 Context Pack manifest 都通过，或以结构化 blocker 退出。
- [ ] 执行仓库既有 quick gate，确认新的 `.agent` 规则不会跳过或替代 LMM、containment、浏览器、性能和 release evidence。
- [ ] `git diff --check`、秘密扫描测试、所有控制面测试通过后，更新 release ledger 为“control plane accepted”或真实阻塞状态；不能把这项控制面通过表述为 v1.7.3 发布通过。

## 计划自检

- 覆盖设计的事件事实源、回顾、全部九项指标、1/2/3 提升、Context Pack、去敏、并发、历史回填和 gate 接线。
- 没有让本地同 UID 文件权限被误称为绝对防篡改，也没有让自动规则未审阅地修改 AGENTS 行为。
- 所有实现任务先写失败测试，且 Context Pack/日志失败都 fail closed。
