# Codex 实现 / Claude 核验 对接协议

> 生效于 2026-08-08。基线 `c213abd`（P0 + P1 完成）。
> 分工：**Codex 实现，Claude 核验与挖掘问题。** 用户在两者之间做决策。
> 所有路径相对 `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.8`。

---

## 0. 信任边界（用户已定，最重要的一节）

**Claude 只信 git，不信汇报。**

Codex 的文字汇报**只当线索**。每一轮核验，Claude 都从 commit、diff、自己跑测试、自己做突变**重新得出结论**。

这不是不信任，是这一版的实测结果。Codex 的三次汇报都**基本属实但不完整**：

| 汇报说的 | 实际 |
|---|---|
| 「测试全过」 | 有一条用 cwd 相对路径，换目录跑就假红 |
| 逐轮列了 171/150/46 | 合起来跑是 320，且它从未跑过合集 |
| 「纯新增，merge 干净」 | 三天后变成 104 新增 + **16 修改**，动了共享引擎路径 |

**没有一条是撒谎，全部是「没被问到就没说」。** 所以协议的设计目标不是抓谎，是**让没被问到的东西也暴露出来**。

**推论**：Codex 不需要为了让 Claude 相信而写更长的汇报。汇报只需要给出**线索与去向**（改了哪些文件、做了什么突变、哪些没做），Claude 自己去看。

---

## 1. 必读文件（按这个顺序，约 60 分钟）

### 第一层：这个版本在做什么、为什么

| 文件 | 读什么 |
|---|---|
| `docs/superpowers/specs/2026-08-07-v1.8.8-data-management-in-natural-language-design.md` | **§0 三条北极星约束**（一切取舍由它裁决）、§2 四个决策、§5 分期表与 P0 完成记录 |
| `docs/superpowers/plans/2026-08-07-v1.8.8-p0-composition-seam.md` | 顶部那条「**断言必须验活**」的硬规矩，以及它为什么存在 |
| `docs/superpowers/plans/2026-08-07-v1.8.8-p1-capability-contract.md` | **§0 能力 ≠ 操作**（这是全局最容易搞错的概念） |

### 第二层：现在的地基长什么样

| 文件:行 | 是什么 |
|---|---|
| `backend/workbench/agent/capability_contract.py` | P1 的产物。`CapabilityContract` / `capability_inventory()` / `unreachable_capabilities()` / `CAPABILITY_SURFACES` 判决表 |
| `backend/workbench/agent/workflow_contracts.py` 的 `StepSpecContract` | step 契约。注意 `produces_dataset` / `consumes_input_frame` / `replayable_by_recipe` 三个 P0 新增字段，以及从它们**派生**的三个 frozenset |
| `backend/workbench/agent/workflow_contracts.py` 的 `validate_workflow_steps` | `source` 来源承诺的校验、`_reject_unreadable_data_sources` |
| `backend/workbench/agent/workflow_runtime.py` 的 `_resolve_committed_source_frame` / `_lineage_source` | P0 的执行期解析与血缘归属 |
| `backend/workbench/agent/workflow_contracts.py` 的 `workflow_step_vocabulary` | **公布给 planning agent 的唯一出口** |
| `tests/test_workflow_seam.py` | P0 的 44 条守卫。**读它就知道什么算「验活过的断言」** |
| `tests/test_capability_inventory.py` | P1 的 28 条。特别看 `test_no_summary_is_the_capability_name_echoed_back` 与那条钉死当前数字的测试 |

### 第三层：待做的与已知的坑

| 文件 | 读什么 |
|---|---|
| `docs/superpowers/specs/2026-08-08-p7-capability-adoption.md` | P7 的 29 个能力怎么接入，含四个已定位的坑 |
| `docs/superpowers/followups/BACKLOG.md` 的 §6 | v1.8.8 途中发现、不在范围内的 |
| 本文 §5 | 未决问题清单 |

---

## 2. 环境铁律（每一条都是踩过的）

**① 每条 shell 命令自带绝对路径 `cd`。** 工作目录会漂到别的 worktree。本会话踩过三次：`git log` 给出别的分支的 HEAD、`grep` 给出旧文件的行号、`cd backend` 报 no such file。**最危险的一次是 `git log` 那次——它给出的是 v1.8.7 的 HEAD，我差点据此下结论。**

**② 跑 Python 必须用 worktree 自己的解释器。** 裸 `python` / `python3` 会解析到别的 worktree 的引擎。

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.8/backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/xxx.py -v
```

**③ 跑全量必须从仓库根跑。** 在 `backend/` 下跑会让若干用 cwd 相对路径的测试**假红**（`test_acceptance_templates`、`test_manova_pack` 里各有一条）。

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.8 && PYTHONPATH=$PWD/backend ./.venv/bin/python -m pytest tests -q \
  --ignore=tests/test_cs_did_oracle.py --ignore=tests/test_sa_did_oracle.py --ignore=tests/test_cs_did_clustering.py
```

后三个文件在 collection 阶段就 `FileNotFoundError`（缺 R oracle fixture），与任何改动无关。

**④ full gate 只能在宿主终端跑。** agent 沙箱里那段 containment 检查会**假报约 20 个失败**（macOS 拒绝嵌套 `sandbox_apply`）。

**⑤ 内存**：`run_pytest` 无 `-n`，单进程，安全。风险在 `npx vitest run`——但 `frontend/vite.config.ts` 已有 `maxWorkers: 4`，注释里记着那次打到 40GB 的事故。**不要提高这个值。**

**⑥ 等待循环别用 `pgrep -f "模式"`。** 循环自己的命令行含有那个模式，会永远等自己。本会话因此白等 24 分钟——测试其实 11 分钟就跑完了。用 `[p]ytest` 括号写法或匹配 PID。**推论：先看终止信号（结束行、退出码），别先看活动信号（进度点）。**

**⑦ 未经用户明确授权，不 push / 不建 PR / 不 merge / 不 tag。**

---

## 3. 五条硬规矩（这一版挖出来的，不是洁癖）

### 规矩一：断言必须验活

**每写一条新断言，把实现临时改成它声称要拦的那个错误，确认测试变红，再改回。只跑出绿色不算数。**

本会话出现过**六条**「看起来在守卫、实际什么都不守」的断言，**其中三条出在设计者自己写的东西里**：

| 假守卫 | 为什么假 |
|---|---|
| `assert produced["artifact_id"] in result.artifact_ids` | `artifact_ids` 里数据和 recipe 两个都有，`in` 对二者同真 |
| 比对 `produced["result_fingerprint"] != upstream.result_fingerprint` | **两边是同一个 str 对象**，恒不触发 |
| `if not summary.strip()` 拦「空 summary」 | 拦不住「拿 capability_id 回显顶上」 |
| `assert len(subject) == 7` | 硬编码计数，对**合法**新增也会红 |

**验活时也要小心验活脚本本身**：本会话有一次四个突变全部「跑」成了 `no such file`（脚本路径写错），等于四条假验活。**脚本要先 assert 锚点存在、再 assert 文件确实变了。**

### 规矩二：派生，不手写第二份清单

值集合从声明派生，配一条元测试防漂移。范式见 `STEP_REPLAYABLE_BY_RECIPE`（从 `StepSpecContract.replayable_by_recipe` 派生）与 `capability_inventory()`。

**验活方式固定**：注入一个假条目 → 清单自动包含、测试不改仍绿；再把派生换成硬编码 → 同一假条目让测试变红。**只做第一步证明不了什么**——手写清单在没加假条目时也是绿的。

### 规矩三：先问「谁真的会读这份东西」

这是本仓库反复出事的根因。已知的多消费者陷阱：

- **`workflow_step_vocabulary()` 有三个消费者**：`planning_agent.py`（整 dict）、`operations.py:353` → `inspect_operation_contract`（整 dict）、**`agent_routes.py` 逐键挑选渲染成 agent 协议文本**。只往 dict 里加一项，chain agent **一个字都看不到**。
- **LLM 读 `proposal_schema`，不读 `editable_schema`**。
- **前端 `ProvenanceDiff` 故意不按 `kind` 分支**，读 present 的字段。

### 规矩四：静默降级 / 回退 / 丢弃 / 排除 = 严重缺陷

事故原型：一次名字不匹配静默 `continue`，标准误用了 **0.7804** 而不是正确的 **1.5955**，**run 成功、报告正常、全套测试绿**。

推论：

- 「不在清单里」和「在清单里但显式豁免」是两个不同的断言。排除必须写理由。
- 「够不着」和「有意不给」必须分开。把缺口写成豁免是粉饰。
- 类型不对不要静默转 `None`——写侧和读侧的严格度要一致。
- 报错**不要把一种可能原因断言成唯一原因**。

### 规矩五：元测试胜过人工点名

Task 4.6 是最好的例子：审查人工点出 4 条说谎路径，**元测试跑出 8 个算子里 7 个在说谎**。

**人只能点出他看见的那几条。** 凡是「某类东西都应该满足某性质」，写成遍历式元测试，而不是逐个断言。有意例外**显式白名单化并写明理由**，不得静默跳过。

---

## 4. 流程

### 4.1 每个 Task 的循环

```
Codex 实现（含自我验活） → 提交 → 通知用户
      ↓
Claude 从 git 重新核验（不看汇报也能做完）
      ↓
有问题 → Codex 修 → Claude 重验
无问题 → 用户放行下一个 Task
```

**Claude 每轮固定做的事**（无论 Codex 汇报什么）：

1. `git log` / `git status` / `git diff --stat` 确认改了什么、有无未提交残留
2. **自己跑测试**，从仓库根跑
3. **自己做突变**，验 Codex 声称的守卫是不是活的
4. 检查**范围**：有没有碰不该碰的路径
5. 检查**多消费者**：这次改的东西有几个读者，是不是都接上了
6. 固定一问：**有没有留下「做出来了但够不着 / 没接线」的东西**——并区分「暂时没消费者（任务切分）」与「消费者不在 agent 那一侧（本版要修的病）」

### 4.2 Codex 每个 Task 要汇报的（简短即可，Claude 会自己查）

1. **状态**：DONE / DONE_WITH_CONCERNS / BLOCKED
2. **改了哪些文件**（Claude 会 diff 核对）
3. **红测的真实报错原文**——以及它是否为**预期的原因**（因为别的原因红，等于这条测试测的不是你以为的东西）
4. **每条新断言的验活结果**：突变了什么、报错原文
5. **偏离计划的地方 + 为什么**
6. **哪些没做 / 留给后续**（这一项最有价值——本版几次重要发现都来自实现者主动说「我没做 X」）
7. 固定一问同上

**不需要**长篇复述做了什么。Claude 读 diff 比读散文快。

### 4.3 什么时候必须停下来问用户

- 计划本身错了（本版发生过四次，包括「组合不存在」和「Task 4 把缺口当豁免」）
- 要改动 P0/P1 的地基（`capability_contract.py` / `workflow_contracts.py` 的契约字段）
- 要放宽任何一条硬规矩
- 红测**意外通过**——那说明测试是假的，别自己换个断言绕过去

---

## 5. 未决问题清单（Codex 接手时的真实状态）

### 🔴 P2 动手前必须解决

**`CapabilityContract.is_reachable` 是乐观的。** 它只看 `proposed_by` / `composable_as` 非空，**不看那条路径自然语言走不走得通**。

已核实：自然语言可提议的 operation 只有 **4 个**——`data.columns.cast` / `graph.fork` / `model.rerun` / `operation.multi_step`。**`model.genesis` 的 `natural_language_enabled=False`**，而 22 个模型族的 `proposed_by` 全指着它。

诚实的可达数字（含经 `operation.multi_step` 的组合路径）：

```
直接提议可达            4
经 multi_step 组合可达  30  （20 模型族 + 10 数据操作）
────────────────────────────
真实可达               34 / 54 = 63%
两条路都不通            20
```

> ⚠️ 算这个数字时**必须算上组合路径**。只算直接提议会得出 4/54 = 7%，与真相差九倍。
> 本会话差点报出那个错数字。

那 20 条里 **2 条是有意关闭**（`code.execute` 是用户既定决定；`data.column.cast` 被批量版取代），**18 条是真缺口**：8 检验族 + 3 预测模型 + 4 数据准备 + 2 时序族 + 1 selector。

**P2 的第一个任务应该是让可达性判定认得 `natural_language_enabled`**，然后再上守卫。否则守卫会对走不通的路径判绿。

### 🟠 P7 接入前必须重验

**我 8 月 7 日那份「纯新增、merge 干净」的核验已经过期。** 现在 P7 worktree 是：

```
104 新增 + 16 修改 + 50 行删除
```

修改的是**共享引擎路径**：`backend/workbench/imputation.py`、`engine/stages/{estimation,diagnostics,imputation}.py`、`orchestrator/_report_build.py`、`report_view_model.py`，以及 golden 测试和契约样本。

merge 目前**仍然干净**（`git merge-tree` exit 0），因为 P0/P1 没碰这些文件。但风险性质变了——**合并前必须重跑核验，不要引用旧结论。**

### 🟡 已定位、待处理

| 问题 | 位置 |
|---|---|
| `power_analysis.py` 有 `CONTRACT` 但**无 `*_OPERATION_IDS`**，按命名约定枚举会静默漏掉它；且它的能力空间是 3 designs × 4 targets 的组合，「补齐 frozenset」要先决定补 2 条还是 12 条 | P7 worktree |
| multivariate 的 8 个 id 拆在**两个** frozenset 里，只查「存在 `*_OPERATION_IDS`」的元测试仍漏 5 条 | P7 worktree |
| 「29 个能力都消费输入帧」**只有 23/29 成立**。`combine_effects(studies: Any = None)` 的 `Any` 标注最坏——标成 `consumes_input_frame=True` 而不写适配层，DataFrame 会被当 `studies` 吞掉而不报错 | P7 worktree |
| `SAMPLING_UI` 三项无 description，`PREDICTION_UI` 的 description 只有三个词。P1 在派生处合成 summary 并注释说明缺失，未改注册表（越界） | `capabilities.py` |
| `branches` payload 有与 `produced_dataset` **相同的 resume 缺陷**，且**没有兜底**。不在 P0 契约内，属存量 | `workflow_runtime.py`，已记 BACKLOG |
| `"model_artifact_id": "ols_1"` 硬编码，非 OLS 族会写一个不存在的 artifact 名 | `workflow_runtime.py`，已记 BACKLOG |
| P0 Task 4 的三项质量整改（M2/M3/M4）**故意未做** | 已记 P0 计划 |

### 尚未做的验收

**真机链式验收从未做过。** Task 7 之前，P0 全部成果的唯一消费者是测试。现在 `source` 已公布，必须真机跑一次（真 DeepSeek → 出含 `source` 的方案 → 批准 → 执行 → 查 lineage）。

**但今天能演示的形状很窄**：`produced_by` 只有 `statistical.derive_numeric` 一个，能被 `from_step` 指名的只有「派生数值列」。reshape/subset/merge 要到 P3 才注册。

---

## 6. 验收标准（每个 Task 通用，可打勾）

**正确性**

- [ ] 红测的失败原因是**预期的那个**，不是别的原因
- [ ] **每条新断言都验活过**：突变实现 → 变红 → 改回。贴报错原文
- [ ] 突变时**只红对应的那一条**（若多条同时红，说明它们互相掩盖，分不清谁在守什么）
- [ ] 凡「某类东西都应满足某性质」，写成**遍历式元测试**，例外显式白名单化

**范围**

- [ ] 没碰不该碰的路径
- [ ] 没有为了让测试绿而放宽实现
- [ ] 偏离计划的地方都有陈述的理由

**可达性（本版的主线）**

- [ ] 新增的能力**在两张词表里都注册**，或在清单里带**陈述的豁免理由**
- [ ] 改了 `workflow_step_vocabulary()` 的话，**三个消费者都验过**（尤其 `agent_routes.py` 那条渲染路径）
- [ ] 固定一问答过：有没有「做出来了但够不着 / 没接线」的东西

**工程**

- [ ] 全量回归**从仓库根**跑，不低于基线（当前 **BE 4824** / FE 1648 / tsc 0）
- [ ] `git status` 干净，无突变残留、无未提交改动
- [ ] commit message 说清**为什么**，不只说做了什么
- [ ] 未 push / 未建 PR / 未 merge / 未 tag

**数值正确性（新统计能力专用）**

- [ ] **不接受「自洽即通过」**。对外部基准：statsmodels 或 R，容差参照 v1.5.8/v1.5.9 对 R 的做法（~1e-13）
- [ ] R 只在测试中调用，**生产代码零 shell/R**

---

## 7. 一句话总结这一版的方法论

**每一个真问题都是「今天无害、换个条件就静默出错」的形状，而且没有一个会让当时的测试变红。**

所以流程的全部重量都压在两件事上：**让断言证明自己是活的**，和**先问谁真的会读这份东西**。
