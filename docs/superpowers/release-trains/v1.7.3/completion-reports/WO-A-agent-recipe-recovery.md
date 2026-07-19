# WO-A Agent Recipe Recovery — Completion Report

状态：本地候选已提交，等待 Integration/主控复核；不是 release、PR 或路由接线声明。

## 可追溯性

| 项目 | 值 |
| --- | --- |
| worktree / branch | `/Users/jiayuanren/项目规划/.worktrees/v173-agent-recipes-recovery` / `feat/v173-agent-recipes-recovery` |
| release baseline | `4b2e6c1d9ddd289005b84c186255fec2e9cbd86a` |
| branch start / C1.1 contract lock | `0251f0a30d984bdbb2cfab404e6c646deab60cae` |
| governance receipt reference | `f25ffd119df91479aabfcebcb549a47a1153e227`（只读引用；未 cherry-pick） |
| candidate code commit | `5ce9824014d8d961bfd73d243776f41d89b785fe` |

初始审计确认 HEAD 等于 contract lock、`git status --short` 为空、`git diff --check` 静默，且两个 WO-A 测试文件按预期不存在。

## 产物与范围

候选提交的精确代码/测试文件：

- `backend/workbench/agent/recipes/repeated_measures.py`
- `backend/workbench/agent/recipes/lmm_explanation.py`
- `tests/agent/test_repeated_measures_recipe.py`
- `tests/agent/test_repeated_measures_recovery.py`

本报告是本 Lane 唯一新增 metadata 输出：

- `docs/superpowers/release-trains/v1.7.3/completion-reports/WO-A-agent-recipe-recovery.md`

实现是纯声明式 recipe：仅当 source 为 `linear_mixed_effects`、源 `random_slope` 为 `true`、诊断码为两个锁定 recoverable 码、candidate 字段/操作/patch 精确匹配且 confirmation 为 `true` 时，才返回一个 `model.rerun` proposal。任何 blocker、未知或畸形 diagnostic 都抑制 proposal；允许的 patch 只会把 `random_slope` 从 true 改为 false。

中文说明仅从固定的 code/status/restricted-REML reason 字典生成，不回显 evidence 或 compare 文案，也不包含 `导致`、`造成`、`证明因果`、`因果效应`。

## TDD 证据

Python 命令固定为 `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest`。

| 切片 | RED 结果 | GREEN 结果 |
| --- | --- | --- |
| locked near-zero proposal | `tests/agent/test_repeated_measures_recipe.py -q`：`ModuleNotFoundError`（recipe module 不存在） | 同命令：`1 passed` |
| missing subject explanation | 同命令：`subject identifier` 不在空说明中 | 同命令：`2 passed` |
| confirmation gate | 两个 WO-A 测试：`DID NOT RAISE ValueError` | 同命令：`3 passed` |
| patch validator | 两个 WO-A 测试：无法 import `validate_recovery_patch` | 同命令：`5 passed` |
| source model type | 两个 WO-A 测试：non-LMM source 仍有 proposal | 同命令：`6 passed` |
| source true-to-false condition | 两个 WO-A 测试：source `random_slope: false` 仍有 proposal | 同命令：`7 passed` |
| singular recovery | 两个 WO-A 测试：singular diagnostic 没有 proposal | 同命令：`8 passed` |
| blocker/unknown global suppression | 两个 WO-A 测试：blocker/unknown 与 valid candidate 并存时仍有 proposal | 同命令：`10 passed` |
| fixed Chinese explanations | 两个 WO-A 测试：`comparison=` 参数尚不存在 | 同命令：`11 passed` |
| malformed code fail-closed | 两个 WO-A 测试：list diagnostic code 触发 `TypeError` | 同命令：`12 passed` |
| candidate field closure | 两个 WO-A 测试：额外 `auto_execute` 字段仍有 proposal | 同命令：`13 passed` |
| fresh PlanDiff | 两个 WO-A 测试：一次调用的列表 mutation 污染下一次输出 | 同命令：`14 passed` |

`source random_slope` 边界加入后，confirmation 测试夹具补齐为 `random_slope: true`，以保持测试到达其合同校验分支；该修正后两份 WO-A 测试为 `7 passed`。

## 新鲜验证

```text
PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  tests/agent/test_repeated_measures_recipe.py \
  tests/agent/test_repeated_measures_recovery.py \
  tests/test_agent_analysis_loop_contracts.py -q
# 51 passed in 1.31s

PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  tests/contracts/test_lmm_contracts.py \
  tests/contracts/test_lmm_error_contract.py \
  tests/contracts/test_lmm_canonical_packets.py -q
# 29 passed in 0.53s
```

对 candidate 执行 `git show --check 5ce9824014d8d961bfd73d243776f41d89b785fe` 和 `git diff --check 0251f0a30d984bdbb2cfab404e6c646deab60cae..HEAD` 均静默。

## 保护文件审计

`git diff --name-only 0251f0a30d984bdbb2cfab404e6c646deab60cae..5ce9824014d8d961bfd73d243776f41d89b785fe` 仅列出上方四个候选代码/测试文件。针对全部 forbidden 文件和全部 read-only C1 contract/test 文件的精确路径匹配均无输出；没有更改 `orchestrator.py`、`operations.py`、analysis-loop central seam、pack/registry/capabilities、graph store、Agent Surface、gate 或两个 protected Honest-DiD tests。

## 限制、Integration 风险与回滚

- 未注册 recipe，未修改中央 route，未执行 proposal，未创建 child run，未调用 LLM，也未读取真实 key 或真实 provider。
- 未实现 Model Pack、UI、独立 Evaluation 或 release acceptance；本候选仅消费已锁 C1/C1.1 facts。
- Integration 必须以机械 declaration/route dispatch 接入该 pure builder，并保持现有 OLS route 的回归保护；不得把本 Lane 的 proposal 解释为已执行 rerun。
- 若复核拒绝该候选，在集成分支上回滚 `5ce9824014d8d961bfd73d243776f41d89b785fe`（或不 cherry-pick）即可；本 Lane 未产生运行、child、数据或外部副作用。
