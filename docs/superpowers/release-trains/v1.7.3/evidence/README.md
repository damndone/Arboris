# v1.7.3 LMM 独立评估证据规则

此目录只保存针对真实、干净 candidate commit 生成的不可变证据；当前没有 supplied candidate，禁止提交占位 manifest。性能记录由 `scripts/collect_v173_lmm_evidence.py` 在明确 `--candidate`、candidate worktree 和新的 worktree 外 `--output` 路径下生成。

收集器只接受小写 40 位完整 SHA，且它必须精确等于干净 candidate worktree 的 `HEAD`、不是 C1.1 本身并且是 C1.1 后代。执行前后都会审计 candidate 的 `HEAD`、worktree status、C1 contracts/fixtures/central adapter protected diff、Feature allowlist 与全部 LMM fixture SHA-256；同时审计 evaluator 自己的 clean status 与固定 `HEAD`。candidate fixture 的 `known_truth.csv` hash 必须与 strict runner 实际使用并写入 performance evidence 的文件相同。

父收集器绝不 import candidate code。它启动唯一的 `tests/evaluation/linear_mixed_effects/strict_runner.py` 子进程；该进程在 candidate import 前清空 provider-bearing environment、切换隔离 HOME，并安装 scoped、进程内 Python guard：socket connect 路径以及 `subprocess`/常见 `os` process-spawn 路径被阻断。它不是 OS-level sandbox，也不构成“所有网络均不可用”或“绝无 provider 调用”的证明。

strict runner 只显式运行六个 candidate-facing test 文件：contract validation、known truth、fault injection、Agent boundaries、compare restrictions、deterministic overclaim checks。meta/guardrail 测试不进入 strict command。JUnit 必须存在、可解析、无 skip、无非 candidate testcase，并且六个结果类别各至少有一个 testcase；否则 strict evaluation 失败。只有这些结果全部通过后，才在同一进程执行 2 次 warmup、7 次 cold 与 7 次 hot local fit。

runner result 必须是 C1 `PacketEnvelope`，并固定为 `linear_mixed_effects.result` / `1.0` / `linear_mixed_effects@1.0`；performance 和 known-truth 均只从已解析 payload 读取事实，且 run-root 的 JSON 必须与返回 envelope 完全相同。fault fixtures 使用完整 versioned diagnostic envelope；Agent fixture 使用 C1.1 server-owned `model_options_binding` 和完整 `LmmDiagnostic`，缺失/篡改/错误 owner binding 或畸形 diagnostic 都必须 fail closed。

runner-owned stdout/stderr/JSON 以原子写入完成；JUnit 及全部 inner artifact 在 parent 接受前都会被重新校验 path、hash、JSON/schema 与 JUnit 内容。外层 manifest 直接保留 inner pytest command、exit code、duration 和 stdout/stderr/JUnit hashes。所有 evidence 保存在与输出 JSON 同级的 `<output-stem>.artifacts/` 目录，永不使用结束时删除的性能临时目录。

`status: passed` 仅表示一轮严格本地 candidate evaluation、performance、candidate/evaluator post-audit 都通过。它仍写入 `acceptance.accepted: false` 与 `browser_acceptance: not_run`，直到独立 browser scenario 和 screenshot evidence 实际完成；没有 supplied candidate 或 browser acceptance 时，任何 candidate 都不得接受。

每个 `eval-v173-lmm-XXX.yaml`（JSON 也是合法 YAML）必须只包含实际观察值，并至少包含：

```yaml
schema_version: v173_lmm_performance_evidence_v2
evaluation_id: actual unique id
evaluated_commit: exact clean candidate commit
candidate_worktree: actual clean candidate worktree
contract_lock_commit: 0251f0a30d984bdbb2cfab404e6c646deab60cae
evaluation_harness_commit: exact clean evaluator commit
supersedes: []
environment:
  python_version: observed
  statsmodels_version: observed
  node_version: observed or not_run
  os_family: observed
  dependency_lock_hash: observed hash
fixtures:
  - path: candidate fixture actually hashed and used
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
inner_pytest:
  command: exact inner pytest command
  exit_code: observed integer
  duration_seconds: observed number
  stdout_sha256: actual SHA-256
  stderr_sha256: actual SHA-256
  junit_sha256: actual SHA-256
commands:
  - command: exact outer command
    exit_code: observed integer
    duration_seconds: observed number
    output_sha256: actual SHA-256
strict_isolation:
  network_guard: observed scoped Python guard description
  process_spawn_guard: observed scoped Python guard description
  provider_environment: observed clean-environment description
  limitations: no OS-level sandbox or all-network/no-provider proof
acceptance:
  accepted: false until browser acceptance is actually recorded
  reason: actual non-secret reason
artifacts:
  - path: actual non-secret evidence artifact
    sha256: actual SHA-256
generated_at: actual UTC timestamp
```

没有完整 protected/evaluator/candidate audit、没有可校验 JUnit 或 inner artifacts、任何 required result 不是 `passed`，或没有 browser acceptance 的 candidate 都不得接受。新 candidate 行为变更必须生成新的 manifest，并在新文件的 `supersedes` 中引用旧 evaluation id；绝不回写旧证据。
