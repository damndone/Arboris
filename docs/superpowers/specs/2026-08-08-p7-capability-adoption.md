# P7 的 29 个统计能力如何接入 CapabilityContract

- 日期：2026-08-08
- 状态：设计说明，**不含实现**（实现要等 P7 merge 进主线）
- 相关：`docs/superpowers/plans/2026-08-07-v1.8.8-p1-capability-contract.md`（P1 Task 5）、
  `docs/superpowers/plans/2026-08-07-v1.8.8-p0-composition-seam.md`
- 被说明的代码：`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.8-p7-multivariate`

---

## 0. 先说结论：这份文档要拦住的三件事

1. 按 `*_OPERATION_IDS` 命名约定枚举，会**静默漏掉 power_analysis 整个包**。
   「29」这个数字本身就是这个漏洞的产物 —— 见 §4。
2. P7 的 8 个包**内核形状不统一**。「都是 `fit_x(frame, columns, *, ...)`、
   都消费输入帧」这个前提对其中 4 个包不成立 —— 见 §3。
3. 接入 `proposed_by` 时不要复制 `model.genesis` 的现状：清单目前把
   `model.genesis` 记成一条 `proposed_by` 路径，而 `model.genesis` 的
   `natural_language_enabled` 是 `False` —— 见 §2.3。这是一条**已经存在的
   高估**，29 个新能力如果照抄，就会把它放大 29 倍。

---

## 1. 29 个能力从哪来：`capability_id` / `kind` / `summary`

### 1.1 清单（按 pack）

契约模块里的 `*_OPERATION_IDS` frozenset 就是能力 id 的来源，
文件在 `backend/workbench/contracts/model/`：

| pack | 契约模块 | operation ids | 数量 |
|---|---|---|---|
| multivariate | `multivariate.py` | `multivariate.pca` / `.efa` / `.cronbach_alpha` / `.clustering` / `.discriminant` / `.correspondence` / `.mca` / `.manova` | 8 |
| time series | `time_series_pack.py` | `time_series.acf` / `.pacf` / `.adf` / `.kpss` / `.arima` / `.var` / `.granger` / `.irf` / `.cointegration` / `.vecm` | 10 |
| survival | `survival_analysis.py` | `survival.kaplan_meier` / `.log_rank` / `.rmst` | 3 |
| repeated measures | `repeated_measures_anova.py` | `repeated_measures_anova.repeated_only` / `.mixed_design` | 2 |
| roc | `roc_diagnostics.py` | `roc.curve` / `roc.calibration` | 2 |
| categorical | `categorical.py` | `categorical.cramers_v` / `categorical.mcnemar` | 2 |
| meta | `meta_analysis.py` | `meta.effect_size` / `meta.combine` | 2 |
| **power analysis** | `power_analysis.py` | **没有 frozenset** | **0** |
| 合计 |  |  | **29** |

**注意 SARIMA 不在里面**：它是 `fit_arima(..., seasonal_order=...)` 的一个参数，
不是独立 operation id。同理 `multivariate` 把 8 个 id 拆成
`MULTIVARIATE_OPERATION_IDS`（3 个）和 `MULTIVARIATE_EXTENSION_OPERATION_IDS`（5 个）
两个 frozenset，并集叫 `MULTIVARIATE_ALL_OPERATION_IDS`。**枚举必须取并集**，
只读第一个会漏掉 clustering/discriminant/correspondence/mca/manova 五条。
这是与 §4 同一形态的坑：一个包内部的第二个 frozenset。

### 1.2 `capability_id`

直接用 operation id 原文，**不加前缀**。理由与 `_operation_capabilities()`
一致：这些 id 本身就带 pack 前缀（`multivariate.pca`、`time_series.acf`），
再包一层会让「调用方要发的线上值」无法从 capability_id 还原 ——
`_prediction_capabilities()` 的注释已经把这条规矩写下来了。

### 1.3 `kind`

`CAPABILITY_KINDS` 里预留的 `"pack"` 至今无人使用，正是留给它们的。
**建议：29 条全部用 `"pack"`，不细分。**

理由是 kind 的判据不是「学科分类」而是「**这一类能力在到达用户的路径上有什么共同结构**」。
现有 kind 全都是这么划的：

- `model_family` = 走 `model_type` 字段
- `prediction_model` = 走 `prediction_model_type` 字段、由 diagnostics 阶段派发
- `data_preparation` = run config 上的具名方法、改帧不产结果
- `data_operation` = 注册在 `OperationRegistry` 的条目

29 条共享的结构是：**注册为独立 operation、消费某种输入、产出一个版本化的
result envelope、不产出数据集、不进 `model_types`**。这一条结构对 8 个包一致，
所以是一个 kind。按学科拆成 `multivariate` / `time_series` / `survival` …
会造出 8 个 kind 却没有任何守卫能对它们提出不同的问题 —— 那是分类学，不是契约。

**唯一的例外候选是 power_analysis**（§4）：它不消费任何数据，
共享结构在它身上断掉了。如果它最终以「不吃数据的求解器」形态接入，
它需要一个自己的 kind，而不是硬塞进 `"pack"`。

### 1.4 `summary`

**这是最容易出事的一格，因为 P7 现在没有任何地方写着人类可读的描述。**

`build_capabilities()` 对 model_types 有 `description`，对 prediction_models 有
`description`，对 sampling_methods 只有 `label`（`_data_preparation_capabilities()`
已经因此写了「No description is registered for it」的兜底）。P7 的契约模块
**一个 description 字段都没有** —— 只有 frozenset 和 dataclass。

三条路，按优先级：

1. **（推荐）P7 在契约模块里补一个 `*_OPERATION_SUMMARIES` mapping**，
   与 `*_OPERATION_IDS` 同址同生命周期，加 id 时必须同时加描述。
   契约模块的 `__post_init__` 风格已经在做这种「结构性强制」。
2. 从 `fit_x` 的 docstring 首行取。**不推荐**：docstring 是给读代码的人写的
   （`"""Compute bounded Kaplan--Meier curves, with optional declared RMST."""`
   已经不错，但 `"""Fit correspondence analysis to an explicit non-negative table."""`
   对 planner 没有信息量），而且 docstring 可以被删而不触发任何测试。
3. 在 `capability_contract.py` 里手写一张表。**明确反对**：那正是
   「第二个要记住的地方，也是被忘掉的那个」，`capability_inventory()` 的
   docstring 已经把这条写成了模块的立身之本。

无论走哪条，`CapabilityContract.__post_init__` 的非空校验都拦不住
「拿 id 回显顶上」（Task 1 的实现者已经发现过这个洞，
`test_no_summary_is_the_capability_name_echoed_back` 是补丁）。29 条接入时，
那条测试的覆盖面要跟着扩到新 kind 上，否则
`summary="multivariate.pca"` 会一路绿灯。

---

## 2. `proposed_by`：新 operation 还是复用承载者

### 2.1 两种形态各自的代价

| | **A. 一 id 一 operation**（29 个 operation） | **B. 一个承载者**（如 `pack.execute`，operation_id 作为参数） |
|---|---|---|
| 注册成本 | 29 份 `OperationDefinition` + 29 份 proposal schema | 1 份 |
| Agent 提案 schema | 29 个 oneOf 分支（见 `operations.py:494` 的 union） | 1 个分支 + 一个 29 值的 enum |
| 参数校验 | 每个 operation 自己的封闭 schema，错参在 schema 层被拒 | 参数集是 29 个的并集，schema 只能松到「任意 object」，错参要等运行期 |
| 提示词体积 | `_step_vocabulary_lines()` 逐条渲染，+29 段 | +1 段 + 一行 enum |
| 「哪些能力可达」可否被守卫求值 | 逐条可查 | **只能查到承载者可达，查不到 29 条** |
| 前例 | `statistical.derive_numeric` 等 | `model.genesis`（23 个模型族） |

最后一行是决定性的：**形态 B 正是 v1.8.7 漏掉整个 data_operation 族的机制**。
`capability_contract.py` 的模块 docstring 第一句就写着这件事 ——
「`model.genesis` 是一个承载 23 个模型族的 operation，所以写在 operation 层面的
守卫在第 24 个族够不着时仍然是绿的」。

**判断：走 A，但不是 29 个顶层 operation —— 是 29 个 workflow step。**

理由见 §3：这些能力全都不产出数据集、只产出结果，天然是 plan 里的一步而不是
一次独立的图操作。注册 29 份 `WorkflowStepSpecContract` 之后：

- `composable_as` 逐条成立（`operation.multi_step` 内可指名）
- `proposed_by` 逐条为空 —— 而这**不是缺口**，见 §2.3
- `STEP_CONSUMES_INPUT_FRAME` / `STEP_PRODUCES_DATASET` 是从
  `WORKFLOW_STEP_SPEC_CONTRACTS` 派生的（`workflow_contracts.py:1852-1865`），
  所以不需要第二处编辑

如果 29 份契约的样板文件太重，可以写一个 `pack_step_contract(operation_id, ...)`
工厂来生成它们 —— 那仍然是形态 A：**每条能力有自己的注册条目**，
只是构造它的代码被复用了。这与形态 B 的差别不在代码量，在于
「守卫能不能逐条点名」。

### 2.2 顺带修掉一个 P0 已经踩过的形状

`operations.py:594` 会把 `WorkflowStepSpecContract` 反向注册成
`OperationDefinition`。所以注册 29 个 step **会**让它们出现在
`OperationRegistry()` 里 —— 也就是说 `_operation_capabilities()` 会
**自动**把它们当成 `data_operation` 收进清单，`kind` 是错的，
而且会和 §1.3 的 `"pack"` 条目重复，撞上
`test_the_inventory_has_no_duplicate_capability_ids`。

**接入前必须先决定 `_operation_capabilities()` 怎样把 pack step 排除出去
（或者反过来：让它成为 pack 条目的唯一来源）。** 这不是可以留到最后收拾的细节，
它决定 §1 那张表要不要存在。

### 2.3 ⚠️ 一条已经存在的高估：`proposed_by` 现在是可以说谎的

`_operation_capabilities()` 给每个注册 operation 无条件写上
`proposed_by=(operation_id,)`，`_model_capabilities()` 给每个可选模型族写上
`proposed_by=("model.genesis",)`。但注册表里的实情是：

```
code.execute                        natural_language_enabled=False
data.column.cast                    False
data.columns.cast                   True
graph.fork                          True
model.custom                        False
model.genesis                       False   ← 22 个模型族的 proposed_by 指向它
model.joint_f_test                  False
model.quadratic_stationary_point    False
model.rerun                         True
model.white_test                    False
operation.multi_step                True
report.compose                      False
statistical.derive_boolean          False
statistical.derive_numeric          False
statistical.derived_group_summarize False
statistical.explore                 False
```

16 个注册 operation 里只有 **4 个**对自然语言开放。
`natural_language_operation_ids()`（`operations.py:417`）按
`natural_language_enabled` 过滤，Agent 提案 schema 的 union
（`operations.py:500`）按同一个字段过滤，`context_tools.py:1369` 则明说
「这是 workflow step，不是顶层提案契约，去 inspect `operation.multi_step`」。

**也就是说：清单今天记录的 `proposed_by` 里有相当一部分是拿不到的路径。**
这与 v1.8.7 犯的错是同一形态（记下的不是消费者读的那份），只是层级更深一层。
**这不在 P1 Task 4 的范围内**（Task 4 只做「不可达」的分区，
且明令只观察不改变），但它会直接决定 P2 的守卫是绿是红，
**应该在 P2 动手之前先解决**：要么 `proposed_by` 只收
`natural_language_enabled=True` 的 operation，要么把这个字段改名成
它实际表达的意思（「注册了哪个 operation」而不是「自然语言能提哪个」）。

29 个新能力接入时**不要**照抄现状。它们的正确形态是
`proposed_by=()`、`composable_as=(operation_id,)`，
外加**在 `reachability_exempt_reason` 里写明「pack step 不作为顶层提案暴露，
经 operation.multi_step 组合」** —— 这样它们落在 Task 4 分区的 `exempt` 一侧，
而不是 `gaps` 一侧。见 §5。

---

## 3. `composable_as`：核实「都消费输入帧、都不产出数据集」

### 3.1 「不产出数据集」：成立，8 个包一致

8 个契约模块全部产出一个版本化 result envelope
（`multivariate.result` / `time_series.pack.result` / `survival_analysis.result` /
`repeated_measures_anova.result` / `roc_diagnostics.result` /
`categorical_count.result` / `meta_analysis.result` / `power_analysis.result`），
没有一个写数据集子节点。

对 P0 的两个集合，含义是：

- `produces_dataset=False` → 它们**不进** `STEP_PRODUCES_DATASET`
  → `source.from_step` **不可以指名它们**。
  `workflow_contracts.py:2284` 会拒掉，错误里会列出合法的生产者。
- `replayable_by_recipe` 同理为 `False`。注意
  `workflow_contracts.py:1867` 的注释已经预言了「`STEP_REPLAYABLE_BY_RECIPE`
  今天等于 `STEP_PRODUCES_DATASET`，写成两个就是为了它们迟早分家」——
  29 个 pack step 不会让它们分家（两边都是 False），P3 的 reshape/subset 才会。

### 3.2 「都消费输入帧」：**不成立**。这是本文档最要紧的一条更正

P1 计划里写的「内核形状 `fit_x(frame: pd.DataFrame, columns, *, 封闭 Literal 参数)`」
只对一部分包成立。逐个核实的结果：

| 包 | 内核签名首参 | 消费 step_frame？ |
|---|---|---|
| multivariate（pca/efa/clustering/discriminant/manova） | `frame: pd.DataFrame, columns: Sequence[str], *` | ✅ 是 |
| multivariate（**correspondence / mca**） | `table: pd.DataFrame, *, n_dimensions` | ⚠️ 是帧，但要求**列联表**，不是原始观测帧 |
| time_series（全部 10 条） | `frame: pd.DataFrame, *, time_column, value_column, ...` | ✅ 是（**没有 `columns` 位置参**，列角色是具名的） |
| survival（全部 3 条） | `frame: pd.DataFrame, *, duration_column, event_column, ...` | ✅ 是（同上，具名列角色） |
| repeated_measures | `frame: pd.DataFrame, *, operation_id, response_column, ...` | ✅ 是 |
| **roc** | `run_roc_curve(y_true, scores, *, ...)` | ❌ **两个序列，不是帧** |
| **categorical** | `fit_cramers_v(table, *, correction)` | ❌ **计数表，不是观测帧** |
| **meta** | `combine_effects(studies: Any, *, ...)` | ❌ **一串 study 记录，不是帧** |
| **power_analysis** | `solve_power(*, design, solve_for, alpha, power, ...)` | ❌ **完全不吃数据** |

**结论**：29 条里可以直接标 `consumes_input_frame=True` 的是
multivariate 8 + time_series 10 + survival 3 + repeated_measures 2 = **23 条**；
剩下 6 条（roc 2 + categorical 2 + meta 2）需要在 step 契约里补一层
「从 step_frame 取出内核要的形状」的适配（`y_true`/`scores` 两列、
交叉表、study 表），power_analysis 0 条则**根本不该有 `source`**。

这一层适配不是可选的。`STEP_CONSUMES_INPUT_FRAME` 的注释写得很直白：
不在这个集合里的 step「自己解析数据，所以一个 `source` 会通过校验、
被解析、然后被静默丢掉」。如果给 roc/categorical/meta 标了
`consumes_input_frame=True` 却没写适配，就是同一个失败：
`source` 生效了，帧到了，内核签名对不上 —— 好一点是 TypeError，
坏一点是 `Any` 类型的首参把 DataFrame 当 `studies` 吞下去。
`combine_effects(studies: Any = None, ...)` 的类型标注恰好是坏的那种。

**建议**：先接 23 条帧原生的，6 条适配型和 power_analysis 分期。
见 §5。

---

## 4. ⚠️ 已知的坑：power_analysis 没有 `*_OPERATION_IDS`

`backend/workbench/contracts/model/power_analysis.py` 有
`POWER_ANALYSIS_CONTRACT = "power_analysis.result"`、
`POWER_ANALYSIS_CONTRACT_VERSION`、`POWER_ANALYSIS_DESIGNS`、
`POWER_ANALYSIS_SOLVE_TARGETS`、`POWER_ANALYSIS_STATUSES`、
`POWER_ANALYSIS_REASON_CODES` —— 该有的都有，
**唯独没有 `POWER_ANALYSIS_OPERATION_IDS`**。另外 7 个包都有。

### 4.1 它不是笔误，是形状不同

`solve_power()` 的签名里没有 operation_id，也没有数据：

```python
def solve_power(*, design, solve_for, effect_size_type, alpha=None, power=None,
                sample_size=None, effect_size=None, ratio=None, alternative=None,
                k_groups=None, sensitivity_grid=None) -> dict
```

能力空间是 `POWER_ANALYSIS_DESIGNS`（3）× `POWER_ANALYSIS_SOLVE_TARGETS`（4）
的组合，再加一个 `solve_power_grid` 变体。**没有一层 id 可以枚举**，
所以「补一个 frozenset」这句话本身要先决定：补的是
`{"power.solve", "power.grid"}`（2 条，design/solve_for 降为参数），
还是 12 条组合 id。前者与其他 7 个包的粒度一致，
后者才让「用户能不能求样本量」成为可被守卫单独求值的命题。

**建议前者（2 条 id）**，理由与 §1.3 一致：`solve_for` 是封闭 Literal，
在 step 契约的 schema 里就能穷举，不需要升级成 id。

### 4.2 真正的教训：**枚举方式不能依赖命名约定**

**「29」这个数字就是漏掉的证据。** 8 个包里 7 个有 frozenset、
一个没有，按约定枚举得到 29，而 power_analysis 的求解器代码
（`backend/workbench/engine/packs/power_analysis/solver.py`，400 行）
一行都不在这 29 里。没有任何东西会报错 —— 少一条能力就是少一条，
清单照样绿。

这与本仓库反复出事的形态**一模一样**：v1.6.5 的 `.gitignore` 尾斜杠
（`node_modules/` 只匹配目录、漏掉符号链接），v1.8.7 的
「核对了模型族、漏了数据操作族」。共同点是**枚举的边界由一个约定隐式定义，
而约定的例外不会发出声音**。

**接入前必须二选一，`capability_inventory()` 才可以碰这 29 条：**

- **(a) 补齐约定，并让约定可强制**：每个包补 `*_OPERATION_IDS`，
  同时加一条元测试 ——「`contracts/model/` 下每个定义了 `*_CONTRACT`
  常量的模块，必须同时定义 `*_OPERATION_IDS`」。约定本身变成断言，
  第 9 个包漏了就红。
- **(b) 不靠命名**：`PackDeclaration`（`engine/packs/builtin_declarations.py`）
  已经是「集成方拥有的显式声明表」了，但今天只登记 model-type 包
  （linear_mixed_effects / arma_garch / ets / anova / v186 那批），
  8 个新包**一个都不在里面**。让 pack 在这张表里显式登记自己的能力 id，
  枚举就从「扫模块名」变成「读声明」。

**(b) 更符合这份清单的立身之本**（「派生自活的注册表，不是手抄」），
但代价是 P7 要改 8 个包的声明。**(a) 更便宜且足够**，
只要那条元测试真的存在 —— 没有元测试的 (a) 等于什么都没做。

无论选哪个，都要注意 §1.1 提到的 `MULTIVARIATE_EXTENSION_OPERATION_IDS`：
(a) 的元测试如果只查「存在 `*_OPERATION_IDS`」，
multivariate 的第二个 frozenset 照样漏 5 条。

---

## 5. 接入顺序与 P2 的关系

### 5.1 问题

P2 的守卫会断言「每条能力要么可达、要么有陈述的豁免理由」。P1 Task 4 做出的
`unreachable_capabilities()` 把不可达分成 `exempt`（有理由）和 `gaps`（无理由），
守卫应当**接受 exempt、在 gaps 上失败**。

今天的事实被 `test_todays_unreachable_capabilities_are_all_gaps` 钉死：
`exempt` 为空、`gaps` 15 条（8 检验族 + 3 预测模型 + 4 数据准备）。

如果 29 条能力在 P2 之后以 `proposed_by=()`、`composable_as=()`、
无豁免理由的形态接入，`gaps` 会从 15 涨到 44，守卫立刻红。

### 5.2 判断：**这不是「期望的红」，要分期**

「期望的红」是有意义的红 —— 它要么指着一个应该修的缺口，要么指着一次
需要更新的记录。29 条同时变红两个条件都不满足：

- 它们不是「没人接线的缺口」。它们是**还没轮到接线的新代码**，
  merge 当天就把它们记成 29 个缺口，是把「工作没做完」写成了「产品有窟窿」，
  跟给缺口编造豁免理由是同一类失真的两个方向。
- 一次 29 条的红没有可操作性。守卫失败信息里 29 个 id 排在一起，
  读的人做不出任何单条判断，最可能的结局是把守卫标成 xfail —— 那就等于
  P2 白做。

**建议顺序：**

1. **先解决 §2.3**（`proposed_by` 的高估）。这一步不涉及 P7，
   但它决定守卫在存量 54 条上是不是绿的。**在这之前上 P2 的守卫没有意义** ——
   一条建立在错误可达性上的绿线，正是 v1.8.7 交付的那种东西。
2. **P2 上守卫**，基线是修正后的存量清单。此时 `gaps` 是一个人读得完的数字，
   每一条都指着一个真缺口。
3. **P7 merge**，`capability_inventory()` **暂不收录**这 29 条（它们此时既没有
   operation 注册也没有 step 契约，本来就不在任何一个活注册表里，
   所以「不收录」是自动的，不需要写豁免）。
4. **分批接入，每批自带 exempt 或可达状态**，每批都是一次守卫从绿到绿的变更：
   - 批 1：§3.2 的 23 条帧原生能力，注册为 workflow step，
     `composable_as=(operation_id,)` → **可达**，不需要豁免。
   - 批 2：roc / categorical / meta 6 条，先写输入适配再注册。
     如果适配要押后，就带着**明写的豁免理由**接入
     （「内核消费的是两列序列 / 交叉表 / study 表，step_frame 适配未完成」）——
     这才是 `reachability_exempt_reason` 的正当用法：
     一个**做过的决定**，而不是一个被粉饰的窟窿。
   - 批 3：power_analysis，先解决 §4 的枚举问题和「不吃数据」的形态问题。

关键点：**每一批都在同一个 commit 里既加能力又给出它的可达性状态**。
29 条一次性落地、可达性留到下一步补，就是让守卫先红 29 条再慢慢变绿 ——
中间那段时间守卫是被无视的，而被无视的守卫和没有守卫是一回事。

### 5.3 附带的记录义务

批 1 落地时，`test_todays_unreachable_capabilities_are_all_gaps` 里钉死的
`len(gaps) == 15` 和 kind 集合**会变**（如果 §2.3 的修正先落地，
数字在第 1 步就已经变过一次）。那条测试的 docstring 已经写明这是设计意图：
**改动这份记录的那次提交，就是更新它的那次提交**。不要把它标成
flaky，也不要为了让它绿而少收录能力。

---

## 6. ⚠️ 必须提前警告：`workflow_step_vocabulary()` 有三个消费者

P0 Task 7 踩过这个坑，29 个能力会以 29 倍的规模再踩一次。

`workflow_step_vocabulary()`（`backend/workbench/agent/workflow_contracts.py:1773`）
返回一个 dict。它的消费者是三个，读法完全不同：

1. `backend/workbench/agent/operations.py:353` —— 传 `vocabulary_builder`，
   整份用。
2. `backend/workbench/agent/notebook/planning_agent.py:1871` ——
   `"step_vocabulary": workflow_step_vocabulary()`，整份塞进 context。
3. `backend/workbench/http/agent_routes.py:151` `_step_vocabulary_lines()` ——
   **逐键挑选**，手写渲染成 chain agent 读的协议文本。

第 3 个是坑。它只渲染 `step_operations`、`reported_percentiles`、`ordering`、
`source` 这几个键，而且 `source` 内部还是逐字段拼的
（`purpose` / `shape` / `outputs` / `produced_by` / `declarable_by` / `semantics`）。
函数里那行注释是 P0 留下的：

> `# The dict is not the prompt: only what is rendered here reaches the Agent.`

**往 dict 里加一个新顶层键，chain agent 一个字都看不到。** 测试断言 dict 的
内容会全绿，因为验证的不是消费者读的那份 —— 这正是 v1.8.7 记在
`MEMORY.md` 里的那句教训。

### 6.1 29 个能力会以两种方式撞上它

**(a) 新顶层键完全不可见。** pack step 很可能想发布一些结构化信息 ——
比如「哪些 step 是 pack、它们不产数据集所以不能被 `from_step` 指名」，
或者每个 pack 的封闭参数枚举。如果它以新顶层键的形式加进 dict，
chain agent 看不见。必须**同时**改 `_step_vocabulary_lines()`。

**(b) 已有键会撑爆提示词。** `step_operations` 这个键是被遍历渲染的，
所以 29 条**会**自动出现 —— 这一半是好事。但渲染的形状是

```
  - {operation_id} -> {summary} Required: {required}.
      {field}: {description}      ← 每个字段一行
```

时间序列一条就有 `time_column` / `value_column` / `time_order` / `nlags` /
`adjusted` …，29 条按现状估计会往每次 chain agent 调用的系统提示里
加进几百行。这不会有任何测试变红，只会让提示词变长、
让模型更容易在 29 个陌生 id 里挑错一个。

**建议**：在接批 1 之前，先给 `_step_vocabulary_lines()` 加一条测试 ——
断言**每一个** `WORKFLOW_STEP_SPEC_CONTRACTS` 里的 operation_id
都出现在渲染出的文本里，并且断言 `workflow_step_vocabulary()` 的
**顶层键集合**与渲染器处理的键集合一致（新键必须要么被渲染、
要么被显式列进「不渲染」名单）。这条测试对 P0 已有的 source 键也成立，
是把 P0 Task 7 的教训固化下来，而不是每次靠人记得。

---

## 7. 待办清单（接入前）

- [ ] §2.3：修正 `proposed_by` 的高估（或改名），**先于 P2 守卫**
- [ ] §2.2：决定 `_operation_capabilities()` 如何与 pack step 互不重复
- [ ] §4：补齐 `POWER_ANALYSIS_OPERATION_IDS` + 元测试，或改用显式声明表
- [ ] §1.1：确认枚举取到 `MULTIVARIATE_ALL_OPERATION_IDS` 而非第一个 frozenset
- [ ] §1.4：P7 侧补 `*_OPERATION_SUMMARIES`
- [ ] §3.2：roc / categorical / meta 的 step_frame 适配层
- [ ] §6：`_step_vocabulary_lines()` 的覆盖测试 + 顶层键一致性测试
- [ ] 复核 P7 worktree 的当前规模（见下）

---

## 8. 附：P7 worktree 的核验数字已经过期

P1 计划记录的核验是「12315 行插入、0 行修改、127 个文件」。
写这份文档时（2026-08-08）实测：

```
127 files changed, 30799 insertions(+), 57 deletions(-)
```

**已经不是纯新增了**（57 行删除），而且体量翻了一倍多。
worktree 里 HEAD 之后又叠了若干 commit
（`4617d43 feat(p7): adapt survey replicates to shared combiner`、
`26ebd11 add Scheffe and Games-Howell post-hoc pack`、
`858e287 add explicit GMM and weak-instrument pack`、
`7b3f8c3 add bootstrap and permutation inference packs`、
`cb775d1 add typed replicate combiner execution`、
`4bb30c7 fix(p7): pool OLS estimates across MICE datasets`、
`9109b55 add missingness evidence and Rubin pooling`、
`cbcc353 add replicate-and-combine foundation`），
`contracts/model/` 下还多了 `missing_data.py`、`multiple_comparisons.py`、
`iv_gmm.py`、`resampling.py`、`replicate_combine.py` 等模块。

**本文档处理的是那 8 个包 / 29 条能力。** merge 前必须重跑一次核验
（`git merge-tree`、行数、注册计数、shell/R 调用扫描），
并把新增的那几个包按 §1 到 §5 同样过一遍 —— 它们同样可能没有
`*_OPERATION_IDS`，而 §4 的教训是：**不会有任何东西提醒你它们被漏掉了。**
