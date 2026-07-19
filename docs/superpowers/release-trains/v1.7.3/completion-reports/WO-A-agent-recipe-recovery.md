# WO-A Agent Recipe Recovery — Completion Report

状态：本地候选代码链已提交，等待 Integration/主控复核；不是 release、PR 或路由接线声明。

## 可追溯性

| 项目 | 值 |
| --- | --- |
| worktree / branch | `/Users/jiayuanren/项目规划/.worktrees/v173-agent-recipes-recovery` / `feat/v173-agent-recipes-recovery` |
| release baseline | `4b2e6c1d9ddd289005b84c186255fec2e9cbd86a` |
| branch start / C1.1 contract lock | `0251f0a30d984bdbb2cfab404e6c646deab60cae` |
| governance receipt reference | `f25ffd119df91479aabfcebcb549a47a1153e227`（只读引用；未 cherry-pick） |
| 初始 recipe 实现 | `5ce9824014d8d961bfd73d243776f41d89b785fe` |
| 当前信任边界修复 | `a45082218cfc797b2eaaeda85b2ef2d1376a06b4` |
| 前一份证据报告 | `d148000b3377a0e5df2749a7a2258a263a4b059b` |

初始实现完成后，主控复核指出它把 raw source、raw diagnostics 和裸 compare mapping 当作可信输入。当前候选以 `a450822` 在原实现上收紧边界；Integration 应将 `5ce9824` 和 `a450822` 视为同一候选代码链，而不是单独采用旧实现。

## 产物与范围

候选代码提交只改动下列允许路径：

- `backend/workbench/agent/recipes/repeated_measures.py`
- `backend/workbench/agent/recipes/lmm_explanation.py`
- `tests/agent/test_repeated_measures_recipe.py`
- `tests/agent/test_repeated_measures_recovery.py`

本文件是本 Lane 唯一 metadata 输出。没有注册 recipe、修改中央 route/dispatcher、执行 proposal、创建 child run、调用 LLM，或读取真实 key/provider。

## 已修复的信任边界

1. 非空 `source.model_options` 在任何 proposal 或具体 LMM 说明前，都会通过既有 C1.1 `verify_bound_model_options` 和 `verify_binding_owner_for_model_type`。缺失 binding、owner/model 不匹配、hash 篡改、非 LMM、`random_slope: false`、blocked/unknown source 均只返回中性说明。
2. 诊断列表先整体解析为完整 C1 `LmmDiagnostic`，再开始任何扫描。每一项都要求完整字段、合法 evidence/severity/status/candidate；包括 `0`、`0.0` 或字符串伪装的 false patch。任一项无效时，混合列表无论次序都不会生成 proposal 或具体说明。
3. `build_lmm_explanation` 也重走 source 与完整 diagnostics 校验。restricted-REML 说明只接受 C1 `PacketEnvelope`、LMM producer/version 和受限 reason/safe-message/run-id 事实均匹配的 compare packet；裸或畸形 compare 不会触发该说明。
4. recovery patch 结构严格锁为 `{"model_options": {"random_slope": false}}`，并要求 Python `bool` 的精确 `False`，不依赖 Python 中 `0 == False` 的宽松相等性。

中文说明只从固定的受控事实生成，不回显 evidence 或 compare 文案，也不包含 `导致`、`造成`、`证明因果`、`因果效应`。

## TDD 证据

Python 命令固定为 `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest`。

| 修复切片 | RED 结果 | GREEN 结果 |
| --- | --- | --- |
| 非空但未绑定的 LMM source | 原 builder 仍产生 proposal | `-k nonempty_unbound_lmm_source`：`1 passed` |
| 无效 evidence 与随后有效 candidate | 原 builder 在看到后项后仍产生 proposal | `-k invalid_diagnostic_suppresses`：`1 passed` |
| exact bool patch | `0` 与 `0.0` 没有被拒绝 | `-k exact_boolean_false_literal`：`4 passed` |
| source 未验证时的具体 compare 说明 | 新 API 前 `source=` 参数不受支持 | `-k unverified_source_cannot_emit`：`1 passed` |
| 裸 restricted compare mapping | 仍输出 restricted-REML 说明 | `-k unverified_compare_payload`：`1 passed` |
| 畸形 diagnostics 绕过合法 compare packet | 仍输出 restricted-REML 说明 | `-k malformed_diagnostics_cannot_bypass`：`1 passed` |

测试中的临时 LMM handler 只通过 `monkeypatch` 注册，用于构造真实 C1.1 server-owned binding；生产代码只消费既有 C1.1 公开验证 API，未复制或改写 resolver。

## 新鲜验证

```text
PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  tests/agent/test_repeated_measures_recipe.py \
  tests/agent/test_repeated_measures_recovery.py -q
# 37 passed in 0.79s

PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  tests/contracts/test_lmm_contracts.py \
  tests/contracts/test_lmm_error_contract.py \
  tests/contracts/test_lmm_canonical_packets.py \
  tests/test_agent_analysis_loop_contracts.py -q
# 66 passed in 0.25s
```

`git show --check a45082218cfc797b2eaaeda85b2ef2d1376a06b4`、候选范围的 `git diff --check` 均静默；本地未安装 `ruff`，因此没有把不可运行的 ruff 调用伪装成 lint 通过。

## 保护文件审计与交接

`git show --format= --name-only a45082218cfc797b2eaaeda85b2ef2d1376a06b4` 仅列出上方四个允许代码/测试文件。初始代码提交也只包含同一四个路径；本报告后续提交将只变更本文件。未更改 orchestrator、operations、analysis-loop central seam、pack/registry/capabilities、graph store、Agent Surface、gate 或两个 protected Honest-DiD tests。

Integration 可机械地接入这个 pure builder，但必须保留 confirmation boundary，不能将 proposal 叙述为已经执行 rerun。若拒绝整个 Lane，不 cherry-pick 两个候选代码提交即可；若两个提交都已进入集成分支，则按相反顺序回滚 `a450822`、`5ce9824`。本 Lane 未产生运行、child、数据或外部副作用。
