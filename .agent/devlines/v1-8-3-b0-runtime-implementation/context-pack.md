# Frozen Context Pack

Line: `v1-8-3-b0-runtime-implementation`
Baseline SHA: `af05f1857d916ac5279821f2a8a21a5e511b5059`

## Objective
# B0 通用自定义能力运行时基础

**状态**：设计已批准，等待实现计划

**基线设计**：`docs/superpowers/specs/2026-07-25-model-custom-contract-design.md`

## 目标

为 Agent 后续补齐 Workbench 缺失算法建立通用、隔离、可验证的执行基础。该基础不以单方程、系数表、经典标准误、p-value、某个示例模型或逐字节结果相等为根契约。

本开发线只交付三个切片：

1. **通用契约与身份**
   - `custom_capability_contract_v1`
   - 类型化输入角色
   - observation identity
   - `parameter_table`、`metric_set`、`indexed_series`、`structured_artifact`
   - 全面有界的输出校验
   - 作者字段与服务端保留字段隔离
   - 覆盖代码、运行时、依赖 manifest、harness、契约和策略的 `handler_bundle_sha256`
2. **可复现性与证据**
   - `exact | numeric | statistical` profile
   - 分字段 comparator
   - 作者自测与独立 evidence packet 分离
   - 服务端派生的 E0/E1/E2/E3
   - E1 强制 `experimental`、`source_eligible=false`
3. **严格运行边界**
   - 独立 `untrusted_capability_v1` profile
   - deny-by-default 宿主文件读取
   - 无网络
   - 密封解释器、依赖、输入、harness 和输出
   - host-read canary
   - 进程树级资源策略与 fail-closed admission
   - 有界 stdout、stderr、JSON 和输出文件

## 架构约束

- 通用运行时只执行密封 `input bundle -> output bundle`，不理解具体模型。
- `model.custom` 是后续第一个可信适配器；Agent 代码本身不是进程内 `ModelHandler`。
- 当前全局 `MODEL_REGISTRY` 不动态注册 Agent 代码，也不允许覆盖原生 model type。
- 报告、诊断、图表、Compare 和 rerun 支持必须由后续适配器显式声明，不能因 bundle 可运行而自动继承。
- 服务端独占 lineage、result/source/artifact 身份、样本指纹、授权、信任等级与 `source_eligible`。
- `code_sha256` 仅为源码证据；历史 rerun 必须绑定完整 bundle identity。
- 双跑不是统一字节等值闸门；验证按 exact、numeric 或 statistical 语义执行。
- 作者自带 fixture、expected 和 authority 只能获得 E1，不能单独产生 verified 或 promotion 资格。
- 现有 `code.execute` G3 行为不在本开发线中被静默修改；新能力使用独立且更严格的 profile。
- 无法提供所声明隔离和资源保证的宿主必须拒绝执行。

## 本开发线不实现

- `dependency.request`
- chain-scoped handler registry
- `model.custom` Agent operation 或自然语言入口
- UI
- 报告、诊断、图表或 Compare 适配
- `pack.promote`
- `WORKFLOW_STEP_SPEC_CONTRACTS` 变更
- 任一具体新模型的产品能力

## 完成边界

- 多种互不等价的 fixture 证明根契约不强迫所有算法伪装成 OLS。
- NaN/Inf、服务端字段伪造、样本错位、未知 facet、输出超限全部 fail closed。
- exact、numeric、statistical profile 都有正反测试。
- E1 无法越权为 verified 或 source-eligible。
- bundle 任一身份成分改变都会改变 digest。
- 宿主 sentinel 不可读、不可枚举；网络和越界写入不可用。
- 子进程树、CPU、内存、PID、墙钟与输出总量受策略约束；保证不足时拒绝。
- 不接 Agent、dependency、registry、workflow 或 promotion。
- `tests/test_no_exercise_specific_naming.py` 和相关 sandbox、`code.execute` 回归测试通过。

## Boundary
- Affected paths: `backend/workbench/custom_capability/__init__.py`, `backend/workbench/custom_capability/contract.py`, `backend/workbench/custom_capability/identity.py`, `backend/workbench/custom_capability/evidence.py`, `backend/workbench/custom_capability/runner.py`, `backend/workbench/custom_capability/sandbox.py`, `tests/test_custom_capability_contract.py`, `tests/test_custom_capability_identity.py`, `tests/test_custom_capability_evidence.py`, `tests/test_custom_capability_runner.py`, `tests/test_custom_capability_sandbox.py`
- Allowed paths: `backend/workbench/custom_capability/__init__.py`, `backend/workbench/custom_capability/contract.py`, `backend/workbench/custom_capability/identity.py`, `backend/workbench/custom_capability/evidence.py`, `backend/workbench/custom_capability/runner.py`, `backend/workbench/custom_capability/sandbox.py`, `tests/test_custom_capability_contract.py`, `tests/test_custom_capability_identity.py`, `tests/test_custom_capability_evidence.py`, `tests/test_custom_capability_runner.py`, `tests/test_custom_capability_sandbox.py`
- Protected paths: `backend/workbench/agent`, `backend/workbench/engine/registry.py`, `backend/workbench/sandbox.py`, `backend/workbench/code_execution.py`, `backend/workbench/frozen_containment.py`, `frontend/src`, `scripts/gate.sh`, `docs/superpowers/specs/2026-07-25-model-custom-contract-design.md`, `docs/superpowers/specs/2026-07-25-custom-capability-foundation-objective.md`, `docs/superpowers/specs/v1.8.3`
- Dependencies: `docs/superpowers/specs/2026-07-25-model-custom-contract-design.md`, `docs/superpowers/specs/v1.8.3/README.md`, `backend/workbench/sandbox.py`, `backend/workbench/frozen_containment.py`, `.agent/development/global_rules.md`
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/test_custom_capability_contract.py tests/test_custom_capability_identity.py tests/test_custom_capability_evidence.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_custom_capability_runner.py tests/test_custom_capability_sandbox.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_sandbox.py tests/test_code_execution.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_no_exercise_specific_naming.py`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python scripts/devline_control.py verify --line v1-8-3-b0-runtime-implementation`
- Known gates: `New worktree must run bash scripts/link-shared-deps.sh with its absolute worktree path before tests.`, `Use LC_ALL=en_US.UTF-8 and LANG=en_US.UTF-8 for Python and gate commands under the repository path.`, `Strict untrusted-capability profile may be unavailable on the managed host; unsupported guarantees must fail closed and native-host acceptance remains required.`, `scripts/gate.sh refuses to run while a Vite dev server or another Vitest process is live.`, `Run npx tsc --noEmit without piping to tail and inspect the compiler exit code directly.`, `No real provider or external API calls are permitted in this line.`, `Full scripts/gate.sh remains a release-quality gate and does not replace sandbox or model acceptance evidence.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
