# v1.7.3 Verified Path Manifest

验证日期：2026-07-18。工作目录必须是 `.worktrees/integration-v1.7.3`。

## C1 Integration control surfaces

| 范围 | 已验证路径 | 当前事实 |
| --- | --- | --- |
| Pack / registry | `backend/workbench/engine/pack.py`, `registry.py`, `capabilities.py`, `stages/estimation.py` | `AnalysisPack` 拒绝未接线 diagnostics、recommended actions、report blocks 和 restrictions；model/capability 注册仍集中。 |
| Run transport | `backend/workbench/http/runs_routes.py`, `services/run_service.py`, `services/rerun_service.py`, `orchestrator/__init__.py`, `lineage/op_spec.py` | 没有 generic `model_options` transport。 |
| Analysis Loop | `backend/workbench/http/agent_routes.py`, `analysis_loop/contracts.py`, `compare.py`, `validation.py`, `recovery.py`, `resolver.py` | 当前 route、recovery、source resolution 和 Compare strategy 是 OLS clustered golden flow；Compare 还没有 `restricted`。 |
| Agent | `backend/workbench/agent/operations.py`, `agent/orchestrator.py` | 通用 confirmation/execution/reconcile 已存在；LMM 不得直接写入 OLS conditional。 |
| Frontend | `frontend/src/api.ts`, `frontend/src/runForm/RunForm.tsx`, `frontend/src/workbench/agent/AgentSurfaceContext.tsx`, `frontend/src/lineage/detail/sections/AnalysisLoopSection.tsx`, `frontend/src/workbench/registry/sectionRegistry.ts` | RunForm 无 LMM controls；Analysis Loop 展示仍含 OLS 文案；实际 section registry 是 `.ts`，不是旧清单中的 `.tsx`。 |

## C1 新边界（尚未创建）

- `backend/workbench/contracts/common/**`
- `backend/workbench/contracts/model/**`
- `backend/workbench/contracts/agent/**`
- `backend/workbench/analysis_loop/adapters.py`
- `backend/workbench/engine/packs/**`
- `backend/workbench/agent/recipes/**`
- `frontend/src/workbench/agent/featureRegistry.ts`
- `tests/contracts/**` 与 `tests/fixtures/models/linear_mixed_effects/**`

这些公共合同、thin seams 和 fixture 在 C1 后由 Integration / Evaluation 持有；Feature Lane 只读消费，不能自行补字段。

## 保护边界

- `tests/test_honest_did_adversarial.py`
- `tests/test_honest_did_sd_adversarial.py`
- `backend/workbench/agent/orchestrator.py`
- `backend/workbench/agent/operations.py`
- `backend/workbench/analysis_loop/contracts.py`
- `backend/workbench/analysis_loop/storage.py`
- `backend/workbench/engine/pack.py`
- `backend/workbench/engine/registry.py`
- `backend/workbench/engine/capabilities.py`
- `backend/workbench/graph_store.py`
- `frontend/src/workbench/agent/AgentSurfaceContext.tsx`
- `scripts/gate.sh`

除 C1 中的 Integration-owned 薄接缝外，任何 Feature Lane 均不得修改上述中心路径。
