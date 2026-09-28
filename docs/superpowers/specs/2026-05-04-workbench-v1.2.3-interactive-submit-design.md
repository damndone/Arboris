# V1.2.3: 交互式文件预览 + 模型增强 + 单页结果展示

## 背景

V1.2.2 完成了异步后台运行 + SSE 进度推送。用户反馈了 7 个前端交互和功能欠缺问题，归纳为 4 个改进方向：

1. **文件选择**：只支持 `.csv`，需要 `.xlsx`；选择后无预览、无自动变量识别
2. **变量配置**：逗号分隔文本输入不直观，不易发现多变量能力
3. **统计学能力**：永远只跑 OLS（固定效应已实现但未接入），图表只有 2 种，叙事只报告系数符号
4. **结果可达性**：运行完跳转到独立 detail 页，用户期望在 Submit 页直接看到结果；但 V1.2.1 引入的可分享 detail URL 不能回退

## 目标

Submit 页变为端到端工作台：上传文件 → 预览 → 自动推荐变量 → 多选配置 → 运行 → 本页实时进度 + 结果。保留 History 页和可分享的 detail URL（`/runs/:runId`）不变，但结果组件共享。

## 平台限制声明

**浏览器安全沙箱不暴露本地绝对路径。** `showDirectoryPicker()` 和 `webkitdirectory` 都无法获取如 `/Users/.../workspace` 的真实路径。项目路径（`project_root`）**保持手动输入**。不做任何伪装成"原生目录选择器"的 UI——那会误导用户。

Browse 按钮的合理用途：辅助选择上传文件（用标准的 `<input type="file">`），不用于选择 project_root。

---

## 文件变更总览

| # | 文件 | 类型 | 说明 |
|---|---|---|---|
| 1 | `frontend/src/api.ts` | 修改 | 新增客户端文件解析 `previewFile()` + `FilePreview` 类型；扩展 `RunDetail` 类型包含 `model_results` |
| 2 | `frontend/src/runResult.tsx` | **新建** | `RunResultView` 共享组件：管理 detail/artifacts/SSE/progress/report iframe，接收 `projectRoot` + `runId` |
| 3 | `frontend/src/App.tsx` | 重写 | SubmitRoute：文件预览 UI + 列选择器（checkbox 多选 x，radio 单选 y）+ 内联 `<RunResultView>` |
| 4 | `frontend/src/runDetail.tsx` | **删除** | 逻辑已提取到 `runResult.tsx`；`RunDetailRoute` 替换为使用 `RunResultView` 的薄 wrapper |
| 5 | `frontend/src/runHistory.tsx` | 修改 | 点击行设置 URL search param `?selected=<runId>`，在表下方渲染 `RunResultView` |
| 6 | `frontend/src/styles.css` | 修改 | 预览表格、列选择器、系数表、诊断图样式 |
| 7 | `backend/workbench/api.py` | 修改 | `get_run_endpoint` 返回 `model_results` 数据 |
| 8 | `backend/workbench/orchestrator.py` | 修改 | 模型路由矩阵（panel/ts/cs）+ 多模型结果收集 + 模型结果传给 `create_figures` |
| 9 | `backend/workbench/visualization.py` | 修改 | 新增残差图、QQ图、系数森林图（需 `model_results` 参数） |
| 10 | `backend/workbench/narrative.py` | 修改 | 增强声明：幅度 + 显著性 + R² 解读 |
| 11 | `frontend/package.json` | 修改 | 新增 `xlsx` 依赖（SheetJS） |
| 12 | `frontend/src/App.test.tsx` | 修改 | 适配新 UI：列选择器、内联结果、`previewFile` mock |
| 13 | `frontend/src/api.test.ts` | 修改 | `previewFile` 单元测试 |
| 14 | `tests/test_api.py` | 修改 | detail API 返回 `model_results` 断言 |
| 15 | `tests/test_orchestrator_e2e.py` | 修改 | 模型路由：panel→fe、cs→ols only、ts→diagnostics |
| 16 | `tests/test_visualization.py` | **新建** | 新图表输出验证 |
| 17 | `tests/test_reporting_exports.py` | 修改 | 叙事增强 + export 含多模型 |
| 18 | `docs/superpowers/specs/2026-05-04-workbench-v1.2.3-interactive-submit-design.md` | **新建** | 本设计文档归档 |

---

## 详细设计

### A. 前端 — `previewFile()` 客户端文件解析

**文件：** `frontend/src/api.ts`

**依赖：** `npm install xlsx`

```typescript
import * as XLSX from "xlsx";

export type ColumnPreview = {
  name: string;
  dtype: "numeric" | "string" | "date" | "other";
  missingRate: number;       // 0.0–1.0
  uniqueCount: number;
  mean?: number;             // numeric 列
  std?: number;              // numeric 列
  suggestedRole: "y" | "x" | "id" | "time" | "ignore";
};

export type FilePreview = {
  fileName: string;
  rowCount: number;
  columnCount: number;
  columns: ColumnPreview[];
  previewRows: Record<string, unknown>[];  // 前 10 行
  suggestedY: string | null;
  suggestedX: string[];
};

export function previewFile(file: File): Promise<FilePreview> { ... }
```

**解析边界 & 验收规则：**

| 场景 | 处理 |
|---|---|
| 大文件（>100MB 或 >100K 行） | `XLSX.read(file, {sheetRows: 10001})` 只读前 10001 行；`previewRows` 只保留前 10 行；`rowCount` 为实际读取行数（上限标注 "+"） |
| 空 sheet / 全空列 | 空列 `missingRate=1.0`，`dtype="other"`，`suggestedRole="ignore"` |
| 重复列名 | XLSX 自动去重（`col`, `col_1`）；不去干预，原样展示 |
| `.xlsx` 日期列 | `XLSX.read` 的 `raw: false` 让 SheetJS 自动格式化日期为字符串；检测格式 `yyyy-mm-dd` 或类似 → `dtype="date"` |
| Excel serial number 日期 | SheetJS `raw: false` 默认将 serial number 转为格式化日期字符串；若 `raw: true` 则视为 numeric——统一用 `raw: false` |
| 非 CSV/XLSX 文件 | `XLSX.read` 会抛异常 → `previewFile` reject，UI 显示 "Unsupported file format" |

**`suggestedRole` 推断优先级：**

```
1. 列名含 y/dependent/outcome/target/result → "y"
2. 列名含 date/time/year/month/timestamp/quarter → "time"
3. 列名含 id/code/key/firm/user/store/gvkey/permno → "id"
4. dtype=="numeric" → "x"
5. 其他 → "ignore"
```

**`suggestedY` 推断：** 第一个 `suggestedRole=="y"` 且 `dtype=="numeric"` 的列；若无，取第一个 `dtype=="numeric"` 且 `suggestedRole!="time"` 且 `suggestedRole!="id"` 的列。

**`suggestedX` 推断：** 所有 `suggestedRole=="x"` 的列，**排除** `suggestedY`、所有 time/id 列。

### B. 前端 — Submit 页 UI 改造

**文件：** `frontend/src/App.tsx`

**保留不变：** Project panel（手动输入 parent folder + name + Create 按钮）。理由：浏览器不暴露绝对路径。

**Run panel 改造：**

```
[Mode: auto/stepped]
[Data file: 文件选择器 accept=".csv,.xlsx,.xls"]
  → 选择后立即调 previewFile(file)，显示 spinner
  → 完成：显示预览区域

预览区域：
┌─────────────────────────────────────────┐
│ data.csv · 150 rows · 8 columns         │
│ ┌─────────────────────────────────────┐ │
│ │ 数据预览表格 (前10行, 可横向滚动)    │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ Dependent variable (y):                 │
│  ○ gdp  ○ inflation  ○ year  ● other   │
│                                         │
│ Regressors (x):                         │
│  ☑ gdp  ☑ inflation  ☐ year  ☐ ...    │
│                                         │
│ (保留手动输入框作为高级选项:            │
│  y: [________]  x: [______________])    │
└─────────────────────────────────────────┘

[Run workflow] button
```

**y 选择器：** radio button 单选。选项来自 `columns` 中所有 numeric 列 + "其他"（选"其他"时展开手动输入框）。

**x 选择器：** checkbox 多选。选项来自 `columns` 中所有 numeric 列（排除已选 y）。保留手动输入框兼容高级用户。

**运行后：** `onRun()` 不导航，而是设置 `lastRunId` 状态，Submit 页下方渲染：

```tsx
{lastRunId && (
  <RunResultView
    projectRoot={projectRoot}
    runId={lastRunId}
    onError={setError}
  />
)}
```

### C. 前端 — RunResultView 共享组件

**文件：** `frontend/src/runResult.tsx`（新建）

**职责声明：** 这是一个纯粹的"给定 projectRoot + runId，展示完整 run 结果"的组件。不感知调用方是 Submit、History 还是 direct URL。内部管理：
- `fetchRunDetail()` + `fetchRunArtifacts()` 获取数据
- SSE `connectRunEvents()` 管理（仅当 `detail.status === "running"`）
- 12 步 progress 面板
- 系数表（来源：`detail.model_results`）
- 诊断图展示（`<img>` 加载 artifact 图片 URL）
- Report iframe toggle
- Artifact 分组下载列表
- Issues 错误展示
- Loading / error / retry 状态

**Props：**
```typescript
type RunResultViewProps = {
  projectRoot: string;
  runId: string;
  onError?: (msg: string | null) => void;
};
```

**使用方：**
- `SubmitRoute`：`<RunResultView projectRoot={...} runId={lastRunId} />`
- `RunDetailRoute`（保留）：`<RunResultView projectRoot={...} runId={runId!} />`
- `RunHistoryRoute`：`<RunResultView projectRoot={...} runId={selectedRunId} />`

### D. 前端 — 路由结构

**保留 V1.2.1 的 `/runs/:runId` 可分享 URL。** 修改 RunDetailRoute 为薄 wrapper 用 `RunResultView`。

**History 页增强：** 点击行 → 设置 `?selected=<runId>`（不导航离开 History 页），在表下方展开 `RunResultView`。用户可通过 URL 复制分享（`#/runs?selected=run-123&project_root=/tmp/demo`）。

**不新增 `/runs/:runId` 之外的独立路由。不删除现有路由。**

### E. 后端 — API 返回 model_results

**文件：** `backend/workbench/api.py` 的 `get_run_endpoint`

**改动：** 在 detail 响应中新增 `model_results` 字段。读取 `{run_root}/model_results/*.json`，返回 `{model_id: result_dict}`：

```python
def _read_model_results(run_root: Path) -> dict[str, dict]:
    results_dir = run_root / "model_results"
    if not results_dir.is_dir():
        return {}
    results: dict[str, dict] = {}
    for path in sorted(results_dir.glob("*.json")):
        model_id = path.stem
        results[model_id] = read_json(path)
    return results
```

在 `get_run_endpoint` 中调用：
```python
return {
    **summary,
    "lineage": ...,
    "artifact_counts": ...,
    "errors": ...,
    "model_results": _read_model_results(run_root),
}
```

### F. 后端 — 模型路由矩阵

**文件：** `backend/workbench/orchestrator.py` estimation 步骤

**规则矩阵：**

| `routing["kind"]` | 有 entity id | 有时间列 | 跑的模型 |
|---|---|---|---|
| `cross_section` | — | — | `ols_1` (robust OLS) |
| `panel` | 是 | — | `fe_1` (固定效应) + `ols_1` (baseline OLS) |
| `panel` | 否 | — | `ols_1` (仅 OLS)，记录 WARNING issue |
| `time_series` | — | 是 | `ols_1` + time series diagnostics (lag1 autocorrelation) |
| `time_series` | — | 否 | `ols_1` (仅 OLS) |
| `repeated_cross_section` | — | — | `ols_1` |
| `unknown_mixed` | — | — | `ols_1` |

**实现方式：** `_run_workflow` 的 estimation 步骤内，`model_results: list[tuple[str, dict]]` 列表。每个模型都写入 `model_results/{model_id}.json`，都传给 `create_figures`。

**`on_step` 消息动态化：**
- `"Fitting OLS..."` → `"Fitting baseline OLS..."`
- `"Fitting OLS + Fixed Effects (entity={entity})..."`

**OLS baseline 始终跑**（除非 model_check 阶段已 blocked）。面板数据额外跑 FE。FE 失败不影响 OLS baseline。

### G. 后端 — 增强图表

**文件：** `backend/workbench/visualization.py`

**函数签名扩展：**
```python
def create_figures(
    frame: pd.DataFrame,
    run_root: Path,
    *,
    numeric_columns: list[str],
    time_column: str | None,
    model_results: list[tuple[str, dict]] | None = None,  # 新增
) -> dict[str, str]:
```

**新增图表：**

| 图表 | artifact ID | 条件 | 内容 |
|---|---|---|---|
| `residuals_fitted.png` | `residuals_fitted` | 有 model_result 且含 `resid` + `fittedvalues` | 散点图 + 水平零线 + lowess 平滑线 |
| `qq_residuals.png` | `qq_residuals` | 同上 | `scipy.stats.probplot` Q-Q plot |
| `coef_plot.png` | `coef_plot` | 有 model_result 且含 coefficients | 水平森林图：estimate ± 1.96×SE，虚线零线 |
| `correlation_heatmap.png` | `correlation_heatmap` | ≥2 numeric cols | 保持现有 |
| `time_trend.png` | `time_trend` | 有时间列 | 保持现有 |

### H. 后端 — 增强叙事

**文件：** `backend/workbench/narrative.py`

**`build_claims()` 增强：**

对每个 coefficient（跳过截距）：
- `"{term}: 每增加一个单位，Y 平均变化 {estimate:.4f} 个单位"`
- `p_value < 0.01` → `"在 1% 水平显著"`
- `p_value < 0.05` → `"在 5% 水平显著"`
- `p_value >= 0.05` → `"未达到常规显著性水平 (p={p_value:.3f})"`

对模型级别的声明：
- `"模型 R² = {r_squared:.4f}，解释了 Y 变异的 {r_squared*100:.1f}%"`
- 如有观测数：`"基于 {nobs} 个观测"`

---

## 验证命令

```bash
# 后端测试
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.2.1-browsing
python3 -m pytest tests/ -q

# 前端测试
cd frontend && npx vitest run

# 前端构建检查
cd frontend && npx vite build

# 手动 E2E
# 1. 选择 .xlsx 文件 → 预览表格出现，y/x 自动推荐
# 2. 调整变量选择（多选 x checkbox）→ Run → 进度条在本页显示
# 3. 完成后 → 系数表（model_results）、诊断图、report iframe、artifact 下载均可见
# 4. 面板数据（entity + time 列）→ 验证 FE + OLS 双模型自动运行
# 5. 切到 History → 点击行 → 同页下方展示结果；URL 含 ?selected=runId
# 6. 直接访问 #/runs/:runId?project_root=... → 独立 detail 页仍可用
# 7. 大文件（>10MB .csv/.xlsx）→ 预览不卡、只显示前 10 行
```

## 已知取舍

- **项目路径仍手动输入**：浏览器安全模型不暴露本地绝对路径，这是平台限制不是实现缺陷。不做误导性 UI。
- **客户端预览的 dtype 推断比后端 `infer_schema()` 简单**：不做完整语义角色推断，但足够覆盖 90% 的列推荐场景。
- **仅处理第一个 sheet**：XLSX 多 sheet 文件只预览/处理第一个 sheet，与后端 `ingest_files` 行为一致。
- **FE 模型的 entity/time 列自动从 router 的 id_candidates/time_candidates 取**：不新增用户配置项。若推断错误，用户可通过 History→errors 面板看到 WARNING。
