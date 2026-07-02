# Workbench v1.6.6 — 图内编辑地基 + 诚实化清债 · 设计 spec

> 起草 2026-07-02 · 用户拍板范围(见 roadmap §3 v1.6.6 段 + backlog §3.5)
> 分支 `workbench-v1.6.6` @ `main`(v1.6.5=`5babde6`)· worktree `.worktrees/workbench-v1.6.6`
> 前置阅读:`docs/superpowers/roadmap/2026-07-01-unified-graph-workbench-roadmap.md`、
> `docs/superpowers/followups/v1.6.5-followups.md` §7(技术债全景)

## 0. 一句话
v1.6.6 = 为 v1.6.7「图内编辑」铺**控件地基** + 把**说谎的死界面诚实化**(占位一律保留、不删)。
低风险、见效快。**明确不做**:warning 体系完善(手动挂旗)、底部面板控制台、Pipeline↔graph 合并(→ roadmap §3.5 backlog)。

## 1. 范围(4 项核心)

### ① controlFactory:5 只读控件 → 可交互
**现状**(`frontend/src/lineage/controls/controlFactory.tsx`):`CONTROL_REGISTRY` 里 `radio/slider/text/textarea/toggle` 都是 `makePlaceholder`(渲染 label+value,`aria-disabled`,不接 `onChange`);只有 `select/columns/multiselect` 是活的。`ENABLED_CONTROL_KINDS` 只含后三者。
**目标**:5 个占位替换为真实交互控件,全部走既有 `renderControl(control, onChange)` 契约 + `EditableControl` 字段(`value/options/min/max/step/unit/label/key`)。注册表**禁止 switch**(硬约束,见文件头 §8)。
- `radio` — 单选组,`options` 归一化(复用 `normalizeOptions`),`onChange(key, value)`。
- `toggle` — 布尔开关(checkbox/switch),`onChange(key, boolean)`。
- `slider` — `<input type=range>` 读 `min/max/step`,显示当前值 + `unit`;`onChange(key, number)`。缺 min/max 时给安全默认或降级为 number input。
- `text` — 单行 `<input type=text>`,`onChange(key, string)`。
- `textarea` — 多行,`onChange(key, string)`。
**边界**:`visible_when` 仍只保留不强制(与现状一致)。`ENABLED_CONTROL_KINDS` 更新为全 8 种。
**test id 契约**:保持 `control-<kind>`(现有测试/OperationSection 依赖)。
**交付判据**:`OperationSection` 里任何 `editable_schema` 用到这 5 种 kind 的参数都能真正改值并触发 onChange;controlFactory.test 覆盖 5 种交互。

### ② Table 结果预览视图
**现状**(`frontend/src/workbench/views/TableView.tsx`):"coming in V1.5.3" placeholder,只有 `data-view=table` 让 switcher 契约成立。
**目标(用户定义)**:从 graph 切到 Table 就能**预览本 run 产出的 artifacts/结果**——figures、表格、系数。定位是「结果速览」,不是节点 DAG 的表格化。
**数据来源**:run 的 artifacts(`GraphViewNode.artifacts`/`coefficients`/`stats`/`preview` 已是 view model 的 forward-compat slot;需确认 serve 层是否已填,未填则本轮读取 run 的 artifact 索引)。
**MVP 内容**(按可得数据递进,至少做到系数表 + artifact 清单):
- 系数表:选中 model 节点 → 显示 `coefficients`(name/est/ci/p),若节点无则显示 run 内首个 model。
- artifact 清单:列出 run 产出的 figures/表格(名称 + 类型 + 可点开/预览缩略)。
**契约保持**:与 GraphView 同一 `selected/focus/search/action` workbench 状态(`useWorkbench`);切换不破坏 drawer/topbar/bottom panel。
**交付判据**:跑完一个 run,切到 Table 能看到该 run 的系数 + artifact 列表(非 "coming soon")。
**非目标**:表格内编辑、变量级 DAG 表格化(留后续)。

### ③ 死按钮诚实化(不删任何按钮)
**现状**(`frontend/src/workbench/registry/actionRegistry.ts`):`askAiAboutNode`/`markNeedsReview`/`rerun`(topbar)/`generateReport` 全 disabled,reason 文案是过时的 "lands in V1.5.3 / V2.0"。
**目标**:保留全部占位;把 disabled reason 改成**真实 roadmap 目标**;能激活的激活。
- **顶栏 `rerun`** → **接真回滚后端**:走已有 `POST /runs/<id>/rerun`(节点级 rerun 已活,见 memory v1.6.1/OperationSection)。语义 = 回滚/rerun 到当前选中节点所属 run 的操作(fork child)。不再 disabled。**这是 ③ 里唯一"做实"的按钮。**
- `generateReport` → disabled reason 改为「跑完 run 后接 AI 生成报告 — v1.6.8」;`shouldRender` 可加"仅在有结果的 run 上高亮/可点"的提示(至少文案诚实)。
- `markNeedsReview` → disabled reason 改为「人工挂/消 review 旗 — v1.6.6.x/v1.6.7(warning 体系)」;不接线(手动挂旗在 backlog W)。
- `askAiAboutNode` → disabled reason 改为「节点 Ask AI 接 /llm/chat — v1.6.8」。
**交付判据**:界面无过时/说谎文案;顶栏 Rerun 真触发 rerun 后端;其余 3 个 disabled 但 tooltip 诚实指向真实版本。
**测试**:actionRegistry.test 断言 reason 文案 + rerun 不再 disabled + rerun invoke 调用 POST。

### ④ Trust/review 徽章(只读)— 精确化,非从零
**重要更正**(2026-07-02 读码发现):徽章系统**已大部分实现**,followups §7 未列它为缺口是对的;缺的是精度:
- `GraphNode.badgeFor`(GraphNode.tsx:122)已渲染 `Caution`/`Review` 徽章,读 `node.trust` + decision 级 `reviewStatus∈{needed,failed}`。
- `graphAdapter.normalizeTrust`(graphAdapter.ts:74)已映射后端 trust → FE。
- `GraphTooltip` 已显示 trust label。
**真实缺口**:
- **BLOCKER 被吞**:`normalizeTrust` 把 `blocker→caution`、`warning→review`(第 76-77 行)。BLOCKER(硬阻断)与 CAUTION(轻警示)视觉无法区分。→ 让 **BLOCKER 成为独立最强变体**(FE `Trust` 加 `"blocker"`,徽章 + 配色区分;`normalizeTrust` 不再折叠)。
- **reason 不显**:`trustReason`/review 原因未进徽章 tooltip。→ 徽章 hover/tooltip 显示 `trustReason`(及 decision review 原因)。
**边界(只读)**:不做手动挂/消旗(backlog W)、不做图上按严重度重着色布局(backlog W)。仅"把后端已算好的严重度**更忠实地显示**"。
**交付判据**:后端 trust=BLOCKER 的节点显示独立 blocker 徽章(区别于 caution);徽章 tooltip 显示 trustReason。回归:现有 caution/review 徽章测试不破。

## 2. 明确不做(→ roadmap §3.5 backlog)
- **W warning 体系完善**:手动 Mark needs review 挂/消旗、图上按严重度着色/角标、自动 warning 规则扩充。
- **C 底部面板控制台**:Shell/Pending/Timeline 从 placeholder 做成真面板。
- **M Pipeline↔graph 合并**:= v1.6.7 Draft 融入主图。
- Ask AI 真 `/llm/chat`:= v1.6.8。

## 3. 风险 & 依赖
- ①②④ 纯前端,互不依赖,可并行 TDD。③ 顶栏 rerun 接线需确认 `POST /runs/<id>/rerun` 的调用点(OperationSection 已有,复用其 client)。
- ④ 改 `Trust` 联合类型(加 `"blocker"`)牵动 `graphViewTypes`/`graphAdapter`/`GraphNode`/`GraphTooltip` + 各测试,小心回归。
- 无后端契约破坏;无新依赖;golden 估计不变性不受影响(纯 UI/展示)。

## 4. 验收 gate
`LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh` 在 worktree 内跑;FE 测试用 `frontend/node_modules/.bin/vitest`。要求:BE 全绿 / golden 0-drift / FE 全绿 + 新增测试 / tsc 0。

## 5. 流程
每项 TDD(先写失败测试)→ 实现 → 三级评审(Implementer→Test&QA→Reviewer)→ 频繁提交。绝不 `git add` node_modules/.venv。不 push(用户指令,发版时统一)。
