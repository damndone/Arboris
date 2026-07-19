# WO-D Independent Evaluation Completion Report

状态：WO-D evaluation harness correction 已提交；没有 supplied Feature candidate、没有 B/C integrated candidate、没有 browser acceptance。因此没有任何 candidate 被接受或标记为 release-ready。

## 不可变起点与提交

- release baseline：`4b2e6c1d9ddd289005b84c186255fec2e9cbd86a`
- branch start / C1.1 contract lock：`0251f0a30d984bdbb2cfab404e6c646deab60cae`
- governance receipt（只读）：`f25ffd119df91479aabfcebcb549a47a1153e227`
- WO-D branch：`test/v173-evaluation-harness`
- prior strict correction：`8b23cf25a854aad89dc6f13fa837911518b07c17`
- current code correction：`020db1a36beebf3d9c1cf99666e906ae4277503d`（`test: close WO-D strict evaluation boundaries`）
- supplied candidate commit：未提供。

## 已收紧的评估边界

- runtime/performance/known-truth runner result 都通过 `PacketEnvelope.from_dict(result)`，固定核验 `linear_mixed_effects.result` / `1.0` / `linear_mixed_effects@1.0`，并且只读取解析后的 payload。run-root `linear_mixed_effects_contract.json` 必须与同一 parsed envelope 完全相等。
- fault fixtures 读取 candidate-root 下的 canonical versioned diagnostic envelopes，并以完整 `LmmDiagnostic` 复核；Agent fixtures 使用完整 C1.1 server-owned binding 与完整 diagnostic fields。缺失、hash 篡改、错误 owner binding 和畸形 diagnostic 的候选行为均被要求 fail closed，不能产生 proposal。
- strict suite 不再执行整个目录后容忍 meta skip，而是只显式运行六个 candidate-facing 文件。JUnit 缺失、不可解析、任意 skip、非 candidate testcase 或任一 required result 零 testcase 都失败。
- strict runner 会在 candidate import 前清空环境并阻断 scoped Python socket/process-spawn 路径；`subprocess.Popen` 和 `os.system` canary 均已覆盖。该措施仅是 process-level Python guard，不是 OS sandbox，不证明所有 egress 被阻断，也不证明绝无 provider 调用。
- collector 在前后审计 candidate 和 evaluator 的 clean status/HEAD；校验 strict payload schema、candidate root/SHA、精确 required result keys、JUnit/artifact hash/path，以及 candidate fixture hash 与实际使用的 fixture。outer manifest 直接记录 inner pytest command、exit code、duration、stdout/stderr/JUnit hashes。

## 代码 correction 的精确修改文件

- `scripts/collect_v173_lmm_evidence.py`
- `tests/evaluation/linear_mixed_effects/_fixtures.py`
- `tests/evaluation/linear_mixed_effects/strict_runner.py`
- `tests/evaluation/linear_mixed_effects/test_agent_boundaries.py`
- `tests/evaluation/linear_mixed_effects/test_candidate_import_boundary.py`
- `tests/evaluation/linear_mixed_effects/test_collector_guardrails.py`
- `tests/evaluation/linear_mixed_effects/test_compare_restrictions.py`
- `tests/evaluation/linear_mixed_effects/test_contract_compatibility.py`
- `tests/evaluation/linear_mixed_effects/test_fault_injection.py`
- `tests/evaluation/linear_mixed_effects/test_fixture_provenance.py`
- `tests/evaluation/linear_mixed_effects/test_known_truth.py`
- `tests/evaluation/linear_mixed_effects/test_strict_candidate_entrypoint.py`
- `tests/evaluation/linear_mixed_effects/test_strict_runner_guardrails.py`

没有修改 central source、C1 contracts、canonical fixtures、protected files 或任何 Feature/Integration Lane 文件。

## 验证记录

| 命令 | 实际结果 |
| --- | --- |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/evaluation/linear_mixed_effects -q` | exit 0；`40 passed, 27 skipped in 7.94s`。本地 authoring mode 对未提供 candidate-only module 保留 skip；strict mode 不允许它们 skip。 |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/evaluation/linear_mixed_effects tests/contracts/test_lmm_contracts.py tests/contracts/test_lmm_error_contract.py tests/contracts/test_lmm_canonical_packets.py tests/test_lmm_extension_seams.py tests/test_model_options_owner_binding.py -q` | exit 0；`120 passed, 27 skipped, 3 warnings in 16.59s`。warnings 是既有 FastAPI deprecation。 |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests -q` | exit 1；`20 failed, 2232 passed, 35 skipped, 47 warnings in 461.86s`。失败全部位于既有 code-execution/sandbox tests；首次独立复现为 `SandboxResult(returncode=71, stderr='sandbox-exec: sandbox_apply: Operation not permitted')`。当前受管环境拒绝 OS sandbox profile；WO-D 未修改 sandbox/central code，也没有用 workaround 掩盖该 blocker。 |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/test_sandbox.py -q -x` | exit 1；首个失败在 0.04s，复现同一 `sandbox-exec` operation-not-permitted 环境错误。 |
| `git diff --check` | exit 0（code correction 提交前与 report-only 更新前）。 |

## 未接受项与集成风险

- 没有真实 supplied candidate，因此没有生成 `eval-v173-lmm-XXX` manifest、performance evidence 或 browser screenshot；测试中的临时 candidate 仅验证 fail-closed guardrail，不构成 acceptance。
- browser scenario 尚未执行，`browser_acceptance` 必须保持 `not_run`，`acceptance.accepted` 必须保持 `false`。
- WO-D 只验证 evaluator 证据边界。它不把任何 Feature Lane 私有输出形状当作冻结 Integration contract；尤其不因 WO-B 的私有 FigureContext 形状而认可 B/C integrated candidate。
- 全量 test 的 sandbox 失败需要具备 OS sandbox profile 应用权限的环境来处理；这超出 WO-D 的 allowed files 和本 correction 的授权范围。
- 即使未来 candidate 通过 strict evidence，仍需要独立 browser scenario、截图 hash 和新的不可覆写 manifest，才可另行讨论 acceptance。

没有读取真实 API key、调用真实 provider、安装依赖、push、PR、merge、tag 或 release。
