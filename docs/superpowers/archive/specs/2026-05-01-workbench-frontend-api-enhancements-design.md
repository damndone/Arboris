# V1.1 工作台前端与 API 增强设计

日期：2026-05-01

## 1. 背景

V1 plan 已封口，PR #1 待 merge 到 `main`。后端跑通了"原始数据到可信报告"闭环，但前端只能提交 run，不能浏览结果。API 只有 `/projects` 和 `/runs`，缺少 run 详情、artifact 列表、报告下载等只读能力。

V1.1 的目标是让本地工作台从"能提交"演进到"能浏览"，把已有的 artifact registry 通过 API 暴露给前端，让用户在浏览器里查看 run 历史、报告和产物。计量内核不动，模型与诊断扩展推到后续阶段。

## 2. V1.1 目标与边界

第一目标：**API-backed result browser**。前端围绕"当前项目的 run 历史 + 单个 run 的摘要与产物"展开；后端提供与之配套的只读 endpoints。

V1.1 必须支持：

- 列出当前项目下所有 run。
- 查看单个 run 的状态、配置摘要、错误信息。
- 浏览 run 的 artifact 索引并下载单个 artifact。
- 在前端内嵌查看 run 的 HTML 报告。
- 统一的错误响应结构。

V1.1 明确不做（推到 V1.2 及以后）：

- 异步 / 后台 run、长任务进度推送。
- 模型种类扩展、诊断扩展、可配置参数 UI。
- 数据预览 / profiling UI。
- 新增导出格式（PDF/XLSX 扩充）。
- 跨项目 run history 聚合。
- Example dataset quick-start、上传进度 UI。
- README / 教程改版。
- 产物的重命名 / 删除 / 重新生成等写入能力。

## 3. 架构与边界

V1.1 在现有结构上**只增不改**：

- 后端：在 `backend/workbench/api.py` 增加只读 endpoints。所有写入路径仍只走 `orchestrator.run_workflow`。
- Artifact 读取统一走 `backend/workbench/artifacts.py` registry，API 不直接拼接文件系统路径。
- 前端：在现有 `frontend/src/App.tsx` 与 `frontend/src/api.ts` 上扩展，新增 run history、run detail、artifact browser、report viewer 视图。
- 前端不直接读本机文件系统；报告与产物全部通过 API 拉取。

边界原则：

- API 新增能力先有测试，再写实现，再被前端消费。
- 任何后端能力必须由 API 暴露，前端不允许猜文件路径。
- 前端不绕过 `/runs` 触发任何写入；新 endpoints 只读。

## 4. API 设计

所有新 endpoints 都是只读。响应统一使用 JSON。出错时使用统一错误信封。

### 4.1 错误响应格式

```json
{
  "error": {
    "code": "RUN_NOT_FOUND",
    "message": "Run abc123 not found in project /path/to/project",
    "details": {}
  }
}
```

错误码使用大写下划线，至少覆盖：`PROJECT_NOT_FOUND`、`RUN_NOT_FOUND`、`ARTIFACT_NOT_FOUND`、`REPORT_NOT_FOUND`、`INVALID_PATH`。错误码集中维护，前端按 code 渲染，不依赖 message 文本。

### 4.2 Endpoints

所有读端点都用 query 参数 `project_root` 标识项目。这与现有 `POST /runs` 的入参方式一致，避免给 project 引入新的 ID 体系，也避免 URL 编码本机路径。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/runs?project_root=...` | 列出该 project 下所有 run，含 run_id、status、started_at、mode、y、x 摘要 |
| GET | `/runs/{run_id}?project_root=...` | 单个 run 的详情，含 status、config 快照、错误（若有）、artifact 概要计数 |
| GET | `/runs/{run_id}/artifacts?project_root=...` | 该 run 的 artifact 索引，按类型分组 |
| GET | `/runs/{run_id}/artifacts/{artifact_id}?project_root=...` | 下载指定 artifact，二进制流式响应，`Content-Disposition: attachment` |
| GET | `/runs/{run_id}/report?project_root=...` | 返回 `report.html` 内容，`Content-Type: text/html`，供 iframe 加载 |

`run_id` 是项目内已存在的 run 目录名。后端先 resolve `project_root`，再在其 runs 子目录下定位 `run_id`。任一环节解析失败或越权（resolve 后跳出 `project_root`）返回 `INVALID_PATH`。

### 4.3 安全与一致性

- 所有路径参数都做 resolve + 边界校验，禁止跳出 project_root。
- 二进制下载与 HTML 响应都流式发送，避免内存峰值。
- artifact 元数据 100% 来自 registry，绝不读取 registry 外的文件。
- 时间字段统一 ISO8601 UTC。

### 4.4 Run 摘要字段来源

V1 `_write_manifest` 当前只写 `{run_id, mode, status, lineage}`。run 列表与详情需要的 `started_at` / `mode` / `y` / `x` 字段没有源头。V1.1 通过**扩展 manifest 写入路径**补齐：

- 在 `orchestrator.run_workflow` 内部写 manifest 时新增字段：`started_at`（UTC ISO8601）、`y`（字符串）、`x`（字符串数组）。`mode` 已存在。
- 写入时机：`run_workflow` 入口立即写一次最小 manifest（status=`running`、started_at + mode + y + x），结束时再覆盖写入最终 status 与 lineage。这样失败的 run 也能被列出和查看错误。
- 不引入独立 `run_summary.json`，保持单一来源。
- 这是对 V1 写入路径的**最小受控扩展**，不改变 artifact 语义，不动 registry。"只增不改"原则应用于 API 表面与 artifact 写入入口，不禁止给 manifest 增加向后兼容字段。
- 旧 run（升级前生成）允许字段缺失：API 返回时对缺失字段填 `null`，不报错。前端按 `null` 渲染为 `--`。

## 5. 前端设计

前端在 `frontend/src` 下扩展，结构上从单组件提交表单演进为带导航的多视图应用。

### 5.1 视图

1. **当前项目 run 历史列表**
   - 以表格形式展示 run_id、status、started_at、mode、y、x 摘要
   - 行点击进入 run 详情

2. **Run 详情页**
   - 顶部展示 status 徽章、started_at、mode、y、x
   - 配置快照面板（折叠展开）
   - 错误 / 校验信息面板（仅当 run 失败或带告警时显示）
   - artifact 摘要计数（按类型）
   - 报告 / artifact 入口

3. **Artifact 浏览器**
   - 按类型分组（report、figure、table、log、data 等）
   - 每行显示 artifact_id、type、step、相对路径、下载按钮
   - 点击下载触发 `/runs/{id}/artifacts/{aid}` 流式下载

4. **Report viewer**
   - iframe 加载 `/runs/{id}/report`
   - 提供"在新标签打开"和"下载报告 HTML"两个动作

### 5.2 状态管理

- 不引入新的全局状态库，使用 React 自带 state + hooks
- API 层集中在 `frontend/src/api.ts`，新增的函数封装错误信封解析
- 错误统一抛出后由组件捕获并渲染到错误面板

### 5.3 路由

- 单页应用内部用最小的视图切换（无需引入 react-router）：通过组件状态切换 list / detail / report / artifacts
- 浏览器后退能力非 V1.1 必须项

## 6. 数据流

```text
用户打开前端
→ 选择 / 输入 project_root
→ 前端调用 GET /runs?project_root=...
→ 列出 run 历史
→ 用户点击某个 run
→ 前端调用 GET /runs/{run_id}?project_root=... + /runs/{run_id}/artifacts?project_root=...
→ 渲染 run 详情与 artifact 列表
→ 用户点击「查看报告」→ iframe 加载 /runs/{run_id}/report
→ 用户点击 artifact 下载 → 触发 /runs/{run_id}/artifacts/{aid}
```

写入流仍保持 V1 现状：`POST /runs` → `orchestrator.run_workflow` → 落地到 artifact registry。V1.1 不改这条链路。

## 7. 测试策略

### 7.1 后端

每个新 endpoint 至少：

- 一个 happy path 测试（正常返回，字段齐全）
- 一个错误 path 测试（资源不存在 → 错误信封 + 正确 code）
- artifact / report endpoint 增加路径越权用例（试图访问 project 外文件）

测试沿用 `tests/test_api.py` 的 fixture 与 pattern，不引入新框架。

### 7.2 前端

在 `App.test.tsx` 与新增测试文件中：

- run history 列表渲染
- run 详情页渲染（含错误面板）
- artifact 浏览器渲染与下载链接 href 校验
- report viewer iframe src 校验

API 错误信封解析单测放在 `api.ts` 对应测试文件。

### 7.3 回归

- `tests/test_orchestrator_e2e.py`、`tests/test_acceptance_templates.py` 不动，作为 V1 基线
- 每批 task 结束跑 backend + frontend 全量测试套件

## 8. 流程与里程碑

- 等 PR #1 merge 进 `main`
- 从最新 `main` 切 `feature/workbench-frontend-api-enhancements`
- 任务批次顺序（API 优先）：
  1. 扩展 `_write_manifest`：新增 `started_at` / `mode` / `y` / `x` 字段 + 测试
  2. 错误信封 + 异常处理基础设施
  3. `GET /runs?project_root=...` 与 `GET /runs/{run_id}?project_root=...` + 测试
  4. `GET /runs/{run_id}/artifacts?project_root=...` 与 artifact 下载 + 测试
  5. `GET /runs/{run_id}/report?project_root=...` + 测试
  6. 前端 API 客户端扩展 + 测试
  7. 前端 run history + run detail 视图 + 测试
  8. 前端 artifact browser + report viewer 视图 + 测试
  9. 全量测试 + 文档更新 + plan 封口
- 每个 task：implementer → spec reviewer → code-quality reviewer
- 每批结束：backend pytest + frontend vitest 全绿才进入下一批
- V1.1 单独 PR，不混入 V1 closure

## 9. 决策日志

| # | 决策 | 选择 | 原因 |
|---|---|---|---|
| 1 | 开发顺序 | API 优先 | 后端先稳，避免前端基于猜测的 API 形状返工 |
| 2 | 产品定位 | 轻量本地工作台 | 计量内核保持 V1，避免平台化蔓延 |
| 3 | 报告/产物处理 | 后端暴露 + 前端内嵌查看 + 下载 | 前端不读本地文件，权限与可移植性更好 |
| 4 | 后端访问 artifact | 只读 registry | 写入仍只走 orchestrator，单一写入入口 |
| 5 | Review 流程 | 三段式 | 沿用 V1，质量优先 |
| 6 | 起点分支 | PR #1 merge 后从 main 切 | V1 封口干净，避免 rebase |
| 7 | V1.1 第一目标 | API-backed result browser | 把已生成的 artifact 暴露出来比新增能力更高优先 |
| 8 | 第一版深度 | 摘要 + 产物 | 不做 profiling / 模型扩展 UI |
| 9 | 支持的 run 范围 | 当前项目历史 | 不做跨项目聚合 |
| 10 | 报告/产物打开方式 | 内嵌 + 下载 | iframe 看 HTML，artifact 走下载 |
| 11 | Project 标识 | `project_root` query 参数 | 与 `POST /runs` 入参一致，不引入新的 project ID 体系，避免 URL 编码本机路径 |
| 12 | 前端路由 / 状态 | 不引入 react-router，不引入全局状态库 | V1.1 视图量级用 React useState/useReducer 足够；引入 router/store 是平台化方向，留给后续阶段 |
| 13 | Run 摘要字段来源 | 扩展 `_write_manifest` 写入 started_at/y/x | 单一来源；旧 run 字段缺失时 API 返回 null，前端容忍 |
