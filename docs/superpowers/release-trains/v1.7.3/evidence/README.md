# v1.7.3 LMM 独立评估证据规则

此目录只保存针对真实、干净候选提交生成的不可变证据；当前没有候选时，不得提交占位 manifest。性能记录由 `scripts/collect_v173_lmm_evidence.py` 在明确 `--candidate`、候选 worktree 和新 `--output` 路径下生成。收集器拒绝脏 worktree、非 C1.1 后代、候选 SHA 与 HEAD 不一致、受保护路径变更、缺失 runner 或任何被阻断的网络访问。

每个 `eval-v173-lmm-XXX.yaml`（JSON 也是合法 YAML）必须只包含实际观察值，并包含以下 schema：

```yaml
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
  - path: tests/fixtures/models/linear_mixed_effects/known_truth.csv
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
artifacts:
  - path: actual non-secret evidence artifact
    sha256: actual SHA-256
generated_at: actual UTC timestamp
```

没有 protected-file verification、没有本地/fake provider 证明、或任何 required result 不是 `passed` 的候选不得接受。新的 candidate 行为变更必须生成新的 manifest，并在新文件的 `supersedes` 中引用旧 evaluation id；绝不回写旧证据。
