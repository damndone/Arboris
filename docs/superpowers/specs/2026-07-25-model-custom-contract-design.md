# 通用自定义能力运行时与 `model.custom` 适配器设计

**状态**：B0 设计已批准；实现尚未开始

**日期**：2026-07-25

**替代**：本文件此前的“单一自定义模型结果契约”设计

**设计原则**：先建立可复用的自定义能力运行时，再把 `model.custom` 作为第一个类型化适配器接入；不得用某个示例模型、某个软件输出或逐字节相等的结果反推通用契约。

**正式开发目标**：`docs/superpowers/specs/2026-07-25-custom-capability-foundation-objective.md`

**上游 v1.8.3 范围**：[`v1.8.3/README.md`](./v1.8.3/README.md)

---

## 上游产品定位

本文件只定义 v1.8.3 的 B0 通用运行时地基。能力需求解析、可信实现优先级、依赖构建、Adapter Factory、算法验证与准入、Notebook 接入和双层领域记忆由独立的 v1.8.3 规格目录定义：

- [`v1.8.3/capability-factory-design.md`](./v1.8.3/capability-factory-design.md)
- [`v1.8.3/domain-memory-design.md`](./v1.8.3/domain-memory-design.md)

这些上游设计不扩大当前 B0 开发线。B0 仍然不接 Agent、不下载依赖、不修改 workflow、不动态注册模型，也不实现 memory；它只提供后续 Capability Factory 可复用的密封运行、身份、结果、证据与隔离基础。

## 0. 决策摘要

Workbench 需要支持 Agent 在现有能力不足时：

1. 使用已经批准并密封的依赖实现新算法；
2. 没有现成依赖时编写算法；
3. 在隔离环境中产生有界、可验证、可追溯的结果；
4. 经独立证据与人工授权后，在限定作用域内复用。

为此，本设计不把 Agent 代码伪装成一个进程内 `ModelHandler`，也不建立第二套平行的 lineage。采用四层结构：

1. **可信控制层**：解析输入、持有身份、授权、证据等级、lineage 与消费者策略；
2. **通用自定义能力运行时**：在严格隔离中执行 `input bundle -> output bundle`；
3. **类型化适配器**：`model.custom` 是第一个适配器，未来可增加其他统计或数据能力；
4. **消费者适配层**：报告、诊断、图表、Compare、rerun 分别显式声明支持，不因“注册成功”自动获得。

当前开发线只建立第 1–3 项所需的**通用基础契约、严格运行边界和验证语义**。它不接 Agent、不下载依赖、不动态注册模型，也不改 workflow。

---

## 1. 目标与非目标

### 1.1 目标

- 结果根契约不依赖单方程、系数表、经典标准误或 p-value。
- 同一运行时以后能承载模型、统计检验、算法和其他有界分析能力。
- 服务端独占所有可信身份、样本指纹、授权状态和信任等级。
- “可复现”区分身份一致、数值等价和统计等价，不强迫合法随机算法逐字节相等。
- 自测、独立 oracle、性质检验和模拟校准拥有不同证据等级。
- Agent 代码及第三方依赖不能读取未声明的宿主文件。
- 运行身份覆盖代码、依赖、解释器、ABI、原生库、harness、契约和运行策略。
- 内置模型和自定义模型继续进入同一 lineage 与结果存储体系，但通过可信适配器进入，不直接导入 Agent 代码。

### 1.2 当前开发线明确不做

- `dependency.request` 的解析、下载、安装或 UI；
- chain-scoped handler registry；
- `model.custom` Agent operation、自然语言入口或确认 UI；
- 项目级 `pack.promote`；
- 报告、诊断、图表和 Compare 的具体适配实现；
- 把 `model.custom` 加入 `WORKFLOW_STEP_SPEC_CONTRACTS`；
- 对任一具体新模型作产品级承诺。

这些功能依赖本开发线的基础，但不能被普通多步确认或一次自测绕过。

---

## 2. 架构边界

### 2.1 `custom_capability_runtime`

通用运行时只理解以下概念：

- 密封输入 bundle；
- 不可信作者代码；
- 密封运行环境；
- 版本化 runtime policy；
- 有界 output bundle；
- bundle 身份；
- 可复现性与证据检查。

它不理解 OLS、Tobit、面板、贝叶斯或任何具体算法。它也不决定结果能否进入 Compare、能否作为下游 source、或能否提升为项目能力。

### 2.2 `model.custom` 适配器

`model.custom` 负责把模型语义映射到通用运行时：

- 声明模型所需角色；
- 将已解析的分析样本封装成输入 bundle；
- 选择允许的输出 facet；
- 将通过校验的作者输出投影到 Workbench 模型结果；
- 声明报告、诊断、图表和 Compare 能力。

Agent 代码不是 `ModelHandler`。未来接入时，全局 `MODEL_REGISTRY` 只注册一个可信的 custom dispatcher；dispatcher 根据服务端持有的 chain-local bundle 引用调用沙箱，不把作者代码 import 到服务端进程。

### 2.3 消费者不自动继承

自定义能力注册成功只表示“这个 bundle 可以在声明的作用域运行”。以下能力分别显式声明：

```json
{
  "consumer_capabilities": {
    "report_projection": "parameter_table_v1",
    "diagnostic_adapter": null,
    "figure_provider": null,
    "compare_adapter": null
  }
}
```

值为 `null` 时，消费者必须显示“该能力未声明”，不能猜测、静默降级或复用不匹配的内置逻辑。

---

## 3. 通用输入契约

### 3.1 作者入口

固定 harness 调用：

```python
def run(input_bundle, capability_spec):
    ...
    return output_bundle

result = run(input_bundle, capability_spec)
```

作者代码不能自行打开用户文件、扫描目录、联网或调用包管理器。输入只能来自服务端封装的 bundle。

### 3.2 类型化角色

角色不能固定为 `outcome/predictors/censor_point`。适配器声明：

```json
{
  "roles": [
    {
      "role_id": "response",
      "kind": "column",
      "cardinality": {"min": 1, "max": 1},
      "data_types": ["numeric"],
      "required": true,
      "missing_policy": "complete_case"
    },
    {
      "role_id": "features",
      "kind": "columns",
      "cardinality": {"min": 1, "max": null},
      "data_types": ["numeric", "categorical"],
      "required": true,
      "missing_policy": "complete_case"
    },
    {
      "role_id": "threshold",
      "kind": "scalar",
      "data_types": ["numeric"],
      "required": false
    }
  ]
}
```

允许的 `kind` 首版为 `column | columns | scalar`。增加新 kind 必须升级契约，不能让作者代码通过自由 dict 猜语义。现有 `y/x` 角色只是兼容投影，不是通用根契约。

首版边界必须诚实：graph、tensor、sparse matrix、event stream 等非表格输入，以及 `test | transform | solve` 等未注册 operation，返回版本化 typed gap（例如 `CUSTOM_CAPABILITY_INPUT_KIND_UNSUPPORTED` 或 `CUSTOM_CAPABILITY_OPERATION_UNSUPPORTED`）。不得把它们压平成 columns，也不得伪装成 `fit`/`predict` 来追求表面接入。扩展只能新增版本化 input-kind/operation vocabulary 及其校验、风险、输出和消费者语义。

### 3.3 样本身份

服务端为每个输入观测分配不可变 `observation_id`。执行前只注册有界的 `InputObservationDeclaration`、输入 `IndexDeclaration` 与 `SampleSelectionPolicyRevision`：前两者绑定输入 bundle、角色、完整 observation-id 集合及顺序；selection policy 声明哪些执行期排除规则、reason code 和验证证据是允许的。执行前不假装知道运行期才确定的最终样本。

若算法合法排除观测，作者必须返回：

- 本地 sample/index claim id；
- 使用的 `SampleSelectionPolicyRevision`；
- 被使用的精确 observation-id 集合或 mask；
- 每个排除的类型化 reason code；
- 必要时声明 group、time 或重复测量映射。

作者返回的是不受信任 `SampleClaim`/`IndexClaim`，不直接成为可信引用。服务端先验证集合、顺序、重复、越界和角色，再根据注册 selection policy 重新计算可确定的 hold-back/缺失规则，或验证执行期排除所需的有界证据；无法由服务端验证的 data-dependent exclusion 拒绝。通过后服务端签发 `TrustedSampleIdentity`/`TrustedIndexIdentity`，计算最终指纹，并把所有 output facet 的本地 refs 重写为可信 identity。仅返回 `nobs <= 输入行数` 或作者自报 reason 不足以证明样本身份。

B0 v1 每次 invocation 只允许一个分析样本。所有 facet 的 `sample_ref` 必须解析到该样本；`index_ref` 只能表达同一 observation 集合的受信任顺序/映射。不同缺失处理、fold、horizon 或 posterior subset 需要多个样本语义时，整个输出以 `CUSTOM_CAPABILITY_MULTI_SAMPLE_UNSUPPORTED` 拒绝。多样本支持需要新的版本化声明契约，不能留给实现临场决定。

序列输出必须声明 `index_ref` 和 `semantic_kind`；不能把任意同长度数组默认当成 fitted value 或普通 residual。

---

## 4. 通用输出契约

### 4.1 作者输出与服务端 envelope 分离

作者只能返回 `custom_capability_output_v1` 的内容字段。以下字段由服务端独占，作者一旦提供就拒绝整个结果：

- 所有 result、source、coefficient、artifact 身份；
- 数据集与样本指纹；
- bundle、环境与授权身份；
- `engine`、`trust_tier`、`source_eligible`；
- lineage、rerun、fork 和 promotion 状态；
- consumer capability 的最终 admission。

服务端创建新对象，不把作者 dict merge 到可信 envelope。

### 4.2 根结构

```json
{
  "contract_version": "custom_capability_output_v1",
  "outputs": [
    {"kind": "parameter_table", "output_id": "primary", "...": "..."},
    {"kind": "metric_set", "output_id": "fit_metrics", "...": "..."}
  ],
  "diagnostics": [
    {
      "code": "OPTIMIZER_CONVERGED",
      "status": "pass",
      "severity": "info",
      "evidence": {"iterations": 14}
    }
  ]
}
```

根契约不要求 `terms`、p-value、标准误、AIC、fitted value 或 residual。所有浮点必须有限；若某类算法需要表达无穷边界或缺失量，必须通过类型化状态表达，不能写 NaN/Inf。

### 4.3 首版 output facets

#### `parameter_table`

表示一个或多个方程、component、response、quantile 或其他轴上的参数：

```json
{
  "kind": "parameter_table",
  "output_id": "primary",
  "estimate_semantic": "point_estimate",
  "axes": ["equation"],
  "rows": [
    {
      "parameter_id": "slope_a",
      "label": "Slope A",
      "coordinates": {"equation": "selection"},
      "estimate": 0.42,
      "inference": {
        "kind": "frequentist",
        "standard_error": 0.08,
        "p_value": 0.001,
        "interval": {
          "level": 0.95,
          "lower": 0.26,
          "upper": 0.58
        }
      }
    }
  ]
}
```

`inference` 可省略。提供时使用判别联合：

- `frequentist`
- `bayesian`
- `set_identified`
- `none`

各分支只校验自己的语义。正则化或纯预测模型不必伪造 p-value；贝叶斯结果不必伪装成频率学派标准误；多方程模型通过 axes 表达，不拼接带特殊含义的 term 名。

#### `metric_set`

每个指标必须携带：

- 稳定 `metric_id`；
- 数值与单位；
- `sample_ref`；
- `comparability_scope`；
- 可选的方向性和计算定义。

两个结果只有在服务端判定 estimand、样本、尺度、似然基础、预测 horizon 等兼容时才能 Compare。名称同为 `rmse` 或 `aic` 不自动可比。

#### `indexed_series`

每个序列声明：

- `series_id`
- `index_ref`
- `semantic_kind`
- `scale`
- 有界值载荷或 artifact 引用

例如 response residual、Pearson residual、posterior mean、state estimate 必须是不同的 `semantic_kind`。

#### `structured_artifact`

用于不能安全压扁为表或序列的有界结构。必须提供受信任适配器认识的 `schema_id`；自由 JSON 不自动进入 UI、报告或 Compare。

### 4.4 诊断不是自由 dict

诊断项必须包含 `code/status/severity/evidence`。`evidence` 仍需通过有限浮点、深度、列表、字符串和总字节限制。迭代次数等易漂移信息是观察证据，不默认进入结果等价指纹。

### 4.5 全面有界

输出限制属于版本化 `runtime_policy_id`，不硬编码进算法契约。策略至少限制：

- 总结果字节；
- JSON 深度；
- facet 数量；
- 表行数、序列长度和 artifact 数量；
- 字符串、列表和 diagnostics 数量；
- stdout、stderr；
- 输出文件总量、文件数量和单文件大小。

超限直接拒绝，不截断成一个看似成功的统计结果。大载荷以后通过内容寻址 artifact 引用解决，不通过无限增大 inline JSON 上限解决。

---

## 5. Bundle 身份与历史 rerun

`code_sha256` 只证明源码文本，不是可执行能力身份。正式身份为 `handler_bundle_sha256`，至少覆盖：

- 作者代码及规范化入口；
- 所有直接与传递依赖的 wheel 名称、tag、SHA-256 和持久化 blob；
- Python binary SHA、实现、版本、cache tag、SOABI；
- OS、架构、libc 或 macOS target；
- 安装树 manifest；
- BLAS/LAPACK 和其他原生动态库身份；
- harness；
- 输入、输出与角色契约版本；
- `runtime_policy_id`；
- 线程、RNG 和其他会影响结果的执行环境。

preview、validation、execute、结果 envelope、chain registry 和 rerun 必须绑定同一 bundle digest。任一组成部分变化都产生新身份。

身份相同仍不等于结果逐字节相同；结果等价由下一节的 reproducibility profile 判定。

---

## 6. 可复现性：身份、数值和统计性质分离

### 6.1 三种 profile

#### `exact`

用于真正离散、规范化且应完全一致的结果。比较 canonical output，但排除运行时长、日志时间和诊断迭代次数等非语义字段。

#### `numeric`

用于确定性数值算法。每个 assertion 自带：

- 字段路径；
- `atol`；
- `rtol`；
- 可选矩阵范数、对称性、PSD 或约束条件。

不能用一个全局 tolerance 同时比较估计、标准误、概率、对数似然和预测序列。

#### `statistical`

用于 bootstrap、MCMC、随机优化、随机森林和其他合法随机算法。验证：

- RNG 算法、seed 与 stream 身份；
- Monte Carlo standard error；
- R-hat、ESS、覆盖率或校准性质；
- 目标函数、KKT、约束和稳定性；
- 预测排序或分布距离；
- 算法声明的其他性质。

posterior draws、bootstrap replicates、迭代次数、等价多解和 tied hyperparameters 不做逐字节比较。

统计验证协议由服务端注册并版本化，至少固定 seed/stream 生成方式、最小重复次数、区间或 MCSE 计算、coverage/power、最大误接受率、允许失败率和 tolerance ceiling。作者只能声明能力性质和返回观测材料，不能提供或放宽 admission threshold；未知协议、低于最小重复数或超过 tolerance ceiling 一律 fail closed。

### 6.2 双跑的真实语义

双跑可以是某个 evidence check，但不是所有能力的统一 admission 条件。验证器根据 profile 比较语义结果；生命周期成本按实际执行次数累计，并在确认前展示。

后续 HTTP 流程应以单次消费 receipt 绑定已完成的 preview/validation，避免 risk-authorize、confirm、apply 无意义地重复昂贵执行。

---

## 7. 证据等级与防特判

作者提供的 fixture、expected 和文字 authority 只能构成自测，不能独立证明算法正确。

证据等级由服务端根据可验证材料派生：

| 等级 | 含义 | 可获得的信任 |
|---|---|---|
| E0 | 契约、边界和运行隔离通过 | 结构可运行 |
| E1 | 作者自测通过 | `experimental`，不可 promotion |
| E2 | 独立 oracle 或独立实现可复现 | 限定作用域 verified candidate |
| E3 | 多案例、对抗、性质、模拟校准及独立复核通过 | 可进入人工 promotion 审查 |

独立 evidence packet 至少绑定：

- fixture hash；
- expected output hash；
- 产生 expected 的工具、版本、命令与选项；
- 输入、样本和输出身份；
- evidence producer；
- 与待测作者代码的独立性来源。

当没有外部 oracle 时，应组合：

- DGP 参数回收；
- invariant/property checks；
- metamorphic tests；
- adversarial cases；
- regression cases；
- 独立复核。

服务器持有的 holdout 或变形案例不能提前暴露给作者代码。仅 E1 的 bundle 始终保持 `experimental` 和 `source_eligible=false`。

E2/E3 独立性由服务端依据 provenance DAG 判断。与作者实现共享作者、生成会话、源码、expected 来源或关键依赖的材料不能仅凭不同文件名成为独立 oracle。最终 holdout 应隔离、轮换、限制尝试次数并只返回粗粒度反馈；泄漏或自适应探测会使对应 assessment 失效。

---

## 8. 严格隔离运行时

现有 `code.execute` G3 允许读取宿主文件系统，不能原样用于 Agent 模型代码或第三方依赖。本设计新增独立的 `untrusted_capability_v1` profile，不改变既有 G3 语义。

### 8.1 文件系统

默认拒绝所有宿主读取与写入，只挂载：

- 固定解释器与必要 stdlib；
- 经过校验的只读依赖环境；
- 固定 harness；
- 单个密封输入目录；
- 单个私有输出目录；
- 最小 `/dev` 与受控运行设施。

禁止读取 repository、用户 home、SSH、云配置、浏览器数据、其他项目和未声明临时目录。canary 必须证明宿主 sentinel 既不能读取，也不能通过目录枚举发现。

### 8.2 Python 启动与依赖载入

专用解释器以隔离模式启动，至少达到 `-B -I -S` 的效果。运行时显式加入经过 manifest 校验的 purelib/platlib 路径，不调用会执行 `.pth` 的机制。

受管环境拒绝：

- executable `.pth`；
- `sitecustomize.py` / `usercustomize.py`；
- 未出现在 bundle manifest 的路径；
- 运行时包管理器；
- writable dependency tree。

wheel-only 只减少构建期风险，不等于运行安全。

### 8.3 网络与进程

- 无网络；
- 固定环境变量白名单；
- 固定 BLAS/线程数；
- 关闭继承文件描述符；
- 子进程和整个进程树受同一预算；
- 领导进程退出后仍清理后代。

### 8.4 资源硬上限

CPU、内存、PID、墙钟和输出预算必须覆盖整个进程树。若某宿主无法提供声明的硬保证，则该 profile 不获得 admission，不能静默退化为当前 G3 或仅依赖可失败的 `RLIMIT_AS`。

输出由父进程通过 no-follow descriptor 读取；拒绝符号链接、额外文件和总 quota 超限。

### 8.5 支持宿主评估

隔离后端“可发现”不等于宿主已受支持。服务端先计算稳定 `host_containment_subject_id`，覆盖 OS/kernel/架构、隔离后端绝对身份、profile、mount/runtime policy 与 harness；随后生成内容寻址、不可变的 `HostContainmentAssessment`，至少绑定：

- OS、kernel、架构及其规范化身份；
- 隔离后端的绝对路径、版本和 executable SHA；
- profile、mount policy、runtime policy 与 harness digest；
- 文件读取/枚举、网络、越界写、进程树、资源与输出摄取 canary 的完整结果；
- assessment 规则版本和评估时间。

Assessment 不携带可变 validity。服务端为同一 subject/assessment 追加 `HostContainmentValidityRecord`，包含单调 `validity_revision`、`effective_control_sequence`、authority、reason 与 evidence refs：

```text
valid → expired | revoked | superseded
```

终态不能恢复；重验通过会产生新 assessment 和新的 validity stream。每次真实执行前重新校验当前宿主 subject identity、assessment identity 与最新 validity revision；任一漂移或失效都在 dispatch reservation 前拒绝。B0 负责生成/验证这些对象；等 Capability Factory 接入 Core Trace 时，由 CF1 注册 `host_containment.assessed` 与 `host_containment.validity.changed` exact events，B0 不因此提前修改 Agent Trace。没有目标支持宿主上的真实全套 canary 证据时，B0 只能报告实现/单元测试完成，不能关闭 supported-host 验收，也不能静默降级到较弱 profile。

---

## 9. `dependency.request` 的后续边界

下载与运行必须分离：

1. Agent 提议需求和用途；
2. 可信解析器产生确定版本和完整传递依赖图；
3. 用户批准具体 lock manifest；
4. 低权限 staging 环境离线安装；
5. 生成 CAS 存储的只读 bundle；
6. `model.custom` 只引用 bundle digest，运行时无网络。

manifest 后续至少记录：

- canonical package 与 index 身份；
- wheel filename、platform tag、hash；
- resolver/installer 版本；
- yanked 状态；
- 许可证；
- SBOM 与漏洞快照；
- 可用的签名或 provenance。

不接受 VCS、任意 URL、本地路径、未固定版本或源码构建。批准一个 lock manifest 不构成以后自动批准同名包的新版本。

---

## 10. Registry、作用域与 promotion

后续 registry 采用可信 dispatcher 加作用域 overlay：

```text
MODEL_REGISTRY["custom"] -> trusted dispatcher
                              |
                              +-- resolve(run_family_id, chain_id, handler_bundle_id)
                                      |
                                      +-- immutable sandboxed bundle
```

- 不动态修改全局 `MODEL_REGISTRY`；
- 不允许自定义 bundle 覆盖原生 model type；
- fork 显式继承 bundle 引用与授权范围；
- rerun 绑定原 bundle、输入、runtime policy 和 evidence；
- `pack.promote` 只能产生待审核、签名的发布候选；
- 正式发布前，Agent 或第三方代码仍不得 import 到服务端进程。

---

## 11. 与 workflow 的关系

`model.custom` 不进入本开发线的 `WORKFLOW_STEP_SPEC_CONTRACTS`。

未来允许的顺序是：

1. 独立完成 dependency admission；
2. 独立完成 custom capability proposal、验证和高风险授权；
3. 服务端生成 chain-scoped `handler_bundle_id`；
4. workflow 只引用已经 admission 的 bundle。

普通 `operation.multi_step` 不能携带代码、依赖请求或 promotion，也不能把多个低风险步骤组合成对高风险授权的绕过。

---

## 12. 错误语义

当前基础应提供稳定、通用且不含具体算法名的错误码：

- `CUSTOM_CAPABILITY_CONTRACT_INVALID`
- `CUSTOM_CAPABILITY_OUTPUT_BOUNDS_EXCEEDED`
- `CUSTOM_CAPABILITY_SAMPLE_IDENTITY_MISMATCH`
- `CUSTOM_CAPABILITY_MULTI_SAMPLE_UNSUPPORTED`
- `CUSTOM_CAPABILITY_INPUT_KIND_UNSUPPORTED`
- `CUSTOM_CAPABILITY_OPERATION_UNSUPPORTED`
- `CUSTOM_CAPABILITY_SANDBOX_UNAVAILABLE`
- `CUSTOM_CAPABILITY_HOST_READ_ISOLATION_UNAVAILABLE`
- `CUSTOM_CAPABILITY_ENVIRONMENT_IDENTITY_MISMATCH`
- `CUSTOM_CAPABILITY_EVIDENCE_INSUFFICIENT`
- `CUSTOM_CAPABILITY_EQUIVALENCE_FAILED`
- `CUSTOM_CAPABILITY_FORBIDDEN_SERVER_FIELD`

失败时不写成功 result、artifact、registry 或 lineage 记录；只写有界、去敏的失败证据。

---

## 13. 当前开发线：B0 通用基础

本开发线只交付以下三个切片：

### B0.1 通用契约与身份

- `custom_capability_contract_v1`
- 输入角色契约
- output facets 与全面边界校验
- 服务端保留字段拒绝
- observation identity
- server-owned sample/index declarations 与可信引用重写
- `handler_bundle_sha256` 纯契约与确定性构造

首版实现 facets 为 `parameter_table`、`metric_set`、`indexed_series`、`structured_artifact`。这不表示所有消费者都已支持它们。

### B0.2 可复现性与证据

- `exact | numeric | statistical` profile；
- 分字段 comparator；
- server-owned statistical protocol thresholds；
- E0/E1/E2/E3 服务端派生规则；
- 作者自测与独立 evidence packet 分离；
- E1 强制 `experimental`、`source_eligible=false`。

### B0.3 严格运行边界

- 新 `untrusted_capability_v1` profile；
- deny-by-default 文件读取；
- 密封解释器、依赖、输入、harness 和输出；
- host-read canary；
- 不可变 `HostContainmentAssessment`、append-only `HostContainmentValidityRecord` 与 execute 前身份重验；
- 进程树资源策略与 fail-closed admission；
- 有界 stdout、stderr、JSON 和输出文件。

本开发线只需用一个最小 `parameter_table` 作者函数证明端到端基础，不把任何具体估计器写进产品契约。

---

## 14. 后续开发顺序

B0 之后的版本切片以 [`v1.8.3/README.md`](./v1.8.3/README.md) 为权威范围地图：

1. **CF1**：Capability Requirement、可信 Registry 与实现解析；
2. **CF2**：`dependency.request`、隔离构建、CAS bundle 与供应链审计；
3. **CF3**：Adapter Factory、Agent 自研算法最后级和独立验证；
4. **CF4**：`model.custom`、Notebook、Graph、消费者与通用 workflow 接入；
5. **MEM1–MEM3**：Project/RunFamily 可重建索引、跨项目领域记忆和受限后台审阅；
6. **Research promotion**：E3 证据和人工审查后的更宽作用域候选流程。

每个阶段使用独立正式开发线和验收边界。B0 不能以“某个示例模型结果对上了”为完成标准，也不能提前实现任何后续切片。

---

## 15. 验收与测试策略

### 15.1 契约通用性

至少覆盖以下互不等价的 fixture：

- 带频率学派推断的单表参数；
- 无推断的正则化参数；
- 带 axes 的多 component 参数；
- 贝叶斯推断；
- set-identified 区间；
- 纯 metric 与 indexed series；
- schema-known structured artifact。

测试目的不是实现这些算法，而是证明根契约没有强迫它们伪装成 OLS。

### 15.2 负面与边界

- NaN/Inf；
- 作者伪造服务端字段；
- 重复 output/parameter/metric 身份；
- 未声明 axis；
- 样本行被静默丢弃；
- series index 不匹配；
- JSON 深度、列表、字符串、总字节和输出文件超限；
- 自由 diagnostics 绕过边界；
- 未知 facet 或 schema。

### 15.3 可复现性

- exact profile 排除非语义运行字段后稳定；
- numeric profile 同时验证 `atol` 与 `rtol`；
- statistical profile 接受不同 draws 但拒绝性质失配；
- 迭代次数变化不导致错误的结果漂移；
- bundle 任一身份成分变化都会改变 digest。

### 15.4 防特判

- 作者自测只能得到 E1；
- server-owned holdout 不暴露给作者；
- expected、代码和 fixture 同源不能伪装成独立 oracle；
- evidence producer、工具版本、命令或 hash 缺失时拒绝 E2；
- E1 不得产生 `source_eligible=true`。

### 15.5 隔离

- 宿主 sentinel 不可读、不可列目录；
- 网络不可用；
- 依赖与 harness 只读；
- executable `.pth` 与 custom site hook 被拒；
- 子进程树、内存、PID、CPU、墙钟和输出总量受限；
- 不具备所需宿主能力时 fail closed；
- 现有 `code.execute` G3 行为不被本开发线静默改变。

### 15.6 仓库通用约束

- `tests/test_no_exercise_specific_naming.py`
- 现有 sandbox 与 `code.execute` 回归测试
- FMS Context Pack 与事件流验证
- `git diff --check`

---

## 16. 完成定义

B0 只有同时满足以下条件才算完成：

- 通用 fixture 证明契约不依赖特定模型家族；
- 服务端身份和作者输出边界 fail closed；
- 样本身份可验证；
- 作者提供的 sample/index 本地引用只能经服务端声明校验后重写；
- exact/numeric/statistical 三种 profile 都有正反测试；
- statistical admission threshold 不能由作者放宽；
- E1 不能越权为 verified 或 source-eligible；
- 目标支持宿主上的 host-read、目录枚举、网络、写盘、进程树与资源 canary 全部通过，并固化不可变 `HostContainmentAssessment` 与有效 `HostContainmentValidityRecord`；
- runtime bundle 身份覆盖全部声明组成；
- 无支持的隔离后端时诚实拒绝；
- 非表格 input kind 与未注册 operation 返回 typed gap，不做隐式压平或伪装；
- 未接 Agent、registry、dependency、workflow 或 promotion；
- 当前开发线的正式 FMS scope、事件流和 Context Pack 验证通过。

---

## 17. 设计取舍

本设计刻意接受三项成本：

1. **首个 `model.custom` 可见功能会更晚**：先补运行时和证据基础；
2. **部分宿主暂时无法运行**：安全保证不足时拒绝，而不是降级；
3. **自研算法长期保持 experimental**：没有独立证据时不假装 verified。

换来的收益是：未来扩展到新的模型家族、随机算法、贝叶斯方法、统计检验或其他自定义能力时，不需要推翻一个围绕 OLS/Tobit 和逐字节相等建立的根契约。
