# V1.2.1 Browsing Enhancement Design

日期：2026-05-03

## 1. 背景

V1.2.0 完成了硬化。当前前端有三个 view（submit / history / detail），全部通过 `App.tsx` 的 `ViewState` discriminated union 切换。浏览器的 URL 始终不变——用户无法分享一个 run 的 URL，后退按钮直接退出应用。

V1.2.1 的目标是让浏览体验具备"分享、后退、直达"的基础能力：引入 react-router、通过 query param 携带 `project_root`、给 run history 加渲染层分页。后端不动。

## 2. 边界

V1.2.1 **只做**：

| # | 项 | 类型 |
|---|---|---|
| 1 | HashRouter + 3 条路由 | 前端架构 |
| 2 | `project_root` query param，支持 URL 分享/刷新 | 前端 |
| 3 | Run history 渲染层分页（前端 `useMemo` 切片） | 前端 |

V1.2.1 **明确不做**：

- 后端分页（`GET /runs` 不改）
- 搜索 / 过滤
- Page size 选择器
- 独立 artifact / report 路由（保持在 detail 页内）
- Data profile / preview UI
- 全局状态库

## 3. 路由设计

### 3.1 Router 选型：HashRouter

不用 BrowserRouter。理由：Vite dev server 和 uvicorn 没有统一 fallback 到 `index.html` 的配置面，`/runs/abc` 刷新会 404。HashRouter 把路由放在 `#/...`，零后端配合。

### 3.2 路由表

| 路径 | 组件 | 说明 |
|---|---|---|
| `#/` | SubmitPanel | 现有项目创建 + run 提交 + last run 面板 |
| `#/runs?project_root=...` | RunHistoryPanel | run 历史列表 + 分页 |
| `#/runs/:runId?project_root=...` | RunDetailPanel | run 详情 + artifacts + report |

### 3.3 `project_root` 处理

- **来源优先级：** URL query string > localStorage fallback > 用户手动输入
- **编码：** 所有 URL 构建必须通过 `URLSearchParams` 或 `encodeURIComponent`，禁止手拼字符串。当前 workspace 路径含中文和空格，手拼会破坏 URL 安全。
- **缺失时的行为：**
  - `/runs` 路径：显示 "Select a project first" 提示，不发请求
  - `/runs/:runId` 路径：显示 "Missing project_root" 错误态，提供返回 `/` 的链接
- localStorage 仅作为创建项目后的便利 fallback——当用户通过 submit panel 创建项目后，写入 `lastProjectRoot`，后续导航到 `/runs` 时若 URL 无 `project_root` 则从 localStorage 读取。

### 3.4 导航边界

| 操作 | 导航方式 |
|---|---|
| Tab "Submit" | `<NavLink to="/">` |
| Tab "History" | `<NavLink to="/runs?project_root=...">`（`project_root` 为空时禁用） |
| Run history row click | `navigate(/runs/${runId}?project_root=...)` |
| Detail "Back to history" | `navigate(/runs?project_root=...)` |

### 3.5 组件层

```
<HashRouter>
  <AppShell>                    ← errorMessage, tabs, 从 URL 提取 project_root
    <Routes>
      <Route path="/" element={<SubmitPanel />} />
      <Route path="/runs" element={<RunHistoryPanel />} />
      <Route path="/runs/:runId" element={<RunDetailPanel />} />
    </Routes>
  </AppShell>
</HashRouter>
```

`AppShell` 用 `useSearchParams` 提取 `project_root`，通过 props 传给子路由组件。子组件只管接收 props，不管 URL 解析。

测试用 `MemoryRouter` + `initialEntries` 包裹 `AppShell`，不依赖 `HashRouter`。

## 4. 前端分页

### 4.1 分页策略

前端全量取 + 渲染层分页。`fetchRuns` 不变，后端 `GET /runs` 不改。

### 4.2 分页控件

`RunHistoryPanel` 拿到全量 `runs` 后用 `useMemo` 切片：

```
PAGE_SIZE = 25
runs.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
```

底部渲染分页栏：

```
[Previous]   Page 2 of 4   [Next]
```

| 状态 | Previous | Next |
|---|---|---|
| 第 1 页 | disabled | enabled |
| 最后一页 | enabled | disabled |
| 空列表 | 隐藏整个分页栏，显示 "No runs in this project yet." |

`Page X of Y` 在空列表时：不渲染分页栏，只显示现有 empty state。`totalPages = Math.ceil(runs.length / PAGE_SIZE)` 或 0。

### 4.3 排序

保持现有后端排序（`started_at` 倒序），前端不改序。

## 5. 文件变更

| 文件 | 变更 |
|---|---|
| `frontend/package.json` | + `react-router-dom` |
| `frontend/src/App.tsx` | 删除 ViewState/historyKey，抽 AppShell，引入 HashRouter |
| `frontend/src/runHistory.tsx` | 接受 `runs`（全量），增加分页按钮 state + `useMemo` 切片 |
| `frontend/src/runDetail.tsx` | `project_root`/`runId` 从 props 取（AppShell 从 URL 提取后传入），`onBack` → `useNavigate` |
| `frontend/src/App.test.tsx` | 所有测试包裹 `MemoryRouter`，mock 链适配路由导航 |
| `frontend/src/api.ts` | 不变 |
| `tests/test_api.py` | 不变 |
| 全部后端文件 | 0 改动 |

## 6. 测试策略

### 6.1 现有测试保护

现有 11 `App.test.tsx` case 全部用 `MemoryRouter` 包裹。mock chain 不变。`fillProject()` helper 用 `fireEvent` 触发，不受 router 影响。

### 6.2 新增前端测试

| # | 测试 |
|---|---|
| 1 | 直接访问 `#/runs/abc?project_root=/tmp` 通过 `MemoryRouter initialEntries`，断言 detail 渲染 |
| 2 | History tab 分页栏渲染，Page X of Y 文案，Previous 禁用/Next 启用 |
| 3 | 空列表时不渲染分页栏 |
| 4 | `/runs` 路由 `project_root` 缺失时显示提示信息 |

## 7. 决策日志

| # | 决策 | 选择 | 原因 |
|---|---|---|---|
| 1 | Router 库 | react-router-dom HashRouter | 零后端配合，本地工作台场景够用 |
| 2 | project_root 传递 | URL query param + localStorage fallback | 分享 URL 包含 project_root，刷新直接恢复 |
| 3 | 分页位置 | 前端渲染层 | 本地项目 run 数量有限，后端改动 0 |
| 4 | Page size | 固定 25 | 避免 UI 复杂度，需要时加选择器一字符一变 |
| 5 | 路由深度 | 3 条 | 再细分 artifact/report 独立路由会倒退用户体验 |
| 6 | 空 project_root | `/runs` 提示选择项目，`/runs/:runId` 显示错误态 | 防止空请求发到后端 |
| 7 | profile 预览 | 推迟 | 格式不确定，需独立 spec |
| 8 | 全局状态库 | 不引入 | react-router URL 驱动 + props 传递已够 |
| 9 | 起点分支 | `origin/main` (V1.2.0 已 merge) | 从最新基线出发 |
