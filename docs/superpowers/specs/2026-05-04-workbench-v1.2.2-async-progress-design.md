# V1.2.2 Async Progress Design

日期：2026-05-04

## 1. 背景

V1.2.1 完成了浏览增强：HashRouter、URL 驱动的 `project_root`、run history 分页和可分享的 run detail 路由。提交一个 run 时，前端仍然等待 `/run` HTTP 请求同步完成，长任务期间页面没有实时进度反馈，也无法展示工作流当前执行到哪一步。

V1.2.2 的目标是把提交从同步执行改成异步后台执行，并通过 Server-Sent Events (SSE) 向前端推送 workflow step 进度。用户提交后立即得到 `run_id`，detail 页在 run 处于 `running` 状态时订阅事件并显示进度。

## 2. 边界

V1.2.2 **只做**：

| # | 项 | 类型 |
|---|---|---|
| 1 | `/run` 立即创建 run 并返回 `status=running` | 后端 API |
| 2 | 单 worker 后台执行 workflow | 后端执行模型 |
| 3 | `/runs/{run_id}/events` SSE 进度流 | 后端 API |
| 4 | orchestrator `on_step` 回调 | 后端工作流 |
| 5 | run detail running 状态的进度面板 | 前端 UI |
| 6 | async/SSE/EventSource/on_step 回归测试 | 测试 |

V1.2.2 **明确不做**：

- 多并发 worker 或队列优先级
- run 取消、暂停、恢复
- 持久化事件日志到磁盘
- WebSocket
- 浏览器通知
- 后端分页或 run history 搜索
- 数据预览、表格上传增强、模型结果内联展示

## 3. 后端设计

### 3.1 `/run` 提交语义

V1.2.1 的 `/run` 同步调用 `run_workflow`，HTTP 响应只在 workflow 完成后返回。V1.2.2 改为：

1. 校验 `project_root`、上传文件大小、`y`、`x`。
2. 使用 `create_run` 创建 run 目录。
3. 将上传文件写入 run 目录下的 `_uploads/`。
4. 写入 `manifest.json`，初始状态为 `running`。
5. 注册 run 事件通道。
6. 把 `_bg_run` 提交到单 worker executor。
7. 立即返回 `{ "run_id": "...", "status": "running" }`。

如果当前已有 run 占用唯一 worker slot，则返回 HTTP 429，避免多个后台工作流同时写共享状态。

### 3.2 EventManager

新增 `backend/workbench/events.py`，提供进程内事件管理：

| 责任 | 说明 |
|---|---|
| slot lifecycle | `try_acquire_slot`、`mark_active`、`release_slot` 控制单 worker |
| event history | 每个 run 保存短期内存事件列表，供晚到的 SSE 订阅者回放 |
| subscriptions | 每个订阅者一个 `queue.Queue` |
| sequence | 每个 run 从 0 递增，便于前端和测试断言顺序 |
| terminal events | completed/blocked/failed/interrupted 后关闭订阅并延迟清理 |

事件只保存在内存中。服务器重启后，如果 manifest 仍是 `running` 且 EventManager 中没有 active run，detail 或 events API 会把 run 标为 `interrupted`，并写入 `errors.json`。

### 3.3 SSE API

新增：

`GET /runs/{run_id}/events?project_root=...`

响应类型：

`text/event-stream`

事件格式：

```text
event: step_start
data: {"event":"step_start","run_id":"...","sequence":0,"timestamp":"...","step":"ingestion","message":"Ingesting files...","status":null}
```

支持事件：

| 事件 | 含义 |
|---|---|
| `step_start` | workflow step 开始 |
| `step_complete` | workflow step 完成 |
| `step_blocked` | workflow step 发现 blocker |
| `workflow_completed` | run 完成 |
| `workflow_blocked` | run 被 guardrail 阻断 |
| `workflow_failed` | 后台执行抛错 |
| `workflow_interrupted` | server 停止导致 running run 中断 |

SSE generator 先回放已记录事件，再等待新事件。等待期间每 30 秒发送 heartbeat `:\n\n`，防止代理或浏览器认为连接闲置。

### 3.4 Orchestrator step 回调

`_run_workflow` 增加可选参数：

```python
on_step: Callable[[str, str, str], None] | None = None
```

回调参数为：

| 参数 | 例子 |
|---|---|
| `step` | `ingestion`, `schema`, `cleaning`, `profiling`, `validation`, `routing`, `model_check`, `estimation`, `visualization`, `narrative`, `reporting`, `export` |
| `status` | `start`, `complete`, `blocked` |
| `message` | `Ingesting files...` |

公开 `run_workflow` 保持同步 API 行为，测试和非 HTTP 调用不需要订阅 SSE。

## 4. 前端设计

### 4.1 API client

`frontend/src/api.ts` 新增：

- `RunProgressEvent`
- `RunProgressCallbacks`
- `connectRunEvents(projectRoot, runId, callbacks)`

`connectRunEvents` 使用浏览器原生 `EventSource`，监听 step 和 terminal 事件。收到 terminal 事件后关闭 source，防止连接泄漏。

### 4.2 Run detail 进度面板

`RunDetailPanel` 在 `detail.status === "running"` 时：

1. 设置 `isLive=true`。
2. 调用 `connectRunEvents`。
3. 根据 `step_start`、`step_complete`、`step_blocked` 更新本地 step 状态。
4. 收到 terminal 事件后重新拉取 run detail 和 artifacts。

固定 step 列表：

```text
Ingestion -> Schema -> Cleaning -> Profiling -> Validation -> Routing -> Model check -> Estimation -> Visualization -> Narrative -> Reporting -> Export
```

UI 用 `pending`、`running`、`completed`、`blocked` 四种状态，避免引入额外状态库。

## 5. 文件变更

| 文件 | 变更 |
|---|---|
| `backend/workbench/api.py` | `/run` 异步化，新增 `_bg_run`、SSE endpoint、中断检测 |
| `backend/workbench/events.py` | 新增 EventManager |
| `backend/workbench/orchestrator.py` | `_run_workflow` 增加 `on_step` 回调并在各阶段发 step |
| `frontend/src/api.ts` | 新增 EventSource client |
| `frontend/src/runDetail.tsx` | running run 的进度面板和事件订阅 |
| `frontend/src/styles.css` | progress panel 样式 |
| `frontend/src/App.tsx` | 保持路由，支持提交后进入 running run |
| `frontend/src/App.test.tsx` | 调整提交/详情测试 |
| `frontend/src/api.test.ts` | EventSource client 单元测试 |
| `tests/test_api.py` | 异步提交、429、SSE、interrupted 覆盖 |
| `tests/test_orchestrator_e2e.py` | `on_step` 顺序和 blocked 覆盖 |

## 6. 测试策略

| 层 | 覆盖 |
|---|---|
| Backend API | `/run` 返回 `running`，并发时 429，SSE 回放 terminal event |
| Event manager | 订阅、历史事件、slot 释放通过 API 测试间接覆盖 |
| Orchestrator | 正常 run 的 step 顺序，blocked path 的 `step_blocked` |
| Frontend API | `connectRunEvents` 绑定 EventSource 事件并关闭 terminal connection |
| Frontend UI | running run detail 渲染 progress panel |

## 7. 决策日志

| # | 决策 | 选择 | 原因 |
|---|---|---|---|
| 1 | 实时协议 | SSE | 单向进度流足够，浏览器原生支持，后端实现小 |
| 2 | 并发模型 | 单 worker | 本地工作台优先稳定，避免多个 run 同时写磁盘 |
| 3 | 事件持久化 | 内存短期保存 | V1.2.2 只做 live progress，不引入事件存储格式 |
| 4 | server 重启处理 | `running` -> `interrupted` | 防止 UI 永远显示 running |
| 5 | 前端状态 | 组件本地 state | progress 只属于 run detail，不需要全局 store |
| 6 | 公开 sync API | 保留 `run_workflow` | 现有测试和非 HTTP 调用不受 async API 影响 |
| 7 | 起点提交 | `5314ecb` | V1.2.1 browsing enhancement 截止点 |
