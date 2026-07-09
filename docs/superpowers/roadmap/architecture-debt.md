# 架构技术债台账（长活）

> 与版本级 followups 分开：这些是**跨版本、长活**的架构/组织债，不绑单个版本。
> 生命周期同 roadmap（就地更新，不归档）。来源：Hermes 架构审查 + 2026-07-09
> 逐条对当前代码核实（main `22a4a04`）。核实时把 Hermes 的几条不准确处校正了。

## 核实快照（2026-07-09，main 22a4a04）

| 债 | 当时 Hermes | 现在核实 | 判定 |
|---|---|---|---|
| 大文件 api.py | 1137 行 | **2204 行**（23 路由 + 39 私有函数 + 72 def） | 成立，已恶化 ~2× |
| 大文件 runner.py | 743 行 | 743 行（15 个 `run_*`） | 成立 |
| 大文件 api.ts | 1002 行 | **1346 行**（44 手写 type + 客户端 + 错误类） | 成立，已恶化 |
| 大文件 App.test.tsx | 1454 行 | 1360 行 | 成立 |
| 全局 CSS styles.css | 864 行 | **1053 行** | 成立，已恶化 |
| CLI 参数 | x / model-type | `--x --model-type --mode --imputation`（4 个） | 成立 |
| lineage 规模 | "过度设计" | 后端 19 文件/2787 行 + 前端 60 文件 | 存在，但见 D5 反驳 |
| OpenAPI codegen | 无 | 确认无 codegen 工具，44 手写 type | 成立 |

> **趋势警告**：api.py / api.ts / styles.css 三个大文件从 Hermes 审查到现在**还在涨**。
> "越改越大"的累积模式没有被遏制——每加一个版本就往垃圾桶里塞。

---

## D1. api.py 是万能垃圾桶（**最高优先**）

- **事实**：2204 行，一个文件同时管：路由定义、请求解析、文件上传、后台任务调度（`_bg_run` + executor）、SSE 推送、结果汇总（`_model_results`/`_normalize_issue_stream`）、错误归一化、项目创建。23 个路由 + 39 个私有辅助函数。
- **判定**：真债，且是最该动的。分层不清导致每个新端点都往这里叠。
- **方向**：拆 controller（路由 + 请求/响应 schema）/ service（`_submit_run`、genesis execute、rerun 编排）/ repository（run 目录、model_results、artifacts 读写）。可先抽最独立的两块：**后台任务调度 + SSE**（events 已有雏形）、**结果汇总层**（`_model_results`/issue 归一化）。
- **注意**：与版本 backlog 的「`WorkbenchRouteContainer` 拆分」是前后端对称的同一种病（承重容器摊大饼）。两个一起立规矩：**新端点/新视图不许直接往大文件加，先看有没有对应 service/hook**。
- **代价**：大。必须先有端点级契约测试护栏（现有 `tests/test_api.py` 34 + 契约测试），再拆。

## D2. GLM 家族 runner 该收敛成策略 + 注册表（中）

- **事实**：15 个 `run_*`。其中 **6 个 GLM 家族**（ols/logit/probit/poisson/negative_binomial/glm）几乎同构：`_ensure_numeric_y/x` → `_ols_formula` → `smf.<fam>(...).fit()` → try/except 收敛 → `normalize_statsmodels_result` → 打 `model_type` 标签。
- **校正 Hermes**："无抽象"不准——**已有共享层**（`_ensure_numeric_*`/`_ols_formula`/`_formula_term`/`normalize_statsmodels_result`/`_add_engine`）。缺的是**顶层**把这 6 个 wrapper 收敛成一个「family → statsmodels 构造器 + 收敛校验策略」的注册表。DID 家族（did/event_study/cs/sa/dcdh）**是真异构**，不该硬套同一模式。
- **方向**：`GLM_FAMILIES = {"logit": smf.logit, ...}` + 一个参数化 `run_glm_family(family, ...)`，保留各自的收敛报错文案；DID 家族维持独立。
- **代价**：中。golden/invariant 测试（23）能钉住数值不漂移，重构风险可控。

## D3. CLI 是 API 的阉割版（中，ROI 高）

- **事实**：引擎里 DID/CS/SA/dCDH/IV/Panel 全实现了，但 CLI 只有 `--x --model-type --mode --imputation`——**entity/time/treatment/endog/iv 一个都传不进**。等于引擎完整、入口残疾。
- **方向**：把 `_submit_run` 已经解析的那套 form 参数在 CLI 上对齐（复用后端同一套 parse），或让 CLI 直接构造 form dict 走 `_submit_run`。
- **代价**：小-中，ROI 高——纯加参数 + 透传，不动引擎。适合当某个版本的顺手清债。

## D4. 前端全局 CSS 1053 行（低，非紧急）

- **事实**：单个 `styles.css` 1053 行 + 组件里散落 inline style（如 BottomPanel/drawer）。无 CSS Modules / CSS-in-JS / Tailwind。lineage 那块另有 `tokens/lineage.css`。
- **判定**：能用，churn 风险 > 收益。低优先。真要动就渐进式（新组件用 CSS Modules，旧的不强迁）。
- **代价**：大且低收益，不建议专门立项。

## D5. lineage「过度设计」——**反驳，标记为有意复杂度**

- **事实**：后端 19 文件/2787 行（node_hash / DAG 不变量 / Merkle 增量 / project_forest / compare-readiness）+ 前端 60 文件。
- **判定**：**与 roadmap 北极星直接冲突**——`2026-07-01-unified-graph-workbench-roadmap.md` 明确把「一张 lineage graph 完成所有操作（编辑/rerun/对比/AI/报告）」当**产品核心卖点和护城河**。所以这是**有意的复杂度投资**，不是意外债。单用户场景确实用不满，但产品方向就是赌它。
- **动作**：不作为"要还的债"。但值得每个大版本做一次「这套抽象是否在为当前功能挣钱」的复查——若某些不变量/Merkle 增量始终没被新功能用到，那部分可以降级。**判断权在用户（产品方向）**。

## D6. 无 OpenAPI codegen，两端类型手动同步（中）

- **事实**：api.ts 44 个手写 `type/interface` 镜像后端返回体；FastAPI 的 OpenAPI schema 放着没用。手动维护迟早漂移。
- **缓解现状**：`docs/api-contracts/` + 契约测试对部分端点有钉，但不是全自动。
- **方向**：`openapi-typescript` 从 `/openapi.json` 生成 `api.gen.ts`，api.ts 只留客户端逻辑 + 错误类，type 改成 import 生成的。CI（若将来启用）跑一次生成 + diff 卡漂移。
- **代价**：中。一次性接入 + 把手写 type 换成生成的引用。

---

## 建议优先级

1. **D1 api.py 拆分**（最高，且还在涨）——但要先有契约测试护栏。与前端 `WorkbenchRouteContainer` 拆分成对推进，立"不许再往大文件加"的规矩。
2. **D3 CLI 补参数**（ROI 最高，代价小）——适合任何版本顺手清。
3. **D6 OpenAPI codegen**（防漂移，中代价）——接入后两端类型一劳永逸。
4. **D2 GLM 家族收敛**（中，golden 护栏使风险可控）。
5. **D5 lineage 复查**（不是债，是每版一次的"抽象是否挣钱"复盘，用户拍板）。
6. **D4 CSS**（低，不专门立项，渐进式）。

> 落地纪律：这些是大重构，都要走 spec/plan/三级评审 + golden/契约护栏，不能裸改。
> 单版本别贪多——D1 或 D6 任一个就够一个版本的重构预算。
