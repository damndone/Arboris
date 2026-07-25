# Frozen Context Pack

Line: `v1-8-3-capability-factory-scope`
Baseline SHA: `c1aba93e3e9f0d478dad36f0bfc927332707e8ec`

## Objective
# v1.8.3 Capability Factory 与双层领域记忆范围目标

**状态**：范围已批准；本文件用于冻结设计开发线，不代表产品能力已实现

**版本边界**：v1.8.3

## 目标

在不扩大当前 B0 自定义能力运行时实现范围的前提下，为 v1.8.3 定义一套可长期扩展的 Agent 能力生产体系：

1. Agent 把用户目标、数据证据和所需输出解析为结构化 `CapabilityRequirement`；
2. 按“原生能力 → 已注册且已验证的第三方能力 → Agent 生成 Adapter → Agent 自研算法”的固定顺序解析实现；
3. 将依赖构建、能力验证、人工准入和分析运行彼此隔离；
4. 让不同来源的能力通过统一但非过度拟合的 capability profile、操作槽位、结果 facet、lineage 与 Artifact 边界进入 Workbench；
5. 复用现有 Agent Notebook 的推荐、并列、证据不足、备选项保留和确认后 materialize 契约；
6. 建立可显式开启或关闭的双层记忆：可重建的 Project/RunFamily 工作记忆，以及需用户批准提升的跨项目领域记忆；
7. 保证记忆只能影响候选检索与检查计划，不能提升统计证据、绕过验证、自动准入或替用户确认。

## 本设计线交付

- `README.md`：v1.8.3 范围地图、文档权威关系和分阶段边界；
- `capability-factory-design.md`：能力解析、解析顺序、Adapter、构建与运行隔离、证据与准入、Notebook 接入；
- `domain-memory-design.md`：双层记忆、用户开关、提升流程、隔离、过期与冲突语义；
- 对既有 B0 设计补充上游产品定位链接，但不改变其实现边界。

## 明确不做

- 本设计线不实现产品代码、数据库迁移、API、UI 或 Agent operation；
- 不在 Workbench 主环境中动态安装依赖；
- 不让 Agent 生成的代码直接接触用户文件、宿主文件系统、网络或主进程；
- 不把用户选择、一次成功运行、作者自测或记忆命中解释为统计正确；
- 不为所有算法强制 `fit/predict/diagnose/summarize/plot` 全接口；
- 不复制或重写现有 Notebook/Graph/Trace 契约；
- 不承诺任一具体算法、数据集、软件格式或固定年份的兼容结果；
- 不执行 push、PR、merge、tag 或发布操作。

## 完成标准

- v1.8.3 文档明确区分运行时、能力工厂、Notebook 编排、领域记忆和消费者投影；
- 能力来源、证据等级、准入状态与用户可见标签彼此独立；
- 第三方 Adapter 与 Agent 自研算法拥有不同风险路径；
- 构建阶段可联网，分析运行阶段默认断网且只读密封输入；
- 推荐“首选”必须来自已注册的支配/比较协议；并列或不可比时不得伪造唯一首选；
- Project/RunFamily 记忆是 Graph/Trace/Option 的可重建索引，不是隐藏事实源；
- 跨项目记忆具有 provenance、作用域、修订、状态、冲突和显式用户批准；
- 所有新增文档通过结构、链接、边界和反过拟合自审，正式 FMS 记录可验证。

## Boundary
- Affected paths: `docs/superpowers/specs/v1.8.3/scope-objective.md`, `docs/superpowers/specs/v1.8.3/README.md`, `docs/superpowers/specs/v1.8.3/capability-factory-design.md`, `docs/superpowers/specs/v1.8.3/domain-memory-design.md`
- Allowed paths: `docs/superpowers/specs/v1.8.3/scope-objective.md`, `docs/superpowers/specs/v1.8.3/README.md`, `docs/superpowers/specs/v1.8.3/capability-factory-design.md`, `docs/superpowers/specs/v1.8.3/domain-memory-design.md`
- Protected paths: `backend/workbench`, `frontend/src`, `docs/superpowers/specs/2026-07-25-model-custom-contract-design.md`, `docs/superpowers/specs/2026-07-25-custom-capability-foundation-objective.md`, `scripts/gate.sh`
- Dependencies: `docs/superpowers/specs/2026-07-25-model-custom-contract-design.md`, `docs/superpowers/specs/2026-07-22-v1.8.1-agent-notebook-analysis-option.md`, `docs/superpowers/specs/2026-07-23-v1.8.1-graph-first-notebook-projection-design.md`
- Tests: `git diff --check`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python scripts/devline_control.py verify --line v1-8-3-capability-factory-scope`
- Known gates: `Design-only line: no product code, migration, API, UI, or runtime implementation.`, `Existing B0 custom capability foundation remains a separate active implementation line.`, `Push, PR, merge, tag, and release require separate approval.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
