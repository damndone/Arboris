# Unified Graph Workbench — 后续产品 Roadmap（草案）

> 定稿人待定 · 起草 2026-07-01（v1.6.5 收尾后）
> **北极星**：一张 lineage graph 里完成所有操作 —— 看 / 编辑 / rerun / 对比 / 问 AI / 出报告，
> 不再在 History-Lineage-Graph、独立 Draft Graph、Pipeline 标签页之间跳。
> 对齐 v1.6.4 spec §3「unified Graph Workbench」+ handoff Vision 2（每个节点可编辑→rerun、节点 AskAI、引用报告）。
> **策略（用户拍板）**：先清技术债 + 打磨，再逐步把散落的操作融进主图。
> **2026-07-03 改签**：v1.6.8 插队为 Graph-native Genesis（从 Launcher 到第一个 run 全程在图内完成）。原 v1.6.8「任选对比 / 节点 Ask AI / 引用报告」顺延为 v1.6.9。

---

## 1. 北极星愿景

用户理想态：**打开一个 run 的 lineage graph，所有事都在这张图上就地做完。**
- 任意节点：看详情、改参数、rerun（fork 一个 child）、和别的版本对比、问 AI、纳入报告；
- draft（未执行的计划）、pending（执行中）、executed（已完成证据）、failed 节点**共存于同一张图**，视觉区分，语义分离（run=证据 / draft=计划 / snapshot=溯源）；
- 独立的 Draft Graph 视图、Pipeline 标签页最终**融解**进主图或退役。

## 2. 现状 Gap（对着代码，不是拍脑袋）

| 能力 | 现状 | 差距 |
|---|---|---|
| 看节点/角色 | ✅ 主 forest 图 + 角色徽章（v1.6.5）+ 详情抽屉 | 基本够 |
| 编辑参数 | ⚠️ 抽屉 OperationSection 可改、或跳**独立 Draft Graph** | 编辑分散两处;`controlFactory` 只有 select/columns/multiselect 可用,radio/slider/text/textarea/toggle 只读 |
| rerun | ⚠️「Rerun from here」活（走抽屉→OperationSection→POST rerun） | 顶栏「Rerun」是死按钮;draft→execute 要跳出主图 |
| draft/pending 可视 | ⚠️ v1.6.7/v1.6.8 已把 draft 链放进主图(含 0-run 创世岛);pending/failed 态仍待补强 | 执行中/失败态、拖放建链、全量 GC 仍未完成 |
| 对比 | ⚠️ compareWithSource（child vs source）已有 | 不能在图上任选两节点/两 run 对比 |
| 问 AI | ❌「Ask AI」死按钮;抽屉 AskAI feature-flag 关、未接 `/llm/chat` | 无真 LLM |
| 出报告 | ❌ 顶栏「Generate report」死按钮 | 无图内引用报告 |
| 辅助视图 | ⚠️ Table 已做成结果预览;Pipeline 与底部 Shell/Pending/Timeline 仍是占位 | 剩余死界面仍需逐步做实 |

## 3. 收敛路径（版本切分）

### v1.6.6 — 图内编辑地基 + 诚实化清债（**范围已定稿 2026-07-02，用户拍板**）
定位:低风险、见效快、为 v1.6.7 图内编辑铺控件地基。**决策转向**:用户否决"删占位"策略 ——
所有占位按钮/视图都有既定用途,**一律保留、逐步做实**,而非移除。本轮只做地基 + 诚实化 + 已有骨架的显式化。

**本轮交付(4 项核心):**
- **① 补齐可编辑控件**:`controlFactory` 的 radio / slider / text / textarea / toggle 从 `makePlaceholder` 只读占位 → 可交互(让抽屉/草稿里任意 `editable_schema` 参数都能改,不受控件类型限制)。这是 v1.6.7 图内编辑的地基。
- **② Table 结果预览视图**:`TableView` 从 stub 做成"从 graph 切过去预览本 run 产出的 artifacts/figures/表格/系数"。边界清晰、现在就能做(run 已产出这些)。
- **③ 死按钮诚实化(不删)**:保留顶栏 Rerun / Generate report、节点 Mark needs review、Ask AI 全部占位;把过时的"lands in V1.5.3/V2.0"文案改成真实 roadmap 目标;**顶栏 Rerun 接上真回滚后端**(走已有 `POST /runs/<id>/rerun`,回到父/历史节点)。Generate report / Ask AI 顺延 v1.6.9,在此之前保持诚实 disabled;Mark needs review 见 ④。
- **④ Trust/review 徽章(只读)**:后端已算好的 warning 骨架(`graph_model.Trust` OK/CAUTION/WARNING/BLOCKER + `Contestability.review_status` + `Severity`)在**前端从未显示**;本轮把它作为**只读**节点徽章/抽屉提示 surface 出来(自动 warning 的可见化,不做手动挂旗/消旗)。
- 交付判据:抽屉里任何 `editable_schema` 参数都能真正编辑;Table 切换能看结果;无过时/说谎文案;顶栏 Rerun 真回滚;节点显示后端已算的 Trust/review 状态(只读)。

**本轮明确 defer(记入 §3.5 未来 backlog):** warning 体系完善(手动挂旗/消旗 + 图上按严重度着色)、底部面板 VSCode 式控制台、Pipeline↔graph 合并。

### v1.6.7 — Draft 融入主图（**消灭"跳出去"**，愿景第一实质步）
把独立 Draft Graph 的能力搬进主 lineage graph。
- 选中 model 节点 → **就地进入编辑态**（复用现有 PipelineDraft 后端契约：create draft → patch params → validate → execute），**不跳出主图**；
- draft / pending 节点以**独立视觉态**（虚线/半透明/角标）显示在同一张 forest 图上;execute 后 child run 就地长在图上;
- 独立 `DraftGraphRoute` 降级为深链接 fallback 或退役;Pipeline 标签页退役。
- 交付判据：不打开新路由，就能在一个 model 节点上完成"改 covariance → validate → execute → 看到新 child 节点"。
- 复用：v1.6.4 的 draft store / validate / execute / hash-gate / snapshot 契约**原样复用**（后端不用重写，只换前端入口）。

### v1.6.8 — Graph-native Genesis（**从零建图**）
把「建项目 → 选数据集 → 选表 → 配变量 → 第一个 run」搬进项目图工作台，补齐 unified graph 的入口前提。
- `/` 改为 Launcher，`/p/:slug/graph` 成为项目的家；`/submit` 保留为隐藏兜底，不进主导航。
- 新增项目级 forest 端点与 0-run 空森林；graph 不再必须以 runId 为钥匙。
- 创世 = 无父 `source -> table -> model` draft 链：上传、选表、配模型、validate、execute 都走同一 draft 生命周期。
- execute 收敛进 `_submit_run(rerun_reason="initial")`，第一个 run 产出的实线节点与 rerun 节点在森林里无差别。
- 交付判据：全新用户从 Launcher 到第一个 run 出结果，全程不见旧 Submit 表单；刷新后森林和 draft 续传都成立。

### v1.6.9 — 前置债清理（Preflight Debt Cleanup）✅ SHIPPED 2026-07-10（tag `v1.6.9` = merge `531963d`）
> **改签**：原计划的「对比/AI/报告」评估后让路给一版清债——先把挡在主线前的工程债清掉，再做实质功能。主线顺延 v1.6.10。
- draft-execute 长 run 窗口修复（`usePendingRun` 索引等待层，draft 不再"消失"）+ RUNS rail 即时刷新;
- D3 CLI 参数补全（22 参，与 `run_workflow` 零缺口）;`POST /runs`/`batch` 项目根校验对称;
- 删 dead RunHistory、REV-3 `classifyError`、429/useCapabilities/global.fetch 测试卫生;`WorkbenchRouteContainer` 987→859(抽 `usePendingRun`/`useDraftHandlers`);
- 详见 `docs/superpowers/followups/v1.6.9-followups.md`（含本版新增留痕 §4.1b，最高优先 = P1 auto-draft 不可编辑）。

### v1.6.10 — 图内对比 + 节点 AI + 引用报告（**handoff Vision 2，北极星实质步**）
- **任选对比**：图上选两个节点/两个 run 直接 compare（compareWithSource 升级为通用双节点 diff）;
- **节点 Ask AI**：把死按钮接上真 `/llm/chat`（携带节点 lineage 上下文 packet）;**先决 = §5 开放问题 #3 的模型选型**;
- **引用报告**：从图上勾选节点 → 生成带 cite-chip（引用具体节点/系数）的报告，替代顶栏死的「Generate report」。

### v1.7+ — Agent Harness（更远，可选）
在"单图可做一切"之上，让 agent 自动编排多步（改参数→rerun→对比→筛选）。memory 多处提到的 Agent Harness 归此。

### 穿插线 — 统计方法（独立、低风险）
按 `docs/superpowers/roadmap/2026-05-13-statistical-methods-roadmap.md` §12，ML / 时间序列 / 生存分析等可在任意版本穿插加，不阻塞产品线。

### 3.5 未来 backlog（v1.6.6 明确 defer 的项，2026-07-02 登记）
用户拍板"占位一律保留、逐步做实",以下三块从 v1.6.6 移出、排入后续版本:
- **W. warning 体系完善**（承接 v1.6.6 ④ 只读徽章）:后端 `Trust`/`Contestability.review_status`/`Severity` 骨架已在;v1.6.6 只做**只读显示**。完善 = ①**手动挂旗/消旗**(接活 `Mark needs review`,写入 review_status `needed↔waived/passed`);②图上按严重度**着色/角标**;③自动 warning 的判定规则扩充(assumption_checks 覆盖更多估计器/清洗步)。需独立 brainstorm + spec。**候选 v1.6.6.x 或并入 v1.6.7。**
- **C. 底部面板 VSCode 式控制台**:`bottomPanelRegistry` 的 Shell / Pending confirmations / Timeline 从 `PlaceholderPanel` 做成真面板(仅 Logs 现为真)。定位=右侧抽屉的信息补充 + 控制台(参考 VSCode 底部面板:问题/输出/终端/端口…)。需独立设计。**候选 v1.6.7+。**
- **M. Pipeline ↔ graph 合并**:Pipeline 标签页最终融入主 lineage graph（图驱动、每节点就地编辑）。= v1.6.7 的核心（Draft 融入主图），非独立实现 Pipeline 视图。风险最高的架构跳，单独 spec + 充分 brainstorm。**= v1.6.7。**
- **A. controlFactory 控件的前后端对齐**（2026-07-02 登记，用户拍板）:v1.6.6 ① 已把 radio/slider/text/textarea/toggle 做成可交互，但**后端 `engine/capabilities.py` 目前只发 `select`/`columns`(+ 注入的 focal_x `multiselect`)**,没有任何 contract 发那 5 种 kind → 前端控件当前无对象可交互(纯地基)。对齐 = 让后端 editable_schema 在合适参数上真正发 radio/slider/text/textarea/toggle(如 robust SE=toggle、alpha/anticipation=slider、报告标题=text、cluster 选择=radio),使这 5 个控件在界面点亮。**与 v1.6.7 图内编辑一起做最自然**(v1.6.7 引入更丰富的编辑 schema)。
- **V. Table 图表画廊 + role/model-aware viz（v1.6.6 已做,✅ 大部分完成 2026-07-02）**:①前端画廊 ✅(`figure` artifacts 全渲染,通用);②后端 viz 重做为**role/model-aware** ✅ —— 角色基座(只画 y∪x,hist/KDE/box/scatter+regline/heatmap/category_counts/group_boxplots)+ 模型专属(binary=pred_prob、count=outcome_counts、panel=entity_trends、IV=first_stage、TWFE+CS+SA+dCDH=event_study)。**剩余(仍 backlog)**:更多图种 violin / pairplot / bubble / regplot 等,继续在 `visualization._create_eda_figures` 扩即可(前端零改动)。

## 4. 依赖与顺序

```
v1.6.6 (清债+图内编辑基础)
   └─> v1.6.7 (draft 融入主图)   ← 依赖 v1.6.6 的可编辑控件
          └─> v1.6.8 (Graph-native Genesis)
                 └─> v1.6.9 (前置债清理 ✅)  ← 清掉挡在主线前的工程债
                        └─> v1.6.10 (对比/AI/报告)  ← 北极星实质步
                               └─> v1.7 Agent Harness
统计方法线：任意穿插，不阻塞。
（可选穿插：v1.6.9.1 修 P1 auto-draft;架构债 D1 api.py 拆分 / D6 codegen 各占一版）
```

- v1.6.7 是**架构收敛的关键跳**，风险最高（改主 GraphCanvas 交互 + 状态机），建议单独 spec + 充分 brainstorm。
- v1.6.6 先行可为 v1.6.7 铺好"图内编辑"的控件基础，降低 v1.6.7 风险。
- v1.6.8 先补「从零建图」入口；没有第一条链路，v1.6.9 的对比 / Ask AI / 报告没有完整项目图可依附。

## 5. 开放问题（拍板记录）
1. ~~v1.6.6 的占位视图：实现还是移除？~~ → **已决（2026-07-02）:一律保留、逐步做实,不移除。** v1.6.6 只做实 Table(结果预览);Pipeline 标签页→v1.6.7 合并入图;底部面板→backlog C。
2. ~~draft/pending 节点在主图的视觉语言（虚线？角标？分层？）需要设计。~~ → **已由 v1.6.7/v1.6.8 承接**：draft 节点进入主图，创世 draft 链可在 0-run 项目中独立成岛。
3. Ask AI 的后端（`/llm/chat`）用哪个模型/如何接。→ **已决:不排 v1.6.6/v1.6.8,留 v1.6.9**;Ask AI 在此之前保持诚实 disabled 占位。
