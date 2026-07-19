# v1.7.3 LMM 独立评估证据规则

此目录只保存针对真实、干净 candidate commit 新建的 write-once evidence；当前没有 supplied candidate，禁止提交占位 manifest。性能记录只能由 `scripts/collect_v173_lmm_evidence.py` 在明确给出 `--candidate`、candidate worktree、candidate mode 和一个新的、位于 candidate/evaluator worktree 外的 `--output` 路径时生成。

## 输入、模式与未来集成政策

收集器只接受小写 40 位完整 SHA。该 SHA 必须精确等于干净 candidate worktree 的 `HEAD`、不是 C1.1 本身并且是 C1.1 后代。执行前后都会审计 candidate 的 `HEAD`、worktree status、允许 diff、全部 LMM fixture SHA-256，以及 evaluator 自己的 clean status 与固定 `HEAD`。所有 Git 审计使用最小、hermetic 环境：不继承 provider/Git 环境变量或用户/系统 Git config，明确禁用 fsmonitor、untracked cache 与 hooks。candidate fixture 的 `known_truth.csv` hash 必须与 strict runner 实际使用并写入 performance evidence 的文件相同。

- 默认 `feature_lane` 只接受 standalone Feature Lane allowlist 中的变更，C1 contracts、canonical fixtures 和 central adapter protected paths 均不可变。
- `integration_tip` 是给未来 Integration Release Train 的可审计候选模式，不是当前 candidate acceptance。它必须显式传入 `--candidate-mode integration_tip`；所给完整 SHA 必须精确等于干净 `integration/v1.7.3` worktree 的 `HEAD`，并且 diff 只能落在 collector 的窄 `INTEGRATION_ALLOWED_CANDIDATE_PREFIXES`。C1 contracts、canonical fixtures、collector/evaluator、`scripts/gate.sh` 与 Honest-DiD adversarial tests 在此模式下仍受保护。
- integration-tip evidence 的指定 owner 是 **v1.7.3 Integration Release Train owner**；指定 trigger 是“Integration Release Train 从已有独立 lane evidence 的 merge-queue entries 组装出干净 `integration/v1.7.3` tip 之后”。命令能检查 SHA、分支、clean status 和 allowlist，不能自行证明该 owner 已授权或该 trigger 已发生。

任何模式的 manifest 都保持 `acceptance.accepted: false`。当前没有运行或接受 candidate；WO-B 的私有 `FigureContext` 形状也不是冻结的 Integration canonical contract，不能据此接受 B/C integrated candidate。

## strict 执行与 best-effort 进程保护

父收集器绝不 import candidate code。它启动唯一的 `tests/evaluation/linear_mixed_effects/strict_runner.py` 子进程；该进程在 candidate import 前清空 provider-bearing environment、切换隔离 HOME，并安装 scoped、进程内 Python guard：socket connect 路径以及 `subprocess`/常见 `os` process-spawn 路径被阻断。

这是 best-effort、process-level Python guard：它不是 OS-level sandbox，也不构成“所有网络均不可用”或“绝无 provider 调用”的证明。

strict runner 只显式运行六个 candidate-facing test 文件：contract validation、known truth、fault injection、Agent boundaries、compare restrictions、deterministic overclaim checks。meta/guardrail 测试不进入 strict command。只有 JUnit 派生的六个结果全部通过后，才在同一进程执行 2 次 warmup、7 次 cold 与 7 次 hot local fit。

runner result 必须是 C1 `PacketEnvelope`，并固定为 `linear_mixed_effects.result` / `1.0` / `linear_mixed_effects@1.0`；performance 和 known-truth 均只从已解析 payload 读取事实，且 run-root 的 JSON 必须与返回 envelope 完全相同。fault fixtures 使用完整 versioned diagnostic envelope；Agent fixture 使用 C1.1 server-owned `model_options_binding` 和完整 `LmmDiagnostic`，缺失、篡改、错误 owner binding 或畸形 diagnostic 都必须 fail closed。

父收集器以二进制 pipe、独立 process session 和两个并发 reader 启动 strict runner；它不会把 child stream 解码或保存在内存中。每个 stream 的 durable 计数最多报告 65,536 bytes，另有每 stream 1 MiB hard limit。超限时收集器会终止该独立 process group、继续 drain 已经写入 pipe 的字节并拒绝 candidate；若无法安全 signal 或 drain，也会 fail closed。只要 child 已启动，drain 失败会以静态 `capture_error_code` 和不含原文的 digest metadata 落盘，再写入 failed manifest；启动本身失败则不会伪造 stream evidence。

## 非原始流证据

raw candidate-facing pytest stdout/stderr、以及所有 Git audit stdout/stderr，都不会写入 durable artifact 或 outer manifest。`strict-suite.output.json` 仅摘要 Python `redirect_stdout` / `redirect_stderr` 所接收的文本流，**不能**覆盖 `os.write` 等 FD 级写入；`strict-runner.output.json`（collector metadata v2）才是 strict runner FD 1/2 的二进制、OS-level 摘要，记录 per-stream SHA-256、65,536-byte reported count、truncation、1 MiB hard-limit flag 和静态 `capture_error_code`，不记录 stream 文本。Git command records 保留其命令、exit code、duration、capture policy、hash/byte count，不记录 stream 文本。outer manifest 仅抄录这些 hashes 与 inner pytest command、exit code、duration。

原始 JUnit XML 仅在唯一的 `0700` 私有临时目录中供 strict runner 解析；无论成功或异常都会在 `finally` 中删除 XML 和空目录。durable evidence 只保留 `strict-suite.junit.summary.json` 的结构化结果和 testcase counts；raw XML 缺失或不可解析时也只落下安全的零计数 summary，再由 parent 拒绝。parent 会重新校验 metadata/summary 的 path、hash、strict JSON/schema 和结果一致性。guardrail 测试用模拟 secret、hostile `core.fsmonitor` 与权限检查验证原始内容不会进入 artifact tree、manifest 或可遍历临时位置。

这不是全盘 secret 扫描或所有 evidence 内容均无敏感信息的承诺：candidate 生成的结果/性能 JSON 仍应按受控本地证据处理。这里的保证仅限于收集器和 strict runner 不持久化其捕获的 raw candidate/Git stdout/stderr，也不会把候选控制的异常文本写入 durable strict suite result。

## 写入排他性与 P2 残余

CLI 在任何 collection 写入前，先完成 output/derived-artifact-root location validation，再通过 `O_CREAT | O_EXCL` 建立同目录的 `.output-name.reservation`。最终 manifest/failure payload 使用同目录临时文件、`fsync` 和 `os.link` 的 no-clobber create；它不是 `exists()` 后再 `os.replace()`。因此同一正常文件系统上的并发 collector 不能相互覆盖已存在 output，reservation 会在正常成功或失败路径释放。

仍有明确的 **P2 残余**：portable Python 文件 API 无法在恶意同权限进程替换父目录/路径、符号链接攻击、跨主机文件系统异常或进程崩溃后遗留 reservation 的情形下给出绝对排他性或物理不可变性。collector 不会自动清理 stale reservation；需要先人工检查，再显式移除。最终 no-clobber link 可阻止普通已存在 target 被覆盖，但不能替代受控目录权限、审计存储或操作系统级锁。

Git audit 已使用 hermetic environment/config 并丢弃 durable raw output，但其解析路径仍使用 text-mode `subprocess.run`，尚未拥有 strict-runner 的二进制 hard quota 或无效 UTF-8 failure manifest 行为。它必须作为单独 P2 通过 binary bounded parser（含严格 `-z`/解析策略）解决；本 WO-D 候选不把该残余表述为已经修复。

## 状态与 manifest 模板

`status: passed` 仅表示一轮严格本地 candidate evaluation、performance、candidate/evaluator post-audit 都通过。它仍写入 `acceptance.accepted: false` 与 `browser_acceptance: not_run`，直到独立 browser scenario 和 screenshot evidence 实际完成。没有 supplied candidate 或 browser acceptance 时，任何 candidate 都不得接受。

每个 `eval-v173-lmm-XXX.yaml`（JSON 也是合法 YAML）必须只包含实际观察值，并至少包含：

```yaml
schema_version: v173_lmm_performance_evidence_v3
evaluation_id: actual unique id
evaluated_commit: exact clean candidate commit
candidate_worktree: actual clean candidate worktree
candidate_mode: feature_lane | integration_tip
integration_evidence_policy: null | { owner: exact policy owner, trigger: exact policy trigger }
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
  stdout_sha256: actual SHA-256 of discarded captured stdout
  stderr_sha256: actual SHA-256 of discarded captured stderr
  junit_summary_sha256: actual SHA-256 of structural JUnit summary
commands:
  - command: exact outer command
    exit_code: observed integer
    duration_seconds: observed number
    capture_policy: actual Git or strict-runner policy
    stdout_sha256: actual SHA-256 when the command is strict-runner
    stderr_sha256: actual SHA-256 when the command is strict-runner
    output_sha256: actual SHA-256 when the command is Git audit
    stdout_bytes_observed: observed integer
    stderr_bytes_observed: observed integer
    stdout_truncated: observed bool when the command is strict-runner
    stderr_truncated: observed bool when the command is strict-runner
    stdout_hard_limit_exceeded: observed bool when the command is strict-runner
    stderr_hard_limit_exceeded: observed bool when the command is strict-runner
    capture_error_code: null or static safe code when the command is strict-runner
strict_isolation:
  network_guard: observed scoped Python guard description
  process_spawn_guard: observed scoped Python guard description
  provider_environment: observed clean-environment description
  limitations: no OS-level sandbox or all-network/no-provider proof
acceptance:
  accepted: false until browser acceptance is actually recorded
  reason: actual non-secret reason
artifacts:
  - path: actual controlled local evidence artifact
    sha256: actual SHA-256
generated_at: actual UTC timestamp
```

没有完整 protected/evaluator/candidate audit、没有可校验 structural JUnit summary 或 inner metadata、任何 required result 不是 `passed`，或没有 browser acceptance 的 candidate 都不得接受。新 candidate 行为变更必须生成新的 manifest，并在新文件的 `supersedes` 中引用旧 evaluation id；绝不回写旧证据。
