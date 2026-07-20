# v1.7.3 Worktree Archive Audit

审计日期：2026-07-20

发布候选：`integration/v1.7.3` @ `1da886b49b50f58c5b151ac5238f8466cc814836`

发布基线：`origin/main` @ `4b2e6c1d9ddd289005b84c186255fec2e9cbd86a`

## 结论

v1.7.3 的七个目录是同一 Git 仓库的七个隔离 worktree，不是七套需要复制拼接的软件。唯一发布候选是 `integration/v1.7.3`；其他分支只作为第一次并行开发的审计历史保留，禁止单独创建产品 PR 或重新合入 `main`。

Integration 从 v1.7.2 线性前进 12 个提交、0 个落后提交。Lane 提交没有作为 ancestry merge 进入 Integration；其功能经过审查后由 Integration 组装和继续演进。这个事实已经记录在 `release-ledger.json`，不能把“某个 Lane 仍有独立提交”误判为“产品遗漏”。

## 七工作树清单

| Worktree | Branch / audited HEAD | 状态 | 与 Integration 的关系 | 归档决定 |
| --- | --- | --- | --- | --- |
| `integration-v1.7.3` | `integration/v1.7.3` / `1da886b` | clean | 最终组装、测试与本机验收事实源 | 推送、创建唯一 release PR |
| `v173-agent-recipes-recovery` | `feat/v173-agent-recipes-recovery` / `d2e43ec` | clean | 4 个 Lane-only 提交；生产能力已由 Integration 演进组装 | 推送为 archive branch，不合入 |
| `v173-c1.1-contract-receipts` | `release-train/v1.7.3-c1.1-contract-receipts` / `f25ffd1` | clean | 2 个合同收据提交；实际 C1.1 lock 已在 Integration | 推送为 archive branch，不合入 |
| `v173-evaluation-harness` | `test/v173-evaluation-harness` / `97c40de` | **dirty：6 files** | 14 个已提交评估提交；未提交 follow-up 属于后来被取消的 C2 hostile-candidate 路径 | 只推送已提交 HEAD；不合入、不清理 dirty worktree |
| `v173-model-linear-mixed-effects` | `feat/v173-model-linear-mixed-effects` / `1262a7c` | clean | 7 个 Lane-only 提交；Pack 已由 Integration 修订并组装 | 推送为 archive branch，不合入 |
| `v173-ui-agent-inspector-compare` | `feat/v173-ui-agent-inspector-compare` / `cd8716a` | clean | 12 个 Lane-only 提交；最终 UI 已收敛到 Integration 的公共投影消费者 | 推送为 archive branch，不合入 |
| `workbench-v1.7.3` | `workbench-v1.7.3` / `edfa855` | clean | 4 个早期规划/ADR 提交；不是产品候选 | 推送为 archive branch，不合入 |

## WO-D dirty snapshot

未提交内容涉及：

- `docs/superpowers/release-trains/v1.7.3/completion-reports/WO-D-independent-evaluation.md`
- `docs/superpowers/release-trains/v1.7.3/evidence/README.md`
- `scripts/collect_v173_lmm_evidence.py`
- `tests/evaluation/linear_mixed_effects/strict_runner.py`
- `tests/evaluation/linear_mixed_effects/test_collector_guardrails.py`
- `tests/evaluation/linear_mixed_effects/test_strict_runner_guardrails.py`

该 snapshot 为 `686 insertions / 153 deletions`，`git diff --check` 通过。它研究的是 frozen-containment collector 在无真实 C2 executor 时 fail closed 的路径。最终产品提交 `7df588e` 已删除未使用的 C2 runtime，并把 hostile/third-party extension containment 转入 `architecture-debt.md` 的事件触发路线。因此这些 dirty 文件：

1. 不属于 v1.7.3 本机产品；
2. 不得进入 release PR；
3. 不得在归档审计中自动删除或覆盖；
4. 在未来真正出现不受信任扩展边界时，只能作为历史研究输入，不能直接恢复成生产代码。

## GitHub 归档策略

- 推送七个已提交 branch tip，使合同、候选实现、评估演进和最终组装历史均可从 GitHub 恢复；
- 只有 `integration/v1.7.3` 创建 PR 并合入 `main`；
- release tag `v1.7.3` 必须创建在 GitHub 合并后的 `main` commit，而不是 Integration 的 pre-merge HEAD；
- 本次不删除任何 worktree。tag 验证完成后，六条非 Integration 工作树可另行执行清理；WO-D 必须先单独处置 dirty snapshot。

## Release-candidate verification

在加入本审计与 release note 后，使用共享项目解释器和真实宿主权限执行：

```text
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 WORKBENCH_PYTHON=<shared-project-python> bash scripts/gate.sh --full
```

结果：backend `2503 passed, 8 skipped`；golden/invariants `23 passed`；frontend `137 files / 1217 tests`；TypeScript 通过；最终输出 `GATE PASSED`。命令记录不保存绝对用户目录或环境密钥。

## 审计限制

不同 Lane 与 Integration 的同名文件大多不是 byte-identical，因为 Integration 在组装时修复了公共结果 transport、持久化 capability、UI reader/fixture parity 和本机执行边界。归档审计证明分支和文件历史可恢复；产品正确性由 exact Integration gate、known-truth smoke、浏览器验收和 release ledger 共同证明，而不是由文件名或 commit ancestry 猜测。
