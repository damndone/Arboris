# V1.2.0 Hardening Design

日期：2026-05-03

## 1. 背景

V1.0 打通了"原始数据到可信报告"闭环。V1.1 在此基础上加了 API-backed result browser，前端有了 run history、run detail、artifact 浏览器、report viewer。经过两轮迭代，代码结构趋于稳定，但也暴露出几个脆弱点：

1. Artifact 加载失败默认静默降级，用户无法区分"空"与"故障"。
2. Report iframe 无 sandbox，在本地工作台场景下风险虽低但仍有隐患。
3. 从未用真实 V1 数据验证过旧 run 兼容性（manifest 缺失 `started_at / y / x`）。
4. `artifacts_index.json` 无版本标识，后续 schema 改动可能造成静默数据解析错误。

V1.2.0 的定位是**加固释放**：不增加任何用户可见的新功能，集中修复四个遗留脆弱点，为 V1.2.x 的架构升级（route、async run、model expansion）提供更稳固的基础。

## 2. 边界

V1.2.0 **只做**这四件事：

| # | 项 | 类型 |
|---|---|---|
| 1 | Artifact 加载错误可见性 | 前端 |
| 2 | Report iframe sandbox | 前端 |
| 3 | 旧 run 兼容性验证 | 测试 |
| 4 | Artifact registry schema / version | 后端 + 测试 |

V1.2.0 **明确不做**（推到 V1.2.1 及以后）：

- 前端路由（react-router）
- Run history 分页
- 异步 / 后台 run + SSE 进度
- 模型 / 诊断扩展
- 跨项目历史聚合
- 参数可配置 UI
- 数据预览 / profiling 可视化
- ISO 时间戳可读性格式化

## 3. 设计原则

- **只增不改**：不动现有 endpoint 行为、不动 manifest 写入路径、不动报告生成逻辑。新增代码全部是保护性/防御性增强。
- **测试先行**：四个 task 都有独立的测试覆盖，不加测试的更改不合并。
- **不引入生产代码新文件、不引入新依赖**：所有生产代码改动在现有文件内完成。测试文件允许新增。

## 4. Item 1 — Artifact 加载错误可见性

### 现状

`RunDetailPanel` 用 `groups: ArtifactGroup[] | null` 二态控制 artifact 区域渲染：
- `null` = loading
- `[]` = 无 artifact / 加载完成

错误时 `setGroups([])` 静默降级，真实错误对用户完全不可见。

### 改动

将状态机改为三态 discriminated union：

```typescript
type ArtifactsState =
  | { status: "loading" }
  | { status: "loaded"; groups: ArtifactGroup[] }
  | { status: "error"; message: string };
```

渲染映射：

| `status` | 渲染 |
|---|---|
| `"loading"` | "Loading artifacts…" |
| `"loaded"` + `groups.length === 0` | "No artifacts recorded." |
| `"loaded"` + `groups.length > 0` | 现有 group 列表渲染 |
| `"error"` | "Failed to load artifacts: {message}" + **Retry 按钮** |

Retry 按钮重置状态为 `loading`，重新调用 `fetchRunArtifacts`。

### Stale response 防御

使用 `useRef` 持有递增的 `fetchId`，每次 fetch 自增。fetch 回调里只有 `fetchId === current` 时才 commit state。组件卸载或 `runId` 变化时在 cleanup 里自增一次，让任何 in-flight callback 自然失效。

### 测试

`App.test.tsx` 新增一个 **合并 case**：mock `fetchRunArtifacts` 首次 reject → 断言出现 "Failed to load artifacts" + Retry 按钮；点击 Retry 后 mock 改为 resolve → 断言 artifact 列表正常渲染。合并为一个测试避免测试间依赖，同时覆盖错误态与恢复路径。

## 5. Item 2 — Report iframe sandbox

### 现状

`RunDetailPanel` 的 report viewer 使用裸 `<iframe>`：

```tsx
<iframe title="Run report" src={reportUrl(projectRoot, runId)} className="report-frame" />
```

无任何 sandbox 限制。

### 改动

加 `sandbox="allow-same-origin"`：
- 禁用 scripts、forms、popups、顶层导航
- 保留 same-origin 让 CSS / 图片 / 字体正常加载

### 安全策略

- **不自动放宽**：如果将来 report.html 需要脚本，**必须另开 spec 重新设计**。届时考虑独立 origin、CSP header 或受控交互组件方案，不在 V1.2.0 范围内放宽。
- **自动化防线**：加一个 backend 测试，定位实际的报告模板文件（如 `reporting.py` + Jinja2 模板），渲染一个最小 report 后扫描输出 HTML，断言无 `<script`、`javascript:`、`\son[a-zA-Z]+\s*=`（事件属性，case-insensitive）。

### 测试

- 前端 `App.test.tsx`：断言 iframe 元素的 `sandbox` 属性等于 `"allow-same-origin"`
- 后端 `tests/test_report_no_scripts.py`（新建）：渲染最小 report，扫描输出 HTML 无 `<script` / `javascript:` / `\son[a-zA-Z]+\s*=`（case-insensitive）

## 6. Item 3 — 旧 run 兼容性验证

### 目标

确保 V1（无 `started_at / y / x`、无 `schema_version`）和 V1.1（有 `schema_version` V1.2.0 之前写入但无版本字段的 registry）的数据在全部 5 个 V1.1 endpoints 下正常渲染。

### 验证方式

新建 `tests/test_legacy_run_compat.py`，包含两个独立 fixture + case：

#### Case A — V1-shape happy path

Fixture 构造一个完整的 V1 run 目录：
- `run_manifest.json` 仅含原始 V1 字段：`{run_id, mode, status, lineage}`（无 `started_at / y / x`）
- `artifacts_index.json` **无** `schema_version` 字段，artifacts 列表含 report + model_result 等类型的记录
- 物理文件齐全（`reports/report.html` 等）

逐个调用 5 个 endpoints，预期响应：

| Endpoint | 预期 |
|---|---|
| `GET /runs?project_root=...` | 200；`runs[0]` 含 `run_id`/`status`/`mode`，`started_at: null, y: null, x: null` |
| `GET /runs/{id}?project_root=...` | 200；同上字段 + `artifact_counts` 非空 + `errors: {issues: []}`（errors.json 不存在时）+ `lineage` 来自 manifest |
| `GET /runs/{id}/artifacts?project_root=...` | 200；`groups` 按 `artifact_type` 分组；items 含 `artifact_id/path/step/sha256` |
| `GET /runs/{id}/artifacts/{aid}?project_root=...` | 200；`Content-Disposition: attachment`；内容匹配磁盘文件 |
| `GET /runs/{id}/report?project_root=...` | 200；`text/html`；body 含 `<html` |

#### Case B — Registry 记录指向缺失文件

Fixture 与 Case A 同构，但删除一个 artifact 的物理文件（registry 记录保留）：

| Endpoint | 预期 |
|---|---|
| `GET /runs/{id}/artifacts` | 200；缺失文件的记录**仍在列表里**（list 不做磁盘存在性检查） |
| `GET /runs/{id}` | 200；`artifact_counts` 包含缺失文件的类型（计数基于 registry） |
| `GET /runs/{id}/artifacts/{aid}` | 404 + `ARTIFACT_NOT_FOUND`（回归测试，V1.1 已有此行为） |

### 手工验证凭证

PR 描述里附前端 UI 截图，将 Case A fixture run 拷贝到一个真实 project 目录，启动 dev server 验证：
- History 表格：null 字段显示为 `—`
- Detail 页：各项文本正确渲染
- Report viewer：iframe 正常加载
- Artifact 下载：链接正确

## 7. Item 4 — Artifact registry schema / version

### 写入侧

`backend/workbench/orchestrator.py` 的 `_finalize_artifacts`（或等同的写入点）在写 `artifacts_index.json` 时增加顶层字段：

```python
{
  "schema_version": 1,
  "artifacts": [...]
}
```

V1 已有的 schema 即是 v1。不改变现有 `artifacts` 数组的结构。

### 读取侧

在 `backend/workbench/api.py` 增加 helper 函数统一所有 registry 读取入口：

```python
SUPPORTED_REGISTRY_VERSION = 1

def _read_artifacts_index(run_root: Path) -> dict:
    index_path = run_root / "artifacts_index.json"
    if not index_path.is_file():
        return {"artifacts": []}
    data = read_json(index_path)
    raw = data.get("schema_version", 1)  # 缺失视为 v1
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_INVALID,
            message="artifacts_index.json schema_version is not an integer",
            details={"found": raw, "type": type(raw).__name__},
        )
    if raw < 1:
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_INVALID,
            message=f"artifacts_index.json schema_version must be >= 1, got {raw}",
            details={"found": raw},
        )
    if raw > SUPPORTED_REGISTRY_VERSION:
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_UNSUPPORTED,
            message=f"artifacts_index.json schema_version {raw} not supported",
            details={"found": raw, "supported": SUPPORTED_REGISTRY_VERSION},
        )
    return data
```

注意 `isinstance(raw, bool)` 显式排除 `True`/`False`（Python 里 `bool` 是 `int` 的子类，不防会被视为 version 1）。

### 替换入口

三处现有 `read_json(index_path)` 改走 `_read_artifacts_index`：
1. `_read_artifact_records` — artifact 列表
2. `_artifact_counts` — run detail 里的计数
3. `download_artifact_endpoint` — 下载入口

### 错误码

在 `backend/workbench/api_errors.py` 新增两个常量：

```python
ERROR_REGISTRY_VERSION_UNSUPPORTED = "REGISTRY_VERSION_UNSUPPORTED"
ERROR_REGISTRY_VERSION_INVALID = "REGISTRY_VERSION_INVALID"
```

命名规范统一：常量名带 `ERROR_` 前缀；API 响应 `error.code` 使用字符串值。

### 测试

`tests/test_api.py` 新增 5 个 case：

| 输入 `schema_version` | 预期 |
|---|---|
| 缺失 | 200，按 v1 解析 |
| `1` | 200 |
| `2`（手工伪造） | 500 + `REGISTRY_VERSION_UNSUPPORTED` |
| `"1"`（字符串） | 500 + `REGISTRY_VERSION_INVALID` |
| `0` | 500 + `REGISTRY_VERSION_INVALID` |

`tests/test_api_errors.py` 新增 2 个 case（两个新错误码的 envelope 测试）。

`tests/test_orchestrator_e2e.py` 新增 1 个 case（新 run 的 `artifacts_index.json` 含 `schema_version: 1`）。

## 8. Manifest 不一起加版本

V1.1 已经通过"加新字段 + 老数据填 null"走了兼容路径，且到目前为止 manifest schema 的字段消费侧没有暴露问题。Registry 更脆弱因为有错误码校验和版本感知需求（后续 schema 变更概率更高），所以现在只加 registry 的版本。Manifest 待真正需要改 schema 时再加。

## 9. 测试统计

| 文件 | 类型 | 新增 case |
|---|---|---|
| `tests/test_api.py` | 后端 | +5（registry 版本校验） |
| `tests/test_api_errors.py` | 后端 | +2（新错误码） |
| `tests/test_orchestrator_e2e.py` | 后端 | +1（schema_version 写入） |
| `tests/test_legacy_run_compat.py`（新建） | 后端 | +2（Case A, B） |
| `tests/test_report_no_scripts.py`（新建） | 后端 | +1（grep 报告模板无脚本） |
| `frontend/src/App.test.tsx` | 前端 | +2（artifact 错误态 + Retry 合并一个 case；iframe sandbox 一个 case） |

**总计：后端 +11 case，前端 +2 case，无现有测试回归。**

## 10. 数据流

```text
旧 run (V1/V1.1) 访问流程：
GET /runs/{run_id}/artifacts
  → _read_artifacts_index(run_root)       # 统一入口
    → read_json → 检查 schema_version
      → 缺失 → 视为 v1 → 返回原始数据
      → 1 → 直接返回
      → >1 → 500 REGISTRY_VERSION_UNSUPPORTED
      → 非 int / <1 → 500 REGISTRY_VERSION_INVALID
  → 下游继续用 artifacts 数组

新 run 写入流程：
orchestrator._finalize_artifacts
  → write_json 含 "schema_version": 1
  → 后续 API 读取与旧 run 同一入口

前端 artifact 区域：
挂载 → fetchRunArtifacts
  → 开始状态: loading
  → 成功: loaded + groups
  → 失败: error + message + Retry
    → 用户点 Retry → 回到 loading → 重新 fetch
```

## 11. 决策日志

| # | 决策 | 选择 | 原因 |
|---|---|---|---|
| 1 | 开发顺序 | 四项全部一次 PR | 每项独立但改动小，逐个 PR 管理负担 > 收益 |
| 2 | Sandbox 放宽路线 | 不放宽 | `allow-same-origin` 足够；如需脚本需新 spec 设独立 origin / CSP |
| 3 | Registry 版本校验范围 | 双向（坏数据 + 未来版本） | 本地文件可能被手改或旧 bug 写坏，不防坏数据是盲区 |
| 4 | 错误码命名 | `ERROR_X = "X"` | 与 `ERROR_RUN_NOT_FOUND` 等 V1.1 命名一致 |
| 5 | Manifest 版本 | 不加 | V1.1 的 null-tolerant 路径已验证稳定 |
| 6 | 是否引入新文件 | 生产代码不引入，测试文件允许 | 保持生产代码变更集中，测试独立更清楚 |
| 7 | Legacy fixture 结构 | 分 Case A / Case B | "正常旧数据"与"破损 artifact 记录"混在一起会影响测试断言清晰度 |
| 8 | `isinstance(raw, bool)` 检查 | 显式排除 | Python 中 `bool` 是 `int` 的子类，不防则 `True`/`False` 会被视为 version 1 |
| 9 | 前端 artifact 错误处理 | 三态状态机 + Retry + fetchId 防 stale | 在"对用户透明"和"对调试透明"之间取平衡，Retry 适合本地工具场景 |
| 10 | 起点分支 | `origin/main` (ddb0922) | 包含 V1 + V1.1 完整代码，从加固基线出发 |
