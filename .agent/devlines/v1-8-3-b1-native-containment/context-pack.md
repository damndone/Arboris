# Frozen Context Pack

Line: `v1-8-3-b1-native-containment`
Baseline SHA: `f07a4a4fe1d711089191493137643a1c85425aa9`

## Objective
# 通用自定义能力信任核心与运行边界设计

**状态**：修订边界已批准；旧 B0-R2 实现未接入产品

**日期**：2026-07-25

**修订日期**：2026-07-26

**设计原则**：B0 只建立小型、可审计、与能力类型无关的 authority contract 与 verifier；不在同一层执行不可信代码，也不把 Python 模块私有性误当作安全边界。

**配套规格**：
[`Capability Factory`](./2026-07-25-v1.8.3-capability-factory-design.md) ·
[`双层领域记忆`](./2026-07-25-v1.8.3-domain-memory-design.md)

**唯一执行入口**：
[`v1.8.3 Execution Control Plan`](../plans/2026-07-25-v1.8.3-execution-control.md)

---

## 0. 决策摘要

v1.8.3 将此前同时承担契约、身份、证据、执行和 OS 隔离的 B0 拆成两个独立安全层：

1. **B0 authority/verifier core**
   - 定义不可变、可规范化的 attestation envelope；
   - 定义可信 authority 的签发契约和 trust-root snapshot；
   - 验证真实性、版本、作用域、完整绑定、有效期、撤销游标和重放状态；
   - 不启动进程、不读取用户数据、不解释模型语义、不产生宿主隔离结论。
2. **B1 native containment adapter/broker**
   - 在独立可信执行边界内启动不可信代码；
   - 负责平台沙箱、文件系统、网络、进程树、资源和输出摄取；
   - 只有完成真实宿主 canary 后才能签发 containment/execution attestation；
   - 不具备声明保证时 fail closed，不回退到较弱 profile。

Capability Factory、`model.custom` 和未来其他能力只消费 B0 已验证的 claims。它们不能直接构造 `verified`、`source_eligible`、evidence、containment、lineage 或 admission 事实。

这次拆分参考 OpenAI Codex 将控制器与宿主选择的独立 Linux sandbox helper 分开的架构方向，但 Workbench 保留自己的协议、统计证据和 Graph/Run 语义：
[Codex Linux sandbox](https://github.com/openai/codex/blob/main/codex-rs/linux-sandbox/README.md)。

## 1. 威胁模型与可信边界

### 1.1 B0 要防止

- 调用方伪造受信任执行、证据、隔离或 eligibility 结论；
- 把针对一个输入、operation、policy 或 attempt 的凭证重用于另一个对象；
- 用旧的、过期的、已撤销的或未知 authority 凭证继续 admission；
- 用输出摘要之外的可变字段替换真实结果；
- 用自由 JSON、字符串 authority 或作者自测冒充服务端事实；
- 未知协议、未知认证方案或缺失绑定被静默接受。

### 1.2 B0 不声称防止

- Workbench 主进程或 authority 私钥/密钥提供者已经被攻破；
- 不可信代码已被 import 到 Workbench 主进程后仍能靠 Python 私有属性隔离；
- 未经 B1 真实 canary 的 OS 隔离实现；
- Capability Factory 的统计协议、消费者语义或人工准入本身有逻辑错误。

因此，不可信作者代码和第三方依赖永远不能进入 B0 所在的可信进程。`_private`、闭包、非导出名称和“只有内部调用”只能减少误用，不能构成恶意同进程代码的安全边界。

## 2. B0 的唯一职责

B0 只处理以下通用对象：

- `AttestationEnvelope`
- `AuthorityTrustSnapshot`
- `InvocationIntentClaims`
- `ExecutionResultClaims`
- `ContainmentClaims`
- `EvidenceClaims`
- `VerificationContext`
- `VerifiedClaims`
- `VerificationFailure`

B0 不理解：

- 模型、统计检验、变换或任何具体 capability kind；
- column、tensor、graph、event stream 等输入类型；
- parameter table、metric、series、artifact 等输出 facet；
- E0–E3 的统计含义或如何产生 independent oracle；
- Notebook、Draft、Run、Graph、Artifact、Trace 或 memory；
- 如何启动进程或选择 macOS/Linux 沙箱。

这些语义由后续版本化 Adapter、Capability Factory 和 B1 producer 负责。B0 只绑定其 contract/protocol digest，不解释其内容。

## 3. Authority 模型

### 3.1 Authority contract，不公开 minting helper

B0 产品包定义 `AttestationAuthorityPort` 契约，但不提供：

- module-level 默认 issuer；
- `server_b0_issuer()` 一类可直接取得签发器的函数；
- 接受调用方自报 trust tier 的构造器；
- unsigned、test-only 或弱认证的生产 fallback；
- 生产私钥、共享密钥或 secret 的生成、持久化与导出。

真实 signer 由受信任 Workbench bootstrap 或 B1 broker 持有。B0 verifier 只接收冻结的 `AuthorityTrustSnapshot` 和认证后 envelope。测试签发器只能存在于测试代码中，不能从产品包导出。

### 3.2 Trust-root snapshot

每次验证绑定不可变 trust snapshot，至少包含：

- `trust_snapshot_id`
- authority id 与允许签发的 attestation kinds；
- key id / authentication scheme；
- 生效和失效边界；
- authority scope；
- 单调 control sequence 或等价 freshness cursor；
- snapshot canonical digest。

未知 authority、kind 越权、scheme 不允许、key 失效或 snapshot 漂移全部拒绝。不得自动尝试旧 key、测试 key 或较弱认证方案。

### 3.3 真实性与密钥边界

`AttestationEnvelope` 必须携带认证方案、key id 和 authentication tag/signature。具体认证实现由受信任部署注册；B0 v1 不把某个密码库写死为产品语义，但生产 verifier 必须：

- 只允许显式 allowlist 中的方案；
- 使用恒定时间或方案规定的安全验证；
- 从受信任 key provider 解析验证材料；
- 拒绝缺失、未知、测试或降级方案；
- 不向调用方返回签发材料。

“结构和 hash 对得上”不是 authenticity。没有生产认证后端时，只能完成契约测试，不能声明 authority 安全验收通过。

## 4. Attestation envelope

所有 attestation 使用同一根 envelope：

```json
{
  "schema_version": "workbench_attestation_v1",
  "attestation_kind": "execution_result",
  "authority_id": "trusted-authority",
  "key_id": "active-key",
  "auth_scheme": "registered-scheme",
  "issued_at": "2026-07-26T00:00:00Z",
  "expires_at": "2026-07-26T00:05:00Z",
  "nonce": "opaque-single-use-value",
  "control_sequence": 42,
  "claims": {},
  "authentication": "opaque"
}
```

规范化规则必须固定：

- UTF-8；
- object key 排序；
- 不允许重复 key；
- 不允许 NaN、Infinity 或隐式类型转换；
- 时间统一为 UTC 规范格式；
- digest 使用带 domain separator 的版本化 preimage；
- authentication 字段不进入自身签名 preimage；
- 未知根字段和未知 schema version 默认拒绝。

canonical digest 必须由服务端重新计算，不能相信调用方附带的 digest。

## 5. 完整绑定

### 5.1 Invocation intent

`InvocationIntentClaims` 至少绑定：

- intent、capability revision 与 implementation revision；
- operation id；
- input bundle digest；
- input contract digest；
- requested output contract digest；
- runtime/policy digest；
- harness/protocol digest；
- expected containment profile；
- backend subject id；
- authorization/confirmation ref；
- attempt budget；
- nonce、expiry 和 control sequence。

operation、输入或策略变化必须产生新 intent，不能沿用旧凭证。

### 5.2 Execution result

`ExecutionResultClaims` 至少绑定：

- 原 invocation intent digest；
- execution attempt id 与 lease epoch；
- backend subject 与 containment assessment ref；
- implementation、harness 和 runtime policy digest；
- input bundle digest 与 operation id；
- terminal outcome；
- output bundle digest；
- bounded log/diagnostic digest；
- producer protocol revision；
- completion sequence。

`result_id` 必须包含 attempt identity 与 output bundle digest。仅依赖样本、policy 或同一 invocation 的身份不足以区分不同输出。

### 5.3 Containment

`ContainmentClaims` 至少绑定：

- OS、kernel、architecture；
- backend absolute identity、version 与 executable digest；
- containment profile、mount/network/process/resource policy digest；
- harness digest；
- canary suite revision 与完整结果 digest；
- assessment id、validity revision 和 control sequence。

B0 只验证这些 claims 来自允许的 containment authority 并与当前预期完全匹配。B0 不运行 canary，也不根据“backend 可发现”自行产生 supported-host 结论。

### 5.4 Evidence

`EvidenceClaims` 至少绑定：

- implementation revision；
- validation protocol revision/digest；
- input/fixture/oracle provenance digests；
- RNG algorithm、seed/stream derivation 与统计协议 digest（适用时）；
- assessment result；
- evidence tier；
- source eligibility；
- validity revision 与 control sequence。

E0–E3 的计算、独立性判断、holdout 和阈值属于 CF3。B0 只验证 evidence authority、签名、绑定与 freshness，绝不接受作者直接构造的 tier 或 eligibility。

## 6. Verifier 语义

验证顺序固定为：

1. 有界解析并拒绝重复/未知/非规范字段；
2. 检查 schema、kind、authority scope、key 和认证方案；
3. 重新规范化 claims 并验证 authenticity；
4. 检查 issued/expiry、control sequence 和当前 trust snapshot；
5. 与 `VerificationContext` 中的预期对象逐字段绑定；
6. 检查当前 validity cursor、revocation 和 supersession；
7. 检查 nonce/replay 状态；
8. 返回不可变 `VerifiedClaims` 或稳定错误。

验证不得：

- 修补缺失字段；
- 选择“最接近”的协议版本；
- 在 stronger profile 不可用时尝试 weaker profile；
- 把部分成功包装成 verified；
- 写入 Run、Artifact、Graph 或 registry；
- 触发执行。

### 6.1 验证与消费不是一回事

纯 verifier 不能单独证明 nonce 从未被消费。未来 dispatch 必须在同一 serializable control stream/CAS 中：

1. 重新验证所有 freshness cursors；
2. 比较 authorization expiry/revocation；
3. 原子消费 intent/nonce；
4. 创建唯一 `DispatchReservation` 和 attempt id。

B0 提供可验证 claims；CF4 control plane 提供 exactly-once reservation。两者不能用“先检查、后单独写状态”替代。

## 7. 通用扩展规则

新增 capability kind、operation、输入形态、输出 facet、证据协议或消费者能力时：

- 新增或升级相应语义 contract；
- 将 contract digest 绑定进 intent/result/evidence；
- 不修改 B0 根 envelope；
- 不向 B0 增加领域字段；
- 不通过自由 dict 绕过版本化；
- 未知版本 fail closed。

因此未来可以支持模型、检验、优化、模拟、变换、图算法或其他能力，而无需把它们伪装成 `fit/predict` 或表格数据。

## 8. B1 native containment adapter/broker

B1 是真实执行安全边界，独立于 B0 验收。它负责：

- 独立 helper/broker 与有界 IPC；
- 平台后端发现、绝对身份和版本固定；
- 只读解释器、依赖、harness 和输入；
- 私有输出目录与 no-follow 摄取；
- deny-by-default 宿主文件系统；
- 默认无网络；
- 固定环境变量、locale、线程和 RNG bootstrap；
- 整个进程树的 CPU、内存、PID、墙钟和输出预算；
- 崩溃、取消、超时和后代清理；
- host-read、目录枚举、越界写、网络和进程树 canary；
- 真实执行后签发 containment/execution attestation。

macOS 与 Linux 后端分别验收。任一宿主没有声明级保证时返回 typed unsupported；不得降级到现有 `code.execute` G3 或仅靠进程内检查。

## 9. 稳定错误语义

B0 至少提供：

- `CUSTOM_CAPABILITY_ATTESTATION_INVALID`
- `CUSTOM_CAPABILITY_ATTESTATION_KIND_UNSUPPORTED`
- `CUSTOM_CAPABILITY_AUTHORITY_UNTRUSTED`
- `CUSTOM_CAPABILITY_AUTHENTICATION_FAILED`
- `CUSTOM_CAPABILITY_BINDING_MISMATCH`
- `CUSTOM_CAPABILITY_ATTESTATION_EXPIRED`
- `CUSTOM_CAPABILITY_ATTESTATION_REVOKED`
- `CUSTOM_CAPABILITY_ATTESTATION_STALE`
- `CUSTOM_CAPABILITY_REPLAY_REJECTED`
- `CUSTOM_CAPABILITY_CONTROL_SEQUENCE_MISMATCH`

B1 与后续语义层提供自己的 containment、contract、evidence 和 consumer 错误。错误码不含具体算法、数据集、列名、软件或年份。

## 10. B0 实现边界

B0 产品实现最多包含以下职责：

- immutable contracts；
- canonical encoding/digest；
- authority/trust-root interfaces；
- verifier 与稳定错误。

不实现 runner、sandbox、registry、evidence producer、sample resolver、result projection 或 Agent operation。若实现过程中需要进程、路径挂载、网络、统计阈值、Notebook 或持久化控制流，说明职责已经越过 B0，必须进入对应后续 phase，而不是扩大 B0。

## 11. B0 验收

B0 只有同时满足以下条件才可接受：

- 产品代码不启动进程、不联网、不读取 capability 输入或宿主文件；
- 产品包没有公开 issuer、默认 signer、测试 key 或 unsigned fallback；
- arbitrary capability/operation/contract digests 可通过同一 envelope；
- input digest、operation、policy、backend、attempt 和 output digest 的任一变化都会导致 binding mismatch；
- 过期、撤销、stale、重放、未知 authority、kind 越权和认证失败均 fail closed；
- result identity 覆盖 attempt 与 output digest；
- statistical evidence 绑定服务端 protocol revision/digest，作者不能替换；
- verifier 不产生 evidence tier、source eligibility 或 containment 结论；
- 无生产认证后端时不宣称安全验收完成；
- 命名 gate、focused tests、diff check 和正式 FMS verify 通过。

B0 通过不等于 native containment、算法验证、Agent 接入或产品端到端已经完成。

## 12. 后续顺序

1. **B0**：authority contract、canonical attestation 与 verifier；
2. **B1**：native containment adapter/broker 与真实宿主 canary；
3. **CF1–CF3B**：需求解析、bundle、Adapter、独立证据和 scoped admission；
4. **CF4**：Notebook、确认、唯一 dispatch、Run/Graph/Artifact 与 `model.custom`；
5. **Integration**：共享注册、浏览器、full gate 和发布级证据。

CORE1 的本地 profile/project identity 保持独立，不因 B0 重整而重写。

## 13. 设计取舍

这个边界刻意让 B0 本身“不运行任何能力”。换来的收益是：

- 信任核心足够小，可以做完整审计和负面测试；
- OS containment 可以独立演进，不污染通用协议；
- 模型和数据结构不会固化进安全根契约；
- 以后替换 broker、增加平台或增加 capability kind 时不需要推翻 B0；
- 所有“已验证”“可作为 source”“宿主受支持”结论都有明确 producer，而不是由调用方自证。

## Boundary
- Affected paths: `backend/workbench/native_containment/executor_darwin.py`, `tests/test_native_containment_executor_darwin.py`, `backend/workbench/native_containment/__init__.py`
- Allowed paths: `backend/workbench/native_containment/executor_darwin.py`, `tests/test_native_containment_executor_darwin.py`, `backend/workbench/native_containment/__init__.py`
- Protected paths: `backend/workbench/agent`, `backend/workbench/http`, `backend/workbench/custom_capability`, `backend/workbench/capability_factory`, `frontend`, `scripts`, `tests/test_sandbox.py`, `tests/test_code_execution.py`
- Dependencies: `v1-8-3-b0-runtime-implementation`, `v1-8-3-cf3-validation-runtime`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_native_containment_contracts.py tests/test_native_containment_policy.py tests/test_native_containment_broker.py tests/test_native_containment_host.py tests/test_native_containment_darwin.py tests/test_native_containment_linux.py`, `git diff --check`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/native_containment`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_no_exercise_specific_naming.py`
- Known gates: `link-shared-deps requires an absolute worktree path before valid gate claims`, `sandbox-exec sandbox_apply Operation not permitted on this managed macOS host; classify as typed unsupported, not native acceptance`, `macOS and Linux containment are independently assessed; unit tests do not substitute for a real target-host canary`, `no weaker containment fallback; fail closed when backend guarantees are unavailable`, `broker and untrusted child never receive authority signing material, Workbench credentials, arbitrary host paths, inherited descriptors, network, or writable dependency tree`, `npx tsc output must not be piped before reading exit status`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
