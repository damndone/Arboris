# BACKLOG — 当前唯一 live 滚动欠账清单

> 2026-07-15 从 `v1.6.9-followups.md` 改名（历次版本名误导已久）。文件名从此固定,
> 不再随版本改名;版本收尾冻结时复制快照进 `archive/followups/`,本文件继续滚动。
> 来源：v1.6.8 起各版评审/smoke 留痕,逐版滚动至今。
>
> **本文件 = 当前 live 的滚动 backlog**（约定见 `docs/superpowers/README.md`）：
> 所有还开着的债都收在这里，做完就删（git 历史留痕），下个版本起手时把
> 新债续在这里，直到某个版本收尾时才整份冻结进 `archive/`。
>
> **§1 是跨三份 canonical 文档（本文件 / `roadmap/architecture-debt.md` /
> `roadmap/2026-07-01-unified-graph-workbench-roadmap.md`）的扁平总索引**——
> 一处看全。架构债 / 主线只放 pointer 行，正文仍在各自文档就地更新。
> 本文件自有的债（P1/W/S/U/R）详情见 §2，已清留痕见 §3。

---

## 0. 一句话结论

**v1.7.2 已 SHIPPED**（tag `v1.7.2`，`origin/main`=`4b2e6c1`）。
本版完成 OLS Agent Analysis Loop、结构化 Plan/Validation/Compare packet、报告与图表契约、
导出、run heartbeat/cancel/timeout 以及 CS-DiD 变量语义修复；发布说明见
`docs/releases/v1.7.2-release-notes.md`。

**当前开发线 = v1.7.3（未发版）**。v1.7.3 不是重新扩展算法，而是对 v1.7.2
报告/运行运维能力做真实 DeepSeek 验收和发布收口：补 provider citation shorthand 回归、
timeout 独立回归、清洁基线和端到端证据。不得把未 commit/未 tag 的工作称为已发布能力。

> NL proposal 当前只开放 `data.columns.cast`；单列 `data.column.cast` 与 `code.execute` 保持 NL 关闭。
> P-SBX2、P-CE1 和 honest-DiD 性能优化仍是独立后续债，不自动并入 v1.7.3。

## 0.1 当前版本状态（2026-07-18）

- v1.7.1：已发布。
- v1.7.2：已发布，PR #24 已合并，tag 与 `origin/main` 指向 `4b2e6c1`。
- v1.7.3：尚未发布；开发基线应从 `origin/main` 开始，当前目标是 report/operations closeout。
- v1.8+：沿 `data.column.cast` 模式扩展更多受控数据 operation，再评估更高自治和算法扩张。

---

## 1. 债务扁平优先级总表（跨三文档索引，一处看全）

> 「详情」列：`§2-x` = 本文件下方展开；`arch:Dn` = `roadmap/architecture-debt.md`；
> `roadmap` = `roadmap/2026-07-01-unified-graph-workbench-roadmap.md`；`roadmap G*` = `roadmap/2026-07-15-graph-scale-artifact-ai-terminal-directions.md`；
> `handoff §5.x` = archived `archive/handoff/v1.6.8-graph-native-genesis-handoff.md`。
> 「阻塞」= 是否阻塞用户正常使用（非验收阻塞）。

| 优先级 | ID | 债务（一句话） | 类别 | 修法 / 下一步 | 阻塞 | 详情 |
|---|---|---|---|---|---|---|
| 🟡 版本收口 | V1.7.3-R | v1.7.3 report/operations closeout：真实 DeepSeek `cs_did_staggered` 报告、8 图展开/导出、citation shorthand 与 timeout regression | 版本交付 | 从 `origin/main` 建立干净 worktree；完成计划后再 commit/PR/merge/tag | 否 | `plans/2026-07-18-v1.7.3-report-ops-closeout.md` |
| 🟡 测试 | N2 | 预存 slot-leak race:`test_run_inputs_persisted` 发 run 不等完成 → EventManager 单例 slot 泄漏，反字母序运行会 429 污染后续 run 测试 | 测试卫生（预存，v1.6.10 发现） | 测试收尾 join/await run 或按测试隔离 slot（字母序下不触发，故 gate 一直绿；非回归） | 否 | §2-N2 |
| 🟡 工程 | W1 | draft-execute dedupe 响应 `produced_lineage` 与 fresh execute 不同形 | 后端协议 | 统一响应形状 | 否 | §2-W1 |
| 🟡 工程 | W2 | 全量孤儿 upload/draft GC（项目级后台回收未做） | 后端 | 单独设计 GC；本版只回收 discard 创世链的无引用 upload | 否 | §2-W2 |
| 🟡 同族 | S1 | genesis 全流程 / Playwright smoke 层未建（只有单测 + fake-timer） | 测试 | 建 e2e smoke 层 | 否 | §2-S1 |
| 🟡 同族 | S2 | 全模型族 FE 真机执行 smoke 剩 `panel_ols`/`cs_did`/`sa_did`/`dcdh`/prediction | 测试 | 真数据肉眼确认 5 家族 Genesis 全流程 + drawer 估计方程渲染 | 否 | §2-S2 |
| 🟡 同族 | S3 | 并发 draft-execute 单槽搁浅（`pendingRerunRun` 单槽，B execute 覆盖 A） | 前端状态 | 按 draftId 键控 pending 集合（无数据丢失，reload 可 rehydrate） | 否 | §2-S3 |
| 🟡 同族 | S4 | forest refetch 卸载整树 → loading 闪烁 + rail 每 30s 重拉 `/runs` | 前端 | stale-while-revalidate（refetch 保留旧 forest） | 否 | §2-S4 |
| 🟡 同族 | S5 | `handleRerun`（顶栏 context rerun）focus 4s 残留 | 前端 | 复用 draft 的 usePendingRun 思路（无 draft 中心） | 否（低优） | §2-S5 |
| 🟡 同族 | S6 | `WorkbenchRouteContainer` Escape/modal 预存 flake（观测 1/10） | 测试 flake | 查独立根因（与 useCapabilities flake 无关） | 否 | §2-S6 |
| 🔵 拍板 | U1 | drawer 元信息裸机器串（`runId·64hex·owner_resolution` 枚举） | UX 拍板 | 人类可读文案 + tooltip/copy 保机器串；连同 v1.6.2 验收意图改 | 否 | §2-U1 |
| 🔵 拍板 | U2 | role 缩写 `X` 二义（`focal` 与 `explanatory_unspecified` 都显示 X） | UX 拍板 | 新呈现方案（淡色/斜体 X），仅 tooltip 可区分现状 | 否 | §2-U2 |
| 🔵 指针 | R1 | Variables 面板规模化（搜索 / 虚拟列表 / role tabs） | 前端规模化 | 规模化时再动 | 否 | handoff §5.3 |
| 🔵 指针 | R2 | Browse 产品边界 / workspace root / 项目注册表 | 产品 | 见 §4 范围外 | 否 | handoff §5.1 |
| 🔵 指针 | R3 | schema-driven `modelParams()` | 前端 | 用 schema 驱动替手写 | 否 | handoff §5.2 |
| 🟠 架构 | A-D2 | GLM 6 家族（ols/logit/probit/poisson/negbin/glm）该收敛成策略+注册表 | 架构 | `GLM_FAMILIES` 注册表；DID 家族维持异构；golden 23 护栏钉数值 | 否 | arch:D2 |
| 🟠 架构 | A-D6 | 无 OpenAPI codegen，api.ts 44 手写 type 迟早漂移 | 架构 | `openapi-typescript` 从 `/openapi.json` 生成 | 否 | arch:D6 |
| 🟠 架构 | A-D4 | 全局 CSS 1053 行（低，churn>收益） | 架构 | 不专门立项；新组件用 CSS Modules 渐进 | 否 | arch:D4 |
| 🟠 复盘 | A-D5 | lineage 复查（**非债**，每版一次"抽象是否挣钱"复盘） | 复盘 | 用户拍板；与 roadmap 北极星一致（有意复杂度投资） | 否 | arch:D5 |
| 🔵 AI | V7 | 超大数据集 Ask AI 策略:profile 摘要已防爆(不随行数涨),但宽表/用户想深入时不够（反馈批3） | 设计 | ①列分块/top-K 列(按缺失率·方差·与y相关)②抽样预览(head+分层随机,标"样本")③v1.7 工具式 drill-down:AI 按需向后端取单列直方图/分位数,上下文只装摘要 | 否 | — |
| 🟢 主线 | V11 | 图内数据层（✅ v1.7 第一典型切片完成）:`data.column.cast`/`data.columns.cast` 已落(typed preview/confirm/immutable child/幂等/failpoint/浏览器验收);cleaning 策略/异常值规则等更多 data operation 未做 | 主线=v1.8+ | 沿 data.column.cast 模式扩 operation 面 | 否 | roadmap |
| ~~🟢 方向~~ | ~~G1~~ | ~~图爆炸~~ **✅ v1.7.2**:batch `data.columns.cast`(N 列→1 record/1 child/1 recipe/1 diff)+ **投影层折叠**(`foldNodeClusters` 把 >3 个同源 data-cast 兄弟折成 "Data operations (N)" 卡,durable graph 一字不改) | — | — | — | — |
| ~~🟢 方向~~ | ~~G2~~ | ~~AI 解读图表~~ **✅ v1.7.2**:figure→chart_type+数值源 context/`/figures/ai-context`/chat figure mode/图库按钮、报告图表 marker 和导出；多模态真·看图仍是 provider-gated 可选方向 | — | — | — | — |
| ~~🟢 方向~~ | ~~G3~~ | ~~terminal 面板~~ **✅ 全闭(2026-07-16)**:输入框去重 + 沙箱 runner(8 条安全测试真验)+ **`code.execute` typed operation 全链路**(preview=沙箱真跑进一次性 temp 目录、项目零写入;execute 二次跑并**校验结果与 preview 逐字节一致**,不确定代码→拒写;同 key 幂等重放)+ registry(`risk_level=high`)+ orchestrator + routes(sandbox 缺失→503 fail-closed)+ UI section + 真机验收(四条边界对真实项目实测)+ **terminal 外观**(sandboxed stdout 进 AgentPanel;诚实:是跑完的捕获输出**不是实时流**,真流式要 SSE) | v1.7 | 已完成 | 否 | roadmap G3 |
| ~~🟢 主线~~ | ~~优先级 6~~ | ~~NL Agent 生成同一份 typed proposal~~ **✅ 真机闭环(2026-07-16)**:只开 `data.columns.cast`(**`code.execute` 保持 NL 关闭**)。模型只出意图,后端绑 `artifact_id`+preview fingerprint;新增只读 `inspect_data_schema`。有单独真机 smoke 记录，但不作为本版 gate 或系统级 E2E 承诺。**真机抓到 4 个确定性测试盖不住的 bug**(contract 不可读 / `casts` 被声明成 string / oneOf 与父级 AND 导致顶层强制 model.rerun 形状 / confirm 端点算错 fingerprint 身份) | v1.7 | 已完成 | 否 | roadmap 优先级 6 |
| ~~🟡 债~~ | ~~P6-1~~ | ~~失败只回 `invalid_tool_arguments`,不带校验详情~~ **✅ 已修(2026-07-16)**:`tools.py` 新增 `validation_details()`,`ToolResult.error_details` 进 tool payload(仅失败时出现,成功 payload 形状不变;`error` 码保持稳定)。**`oneOf` 用 `const` 判别式选分支,不用 `best_match`**——best_match 无判别式概念,曾把 model.rerun 的 `'node_hash' is a required property` 当成 cast 提议的建议:**给错建议比不给更糟**。plain schema 则保留全部顶层错误(一次说完,不要每轮只挤一条)。有界(5 条 / 240 字符,消息里嵌的是调用方自己的参数) | v1.7 | 已完成 | 否 | 本轮 |
| 🟡 债 | P-CE1 | `code.execute` 一次 confirm 用户代码跑 **5 遍**(route freshness + lifecycle prepare/execute preview + apply 确定性 run)。正确但昂贵,每遍 30s wall clock。**减到 2 遍**=把已算 preview 带 execution key 缓存、confirm 复用——但那 4 遍分散在 failpoint 崩溃恢复里(恢复进程不能信任已死进程传入的 preview),减少=重写崩溃恢复契约,高风险须单独立项 | v1.7+ | 缓存 preview 结果 by execution key;prepare/execute/apply 复用而非重跑;崩溃恢复时才重算 | 否 | 本轮实测 |
| ~~🟡 债~~ | ~~P-RISK1~~ | ~~`risk_level`(含 code.execute 的 `"high"`)曾是**纯装饰**~~ **✅ 已修(2026-07-17)**:高风险操作现在要求后端风险授权，授权绑定 proposal、fingerprint、active head、execution key，并一次性消费 | v1.7.1 | 已完成 | 否 | 独立 review；`tests/test_risk_policy.py` |
| ~~🟡 债~~ | ~~P-SBX1~~ | ~~B1 新增的 `tests/test_code_execute_recovery.py` 需要与兄弟沙箱测试一致的无后端 skip 守卫~~ **✅ 已清(2026-07-17)**:已补 `pytestmark = pytest.mark.skipif(isolation_backend() is None, ...)`；生产路径继续 fail-closed | v1.7.1 | 已完成 | 否 | 独立 review 实测 |
| 🟡 债 | P-SBX2 | `isolation_backend()` 只探测二进制存在，不验证后端是否真的可执行；受限工作区会把 exec 拒绝误报为可用，导致沙箱测试红或诱发错误的静默 skip | v1.7+ | 增加仅供测试使用、模块级缓存的 `sandbox_selftest()`；无后端可合法 skip，后端存在但不可用必须以醒目原因失败/可见 | 否 | 独立 review 实测；不得把不可用后端静默 skip |
| ~~🟡 债~~ | ~~N-COV~~ | ~~B2 翻转了 pin 路径的 fallback 测试后，默认路径“store 存在但 active provider 未配全仍回退环境”的行为需要单独钉住~~ **✅ 已清(2026-07-17)**:默认路径 fallback 已由 `test_default_path_falls_back_when_active_provider_is_unconfigured` 固定；pin 语义不变 | v1.7.1 | 已完成 | 否 | N-COV 独立验证 |
| 🟢 更远 | M2 | 画布拖放建链 | v1.7+ | 独立版本，不与图内操作混排 | — | §4 |
| 🟢 更远 | M3 | batch run (`y_list`) 图内化 | v1.7+ | 创世向导 v1 只做单 run | — | §4 |
| 🟢 更远 | M4 | 后端项目注册表 / 项目级设置页 | v1.7+ | Launcher 最近项目仍走前端 localStorage | — | §4 |
| 🟢 更远 | M5 | roadmap §3.5 的 W·C·A + Agent Harness | v1.7 | — | — | roadmap |
| 🟢 穿插 | M6 | 统计方法线未建大类:**机器学习**(RF/XGBoost/CV 框架/SHAP)·**降维聚类**(PCA/K-means/层次)·**高级时序**(VAR/VECM/协整/GARCH)·**生存分析**(KM/Cox PH/log-rank)。⚠️ 统计方法 roadmap §12 版本表是 2026-05-13 旧草稿(写"V1.7=DID"但 DID v1.5.x 已全 ship),版本号作废勿照排 | 统计方法(独立穿插线,低风险不阻塞) | 沿用 DID 模式:自实现+R oracle 验证+golden;每类单独排版本,与主线穿插 | 否 | roadmap §13 |

> **已清（v1.6.11，做完即删，git 历史留痕）**：🔵 **U3**（covariance 默认值硬耦合）
> — 后端 `COVARIANCE_UI` robust 标 `default:True` + `_COVARIANCE_DEFAULT` 单源驱动 param value;
> 合约放行 `default:boolean`;前端 `covarianceDefault()` 读 flag（`[0]` 仅防御兜底）。commit `2a3eca5`。
> 随 v1.6.11 切片 B 折入（图内对比必碰 capabilities 展示契约）。
>
> **已清（v1.6.10，做完即删，git 历史留痕）**：🔴 **P1**（auto-mode draft 不可编辑）
> — `_validate_params` 跳过未变的继承参数（②根因修复,`6739f56`+`f56…`）,store 3 TDD + 端点
> 回归测试 + **真机 uvicorn smoke 复现**（covariance-only PATCH→200、model_type→bogus→422）;
> **A-D1**（api.py 万能垃圾桶）— 2206→32 facade,五层拆分（Phase1-4）。
> **v1.6.10.1**:**N1** — draft 执行编排下沉 `services/draft_service.py`,`drafts_routes` 819→485;
> **所有拆分文件 <500,D1 彻底收口**。
>
> **已清（v1.6.9）**：D3 CLI 补参数（`a914309`+`4d7759e`；架构债台账 v1.6.10 已同步标清）、
> `POST /runs`·`/runs/batch` 校验对称
> （`0c7a4c1`）、useCapabilities flake（`b95369f`）、429 flake 根因（`edd4f8d`）、dead RunHistory
> （`23719ba`）、REV-3 classifyError（`9c7f74d`+`820eb82`+`fc4ef0c`）、rerun-child 长 run 窗口期
> （`8ef74f0`+`06f36bb`+`23a3c2a`）、RUNS rail 及时刷新（`0eada74`）、WorkbenchRouteContainer 拆分
> （`25bc798`+`06619f7`，987→859）、裸 `global.fetch=` 卫生（`fe65cad`）、`did_mode` 值核查（全对）。

---

> **已清（v1.6.12,做完即删,git 历史留痕）**：🔵 **V1**(A3 逐 artifact Explain,`3b826d9`)、
> **V2**(A4 LLM 多供应商设置面板+Home 状态卡)、**V3**(typed `aiActivityLog`+底部 AI activity 面板,
> v1.7 diff 留痕契约打底,`dbdb0f2`)、**V5**(零依赖 markdown 渲染器,AskAI+Report 共用)、
> **V6**(per-node AskAI History)、**V8**(画布 Reset 键,`7d99d41`)、**V9**(折叠框,销案非 bug)、
> **V10**(Workbench Home 视图,`/?home=1` 兼容别名)、**V4**(legacy `/graph` 挂住,v1.6.12 closeout 修复)。
> 🟢 **M1**(图内对比/节点 AskAI/引用报告)已 SHIPPED v1.6.11;🟠 **A-D1**/🔵 **U3** 见上方各版已清块。

## 2. 本文件债务详情（按 ID）

### §2-N2 · 预存 slot-leak 测试污染 race（v1.6.10 发现,非回归）

`test_run_inputs_persisted` POST /runs 后**不轮询等待完成**就结束——后台 `_bg_run` 线程可能仍
持有 `EventManager` 单例 slot。若其后紧跟另一个 POST /runs 的测试（如 `test_graph_editable_
annotation`），第二个 POST 撞 429 → `.json()["run_id"]` KeyError。**pytest 字母序采集下
`test_graph_...`(g) 排在 `test_run_...`(r) 之前,不触发,故 full gate 一直绿**;仅在手动反序运行时
暴露。预存债（EventManager 单例本就如此,v1.6.10 D1 未改其逻辑,仅在验证时发现）。修法=测试收尾
join/await run,或按测试隔离 slot。

### §2-W1 · draft-execute dedupe 响应形状不对称

deduped 响应的 `produced_lineage` 与 fresh execute 不完全同形。本轮忠实保留 from-node 既有行为，未顺手改协议。

### §2-W2 · 全量孤儿 upload/draft GC

本版只做 discard 创世链时回收无引用 upload；项目级后台 GC 仍需单独设计。

### §2-S1 · genesis 全流程 / Playwright smoke 层未建

v1.6.9 已给 draft-execute 补了全 UI 驱动的 fake-timer 测试（成功/失败/长 run 三分支，`WorkbenchRouteContainer.test.tsx` "draft execute — index-wait" describe）；genesis wizard 全流程驱动仍只有单测层，Playwright smoke 层仍未建（见 archived handoff §5.5）。

### §2-S2 · 全模型族 FE 真机执行 smoke（含估计方程渲染）

v1.6.9 已用真数据跑过 CLI 路径的 `did`（two_by_two，ATT≈1.55）与 `iv_2sls`（≈1.49），销掉 CLI 半边；**剩 FE 半边**：`panel_ols`/`cs_did`/`sa_did`/`dcdh`/prediction 的「Genesis 全流程执行 + drawer 估计方程渲染」仍没有用真数据肉眼确认（`EstimatedEquationSection` 家族特判有单测钉住，端到端没跑）。= archived handoff §6.2 剩余部分。

### §2-S3 · 并发 draft-execute 单槽搁浅

`pendingRerunRun` 是单槽状态（沿袭 genesis 单例形状）。draft A execute 进入 index-wait（分钟级）期间 `draftBusy` 已复位，再 execute draft B 会覆盖 A 的 pending + focus ref → A 永久卡 "executing"（不移除、不聚焦、后端 draft 不删；无数据丢失，reload 可 rehydrate 后手动 discard）。修法=按 draftId 键控的 pending 集合。Task 7 评审确认，Important 但不阻塞。

### §2-S4 · forest refetch 卸载整个 shell 子树（loading 闪烁）

`useForestData.refetch()` 会 `setLoading(true)+setForest(null)`，容器 `if (loading||...) return <Loading/>` → 每次 30s 轮询/pending 轮询都整树 unmount+remount（rail 每次重挂重拉 `/runs`）。这掩盖了 rail 延迟、也是闪烁与浪费；修法=refetch 保留旧 forest（stale-while-revalidate）。Task 9 实现与评审双方独立确认。

### §2-S5 · `handleRerun`（顶栏 context rerun）focus 4s 残留

超长 run 下 `pendingFocusTarget` 20×200ms 耗尽后聚焦不落（无 draft 消失、无错数）。与 draft-execute 不同源（无 draft 中心可复用 usePendingRun），spec §7 已记，低优先。

### §2-S6 · `WorkbenchRouteContainer` Escape/modal 预存 flake

全量 vitest 偶发（观测 1/10）`S1: Escape with modal open closes only the modal` 红。与 useCapabilities flake 无关，独立根因未查。

### §2-U1 · drawer 元信息行裸机器串（需拍板）

DetailHeader 渲染 `{runId} · {nodeKey}`（森林下 nodeKey 是 64-hex hash，截成 `·…`）和裸 `owner_resolution` 枚举（`active_head_contains_node`）。这是 v1.6.2 NodeOperationContext 有意的调试可见性，有测试钉住；改法应是人类可读文案 + tooltip/copy 保留机器串，需要连同 v1.6.2 验收意图一起改。

### §2-U2 · role 缩写 `X` 二义（需拍板）

`focal` 和 `explanatory_unspecified` 现在都显示 `X`（v1.6.8 把 `X?` 改掉响应"看不出变量名"的抱怨），仅 tooltip 可区分。如果 unspecified 的视觉信号还重要，需要新的呈现方案（如淡色/斜体 X）。

---

## 3. 已清留痕（做完即删的历史，防重复排查）

> 保留一版可查阅，下次收尾整份冻结进 `archive/` 时一并带走。

- **v1.6.9 前置清债**：见 §1 表末「已清」块。
- **v1.6.9 收尾卫生**：①6 个测试文件裸 `global.fetch=` 无恢复 → 统一 `vi.stubGlobal` + 只还原 fetch（`fe65cad`；注意 `vi.unstubAllGlobals()` 会连带清掉 setup 里一次性装的 ResizeObserver，故只还原 fetch）。②`did_mode` 值拼写核查 → UI 全对（DID `cohort/two_by_two/status`、CS `never/not_yet` 均正确），无需改；仅内部 `EstimatedEquationSection` 有个 `modelType.includes("twfe")` 的 OR 死分支（无 model_type 含 "twfe"，不给用户看、有家族测试钉着，不值得碰）。
- **REV-3**（v1.5.0 滚入）已于 v1.6.9 清（`9c7f74d` + forest 路径去重 `820eb82` + Safari "Load failed" `fc4ef0c`）——更早版本滚入的债至此全部清空。

---

## 4. v1.6.8/v1.6.9 明确范围外（对应 §1 表的 M2–M5 / R2）

- **画布拖放建链**（M2）：数据模型已支持无父创世链，但当前宿主是右侧向导，不做拖放 builder。
- **Submit 表单代码删除**：只摘除主导航和 Launcher 入口；`/submit` 保留给 Command Palette「快速 run（旧表单）」和 batch 兜底。
- **batch run (`y_list`) 图内化**（M3）：创世向导 v1 只做单 run。
- **后端项目注册表 / 项目级设置页**（M4，R2）：Launcher 最近项目仍走前端 localStorage；项目根仍是文件系统路径。
- **图内任选对比 / 节点 Ask AI / 引用报告**（M1）：已 SHIPPED v1.6.11。

---

## 5. 从更早版本滚入、仍未解决的债

> 整理 followups 时（2026-07-08）逐份核销：只有 v1.5.0 的 REV-3 曾滚入本 live backlog，
> **已于 v1.6.9 清掉**（见 §3）。更早版本滚入的债至此全部清空；其余更早 followups 已冻结进 `archive/`。
