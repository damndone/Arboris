# WO-D Independent Evaluation Completion Report

状态：harness 已交付；没有 supplied Feature/Integration candidate，因此没有任何候选被接受。

## 不可变起点与提交

- release baseline：`4b2e6c1d9ddd289005b84c186255fec2e9cbd86a`
- branch start / contract lock：`0251f0a30d984bdbb2cfab404e6c646deab60cae`
- governance receipt（只读）：`f25ffd119df91479aabfcebcb549a47a1153e227`
- WO-D branch：`test/v173-evaluation-harness`
- evaluation harness commit：`f78430edb586bc87416e756e36450dfc4b476dfe`
- candidate commit：未提供。为证明 fail-closed 行为，收集器以 harness commit `f78430edb586bc87416e756e36450dfc4b476dfe` 作为 supplied SHA 运行并拒绝它，因为该提交没有 `workbench.engine.packs.linear_mixed_effects`；这不是候选验收。

## 精确改动

`f78430edb586bc87416e756e36450dfc4b476dfe` 新增：

- `tests/evaluation/linear_mixed_effects/**`：contract compatibility、known truth、fault injection、Agent boundary、compare restriction 和 report-claim 检查；缺失 Feature module 时本地 authoring run 明确 skip，严格候选模式则失败。
- `scripts/collect_v173_lmm_evidence.py`：要求候选 SHA 和干净候选 worktree，验证 C1.1 祖先关系和 protected paths，执行 2 warmups、7 cold fits、7 hot fits，并输出非 secret JSON 证据。
- `docs/superpowers/release-trains/v1.7.3/evaluation/browser-scenario.md`：十步人工 in-app browser 验收。
- `docs/superpowers/release-trains/v1.7.3/golden-change-approvals/README.md`：golden 变更独立审批记录规则。
- `docs/superpowers/release-trains/v1.7.3/evidence/README.md`：实际证据 manifest schema 与不可覆写规则。

## RED → GREEN 记录与验证

| 命令 | 实际结果 |
| --- | --- |
| `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/evaluation/linear_mixed_effects -q`（实现前） | exit 4；目录不存在，`no tests ran`。 |
| `... pytest tests/evaluation/linear_mixed_effects/test_known_truth.py -q`（首个 RED） | exit 2；缺少 `workbench.engine.packs.linear_mixed_effects`，符合尚未提供 Feature candidate 的预期。 |
| 同一 known-truth 命令（加入 candidate gate 后） | exit 0；`1 skipped`，不会把不存在的 Feature 误报为通过。 |
| `... pytest tests/evaluation/linear_mixed_effects -q` | exit 0；首次完整 harness 运行 `6 passed, 23 skipped`。静态 C1 checks 已执行；candidate-only checks 保持 skip-safe。 |
| `... pytest tests/contracts/test_lmm_contracts.py tests/contracts/test_lmm_error_contract.py tests/contracts/test_lmm_canonical_packets.py tests/models/linear_mixed_effects/test_feasibility.py tests/test_lmm_extension_seams.py tests/test_model_options_owner_binding.py -q` | exit 0；`81 passed, 7 warnings in 12.09s`。warnings 为既有 FastAPI deprecation 和 statsmodels singular/boundary warnings。 |
| `... python -m compileall -q scripts/collect_v173_lmm_evidence.py tests/evaluation/linear_mixed_effects` | exit 0。 |
| `... python scripts/collect_v173_lmm_evidence.py --candidate f78430edb586bc87416e756e36450dfc4b476dfe --candidate-worktree /Users/jiayuanren/项目规划/.worktrees/v173-evaluation-harness --output /private/tmp/v173-lmm-no-candidate-failure.json` | exit 1，正确拒绝：`supplied candidate does not provide required module: workbench.engine.packs.linear_mixed_effects`。failure artifact SHA-256：`70de5a54fd586a391403be470c44b2a898b5a3c93f549ed5b613440cabd56e18`。 |

最终 harness suite：`PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/evaluation/linear_mixed_effects -q` exit 0，`7 passed, 23 skipped in 0.94s`。这些 skipped 都是尚未提供 candidate-only Feature module 的明确 skip；它们不构成 candidate acceptance。最终 `compileall` 和 collector `--help` 也均 exit 0。

## Protected-file audit

对 `0251f0a30d984bdbb2cfab404e6c646deab60cae..f78430edb586bc87416e756e36450dfc4b476dfe` 的以下路径执行 `git diff --name-only -- <protected paths>`，结果为空：

- `backend/workbench/agent/orchestrator.py`
- `backend/workbench/agent/operations.py`
- `backend/workbench/analysis_loop/contracts.py`
- `backend/workbench/analysis_loop/storage.py`
- `backend/workbench/engine/pack.py`
- `backend/workbench/engine/registry.py`
- `backend/workbench/engine/capabilities.py`
- `backend/workbench/graph_store.py`
- `frontend/src/workbench/AgentSurfaceContext.tsx`
- `scripts/gate.sh`
- `tests/test_honest_did_adversarial.py`
- `tests/test_honest_did_sd_adversarial.py`
- `docs/superpowers/release-trains/v1.7.3/contract-lock.yaml`

`git diff --check` 为空。没有读取真实 API key、调用真实 provider、安装依赖、push、PR、merge、tag 或 release。

## 已知限制、集成风险与回滚

- Browser、真实 candidate 性能与完整 candidate acceptance 尚未执行；没有干净的 supplied Feature/Integration SHA 时不得创建 `eval-v173-lmm-XXX` manifest，也不得接受候选。
- 未来 candidate 必须提供计划约定的 runner、input、diagnostics 和 Agent recipe APIs；若 API/统计事实不符合，测试会失败，WO-D 不修复 Feature Lane。
- report-claim 和 runtime compare adapter 属于 Integration acceptance；本 harness 通过确定性检查暴露问题，但不修改中央 narrative/adapter 文件。
- candidate worktree 必须干净、HEAD 精确等于 supplied SHA、从 C1.1 派生且 protected audit 为空；收集器在任何一个条件失败时 exit nonzero。
- 回滚方式：在后续集成分支对 `f78430edb586bc87416e756e36450dfc4b476dfe`（以及本报告的独立文档提交）做普通 `git revert`；不改 C1.1 contracts、fixtures 或 receipt，也不删除既有证据。
