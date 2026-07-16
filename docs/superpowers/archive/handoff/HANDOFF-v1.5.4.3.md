# V1.5.4.3 对接清单（新会话窗口从这里接手）

## 你是谁、在干什么
执行 **Workbench V1.5.4.3 — Foundation Hardening（地基加固版）**。纯护栏/结构债，**零用户可见新功能**，必须行为冻结（golden 0-drift）。

## 工作目录（必须用这个，别在旧版或主检出里跑）
```
/Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.4.3
```
- 分支：`workbench-v1.5.4.3`，基于 `main` @ `8553c86`
- venv（全 extras）和 frontend/node_modules **已预装好**（本会话建的；若缺失见下方"环境重建"）

## 必读文档（都在仓库里）
- **Spec：** `docs/superpowers/specs/2026-06-09-workbench-v1.5.4.3-foundation-hardening-design.md`
- **Plan（逐任务 TDD）：** `docs/superpowers/plans/2026-06-09-workbench-v1.5.4.3-foundation-hardening.md`
- 背景（脆弱性评估+反脆弱门槛）：`docs/architecture/2026-06-09-extensibility-assessment-and-antifragility-guide.md`

## 当前进度
- ✅ Task 0 已完成一半：worktree 已建、环境已装。**实现代码一行还没写。**
- ⏭️ 从 **Plan 的 Task 1** 开始（fail-loud 报警器）。

## 范围（9 任务，6 阶段）
1. 后端 pack 护栏：①fail-loud ②`StageInsertion` 显式插入 ③`rerun_actions` 接线
2. 修 pytest 脚枪（`pyproject.toml` 加 `pythonpath=["backend","."]`）
3. 前端类型门（tsconfig + 修光所有 tsc 错，零错门禁）
4. `scripts/gate.sh` 一键网关
5. App.tsx 拆出 `RunForm`（行为冻结，tsc 兜底）
6. 最终 gate + release notes

## 怎么跑测试（关键，别踩坑）
```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.4.3
.venv/bin/python -m pytest -q            # 后端全量（Task 4 修脚枪前，必须用 python -m，别用裸 .venv/bin/pytest）
cd frontend && npx vitest run            # 前端
```
**基线（环境装好后先验证）：后端 751 passed / 前端 582 passed。** 不对就先排查环境，别开工。

## 反脆弱门槛（每个任务都要过）
- **G0-1** 验收跑**全量**套件（不是子集，不是裸 pytest）
- **G0-2** golden 0-drift：`.venv/bin/python -m pytest tests/test_engine_golden.py tests/test_lineage_invariants.py tests/test_behavior_snapshot.py -q` 全过、零漂移；新代码在 CORE_PACK 不触发的情况下行为字节不变
- **G0-3** 接线类测试必须"删掉接线就变红"（Task 3 有显式反验证步骤）

## 推荐执行方式
**Subagent-Driven Development**（每任务派全新 subagent + 两阶段 review：spec→quality，主控不自己写实现）。
- 新窗口第一步：读 Plan 全文 → 跑基线确认 751/582 → 从 Task 1 派 implementer subagent。
- 每个发给 subagent 的 prompt 要自带全部上下文（别让它读 plan 文件），并强调"用 `.venv/bin/python -m pytest`"。

## 发布拓扑（全部做完后）
tag `v1.5.4.3` 打在分支 head → 向前合并进 `main` → 保留分支+worktree 作版本标记（同 v1.5.4.1/4.2）。release notes 写 `docs/v1.5.4.3-release-notes.md`。

## 环境重建（万一缓存丢了）
```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.4.3
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
cd frontend && npm install
```

## roadmap 上下文（别越界）
本版只做地基加固。**不碰**：orchestrator.py 文件拆分（→V1.5.4.5）、IV/2SLS（→V1.5.4.4）、diagnostics/report_blocks 等其余孔（只报警+标注，不接线）。
