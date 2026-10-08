# v1.9.0 第 1 步验收：设计 token 与主题地基

日期 2026-10-08。对应 objective 第 1 步（V1811-FRONTEND-CSS、V1811-DARK-PANEL-CONTRAST）。

## 交付

- `frontend/src/theme/tokens.css` 是唯一的 token 来源：类型、间距、圆角、动效（临界阻尼弹簧，response 0.35 s）、材质；
  浅色（设计 §8.5）与深色（设计图 “Lineage first · dark”）两套颜色，名字完全相同；
  `prefers-reduced-motion`、`prefers-reduced-transparency` 降级。
- 旧的 token 定义从 `lineage/tokens/lineage.css` 移出；`--ios-*` 一组并入主 token；未被引用的 `lineage/tokens/tokens.ts` 删除。
- 27 个从未定义、靠回退写死值生效的颜色变量（如 `--accent`、`--danger`、`--surface`）改为规范名。
- 凡“白字 + 强调色底”的地方改用 `--tint-fill` / `--on-tint`（深色下强调色是浅蓝，白字压不住）；
  角色徽章改用 `--on-role`（深色下为深色字）；浅色下 6 个角色色降低亮度以达到 4.5:1。

## 测量口径（先定口径，再报下降）

| 量 | 定义 | v1.8.12 | 本步之后 |
|---|---|---|---|
| CSS 颜色字面量 | `tokens.css` 以外、自定义属性定义与注释以外的 `#hex`、`rgb[a](数字`、`hsl[a](数字`、`oklch(数字`，以及声明值里的 `white` / `black` | 176 | 0 |
| TS 颜色字面量 | 非测试 TS/TSX 字符串字面量中的同类颜色（含 `var(--x, #fallback)` 里的回退值，以及 `"white"` / `"black"`） | 96（其中 52 在未引用的 `tokens.ts`） | 0 |
| 未定义的 CSS 变量 | `var(--x)` 中 `--x` 不在 `tokens.css`，且不是组件运行时设置的位置 / 节点颜色变量 | 27 个名字 | 0 |
| 内联样式 | 非测试 TSX 中 `style={{` 的出现次数 | 934 | 934（棘轮上限，只降不升） |

BACKLOG 记的“139 处写死颜色”无法复现（来源未记录口径），以上表为准。由 `src/theme/designTokens.test.ts` 守住。

## 测试

- `designTokens.test.ts`：两种主题定义同一组 token；文字与其所在表面的配对（正文三级、强调色 × 四种表面，状态四对，徽章、错误、警示、
  强调填充、角色徽章 × 10 种角色）在两种主题下都 ≥ 4.5:1；焦点环对四种表面 ≥ 3:1；三项棘轮；未定义变量为 0。
- 前端全部 214 个文件 / 1806 个测试通过，`tsc --noEmit` 无错误。

## 浏览器验收（1512 × 982，端口 5194 / 8034）

项目：`local/v190-step1/project`（复制自 v1.8.12 第 4 步验收项目，2 次 OLS 运行）。
对比度审计脚本：`evaluations/v1.9.0/contrast-audit.js`（遍历页面全部可见文字，按实际叠加后的背景计算对比度，大字 3:1、其余 4.5:1）。

| 界面 | 浅色 不达标 | 深色 不达标 |
|---|---|---|
| Graph + 节点详情 | 0 | 0 |
| Notebook | 0 | 0 |
| Data | 0 | 0 |
| Table | 0 | 0 |
| Report（含 Report review） | 0 | 0 |
| 下方面板 Agent / Logs / AI activity | 0 | 0 |
| New analysis | 0 | 0 |
| Settings（LLM providers、Memory） | 0 | 0 |
| ⌘K 面板 | — | 0 |

首轮审计在深色下发现 3 处并已修复：角色徽章白字（2.68–3.10）、React Flow 署名（1.22）、“Ask AI about this node” 按钮（2.33）；
浅色下发现 1 处：下方面板混入 4% 文字色后，日志时间戳只有 4.21，改为窗口底色。
原深色白底问题（`.ios-group`）：深色下背景为 `#1E1E20`，组内文字全部达标。

截图：`graph-node-light.jpg`、`graph-node-dark.jpg`（同一视图）。
