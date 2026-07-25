# `model.custom` 契约设计

**状态**：设计草案，未实现
**日期**：2026-07-25
**背景**：`code.execute` 作为「Agent 补齐缺失算法」的预留口子已存在且沙箱扎实，但签名是 DataFrame→DataFrame，只能表达派生数据，无法表达一个**估计量**。本设计补上这一层。

---

## 0. 一句话定位

**`model.custom` 不是第二条执行路径，而是「Agent 撰写的 `ModelHandler`，在沙箱里跑」。**

它接入的是 `arma_garch` / `ets` / `linear_mixed_effects` 三个内置 pack 用的**同一个** `MODEL_REGISTRY` 扩展点。这个决定是整份设计的支点：一旦自定义模型是个正常的 handler，它就**自动**继承血缘、诊断、图表、报告、对比、rerun、fork —— 不需要为它重建任何一样。

反面做法（另起一套「自定义模型结果」的存储和渲染）会立刻分叉出第二套契约，然后是第二套报告、第二套对比逻辑，最后没人知道哪套是真的。

---

## 1. 签名

### 1.1 作者写什么

Agent 提交的是一段 Python，沙箱内以固定协议调用：

```python
# 沙箱注入的名字：
#   data  : pandas.DataFrame —— 已完成角色解析和缺失处理的分析样本
#   spec  : dict            —— 声明的角色列与选项（只读）
#
# 必须绑定：
#   result : dict           —— 见 §2 结果契约

def fit(data, spec):
    ...
    return {...}

result = fit(data, spec)
```

与 `code.execute` 的 `df`→`result: DataFrame` 相比，唯一变化是 `result` 的类型从 DataFrame 变成受契约约束的 dict。沙箱机制、harness 注入方式、确定性闸门**原样复用**，不新写一套。

### 1.2 声明面（提案里的 typed 字段，非代码）

```json
{
  "operation_id": "model.custom",
  "changes": {
    "model_type": "tobit_ml",
    "label": "Tobit (ML, left-censored)",
    "roles": {
      "outcome":    {"column": "wage",  "required": true},
      "predictors": {"columns": ["educ", "exper"], "min": 1},
      "censor_point": {"value": 0.0}
    },
    "serves_y_types": ["continuous"],
    "code": "<python>",
    "dependencies": [],
    "validation_case": { ... },
    "budget": {"cpu_seconds": 120, "wall_seconds": 300, "memory_mb": 4096}
  }
}
```

`roles` 用现有的角色层（variable role layer, v1.6.5）解析，**不让代码自己从 `data` 里猜列名**。代码拿到的 `data` 已经是选好列、对齐好行的分析样本，`spec["roles"]` 告诉它哪列是什么。这样列名错误在提案校验期就暴露，而不是在沙箱里抛 KeyError。

---

## 2. 结果 schema

### 2.1 最关键的一条：作者供给 vs 服务端独占

现有 `ols_1.json` 有 40+ 个顶层字段，但其中绝大多数是**身份与指纹**，由 `econometrics/runner.py` 独占生成。自定义代码**一个都不能写**。

| 分类 | 字段 | 谁写 |
|---|---|---|
| 估计量 | `estimate` `std_error` `p_value` `ci_lower` `ci_upper` | **作者** |
| 拟合统计 | `nobs` `llf` `aic` `bic` `r_squared`(可选) | **作者** |
| 序列 | `fitted_values` `residuals`（可选，长度须 == nobs） | **作者** |
| 推断元数据 | `inference_distribution` `effective_df` `confidence_level` `covariance_estimator` | **作者声明** |
| 身份 | `result_id` `candidate_result_id` `coefficient_id` `coefficient_identity` `source_id` `result_id_by_source_id` `stable_result_ids` | **服务端** |
| 指纹 | `dataset_snapshot_fingerprint` `analysis_sample_fingerprint` `point_estimation_fingerprint` `coefficient_schema_fingerprint` `inference_config_fingerprint` | **服务端** |
| 样本 | `analysis_sample.row_set` `row_order` `fingerprint` | **服务端** |
| 契约 | `contract_version` `schema_version` `source_eligible` `engine` | **服务端** |

**为什么这条不能松**：如果自定义代码能写 `result_id` 或任何 `*_fingerprint`，它就能让一个编造的结果看起来像一个经过校验的结果 —— 引用系统、对比系统、报告的 verified chip 全部依赖这些 id 的可信度。同理 `source_eligible` 决定该结果能否作为下游操作的源，必须由服务端按策略判定。

作者写的 dict 会被服务端**改写进**一个全新的结果对象，而不是被 merge 进去；任何服务端字段出现在作者输出里 → 直接拒绝，不是忽略。

### 2.2 作者结果契约（`custom_model_result_contract_v1`）

```python
{
  "model_type": "tobit_ml",              # 必须等于声明的 model_type
  "nobs": 4110,                          # int > 0
  "terms": [                             # 顺序即报告顺序
    {"name": "Intercept", "estimate": 1.23, "std_error": 0.45,
     "p_value": 0.006, "ci_lower": 0.35, "ci_upper": 2.11},
    ...
  ],
  "fit_statistics": {"llf": -123.4, "aic": 256.8, "bic": 271.2},
  "inference": {
    "distribution": "normal",            # normal | t
    "effective_df": null,                # t 时必填
    "confidence_level": 0.95,
    "covariance_estimator": "opg",       # 自由文本，进 covariance_evidence
    "library": "statsmodels",            # 用了什么算的
    "library_version": "0.14.2"
  },
  "fitted_values": [...],                # 可选
  "residuals": [...],                    # 可选
  "diagnostics": {"converged": true, "iterations": 42}   # 可选，自由 dict
}
```

### 2.3 服务端 fail-closed 校验（沙箱返回后立即执行）

不通过则整个 run 失败，不写任何产物：

1. `terms` 非空；`name` 唯一、非空、可作列名
2. 每个 term 的 `estimate` / `std_error` 必须是有限浮点（**拒绝 NaN/Inf**）
3. `std_error > 0`
4. `p_value ∈ [0, 1]`
5. `ci_lower <= estimate <= ci_upper`
6. `nobs > 0` 且 `nobs <= len(分析样本)`
7. `fitted_values` / `residuals` 若提供，长度必须 == `nobs`
8. `inference.distribution == "t"` 时 `effective_df` 必须是正有限数
9. 作者输出里不得出现 §2.1 服务端字段名的**任何一个**
10. `model_type` 与声明一致

第 2、4、5 条是重点：一个不收敛的 ML 估计器最典型的产物就是 NaN 标准误和 `[nan, nan]` 区间，而那会在报告里渲染成一个看起来完整的空结果 —— 这正是本仓库反复堵的「非空但无用」失败模式。

### 2.4 可信度标记（不可关闭）

自定义模型的结果**必须**带上：

- `engine: "agent_custom"`
- `custom_model_code_sha256`
- `trust` 标记 —— UI 上与原生模型视觉可区分

**自定义模型的结果绝不能看起来像一个经过验证的原生模型。** 这不是保守，是诚实：Workbench 对 OLS/DID 的数值正确性做过 R/Stata 交叉验证，对 Agent 现写的 Tobit 没有。

---

## 3. 强制校验案例（`validation_case`）

这是本设计里唯一一条「比现有 code.execute 更严」的要求，理由是估计量的错误比变换的错误隐蔽得多。

提案**必须**附一个已知答案的校验案例：

```json
"validation_case": {
  "data_csv": "<内联小样本，≤ 200 行>",
  "expected": [
    {"term": "educ", "estimate": 0.0742, "std_error": 0.0065}
  ],
  "tolerance": 1e-4,
  "authority": "Stata 18 `tobit wage educ exper, ll(0)`"
}
```

服务端在正式估计**之前**，先用同一段代码跑这个案例，与 `expected` 逐项比对；不通过则拒绝执行，正式数据一行都不碰。

这与本仓库既有做法一致 —— DID 的三个估计量（CS / SA / dCDH）都是对着 R 包逐元素验到 1e-13 才发版的。Agent 写的估计量不该有更低的门槛。`authority` 字段进审计留痕：这个数是谁给的。

---

## 4. 沙箱额度

复用 `run_python_sandboxed`，但额度另设 —— 估计不是变换。

| | `code.execute` 现值 | `model.custom` 建议 | 上限（不可超） |
|---|---|---|---|
| CPU | 10 s | 120 s | 600 s |
| 墙钟 | 30 s | 300 s | 900 s |
| 内存 | 1 GiB | 4 GiB | 8 GiB |
| 输出 | 64 MiB | 256 MiB | 256 MiB |

不变的部分（**全部照搬，不放宽**）：

- 无沙箱后端 → 拒绝执行，无降级路径
- 网络：seatbelt `(deny network*)` / `bwrap --unshare-net`
- 写盘：只放开本次输出目录
- `_scrubbed_env`：宿主 API key 不继承
- `python -I`：不读用户 site-packages
- 代码以 JSON 数据送入子进程，不拼模板
- 超时按进程组 SIGKILL

**额度由提案声明、受上限约束、确认前对用户可见** —— 用户批准的是「这个模型最多花 5 分钟 4G」，不是一张空白支票。

### 4.1 确定性闸门的成本（需要决策）

`code.execute` 的做法是 preview 跑一次、execute 再跑一次、指纹必须一致。这条对 Agent 写的估计量**价值更高**（不确定性估计器、未播种的随机初值、并行归约顺序都会漂），但在 120s CPU 下意味着 **2× 成本**。

三个选项，我推荐 A：

- **A（推荐）**：保留双跑等值。额度按双跑预算，用户看到的就是真实成本。理由：一个不可复现的估计量，其结果不该进血缘系统 —— 这正是 `NondeterministicCodeError` 存在的意义。
- B：单跑 + 强制声明 RNG 种子。成本减半，但只覆盖显式随机性，盖不住 BLAS 线程序等来源。
- C：preview 在子样本上跑。**否决** —— 子样本与全样本的指纹本就不同，等值检查失去意义，等于把闸门拆了还留个壳。

---

## 5. 与 `model.genesis` 的关系

两者**不重叠**，是「注册」与「使用」：

| | `model.genesis` | `model.custom` |
|---|---|---|
| 语义 | 用**已注册**的 model_type 估计 | **注册**一个新 model_type，然后估计 |
| 代码 | 无（服务端 handler） | 有（Agent 撰写，沙箱运行） |
| 风险 | `mutating` | `high`（`explicit_single_use` 授权） |
| 校验 | 参数契约 | 参数契约 + §3 校验案例 |
| 结果可信度 | 原生 | `engine: agent_custom` + trust 标记 |

### 5.1 注册后的复用

自定义 handler 一经确认，以 `code_sha256` 为身份登记到**该 chain 作用域**的 handler 表。之后：

- 同一 chain 内再次估计 → 按 hash 引用，不重新提案、不重新授权
- 代码变一个字符 → hash 变 → 新身份 → 重新走高风险确认
- rerun / fork 沿用 hash，历史结果可复现

**不做全局注册。** 一个 chain 里 Agent 写的 Tobit 不应该悄悄成为整个项目的 `tobit` 实现 —— 提升为项目级能力应当是一个显式的、人工的动作（未来的 `pack.promote`，本设计不覆盖）。

### 5.2 与 `operation.multi_step` 的关系

`model.custom` **不进** `WORKFLOW_STEP_OPERATIONS`。多步工作流可以编排已注册的模型，但不能在一次确认里夹带一段新代码 —— 高风险授权必须是它自己那一次确认，不能搭便车。顺序是：先 `model.custom` 注册并验证通过，再在工作流里按 model_type 使用。

---

## 6. 依赖机制的边界

这是最需要划清的一块。

### 6.1 硬约束：装和跑必须分离

沙箱无网络是它安全的**根本原因**，不是可调参数。因此「Agent 自己下载依赖」**不能**通过放宽 `model.custom` 的沙箱实现 —— 那等于拆掉沙箱。

依赖需要一条独立机制，`dependency.request`（本设计不实现，只定边界）：

1. Agent **提议**包名 + 版本区间 + 用途
2. 服务端从**配置好的索引**解析出确切版本、wheel sha256、完整传递依赖集、许可证
3. 把这份清单呈给用户 —— 用户批准的是一个**具体的、带哈希的**依赖集
4. 批准后在沙箱**之外**装进受管环境
5. 后续沙箱运行以**只读**方式挂载该环境

### 6.2 必须拒绝的

- VCS / URL / 本地路径安装（`git+`、`http://`、`file:`）
- 未固定版本、`--pre`、非配置索引的包
- 安装期执行任意代码的源码包（`sdist` 且带 `setup.py`）——**只接受 wheel**
- 「批准一次，以后同类自动放行」的泛化授权

### 6.3 边界的本质

你的原话是「自己去下载现成的依赖并做好全方位的适配」。这句话里有两件事，**必须分开**：

- **下载** = 供应链决策。引入第三方代码到用户机器上，这不能委托给 Agent，无论它多确信。人工授权 + 哈希固定是唯一负责任的做法。
- **适配** = 写一个 handler 把那个库接进 Workbench 的契约。**这恰恰就是 `model.custom` 要做的事**，而且是 Agent 能做得又快又好的部分。

所以 `model.custom` 和 `dependency.request` 是互补的两半：后者把库安全地放进环境，前者把库变成 Workbench 的一等公民。先做前者 —— 因为 statsmodels / scipy / linearmodels 已经在环境里，**大量「Stata 有而 Workbench 没有」的模型（Tobit、Heckman、有序 Probit、分位数回归、负二项)根本不需要新依赖**，只需要一个 handler。

---

## 7. 建议的实施顺序

1. `custom_model_result_contract_v1` + §2.3 校验器 + 单元测试（无沙箱、无 Agent，纯契约）
2. 沙箱 handler runner：`SandboxLimits` 新档位 + §1.1 harness + 双跑确定性
3. `validation_case` 执行器（先于正式估计）
4. 注册表接入：chain 作用域 handler 表，按 `code_sha256` 寻址
5. 服务端身份/指纹装配 + trust 标记 + UI 可区分
6. 注册 `model.custom` 操作（`natural_language_enabled=True`，`risk_level="high"`）
7. 真机验收：拿一个 Stata 有而 Workbench 没有的模型（建议 **Tobit**，statsmodels 已有实现，可对 Stata `tobit` 交叉验证）

第 1–3 步不碰 Agent，可独立验收 —— 契约和沙箱先立住，再把 Agent 接上去。

---

## 8. 本设计明确不覆盖

- `dependency.request` 的实现（只定边界，见 §6）
- `pack.promote`（chain 作用域 → 项目作用域的提升）
- 非截面模型（面板/时序自定义估计量的角色层更复杂，需单独设计）
- 自定义**图表**（本设计只产出结果契约；诊断图沿用现有按预测变量生成的机制）
