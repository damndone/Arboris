# v1.7.3 LMM 独立评估证据规则

此目录只保存针对真实、干净候选提交生成的不可变证据；当前没有候选时，不得提交占位 manifest。性能记录由 `scripts/collect_v173_lmm_evidence.py` 在明确 `--candidate`、候选 worktree 和新 `--output` 路径下生成。

收集器只接受小写 40 位完整 SHA，且它必须精确等于干净 candidate worktree 的 `HEAD`、不是 C1.1 本身并且是 C1.1 后代。它在执行前和执行后都重新检查 `HEAD`、worktree 状态、C1 contracts/fixtures/central adapter protected diff，以及所有 LMM fixture 的 SHA-256。独立 Feature candidate 还必须满足严格路径 allowlist；中央 Integration adapter 的变更不能借此收集器静默放行。

收集器本身绝不 import candidate code。它先启动唯一的 `tests/evaluation/linear_mixed_effects/strict_runner.py` 子进程；该进程只接收最小环境、在任何 candidate import 前清空 provider/key 环境并拦截 socket 网络连接，要求每个 candidate module 的 `__file__` 位于 supplied candidate root。该子进程运行完整 candidate evaluation suite；只有 suite 的每个 required result 都通过后，才在同一隔离进程内执行 2 次 warmup、7 次 cold 和 7 次 hot local fit。所有 stdout/stderr、JUnit、fit contract 和 command receipt 都保存在与输出 JSON 同级的 `<output-stem>.artifacts/` 目录，永不使用会在结束时删除的性能临时目录。

`status: passed` 仅表示这一轮严格本地 candidate evaluation、性能测量和 post-execution audit 全部通过。它仍会写入 `acceptance.accepted: false` 与 `browser_acceptance: not_run`，直到独立浏览器场景和截图证据实际完成；没有 supplied candidate 或浏览器 acceptance 时，任何候选都不得接受。

每个 `eval-v173-lmm-XXX.yaml`（JSON 也是合法 YAML）必须只包含实际观察值，并包含以下 schema：

```yaml
schema_version: v173_lmm_performance_evidence_v2
evaluation_id: actual unique id
evaluated_commit: exact clean candidate commit
contract_lock_commit: 0251f0a30d984bdbb2cfab404e6c646deab60cae
evaluation_harness_commit: exact harness commit
supersedes: []
environment:
  python_version: observed
  statsmodels_version: observed
  node_version: observed or not_run
  os_family: observed
  dependency_lock_hash: observed hash
commands:
  - command: exact command
    exit_code: observed integer
    duration_seconds: observed number
    output_artifact: non-secret actual path
    output_sha256: actual SHA-256
fixtures:
  - path: every locked LMM fixture actually hashed
    sha256: actual SHA-256
results:
  contract_validation: passed | failed | not_run
  known_truth: passed | failed | not_run
  fault_injection: passed | failed | not_run
  agent_boundaries: passed | failed | not_run
  compare_restrictions: passed | failed | not_run
  deterministic_overclaim_checks: passed | failed | not_run
  performance_collection: passed | failed | not_run
  browser_acceptance: passed | failed | not_run
strict_isolation:
  network_guard: observed strict guard description
  provider_environment: observed clean-environment description
acceptance:
  accepted: false until browser acceptance is actually recorded
  reason: actual non-secret reason
artifacts:
  - path: actual non-secret evidence artifact
    sha256: actual SHA-256
generated_at: actual UTC timestamp
```

没有 protected-file verification、没有本地/fake provider 证明、或任何 required result 不是 `passed` 的候选不得接受。新的 candidate 行为变更必须生成新的 manifest，并在新文件的 `supersedes` 中引用旧 evaluation id；绝不回写旧证据。
