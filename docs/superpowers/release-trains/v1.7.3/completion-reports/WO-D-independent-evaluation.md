# WO-D Independent Evaluation Completion Report

状态：`BLOCKED_PENDING_FROZEN_CONTAINMENT_EXECUTOR`。WO-D 已在本地修复 lifecycle、selector setup、Git worktree/index identity、stat-cache 与 failure-manifest 边界；但独立审计证明 pre/post Git audit 无法绑定运行期间实际 import 的字节。生产 collector 因此在任何 candidate/evaluator child 启动前 fail closed，直到单独实现并验证 immutable-input OS containment executor。没有 supplied Feature candidate、没有 B/C integrated candidate、没有 browser acceptance。因此没有任何 candidate 被接受或标记为 release-ready。

## 不可变起点与提交

- release baseline：`4b2e6c1d9ddd289005b84c186255fec2e9cbd86a`
- branch start / C1.1 contract lock：`0251f0a30d984bdbb2cfab404e6c646deab60cae`
- governance receipt（只读）：`f25ffd119df91479aabfcebcb549a47a1153e227`
- WO-D branch：`test/v173-evaluation-harness`
- initial strict correction：`020db1a36beebf3d9c1cf99666e906ae4277503d`（`test: close WO-D strict evaluation boundaries`）
- prior P1 collector correction：`8f7cb6b1a00c2b39cddd473c3cec157f0bb6fe5b`（`test: harden LMM evidence collection`）
- current remaining-P1 code correction：`98be242895cfd2915da029abd24a64af2427de29`（`test: protect LMM evidence artifacts`）
- final P1 follow-up correction：`53cfcd882593e14ea32a7b424152da0179756cfb`（`fix: hermetically audit LMM evidence candidates`）：Git audits use a minimal environment and explicit config overrides, raw Git streams are discarded, and raw JUnit is contained by a unique `0700` private directory.
- parent strict-stream P2 correction：`5b25f2e182612bd37773845a7f4d0e3e8607ba20`（`fix: bound strict evaluator process streams`）：outer collector uses binary concurrent drains, an isolated process session and a 1 MiB per-stream fail-closed quota; it records static capture failures without persisting raw FD bytes.
- lifecycle/worktree/manifest correction：`97c40de7e5f2e6fb5d97e41ef2831f102aee3229`（`fix: bound strict evaluation lifecycle`）：collector now pins every Git audit to the supplied resolved worktree, uses static durable failure errors, and gives strict evaluation a bounded wall/EOF/termination lifecycle with quota-bounded binary reads.
- current local follow-up（尚未形成新的 Git commit）：selector construct/second-register failure now closes local FDs and uses bounded TERM/KILL before a static collection failure; candidate/evaluator pre/postflight reject all `assume-unchanged` / `skip-worktree` combinations and force Git stat settings (`trustctime`, `checkStat`, `ignoreStat`, `fileMode`). Most importantly, the production strict entrypoint now refuses before `Popen` because a frozen containment executor does not yet exist. This snapshot is not an accepted candidate or release artifact.
- supplied candidate commit：未提供。

## 已收紧的评估边界

- **当前生产边界：** `_run_strict_candidate_evaluation()` 固定在 strict command、`Popen`、candidate/evaluator import 之前抛出 frozen-containment error。`main()` 只写静态 `EVIDENCE_COLLECTION_REJECTED` failure manifest；详细原因不进入 durable JSON，且不生成 stream metadata 或 strict-suite artifact。这个 gate 关闭同一 UID 运行期改写/恢复 source、`.git/info/exclude` 隐藏 helper、预置 ignored bytecode 和 host-readable helper 造成的错误 SHA 归因。
- runtime/performance/known-truth runner result 都通过 `PacketEnvelope.from_dict(result)`，固定核验 `linear_mixed_effects.result` / `1.0` / `linear_mixed_effects@1.0`，并且只读取解析后的 payload。run-root `linear_mixed_effects_contract.json` 必须与同一 parsed envelope 完全相等。
- fault fixtures 读取 candidate-root 下的 canonical versioned diagnostic envelopes，并以完整 `LmmDiagnostic` 复核；Agent fixtures 使用完整 C1.1 server-owned binding 与完整 diagnostic fields。缺失、hash 篡改、错误 owner binding 和畸形 diagnostic 的候选行为均必须 fail closed，不能产生 proposal。
- future-only strict suite 不执行整个目录后容忍 meta skip，而是只显式运行六个 candidate-facing 文件。它以位于唯一 `0700` 私有临时目录的 raw JUnit XML 得到结构化 `strict-suite.junit.summary.json`；runner 在 `finally` 中尝试删除 XML 和目录。JUnit 缺失、不可解析、任意 skip、非 candidate testcase 或任一 required result 零 testcase 都失败。同一 UID sidecar/hardlink 仍可能阻断绝对清理，作为 P2 记录。
- future-only strict runner 在 candidate import 前清空环境并阻断 scoped Python socket/process-spawn、`fork`/`forkpty`、常见 `exec*` 与 session/process-group mutation 路径；`subprocess.Popen`、`os.system`、直接 `os.fork`、`posix.fork` 与 `os.execve` canary 均已覆盖。这只是 process-level defense-in-depth，不是 OS sandbox，不能作为恢复执行的理由。
- future-only parent path 保留二进制 pipe、独立 process session 和 selector 驱动的有界生命周期：总 wall deadline 为 120 秒；leader 退出后 pipe 未 EOF 只给 2 秒 drain grace，再 best-effort kill 并最多等待 2 秒。每 stream 最多读取/hash 1 MiB，达到 quota 即拒绝并关闭本地 FD，不会继续读取额外字节。selector construct/second-register failure 会关闭本地 FD、在有界 TERM/KILL 后抛静态 collection error，而不会伪造 stream metadata。Git audit 使用最小环境、关闭 fsmonitor/untracked cache/hooks、显式 `--work-tree=<supplied resolved root>`，强制 `trustctime=true` / `checkStat=default` / `ignoreStat=false` / `fileMode=true`，并验证 top-level、拒绝 hidden index flags；这降低静态 preflight 假 clean，却不能替代 immutable execution input。durable failed manifest 的 `error` 固定为 `EVIDENCE_COLLECTION_REJECTED`，候选控制的 Git path/branch/HEAD 异常详情只留在瞬时 stderr，不会回流 JSON。
- collector 的默认 `feature_lane` 仍只接受 standalone allowlist。未来 `integration_tip` 模式要求显式选择该 mode、完整 SHA 精确等于干净 `integration/v1.7.3` 的 `HEAD`，并受窄 integration allowlist 和 C1 contracts/fixtures/evaluator/gate/Honest-DiD protections 约束。该模式的 owner 是 **v1.7.3 Integration Release Train owner**，trigger 是 merge queue 已依据独立 lane evidence 组装干净 integration tip 后；collector 不能自行证明人类授权或 trigger 已发生。
- CLI 在任何 collection 写入前建立排他 reservation；final manifest/failure payload 以 `fsync` 后的 no-clobber hard link 创建，而不是 `exists()` 后 `os.replace()`。正常并发 collector 不会覆盖已有 output。

## 当前代码 correction 的精确修改文件

已提交的 lifecycle/worktree/manifest code commit `97c40de7e5f2e6fb5d97e41ef2831f102aee3229` 修改：

- `scripts/collect_v173_lmm_evidence.py`
- `tests/evaluation/linear_mixed_effects/strict_runner.py`
- `tests/evaluation/linear_mixed_effects/test_collector_guardrails.py`
- `tests/evaluation/linear_mixed_effects/test_strict_runner_guardrails.py`

当前未提交的 follow-up 仍只修改同一 WO-D collector/runner/guardrail 文件及本报告和 evidence README；没有修改 central source、C1 contracts、canonical fixtures、protected files 或任何 Feature/Integration Lane 文件。

## 验证记录

| 命令 | 实际结果 |
| --- | --- |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m py_compile scripts/collect_v173_lmm_evidence.py tests/evaluation/linear_mixed_effects/strict_runner.py tests/evaluation/linear_mixed_effects/test_collector_guardrails.py tests/evaluation/linear_mixed_effects/test_strict_runner_guardrails.py tests/evaluation/linear_mixed_effects/test_strict_candidate_entrypoint.py` | exit 0。 |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/evaluation/linear_mixed_effects/test_collector_guardrails.py tests/evaluation/linear_mixed_effects/test_strict_runner_guardrails.py tests/evaluation/linear_mixed_effects/test_strict_candidate_entrypoint.py -q` | exit 0；`69 passed in 13.92s`。覆盖 static frozen-containment manifest/no-spawn、Git stat config、hidden-index（含组合）、selector lifecycle、binary quota 与 future-only payload parser。 |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/evaluation/linear_mixed_effects -q` | exit 0；`82 passed, 27 skipped in 14.08s`。本地 authoring mode 对未提供 candidate-only module 保留 skip；strict mode 不允许它们 skip。 |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests -q` | **当前 final snapshot** exit 1；`20 failed, 2274 passed, 35 skipped, 47 warnings in 465.77s`。20 个失败均来自受管环境拒绝 `sandbox-exec` profile（`sandbox-exec: sandbox_apply: Operation not permitted`）：6 个 direct sandbox tests 与 14 个 code-execution cascading tests。它不是当前 frozen-containment snapshot 的 full-gate pass。 |
| `git diff --check` | exit 0（当前未提交快照）。 |

完整 suite 的 sandbox blocker 是环境验收限制，不能据此推断 sandbox 行为在受支持环境中正确；它需要能够应用 sandbox profile 的环境单独重跑，不能由 WO-D 的局部 guardrail 代替。

## 未接受项、P2 残余与集成风险

- **当前 release blocker：** frozen containment executor 尚未实现。它必须从精确 Git tree materialize 不含 ignored/untracked/bytecode 的 candidate 与 evaluator snapshot，在真正可运行的 OS backend 下以读写 allowlist 执行，并在启动前以 canary 验证；现有 G3 sandbox 允许读取 host，不能直接充当 commit-input containment。到此项完成前，collector 的唯一正确行为是 static reject，不能为任何 candidate 生成 passing evidence。
- 没有真实 supplied candidate，因此没有生成 `eval-v173-lmm-XXX` manifest、performance evidence 或 browser screenshot；测试中的临时 candidate 仅验证 fail-closed guardrail，不构成 acceptance。
- `browser_acceptance` 必须保持 `not_run`，`acceptance.accepted` 必须保持 `false`。即使未来 candidate 通过 strict evidence，仍需要独立 browser scenario、截图 hash 和新的不可覆写 manifest，才可另行讨论 acceptance。
- `integration_tip` 是未来集成候选的记录政策，不是本次运行或 acceptance。WO-D 不把任何 Feature Lane 私有输出形状当作冻结 Integration contract；尤其不因 WO-B 的私有 `FigureContext` 形状而认可 B/C integrated candidate。
- stream hardening 只保证 captured candidate/Git stdout/stderr 与候选控制的 strict error/Git-detail 不被持久化；它不是全盘 secret scanner，也不保证 candidate 生成的 result/performance JSON 本身不含敏感内容。evidence 必须保存在受控本地目录。
- **P2 残余：** `O_EXCL` reservation 与 no-clobber hard link 可覆盖正常同文件系统并发，但无法用 portable Python API 对恶意同权限进程替换父目录/路径、符号链接攻击、跨主机文件系统异常或进程崩溃后 stale reservation 给出绝对保证。私有 JUnit directory 消除跨用户临时 XML 暴露，但同一 UID sidecar/hardlink 可能阻断绝对 cleanup。future strict runner 的 Python guard 与 parent bounded cleanup 也不能代替 OS-level containment：native/same-UID bypass 后代可能逃离 session；gate 当前避免启动该路径。stale reservation 不会自动清理，必须先人工检查后显式移除；受控目录权限、审计存储和可用 OS sandbox 仍是必要外部控制。
- **独立 P2（未修复）：** Git audit 虽已 hermetic、不持久化 raw output，并拒绝隐藏实际 source 的 index flags，仍以 text-mode `subprocess.run` 解析输出；它尚无 strict-runner 的二进制 hard quota / invalid-UTF-8 failure-manifest 行为。后续需单独采用 bounded binary parser 与严格 `-z` 解析策略，不能把本次 parent stream hardening 外推为 Git stream hardening。
- **恢复执行前的接口 P2：** `_run_strict_candidate_evaluation_after_frozen_containment()` 当前仅为无生产 caller 的 future-only 测试/解析 helper，尚未要求真实 containment capability。未来 executor 落地时必须移除、私有化为 executor 内部步骤，或显式要求并验证该 capability；不得因为函数名称暗示 containment 就重新接回 production path。

没有读取真实 API key、调用真实 provider、安装依赖、运行/接受 candidate、push、PR、merge、tag 或 release。
