# WO-D Independent Evaluation Completion Report

状态：WO-D evaluation harness 的已知 P1 与父级 strict-stream P2 hardening 均已完成并本地提交；没有 supplied Feature candidate、没有 B/C integrated candidate、没有 browser acceptance。因此没有任何 candidate 被接受或标记为 release-ready。

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
- supplied candidate commit：未提供。

## 已收紧的评估边界

- runtime/performance/known-truth runner result 都通过 `PacketEnvelope.from_dict(result)`，固定核验 `linear_mixed_effects.result` / `1.0` / `linear_mixed_effects@1.0`，并且只读取解析后的 payload。run-root `linear_mixed_effects_contract.json` 必须与同一 parsed envelope 完全相等。
- fault fixtures 读取 candidate-root 下的 canonical versioned diagnostic envelopes，并以完整 `LmmDiagnostic` 复核；Agent fixtures 使用完整 C1.1 server-owned binding 与完整 diagnostic fields。缺失、hash 篡改、错误 owner binding 和畸形 diagnostic 的候选行为均必须 fail closed，不能产生 proposal。
- strict suite 不执行整个目录后容忍 meta skip，而是只显式运行六个 candidate-facing 文件。它以位于唯一 `0700` 私有临时目录的 raw JUnit XML 得到结构化 `strict-suite.junit.summary.json`；原始 XML 与空目录都会在 `finally` 删除。JUnit 缺失、不可解析、任意 skip、非 candidate testcase 或任一 required result 零 testcase 都失败。
- strict runner 在 candidate import 前清空环境并阻断 scoped Python socket/process-spawn 路径；`subprocess.Popen` 和 `os.system` canary 均已覆盖。这只是 process-level Python guard，不是 OS sandbox，不证明所有 egress 被阻断，也不证明绝无 provider 调用。
- raw candidate-facing pytest stdout/stderr、以及 Git audit stdout/stderr 均不再写入 artifact 或 manifest。`strict-suite.output.json` 仅摘要 Python text redirect，不能声称覆盖 `os.write` 等 FD 写入；`strict-runner.output.json` 才是 collector 对 FD 1/2 的二进制、OS-level 摘要，记录完整已捕获 stream SHA-256、最多 65,536 bytes 的 reported count、truncation、1 MiB hard-limit flag 和静态 `capture_error_code`。父收集器使用两个并发 reader 和独立 process session；超限会终止 process group 并拒绝 candidate，drain/signal 不能安全完成也 fail closed。Git audit 仍使用不继承 provider/Git 环境或用户/系统 config 的最小环境，并显式关闭 fsmonitor、untracked cache 与 hooks，因此候选 `.git/config` 不能隐藏 dirty source 或把 hook 输出持久化。候选控制的异常文本也不进入 durable strict result。模拟 invalid UTF-8、FD sentinel、stream overflow、hostile fsmonitor 和目录权限的 guardrail 测试覆盖这些已收紧边界。
- collector 的默认 `feature_lane` 仍只接受 standalone allowlist。未来 `integration_tip` 模式要求显式选择该 mode、完整 SHA 精确等于干净 `integration/v1.7.3` 的 `HEAD`，并受窄 integration allowlist 和 C1 contracts/fixtures/evaluator/gate/Honest-DiD protections 约束。该模式的 owner 是 **v1.7.3 Integration Release Train owner**，trigger 是 merge queue 已依据独立 lane evidence 组装干净 integration tip 后；collector 不能自行证明人类授权或 trigger 已发生。
- CLI 在任何 collection 写入前建立排他 reservation；final manifest/failure payload 以 `fsync` 后的 no-clobber hard link 创建，而不是 `exists()` 后 `os.replace()`。正常并发 collector 不会覆盖已有 output。

## 当前代码 correction 的精确修改文件

本次 parent strict-stream P2 code commit `5b25f2e182612bd37773845a7f4d0e3e8607ba20` 修改：

- `scripts/collect_v173_lmm_evidence.py`
- `tests/evaluation/linear_mixed_effects/strict_runner.py`
- `tests/evaluation/linear_mixed_effects/test_collector_guardrails.py`
- `tests/evaluation/linear_mixed_effects/test_strict_candidate_entrypoint.py`

没有修改 central source、C1 contracts、canonical fixtures、protected files 或任何 Feature/Integration Lane 文件。

## 验证记录

| 命令 | 实际结果 |
| --- | --- |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m py_compile scripts/collect_v173_lmm_evidence.py tests/evaluation/linear_mixed_effects/strict_runner.py tests/evaluation/linear_mixed_effects/test_collector_guardrails.py tests/evaluation/linear_mixed_effects/test_strict_candidate_entrypoint.py` | exit 0。 |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/evaluation/linear_mixed_effects/test_collector_guardrails.py tests/evaluation/linear_mixed_effects/test_strict_runner_guardrails.py tests/evaluation/linear_mixed_effects/test_strict_candidate_entrypoint.py -q` | exit 0；`48 passed in 8.77s`。覆盖 invalid UTF-8 / FD sentinel 的二进制 SHA、overflow fail-closed、capture-error metadata、不持久化 raw stream、hostile fsmonitor/dirty-source、private JUnit directory、integration branch/SHA/clean guard 和 reservation/no-clobber guard。 |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/evaluation/linear_mixed_effects -q` | exit 0；`61 passed, 27 skipped in 9.66s`。本地 authoring mode 对未提供 candidate-only module 保留 skip；strict mode 不允许它们 skip。 |
| `/Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests -q` | exit 1；`20 failed, 2253 passed, 35 skipped, 47 warnings in 451.15s`。20 个失败均来自受管环境拒绝 `sandbox-exec` profile（`sandbox-exec: sandbox_apply: Operation not permitted`）：6 个 direct sandbox tests 与 14 个 code-execution cascading tests；WO-D 未修改这些 sandbox/code-execution 路径，且没有用 workaround 掩盖失败。它不是 full-gate pass。 |
| `git diff --check` | exit 0（文档最终提交前会重跑）。 |

完整 suite 的 sandbox blocker 是环境验收限制，不能据此推断 sandbox 行为在受支持环境中正确；它需要能够应用 sandbox profile 的环境单独重跑，不能由 WO-D 的局部 guardrail 代替。

## 未接受项、P2 残余与集成风险

- 没有真实 supplied candidate，因此没有生成 `eval-v173-lmm-XXX` manifest、performance evidence 或 browser screenshot；测试中的临时 candidate 仅验证 fail-closed guardrail，不构成 acceptance。
- `browser_acceptance` 必须保持 `not_run`，`acceptance.accepted` 必须保持 `false`。即使未来 candidate 通过 strict evidence，仍需要独立 browser scenario、截图 hash 和新的不可覆写 manifest，才可另行讨论 acceptance。
- `integration_tip` 是未来集成候选的记录政策，不是本次运行或 acceptance。WO-D 不把任何 Feature Lane 私有输出形状当作冻结 Integration contract；尤其不因 WO-B 的私有 `FigureContext` 形状而认可 B/C integrated candidate。
- stream hardening 只保证 captured candidate/Git stdout/stderr 与候选控制的 strict error text 不被持久化；它不是全盘 secret scanner，也不保证 candidate 生成的 result/performance JSON 本身不含敏感内容。evidence 必须保存在受控本地目录。
- **P2 残余：** `O_EXCL` reservation 与 no-clobber hard link 可覆盖正常同文件系统并发，但无法用 portable Python API 对恶意同权限进程替换父目录/路径、符号链接攻击、跨主机文件系统异常或进程崩溃后 stale reservation 给出绝对保证。私有 JUnit directory 消除跨用户临时 XML 暴露，但同一 UID 的恶意进程仍不是 portable Python 能绝对排除的威胁模型。stale reservation 不会自动清理，必须先人工检查后显式移除；受控目录权限和审计存储仍是必要外部控制。
- **独立 P2（未修复）：** Git audit 虽已 hermetic 且不持久化 raw output，仍以 text-mode `subprocess.run` 解析输出；它尚无 strict-runner 的二进制 hard quota / invalid-UTF-8 failure-manifest 行为。后续需单独采用 bounded binary parser 与严格 `-z` 解析策略，不能把本次 parent stream hardening 外推为 Git stream hardening。

没有读取真实 API key、调用真实 provider、安装依赖、运行/接受 candidate、push、PR、merge、tag 或 release。
