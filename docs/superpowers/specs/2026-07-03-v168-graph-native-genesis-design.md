# v1.6.8 Graph-native Genesis — 设计文档

日期:2026-07-03
状态:已获用户批准(brainstorm 全程分节确认)
分支/worktree:`.worktrees/workbench-v1.6.8` / `workbench-v1.6.8`(基于 main `2948d19` = v1.6.7)

## 0. Roadmap 改签

原 roadmap 中 v1.6.8 =「对比 / Ask AI / 报告」,**顺延为 v1.6.9**。
本版本 v1.6.8 =「Graph-native Genesis」:Launcher + 路由倒转 + 图内创世链,一次做全。
理由(用户拍板):当前从建项目到第一个 run 仍只能走 Submit 表单,与「一张谱系图完成所有操作」的北极星底层不一致;「对比/报告」是在完整图上的操作,「从零建图」是让图完整的前提,应插队。

## 1. 问题与目标

**现状**:graph 路由为 `/runs/:runId`,以 run 为钥匙——graph 是 run 的下游产物。创世路径(创建项目→选数据集→选表→配 x/y→run)只存在于 Submit 表单。v1.6.7 的 draft-in-graph 只能 fork 自已有 run 的节点,创世第一步无法在图内发生。

**目标(数据模型倒转)**:节点先于 run 存在;run 从「图的容器」降级为「节点上的一次执行事件」。全新用户从打开 app 到第一个 run 出结果,全程在 Launcher + 图工作台内完成,不见旧 Submit 表单。

**验收硬标准**:全新项目,从 Launcher → 画布 → 抽屉创世向导 → 第一个 run 出结果,全程不经过旧 Submit 表单;真机 CDP smoke 走通全链。

## 2. 设计原则:赌契约,不赌 UI(三层分离)

1. **数据模型层(倒转发生地)**:节点先于 run 存在。node_store 允许「无 run 节点」;项目 = 一片森林,不是一堆 run。
2. **操作契约层**:NodeOperationContext(v1.6.2)为唯一语义入口。create-source / select-table / configure-model / validate / execute 及未来 v1.6.9 的 compare/askAI/report 全部是「往这层加操作」,不加架构。
3. **宿主层(可替换,不承载语义)**:右侧抽屉、底部面板、画布右键、⌘K 只负责「把操作渲染在哪」。本版用抽屉向导;未来升级画布拖放只换宿主,下两层不改。

「创建项目」不入图:项目是画布的相框,不是血缘的一环。项目级操作归工作区皮层(Launcher + 顶栏),画布只长血缘。

## 3. 数据模型:创世 = 无父 draft 链

泛化 v1.6.7 draft 生命周期(`draft → validated → executed`),新增三种 draft 节点类型:

| 类型 | payload | 父节点 |
|---|---|---|
| Source draft | `{upload_sha256, filename, 客户端解析的 sheet/列元数据}` | ∅(创世根) |
| Table draft | `{sheet_name, transpose}` | Source draft |
| Model draft | 现有 model draft payload(x/y/角色/模型/协变量/DID…) | Table draft |

- 创世链 = `from_node = ∅` 的 draft 链,同一状态机,无第二种生命周期。
- execute 收敛进 `_submit_run`(与 `POST /runs` 同路):从三节点 payload 组装等价 form → 第一个 run 诞生 → 全链回填 Merkle 身份 → 与 rerun 产节点在森林中无差别。**不存在「创世图」与「血缘图」两种图。**
- draft 链持久于项目级(v1.6.7 draft 持久化的延伸),reload 后完整 rehydrate,向导从断点继续。

## 4. 后端改动(三块薄的 + 一个新端点)

1. **`POST /uploads`(新)**:独立上传端点,复用现有 `upload_store.store_upload_bytes/resolve_upload`(内容寻址,v1.6.0 已有,当前仅在 run 提交内部使用)。返回 `{sha256, filename}`。文件自创世第一步即持久于服务端 → draft 链可完整 rehydrate。沿用 `max_single_file_gb` 上限检查。
2. **`pipeline_drafts` 去掉 `from_node` 必填**:允许创世链;新增链式校验——Source 必有 upload、Table 必有 sheet(单 sheet 文件可默认)、Model 必有 x/y;链序 Source→Table→Model 不可乱。
3. **execute 泛化**:创世链 execute 组装 form → `_submit_run`。`POST /runs` 契约不动(Submit 表单退役是前端的事)。

**明确不做**:后端项目注册表(无 project id 概念,Launcher 最近项目走前端 localStorage)。

## 5. 前端改动:路由倒转 + 三个新组件

### 路由

```
/                      → Launcher(新首页)
/p/:encodedRoot/graph  → 图工作台 = 项目的家(encodedRoot = URL 编码的 project_root)
/runs/:id              → 重定向 /p/:encodedRoot/graph?focus=<run>(深链不断)
Submit 表单            → 从导航摘除,保留为 ⌘K「快速 run」兜底(代码不删,下版本退役)
```

### 组件

- **Launcher**:最近项目卡片(localStorage)+「新建项目」modal(父目录+名称两字段,`POST /projects` 现成)。stale 路径复用 v1.6.5 `PROJECT_NOT_FOUND` 友好空态。
- **顶栏项目切换器**:`项目名 ▾` 下拉 = 最近项目 + 新建 modal;切换/新建不离开图。
- **创世向导(右侧抽屉,复用 v1.6.7 drawer)**:步 1 选文件(客户端 SheetJS `previewFile` 解析 sheet/列——已验证现有逻辑本就在前端跑,零后端改动;同时 `POST /uploads`)→ 步 2 选 sheet/transpose → 步 3 x/y/角色/模型(复用 v1.6.6 controlFactory + capabilities,不新写表单)→ Run。**每完成一步,画布实时长出对应 draft 节点**(虚线);execute 成功后虚线变实线。

## 6. 数据流(创世全流程)

```
Launcher 新建 modal → POST /projects → /p/:root/graph(空画布)
→「＋ 新链路」→ 抽屉步1:选文件 → SheetJS 解析 + POST /uploads → Source draft 上画布
→ 步2:选 sheet/transpose → Table draft
→ 步3:x/y/角色/模型 → Model draft → validate
→ Run → execute → _submit_run → 第一个 run → 全链回填,与既有森林合流
```

reload 任意步:draft 链自后端 rehydrate,向导断点续传。

## 7. 错误处理

- 校验/execute 失败:错误落在对应节点上(复用 v1.6.7 error 硬化:无卡死生命周期、无 unhandled rejection),draft 链保留、可改可重试。
- execute 失败不产 orphan run(沿用现有 cleanup);孤儿 draft 链可整链 discard。
- 上传超限/非法文件:步 1 内联展示,不产 draft。
- Launcher stale 路径:`PROJECT_NOT_FOUND` → 卡片标记失效,可移除,不红条。

## 8. 测试与验收

- **BE**:genesis draft 三类型链式校验 / rehydrate / execute 收敛单测;**golden 23 全 0-drift**(execute 与 `_submit_run` 同路是硬保证)。
- **FE**:Launcher、路由重定向、向导分步、画布 draft 生长 vitest;tsc 0。
- **Gate**:BE + golden + FE + tsc 全绿,在 worktree 内跑(`LANG/LC_ALL=UTF-8`)。
- **真机**:CDP smoke 走通创世全链(硬标准见 §1)。
- **流程**:opus subagent 分派 + 两阶段对抗评审。

## 9. 范围外(明确推迟)

- 画布拖放建链(宿主升级,数据模型已就绪)
- Submit 表单代码删除(本版仅摘除导航)
- 后端项目注册表 / 项目级设置页
- v1.6.9:对比 / Ask AI / 报告(原 v1.6.8 内容)
