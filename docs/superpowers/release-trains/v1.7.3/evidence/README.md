# v1.7.3 LMM 独立评估证据规则

此目录只保存针对真实、干净 candidate commit 新建的 write-once evidence；当前没有 supplied candidate，禁止提交占位 manifest。更重要的是，当前 collector 已进入 **frozen-containment fail-closed** 状态：在可验证的 immutable-input executor 实现前，它不会启动或 import candidate/evaluator strict child，因此不能生成 `status: passed` evidence。

## 输入、模式与未来集成政策

收集器只接受小写 40 位完整 SHA。该 SHA 必须精确等于干净 candidate worktree 的 `HEAD`、不是 C1.1 本身并且是 C1.1 后代。preflight 仍审计 candidate 的 `HEAD`、worktree status、允许 diff、全部 LMM fixture SHA-256，以及 evaluator 自己的 clean status 与固定 `HEAD`；同时拒绝任何能隐藏 tracked source 的 Git index 标记（`assume-unchanged`、`skip-worktree` 或二者组合）。每个 Git 命令都以解析后的传入目录显式设置 `--work-tree`；candidate/evaluator 的 pre/postflight 另验证 `rev-parse --show-toplevel` 等于该目录，candidate-local `core.worktree` 不能把审计重定向到 decoy。Git 环境仍为最小、hermetic：不继承 provider/Git 环境变量或用户/系统 Git config，明确禁用 fsmonitor、untracked cache、hooks，并强制 `trustctime=true`、`checkStat=default`、`ignoreStat=false` 与 `fileMode=true`，避免本地 Git stat 设置伪装 clean。这些检查只能验证静态工作树，**不能**证明运行期间实际 import/执行的字节；因此它们不是执行放行条件。

- 默认 `feature_lane` 只接受 standalone Feature Lane allowlist 中的变更，C1 contracts、canonical fixtures 和 central adapter protected paths 均不可变。
- `integration_tip` 是给未来 Integration Release Train 的可审计候选模式，不是当前 candidate acceptance。它必须显式传入 `--candidate-mode integration_tip`；所给完整 SHA 必须精确等于干净 `integration/v1.7.3` worktree 的 `HEAD`，并且 diff 只能落在 collector 的窄 `INTEGRATION_ALLOWED_CANDIDATE_PREFIXES`。C1 contracts、canonical fixtures、collector/evaluator、`scripts/gate.sh` 与 Honest-DiD adversarial tests 在此模式下仍受保护。
- integration-tip evidence 的指定 owner 是 **v1.7.3 Integration Release Train owner**；指定 trigger 是“Integration Release Train 从已有独立 lane evidence 的 merge-queue entries 组装出干净 `integration/v1.7.3` tip 之后”。命令能检查 SHA、分支、clean status 和 allowlist，不能自行证明该 owner 已授权或该 trigger 已发生。

任何模式的 manifest 都保持 `acceptance.accepted: false`。当前没有运行或接受 candidate；WO-B 的私有 `FigureContext` 形状也不是冻结的 Integration canonical contract，不能据此接受 B/C integrated candidate。

## 当前 frozen-containment gate

`_run_strict_candidate_evaluation()` 在构造 strict runner 命令、`Popen`、candidate/evaluator import 之前，固定抛出 `EvidenceCollectionError`。`main()` 仅会生成静态 `EVIDENCE_COLLECTION_REJECTED` failed manifest；详细 containment 原因不进入 durable JSON，也不会伪造 stream metadata 或 strict-suite artifact。

触发这个 gate 的原因不是“缺少更多 Git 检查”，而是已证实的执行期归因漏洞：同一 UID 的 candidate 可修改后恢复 source、使用 `.git/info/exclude` 隐藏 helper、或让 Git-ignored `.pyc` 参与 import。pre/post Git status 即使完全 clean，也不能证明运行的是候选 commit 的唯一字节集。

恢复严格执行必须作为单独的 frozen containment executor 工作项，同时满足以下全部条件：

- 从 candidate/evaluator 的精确 Git tree materialize 新鲜输入，不复用工作树，也不携带 ignored/untracked/`__pycache__` 内容。
- 在执行前验证 OS isolation backend 实际可运行；不能仅凭 `sandbox-exec`/`bwrap` 二进制存在，也绝不回退到裸 Python。
- 使用 OS 强制的读写 allowlist：snapshot、受控 fixture 和必要 runtime 为只读；仅临时 output/home 可写；不能使用允许读取整个 host 的现有 G3 sandbox profile 作为“commit 输入隔离”。
- Python 启动即采用 `-B`/等价环境，控制 `TMPDIR`，并保持 parent 的二进制 pipe、1 MiB quota、wall/TERM/KILL 有界生命周期。
- 以真实 canary 证明 candidate/evaluator write、ignored helper 和预置 bytecode 都不能影响执行；失败只能 static reject。

## future strict execution 与 best-effort 进程保护

父收集器绝不 import candidate code。下一版 frozen executor 才会启动唯一的 `tests/evaluation/linear_mixed_effects/strict_runner.py` 子进程；该 runner 已保留的进程内 Python guard 会在 candidate import 前清空 provider-bearing environment、切换隔离 HOME，并阻断 socket connect、`subprocess`、以及选定 `os`/POSIX process-spawn、`fork`/`forkpty` 与 session/process-group mutation 属性。它们是 defense-in-depth，不是当前 gate 的替代品。

这是 best-effort、process-level Python guard：它不是 OS-level sandbox，也不构成“所有网络均不可用”“绝无 provider 调用”或“能杀死所有同 UID/native bypass 后代”的证明。父收集器只保证自己的 capture/manifest 生命周期有界；需要进程级 containment 的评估必须在可用的受管 OS sandbox 中另行运行。

strict runner 只显式运行六个 candidate-facing test 文件：contract validation、known truth、fault injection、Agent boundaries、compare restrictions、deterministic overclaim checks。meta/guardrail 测试不进入 strict command。只有 JUnit 派生的六个结果全部通过后，才在同一进程执行 2 次 warmup、7 次 cold 与 7 次 hot local fit。

runner result 必须是 C1 `PacketEnvelope`，并固定为 `linear_mixed_effects.result` / `1.0` / `linear_mixed_effects@1.0`；performance 和 known-truth 均只从已解析 payload 读取事实，且 run-root 的 JSON 必须与返回 envelope 完全相同。fault fixtures 使用完整 versioned diagnostic envelope；Agent fixture 使用 C1.1 server-owned `model_options_binding` 和完整 `LmmDiagnostic`，缺失、篡改、错误 owner binding 或畸形 diagnostic 都必须 fail closed。

future executor 必须通过已有的二进制 pipe、独立 process session 和 selector 驱动、没有无界 join 的有界生命周期启动 strict runner；它不会解码或持久化 child stream。每个 stream 最多读取并 hash 1 MiB；**达到**该 quota 即拒绝、发送终止信号并关闭本地 pipe，不会继续 drain/hash 额外字节。durable metadata 最多报告 65,536 bytes。正常 strict 子进程的总 wall deadline 是 120 秒；leader 已退出但 pipe 未 EOF 时，collector 只给 2 秒 drain grace，随后 best-effort `SIGKILL`，再等待最多 2 秒，最后以静态 `PIPE_DRAIN_TIMEOUT` 失败返回。wall/pipe/signal/termination 失败同样使用静态 `capture_error_code`（例如 `WALL_CLOCK_TIMEOUT`），并在可写时写入失败 manifest。若 `Popen` 后 selector 初始化或注册失败，collector 仍会关闭本地 FD、在同样有界的 TERM/KILL 窗口内清理 leader，并抛出静态 collection error；由于没有安全的完整 pipe capture，该分支不会伪造 stream metadata。

## 非原始流证据

raw candidate-facing pytest stdout/stderr、以及所有 Git audit stdout/stderr，都不会写入 durable artifact 或 outer manifest。`strict-suite.output.json` 仅摘要 Python `redirect_stdout` / `redirect_stderr` 所接收的文本流，**不能**覆盖 `os.write` 等 FD 级写入；`strict-runner.output.json`（collector metadata v2）才是 strict runner FD 1/2 的二进制、OS-level 摘要，记录 per-stream SHA-256、65,536-byte reported count、truncation、1 MiB hard-limit flag 和静态 `capture_error_code`，不记录 stream 文本。只有 `capture_error_code: null` **且**两个 hard-limit flag 都是 `false` 时，digest 才代表完整捕获流；其余情形只代表安全地捕获到的 prefix。Git command records 保留其命令、exit code、duration、capture policy、hash/byte count，不记录 stream 文本。失败 manifest 的 `error` 固定为 `EVIDENCE_COLLECTION_REJECTED`，因此 Git 的 candidate-controlled path/branch/HEAD 文本不会从异常消息回流到 durable JSON；详细诊断只写入调用方的瞬时 stderr。outer manifest 仅抄录这些 hashes 与 inner pytest command、exit code、duration。

原始 JUnit XML 仅在唯一的 `0700` 私有临时目录中供 strict runner 解析；runner 会在 `finally` 中尝试删除 XML 和空目录。durable evidence 只保留 `strict-suite.junit.summary.json` 的结构化结果和 testcase counts；raw XML 缺失或不可解析时也只落下安全的零计数 summary，再由 parent 拒绝。parent 会重新校验 metadata/summary 的 path、hash、strict JSON/schema 和结果一致性。guardrail 测试用模拟 secret、hostile `core.fsmonitor` 与权限检查验证原始内容不会进入 artifact tree、manifest 或可遍历临时位置；同一 UID 的恶意 sidecar/hardlink 仍可能使临时目录清理不能给出绝对保证，见 P2。

这不是全盘 secret 扫描或所有 evidence 内容均无敏感信息的承诺：candidate 生成的结果/性能 JSON 仍应按受控本地证据处理。这里的保证仅限于收集器和 strict runner 不持久化其捕获的 raw candidate/Git stdout/stderr，也不会把候选控制的 strict exception 或 Git audit error detail 写入 durable result/manifest。

## 写入排他性与 P2 残余

CLI 在任何 collection 写入前，先完成 output/derived-artifact-root location validation，再通过 `O_CREAT | O_EXCL` 建立同目录的 `.output-name.reservation`。最终 manifest/failure payload 使用同目录临时文件、`fsync` 和 `os.link` 的 no-clobber create；它不是 `exists()` 后再 `os.replace()`。因此同一正常文件系统上的并发 collector 不能相互覆盖已存在 output，reservation 会在正常成功或失败路径释放。

仍有明确的 **P2 残余**：portable Python 文件 API 无法在恶意同权限进程替换父目录/路径、符号链接攻击、跨主机文件系统异常或进程崩溃后遗留 reservation 的情形下给出绝对排他性或物理不可变性。collector 不会自动清理 stale reservation；需要先人工检查，再显式移除。最终 no-clobber link 可阻止普通已存在 target 被覆盖，但不能替代受控目录权限、审计存储或操作系统级锁。

仍有明确的 **P2 残余**：strict runner 的 Python guard 和 parent 的 bounded cleanup 不能替代 OS-level containment；同一 UID/native bypass 后代可能逃离原 session，collector 会有界地关闭本地 FD、写 static failure 并返回，但不能证明该后代必定已被杀死。raw JUnit 的 `0700` 目录同样不能对同一 UID hardlink/sidecar 给出绝对清理保证。Git audit 已使用 hermetic environment/config、固定 worktree identity，并在 candidate/evaluator 的 pre/postflight 拒绝隐藏工作树变更的 index flags；但其解析路径仍使用 text-mode `subprocess.run`，尚未拥有 strict-runner 的二进制 hard quota 或无效 UTF-8 failure-manifest 行为。它必须作为单独 P2 通过 binary bounded parser（含严格 `-z`/解析策略）解决；本 WO-D 候选不把该残余表述为已经修复。

## 状态与 manifest 模板

在 frozen executor 实现并通过真实 canary 前，`status: passed` 是不可达状态。未来 `status: passed` 才可表示一轮严格本地 candidate evaluation、performance、candidate/evaluator post-audit 都通过；它仍写入 `acceptance.accepted: false` 与 `browser_acceptance: not_run`，直到独立 browser scenario 和 screenshot evidence 实际完成。没有 supplied candidate、frozen containment 或 browser acceptance 时，任何 candidate 都不得接受。

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
    exit_code: observed integer or null when termination cannot be reaped safely
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
  containment_backend: observed OS-enforced backend, version, and successful pre-launch canary
  filesystem_policy: observed OS-enforced read-only inputs and writable allowlist
  network_policy: observed OS-enforced network policy
  network_guard: observed scoped Python guard description
  process_spawn_guard: observed scoped Python guard description
  provider_environment: observed clean-environment description
  residual_limitations: actual limitations remaining after verified containment
acceptance:
  accepted: false until browser acceptance is actually recorded
  reason: actual non-secret reason
artifacts:
  - path: actual controlled local evidence artifact
    sha256: actual SHA-256
generated_at: actual UTC timestamp
```

没有完整 protected/evaluator/candidate audit、没有可校验 structural JUnit summary 或 inner metadata、任何 required result 不是 `passed`，或没有 browser acceptance 的 candidate 都不得接受。新 candidate 行为变更必须生成新的 manifest，并在新文件的 `supersedes` 中引用旧 evaluation id；绝不回写旧证据。
