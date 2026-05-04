# V1.2.3: 交互式文件预览 + 模型增强 + 单页结果展示

## 起点

Worktree: `.worktrees/workbench-v1.2.3-interactive`
Branch: `codex/workbench-v1.2.3-interactive`
基于 V1.2.2（`feature/workbench-v1.2.1-browsing`）的全部代码。

## 背景

V1.2.2 完成了异步后台运行 + SSE 进度推送。用户反馈了 7 个前端交互和功能欠缺问题：

1. **文件格式**：只支持 `.csv`，需要 `.xlsx/.xls`
2. **文件预览缺失**：选择文件后看不到数据，不知道有哪些列
3. **变量配置不直观**：逗号分隔文本输入，用户不易发现多变量能力
4. **无自动列推荐**：用户必须提前知道列名
5. **统计学能力不足**：永远只跑 OLS（固定效应已实现但未接入），只有 2 种图表，叙事只报告系数符号
6. **结果不在提交页**：运行完跳转到独立 detail 页，用户期望在 Submit 页直接看到结果
7. **项目路径手动填写**：无辅助选择方式

## 平台限制

浏览器安全沙箱不暴露本地绝对路径。`showDirectoryPicker()` 和 `webkitdirectory` 均无法获取如 `/Users/.../workspace` 的真实路径。**`project_root` 保持手动文本输入。** 不做伪装"原生目录选择器"的 UI。

---

## 文件变更总览

| # | 文件 | 类型 | 说明 |
|---|---|---|---|
| 1 | `frontend/package.json` | 修改 | 新增 `xlsx` 依赖 |
| 2 | `frontend/src/api.ts` | 修改 | 新增 `previewFile()` 客户端解析 + `FilePreview` 类型；`RunDetail` 扩展 `model_results` |
| 3 | `frontend/src/runResult.tsx` | **新建** | `RunResultView` 共享组件：detail/artifacts/SSE/progress/report |
| 4 | `frontend/src/runDetail.tsx` | **保留并精简** | 改为薄 wrapper，内部仅渲染 `<RunResultView>` |
| 5 | `frontend/src/App.tsx` | 修改 | SubmitRoute：文件预览 + 列选择器 + 内联 `RunResultView` |
| 6 | `frontend/src/runHistory.tsx` | 修改 | 点击行设置 `?selected=<runId>`，表下展开 `RunResultView`；页面加载时读取 selected 自动展开 |
| 7 | `frontend/src/styles.css` | 修改 | 预览表格、列选择器、系数表、诊断图样式 |
| 8 | `backend/workbench/api.py` | 修改 | `get_run_endpoint` 返回 `model_results`（数组） |
| 9 | `backend/workbench/orchestrator.py` | 修改 | 模型路由矩阵 + 多模型结果收集 + `model_results` 传给 `create_figures` |
| 10 | `backend/workbench/visualization.py` | 修改 | 新增残差图、QQ图、系数森林图（需 `model_results` 参数） |
| 11 | `backend/workbench/narrative.py` | 修改 | 增强声明：幅度 + 显著性 + R² |
| 12 | `frontend/src/App.test.tsx` | 修改 | 适配列选择器 + 内联结果 + `previewFile` mock |
| 13 | `frontend/src/api.test.ts` | 修改 | `previewFile` 单元测试 |
| 14 | `tests/test_api.py` | 修改 | detail API 断言含 `model_results` |
| 15 | `tests/test_orchestrator_e2e.py` | 修改 | 模型路由：panel→fe+ols、cs→ols only、ts→ols+diagnostics |
| 16 | `tests/test_visualization.py` | **修改**（已存在） | 新图表输出验证 |
| 17 | `tests/test_reporting_exports.py` | 修改 | 叙事增强 + 多模型 export |
| 18 | `docs/superpowers/specs/2026-05-04-workbench-v1.2.3-interactive-submit-design.md` | **新建** | 本设计归档 |

---

## A. 前端 — `previewFile()` 客户端文件解析

**文件：** `frontend/src/api.ts`  
**依赖：** `npm install xlsx`

```typescript
import * as XLSX from "xlsx";

export type ColumnPreview = {
  name: string;
  dtype: "numeric" | "string" | "date" | "other";
  missingRate: number;
  uniqueCount: number;
  mean?: number;
  std?: number;
  suggestedRole: "y" | "x" | "id" | "time" | "ignore";
};

export type FilePreview = {
  fileName: string;
  rowCount: number;
  rowCountTruncated: boolean;   // true if 文件行数超过预览上限
  columnCount: number;
  columns: ColumnPreview[];
  previewRows: Record<string, unknown>[];  // 前 10 行
  suggestedY: string | null;
  suggestedX: string[];
};

export async function previewFile(file: File): Promise<FilePreview> {
  const buffer = await file.arrayBuffer();
  const wb = XLSX.read(buffer, {
    type: "array",
    sheetRows: 10001,    // 最多读 10001 行（含表头）
    cellDates: true,     // 日期自动转 Date 对象
  });
  const sheetName = wb.SheetNames[0];
  const sheet = wb.Sheets[sheetName];
  const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, {
    raw: true,           // 保留原始值（number 不转 string）
  });
  // ... dtype 推断、suggestedRole 推断（见下方规则）
}
```

**dtype 推断（`raw: true` 下）：**
- `typeof v === "number"` → `"numeric"`
- `v instanceof Date` → `"date"`
- `typeof v === "string"` 且可解析为数字 → `"numeric"`
- `typeof v === "string"` 且匹配日期格式 → `"date"`
- 其他 → `"string"`（全列为 null/undefined → `"other"`）

**边界处理：**

| 场景 | 处理 |
|---|---|
| 文件 >10000 行 | `sheetRows: 10001` 截断读取，`rowCount=10000`，`rowCountTruncated=true` |
| `.xlsx` 含多个 sheet | 仅读取第一个 sheet |
| 空 sheet（0 行） | `rowCount=0`，`columns=[]`，`previewRows=[]` |
| 全空列 | `missingRate=1.0`，`dtype="other"`，`suggestedRole="ignore"` |
| 重复列名 | SheetJS 自动加后缀（`col`, `col_1`），原样使用 |
| 不支持的文件格式 | `XLSX.read` 抛异常 → `previewFile` reject，UI 显示 "Unsupported file format" |

**`suggestedRole` 推断规则：**
1. 列名含 `y/dependent/outcome/target/result/gdp` 且 dtype=`numeric` → `"y"`
2. 列名含 `date/time/year/month/timestamp/quarter` → `"time"`
3. 列名含 `id/code/key/firm/user/store/gvkey/permno/entity` → `"id"`
4. dtype=`numeric` → `"x"`
5. 其他 → `"ignore"`

**`suggestedY`：** 第一个 `suggestedRole=="y"` 的列。若无，取第一个 `dtype=="numeric"` 且 role 非 time/id 的列。

**`suggestedX`：** 所有 `dtype=="numeric"` 的列，**排除** `suggestedY`、所有 time/id 列。

---

## B. 前端 — Submit 页 UI

**文件：** `frontend/src/App.tsx` SubmitRoute

**Project panel：** 不变（手动输入 parent folder + name + Create 按钮）。

**Run panel 流程：**

1. 文件选择器：`accept=".csv,.xlsx,.xls"`
2. 选择后立即 `previewFile(file)`，显示 spinner
3. 完成 → 渲染预览区域：

```
┌─────────────────────────────────────────┐
│ data.csv · 150 rows · 8 columns         │
│ ┌─────────────────────────────────────┐ │
│ │ 数据预览表格 (前10行, 可横向滚动)    │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ Dependent variable (y):                 │
│  ● gdp  ○ inflation  ○ year  ○ other   │
│  (radio button, 单选, 默认 suggestedY)  │
│                                         │
│ Regressors (x):                         │
│  ☑ inflation  ☑ unemployment  ☐ year   │
│  (checkbox, 多选, 默认 suggestedX)      │
│                                         │
│ (高级: y[text] x[text] 手动输入框)      │
└─────────────────────────────────────────┘
[Run workflow]
```

4. 提交时：将选中的 x 列用逗号拼接 → `runWorkflow()`（后端 API 不变）
5. 提交后：设置 `lastRunId`，本页下方渲染：

```tsx
{lastRunId && (
  <RunResultView projectRoot={projectRoot} runId={lastRunId} onError={setError} />
)}
```

**Submit 页不更新 URL。** 只有 History 和 `/runs/:runId` 负责可分享 URL。

---

## C. 前端 — `RunResultView` 共享组件

**文件：** `frontend/src/runResult.tsx`（新建）

**职责边界：** 给定 `projectRoot` + `runId`，展示完整 run 结果。不感知调用方是谁。内部管理：

- `fetchRunDetail()` → detail（含 `model_results`）
- `fetchRunArtifacts()` → artifact groups
- SSE `connectRunEvents()` — 仅当 `detail.status === "running"`
- 12 步 progress 面板
- 系数表（来源：`detail.model_results` 数组）
- 诊断图展示：过滤 `artifact_type === "figure"`，用 `artifactDownloadUrl()` 作为 `<img src>`
- Report iframe toggle（`reportUrl()`）
- Artifact 分组下载列表
- Issues 面板
- Loading / error / retry 状态

**Props：**
```typescript
type Props = {
  projectRoot: string;
  runId: string;
  onError?: (msg: string | null) => void;
};
```

**三处使用：**
- `SubmitRoute`：`<RunResultView projectRoot={...} runId={lastRunId} />`
- `RunDetailRoute`（`runDetail.tsx` 薄 wrapper）：读 `useParams().runId`，渲染 `<RunResultView />`
- `RunHistoryRoute`：点击行 → `setSelectedRunId(id)`，表下渲染 `<RunResultView />`

---

## D. 前端 — 路由保留

**保留 `/runs/:runId`（V1.2.1 的可分享能力不回退）。**

`runDetail.tsx` 改为薄 wrapper：
```tsx
function RunDetailRoute() {
  const { projectRoot, setError } = useAppContext();
  const { runId } = useParams<{ runId: string }>();
  if (!projectRoot) return <MissingProjectPrompt />;
  return <RunResultView projectRoot={projectRoot} runId={runId!} onError={setError} />;
}
```

**History 页 URL 状态：** 点击行 → `navigate({search: "?selected=<runId>&project_root=...})`，不离开 History 页。页面加载时 `useEffect` 读取 `searchParams.get("selected")`，若存在则自动展开该 run 的 `RunResultView`。

---

## E. 后端 — API 返回 model_results

**文件：** `backend/workbench/api.py`

`get_run_endpoint` 新增字段。返回 shape：
```python
{
    "run_id": str,
    "status": str,
    "mode": str,
    "started_at": str | None,
    "y": str | None,
    "x": list[str] | None,
    "lineage": list[dict],
    "artifact_counts": dict[str, int],
    "errors": {"issues": [...]},
    "model_results": [
        {
            "model_id": str,
            "model_type": str,
            "nobs": int,
            "r_squared": float | None,
            "coefficients": {...},
            # ... 其他 statsmodels 字段
        },
        ...
    ],
}
```

`model_results` 是**数组**（非 dict）。排序稳定（先 OLS baseline，再 FE）。前端可直接 `model_results.map()` 渲染。

---

## F. 后端 — 模型路由矩阵

**文件：** `backend/workbench/orchestrator.py` estimation 步骤

**规则：**

| `kind` | entity id | time col | 跑的模型 |
|---|---|---|---|
| `cross_section` | — | — | `ols_1` |
| `panel` | 有 | — | `ols_1` → 尝试 `fe_1` |
| `panel` | 无 | — | `ols_1` + WARNING |
| `time_series` | — | 有 | `ols_1` + diagnostics |
| `time_series` | — | 无 | `ols_1` |
| `repeated_cross_section` | — | — | `ols_1` |
| `unknown_mixed` | — | — | `ols_1` |

**FE 失败语义（关键实现规则）：**
1. 先跑 `ols_1`（baseline），写入 `model_results/ols_1.json`
2. 再 `try: fe_1` → 成功则写入 `model_results/fe_1.json`
3. `fe_1` 失败 → `except`：写 WARNING issue（`code: "FE_ESTIMATION_FAILED"`）到 `errors.json`，**不阻断** workflow
4. manifest status 仍为 `completed`（OLS baseline 成功即可）
5. 测试覆盖：mock `run_fixed_effects` 抛异常 → 断言 manifest completed + WARNING 存在 + OLS 结果正常

**`model_results` 列表收集后传给 `create_figures` 和 `build_claims`。**

---

## G. 后端 — 增强图表

**文件：** `backend/workbench/visualization.py`

签名新增参数：
```python
def create_figures(
    frame, run_root, *, numeric_columns, time_column,
    model_results: list[tuple[str, dict]] | None = None,
) -> dict[str, str]:
```

| 图表 | artifact ID | 条件 |
|---|---|---|
| `correlation_heatmap.png` | `correlation_heatmap` | ≥2 numeric cols（现有） |
| `time_trend.png` | `time_trend` | 有时间列（现有） |
| `residuals_fitted.png` | `residuals_fitted` | 有 model_result 含 `resid` + `fittedvalues` |
| `qq_residuals.png` | `qq_residuals` | 同上，`scipy.stats.probplot` |
| `coef_plot.png` | `coef_plot` | 有 model_result 含 coefficients |

诊断图每个 model 独立生成一份（如 `residuals_fitted_ols_1.png`）。

---

## H. 后端 — 增强叙事

**文件：** `backend/workbench/narrative.py`

对每个 coefficient（跳过截距）：
- `"{term}: 每增加1单位，Y 平均变化 {estimate:.4f} (p={p_value:.4f})"`
- p<0.01 → 标注 `** p<0.01`，p<0.05 → `* p<0.05`

模型级声明：
- `"R² = {r_squared:.4f}（解释了 Y 变异的 {pct}%）"`

---

## I. 前端 — `model_results` 类型扩展

**文件：** `frontend/src/api.ts`

```typescript
export type ModelResult = {
  model_id: string;
  model_type: string;
  nobs: number;
  r_squared: number | null;
  coefficients: Record<string, {
    estimate: number;
    std_error: number;
    p_value: number;
    source_id: string;
  }>;
};

// RunDetail 扩展
export type RunDetail = RunSummary & {
  lineage: Array<{ source: string; artifact_id: string }>;
  artifact_counts: Record<string, number>;
  errors: { issues: IssueRecord[] };
  model_results: ModelResult[];  // 新增
};
```

---

## 验证命令

```bash
# 后端测试
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.2.3-interactive
../workbench-v1.2.1-browsing/.venv/bin/python -m pytest tests -q

# 前端测试
cd frontend && npx vitest run

# 前端构建
cd frontend && npx vite build
```

## 手动 E2E

1. 选择 `.xlsx` 文件 → 预览表格出现，y/x 自动推荐
2. 调整变量选择（多选 x checkbox）→ Run → 进度条在本页
3. 完成后 → 系数表、诊断图 `<img>`、report iframe、artifact 下载均可见
4. 面板数据 → 验证 FE + OLS 双模型，系数表有两组
5. History → 点击行 → 同页下方展示结果（URL 含 `?selected=runId`）
6. 直接访问 `#/runs/:runId?project_root=...` → 独立 detail 页仍可用
7. 大文件（>10000 行 .xlsx）→ 预览不卡，仅展示前 10 行，标注 truncated

## 已知取舍

- **项目路径仍手动输入**：浏览器不暴露绝对路径，平台限制。
- **客户端 dtype 推断比后端 `infer_schema()` 简单**：足够覆盖 90% 列推荐场景。
- **仅处理第一个 sheet**：与后端 `ingest_files` 行为一致。
- **FE 的 entity/time 列自动取自 router 的 id_candidates/time_candidates**：不新增用户配置。
- **Submit 页不更新 URL**：只 History 和 `/runs/:runId` 负责可分享。
- **诊断图仅对第一个 model 生成**：`_first_model_result()` 只取 `model_results[0]`，panel 场景下 FE 的残差/QQ/系数图会生成，但 OLS 的不会单独出图。per-model 诊断图推迟到 V1.2.6 诊断增强版本统一处理。
