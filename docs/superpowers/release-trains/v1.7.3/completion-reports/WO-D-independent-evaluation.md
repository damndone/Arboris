# WO-D Independent Evaluation Completion Report

状态：严格 Evaluation harness 已交付；没有 supplied Feature/Integration candidate，也没有浏览器 acceptance。因此没有任何候选被接受。

## 不可变起点与提交

- release baseline：`4b2e6c1d9ddd289005b84c186255fec2e9cbd86a`
- branch start / C1.1 contract lock：`0251f0a30d984bdbb2cfab404e6c646deab60cae`
- governance receipt（只读）：`f25ffd119df91479aabfcebcb549a47a1153e227`
- WO-D branch：`test/v173-evaluation-harness`
- 初始 harness：`f78430edb586bc87416e756e36450dfc4b476dfe`
- strict correction：`8b23cf25a854aad89dc6f13fa837911518b07c17`（`test: harden v1.7.3 LMM candidate evaluation`）
- candidate commit：未提供。

先前 receipt 曾把 harness commit 当作 supplied candidate 的失败演示；那条旧收集路径不是完整隔离 strict evaluation，不能作为 candidate evidence 或 acceptance 依据。本报告只以 `8b23cf25…` 的 strict boundary 和下列当前验证为准。

## 当前严格边界

- 父收集器只做候选 Git/fixture 审计与证据编排，绝不 import candidate code。
- 唯一 strict entrypoint 是 `tests/evaluation/linear_mixed_effects/strict_runner.py`。收集器以子进程传入 candidate root 和完整 SHA；子进程以最小环境启动，在任何 candidate import 前清空 provider/key 环境、切换隔离 HOME 并拦截 socket network access。
- strict mode 将缺失 candidate-only module 的本地 skip 变成失败；每个经 gate 导入的模块必须证明 `__file__` 位于 supplied candidate root。pytest 自身追加 evaluator `pythonpath` 的缓存/路径回退也会在 gate 处清除并重置 candidate backend 优先级。
- strict 子进程运行完整 LMM candidate evaluation suite；只有 suite 全部 required result 通过后，才在同一进程执行 2 次 warmup、7 次 cold 与 7 次 hot local fit。JUnit、stdout/stderr、fit contracts、命令回执和 hash 都持久化到 `<output-stem>.artifacts/`，不再使用会自动删除的性能临时目录。
- candidate 必须是小写 40 位 SHA、精确等于 clean worktree `HEAD`、不是 C1.1、且是 C1.1 后代。收集器在执行前和执行后都复核 HEAD、status、严格 Feature path allowlist、protected diff 与所有 locked fixture SHA-256。
- `status: passed` 只表示严格本地 suite、performance 与 post-execution audit 已完成；manifest 仍写 `browser_acceptance: not_run` 和 `acceptance.accepted: false`。没有实际浏览器证据时不得接受候选。

## P0 负向覆盖与当前验证

| 命令 | 实际结果 |
| --- | --- |
| `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/evaluation/linear_mixed_effects/test_strict_candidate_entrypoint.py tests/evaluation/linear_mixed_effects/test_collector_guardrails.py -q` | exit 0；`14 passed in 3.69s`。覆盖非 40 位/错误 SHA、C1.1 本身、脏 worktree、protected fixture、post-run fixture mutation、缺失 module、import-time network/key canary、strict suite exit 与 collector 实际启动完整 suite。 |
| `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/evaluation/linear_mixed_effects -q` | exit 0；`22 passed, 23 skipped in 4.73s`。本地 authoring mode 仍只对未提供的 candidate-only module skip；移除了越界的 `tests/evaluation/__init__.py`，目录仍可直接收集。 |
| `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/contracts/test_lmm_contracts.py tests/contracts/test_lmm_error_contract.py tests/contracts/test_lmm_canonical_packets.py tests/models/linear_mixed_effects/test_feasibility.py tests/test_lmm_extension_seams.py tests/test_model_options_owner_binding.py -q` | exit 0；`81 passed, 7 warnings in 11.55s`。warnings 是既有 FastAPI deprecation 与 statsmodels singular/boundary warnings。 |
| `/Users/jiayuanren/项目规划/.venv/bin/python scripts/collect_v173_lmm_evidence.py --help` | exit 0。 |
| `git diff --check 0251f0a30d984bdbb2cfab404e6c646deab60cae..8b23cf25a854aad89dc6f13fa837911518b07c17` | exit 0。 |

没有对真实 supplied candidate 运行收集器，也没有创建 `eval-v173-lmm-XXX` manifest、性能 evidence 或 browser screenshot。测试中的临时 candidate 只用于验证 fail-closed guardrail，绝不构成 candidate acceptance。

## Protected-file audit

对 `0251f0a30d984bdbb2cfab404e6c646deab60cae..8b23cf25a854aad89dc6f13fa837911518b07c17` 执行下列 protected paths 的 `git diff --name-only`，结果为空：

- `backend/workbench/contracts`
- `tests/fixtures/models/linear_mixed_effects`
- `backend/workbench/analysis_loop/adapters.py`
- `backend/workbench/analysis_loop/compare.py`
- `backend/workbench/analysis_loop/validation.py`
- `backend/workbench/narrative`
- `backend/workbench/validation.py`
- `backend/workbench/engine/stages/validation.py`
- `backend/workbench/diagnostic_preview/contract_validation.py`

本 correction 仅修改 Evaluation harness、其测试和证据规则；没有读取真实 API key、调用真实 provider、安装依赖、push、PR、merge、tag 或 release。

## 后续入口与回滚

- 未来 evaluator 必须提供一个新的、干净的 candidate worktree 和其 `HEAD` 的完整 SHA；缺少 runner/input/diagnostics/Agent API、任何 protected diff、任何 post-run mutation 或网络访问都会 fail closed。
- candidate 真正通过 strict evidence 后，仍须按 `evaluation/browser-scenario.md` 完成十步 in-app browser 验收、记录截图 hash，并生成新的不可覆写 manifest；那之前 `acceptance.accepted` 始终为 false。
- 若需撤回 harness correction，使用普通 `git revert 8b23cf25a854aad89dc6f13fa837911518b07c17`；不改写 C1.1 contracts、fixtures、receipt 或历史 evidence。
