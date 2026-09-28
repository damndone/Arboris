# Unified Graph Workbench — 后续产品 Roadmap（草案）

> 定稿人待定 · 起草 2026-07-01（v1.6.5 收尾后）
> **北极星**：一张 lineage graph 里完成所有操作 —— 看 / 编辑 / rerun / 对比 / 问 AI / 出报告，
> 不再在 History-Lineage-Graph、独立 Draft Graph、Pipeline 标签页之间跳。
> 对齐 v1.6.4 spec §3「unified Graph Workbench」+ handoff Vision 2（每个节点可编辑→rerun、节点 AskAI、引用报告）。
> **策略（用户拍板）**：先清技术债 + 打磨，再逐步把散落的操作融进主图。

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
| draft/pending 可视 | ❌ draft 在独立视图;主图只显示 executed | executed/draft/pending 没在一张图 |
| 对比 | ⚠️ compareWithSource（child vs source）已有 | 不能在图上任选两节点/两 run 对比 |
| 问 AI | ❌「Ask AI」死按钮;抽屉 AskAI feature-flag 关、未接 `/llm/chat` | 无真 LLM |
| 出报告 | ❌ 顶栏「Generate report」死按钮 | 无图内引用报告 |
| 辅助视图 | ❌ Table / Pipeline 标签页 = 占位符;底部 Shell/Pending/Timeline 占位 | 死界面制造困惑 |

## 3. 收敛路径（版本切分）

### v1.6.6 — 图内操作基础 + 清债（**先清 + 打磨**，用户优先）
把"单图编辑"的**基础能力**补齐、把死界面去掉。低风险、见效快。
- **补齐可编辑控件**：`controlFactory` 的 radio / slider / text / textarea / toggle 从只读占位 → 可交互（让抽屉/草稿里任意参数都能改，不受控件类型限制）。
- **去噪死按钮**：顶栏「Rerun」「Generate report」、节点「Mark needs review」等 disabled 占位 —— 要么实现、要么**移除**（当前只制造困惑）。
- **占位视图收口**：Table 视图 → 要么实现成"节点/变量/系数表格"，要么明确移除标签页；底部 Shell/Pending/Timeline 面板同理。
- 交付判据：主图详情抽屉里，任何 editable_schema 的参数都能真正编辑;界面无死按钮/空标签页。

### v1.6.7 — Draft 融入主图（**消灭"跳出去"**，愿景第一实质步）
把独立 Draft Graph 的能力搬进主 lineage graph。
- 选中 model 节点 → **就地进入编辑态**（复用现有 PipelineDraft 后端契约：create draft → patch params → validate → execute），**不跳出主图**；
- draft / pending 节点以**独立视觉态**（虚线/半透明/角标）显示在同一张 forest 图上;execute 后 child run 就地长在图上;
- 独立 `DraftGraphRoute` 降级为深链接 fallback 或退役;Pipeline 标签页退役。
- 交付判据：不打开新路由，就能在一个 model 节点上完成"改 covariance → validate → execute → 看到新 child 节点"。
- 复用：v1.6.4 的 draft store / validate / execute / hash-gate / snapshot 契约**原样复用**（后端不用重写，只换前端入口）。

### v1.6.8 — 图内对比 + 节点 AI + 引用报告（**handoff Vision 2**）
- **任选对比**：图上选两个节点/两个 run 直接 compare（compareWithSource 升级为通用双节点 diff）;
- **节点 Ask AI**：把死按钮接上真 `/llm/chat`（携带节点 lineage 上下文 packet）;
- **引用报告**：从图上勾选节点 → 生成带 cite-chip（引用具体节点/系数）的报告，替代顶栏死的「Generate report」。

### v1.7+ — Agent Harness（更远，可选）
在"单图可做一切"之上，让 agent 自动编排多步（改参数→rerun→对比→筛选）。memory 多处提到的 Agent Harness 归此。

### 穿插线 — 统计方法（独立、低风险）
按 `docs/superpowers/roadmap/2026-05-13-statistical-methods-roadmap.md` §12，ML / 时间序列 / 生存分析等可在任意版本穿插加，不阻塞产品线。

## 4. 依赖与顺序

```
v1.6.6 (清债+图内编辑基础)
   └─> v1.6.7 (draft 融入主图)   ← 依赖 v1.6.6 的可编辑控件
          └─> v1.6.8 (对比/AI/报告)
                 └─> v1.7 Agent Harness
统计方法线：任意穿插，不阻塞。
```

- v1.6.7 是**架构收敛的关键跳**，风险最高（改主 GraphCanvas 交互 + 状态机），建议单独 spec + 充分 brainstorm。
- v1.6.6 先行可为 v1.6.7 铺好"图内编辑"的控件基础，降低 v1.6.7 风险。

## 5. 开放问题（定稿前需拍板）
1. v1.6.6 的占位视图（Table / Pipeline 标签页 / 底部面板）：**实现**还是**移除**？移除更快、更符合"单图收敛"。
2. draft/pending 节点在主图的视觉语言（虚线？角标？分层？）需要设计。
3. Ask AI 的后端（`/llm/chat`）用哪个模型/如何接，是否本轮排。
