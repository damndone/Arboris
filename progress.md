# v1.8.9 P1 进度日志

## 2026-08-22

- 读取并遵循 formal development-line、planning-with-files-zh、subagent-driven-development、TDD、verification-before-completion 规则。
- 完成当前 worktree、分支、历史 P1 提交和 formal line 状态盘点；尚未修改 P1 代码。

### P1 package-local 完成

- 数据编辑器/元数据与 native interchange：`131 passed`；前端 DataOperations/registry tests `31 passed`；`tsc --noEmit`、Python compileall、`git diff --check` 通过。
- Survey：`146 passed, 2 warnings`；覆盖 replicate correctness、BRR validation、design identifier、variance provenance、Probit/Poisson central projection。
- Classification：阈值/log-loss/解释/Agent-Notebook central reader、搜索和校准尺度联合套件最终 `229 passed, 2 skipped`。
- Classification calibration review：新增并通过 threshold scope/row identity/probability-scale 回归；`selection_threshold` 固定在 raw development OOF，operational `threshold` 固定在 calibrated development calibration-eval，最终 holdout 使用同一 calibrated scale。
- Formal lines `v1-8-9-p1-data-consumer-interchange-closure`、`v1-8-9-p1-survey-correctness-closure`、`v1-8-9-p1-classification-evidence-budget-closure`、`v1-8-9-p1-classification-correctness-central-closure`、`v1-8-9-p1-classification-search-threshold-alignment` 均单独 verify 通过并生成 retrospective。

### Full QA 与边界

- `scripts/gate.sh --full`：backend `6702 passed, 308 failed, 6 skipped, 1 xfailed`；golden/invariants `23 passed`；frontend Vitest `1785 passed, 9 skipped`；frontend TypeScript 单独 `tsc --noEmit` 通过。
- 失败集中于既有 P0 evidence-authority/owner host、legacy Agent/Notebook/Report compatibility 和 restricted host probes；P1 scoped suites 没有失败。浏览器、真实 provider、授权宿主 full gate、merge/tag/release 仍未验证。

## 2026-08-23 本地优先 P0 收口启动

- 已在 candidate `afc7649c` 上通过 formal CLI 冻结 `v1-8-9-local-first-cutover`，范围限定为当前 macOS/Darwin 本机。
- 已先写入 `tests/test_v189_local_first_bootstrap.py` 并确认测试处于红灯：版本拒绝、跨进程 authority 重启、server identity、evidence authority proof 目前尚待实现。
- 当前先处理版本边界、local workflow/evidence authority 和 host bootstrap；随后接 deterministic evaluator、统一 cutover 与内置浏览器自动验收。

## 2026-08-24 本机 example 全链路验收启动

- 用户授权使用真实 DeepSeek API；provider 只负责自然语言规划，Workbench 后端仍负责确认、执行、持久化和 evidence。
- 当前阶段限定为启动与验收，不修改业务代码；先核对现有 worktree、端口和 provider 配置，再建立隔离 example run。

## 2026-08-24 本机 example 全链路验收结果

- 服务：candidate `workbench-v1.8.9-hardening-integration`（HEAD `afc7649c`）的 backend/frontend 已启动；`/health` 通过；`/llm/config` 仅确认 provider=DeepSeek、model=deepseek-v4-flash、key 已配置且脱敏，未把 secret 写入日志。
- Example：复用本机隔离项目 `/private/tmp/wb-v189-browser-20260823-01`，使用 `examples/datasets/cross_section.csv`，生成 run `20260824_195617_395366_dbf9cf55`；摄取 30 行/4 列，OLS(HC1) 拟合和 14 个 figures 完成。
- Notebook：浏览器提交自然语言请求；第一次 server preview 要求 5 个字段，补齐 dataset ref/digest、read、internal、`workflow.post_estimation.joint_f_test` 后，明确返回“能力只有声明，运行时尚未绑定”；未产生 operation、confirmation 或 execution。
- Agent：同一新 run 走 Graph Agent；得到完全相同的 5 字段 clarification → 1 个 runtime capability clarification；没有确认按钮，不执行。这证明两个入口共享同一 server compiler/cutover 行为。
- Report：浏览器 Report 页面看到 `Legacy model_results: NON-AUTHORITATIVE / UNAVAILABLE`、`Evidence inventory: 0 facts`、`Generate report` disabled、reason=`REPORT_EVIDENCE_SCHEMA_INVALID`；没有 raw fallback，也没有生成伪报告。
- Backend run evidence：`run_manifest.json`、`model_results/ols_1.json`、`report_evidence.json`、evidence packet/commit、diagnostic summary 均存在；但 reporting 阶段记录 `REPORT_EVIDENCE_FACTORY_FAILED` 与 `REPORT_EVIDENCE_REQUIRED`，最终 run status=`failed`。因此“生成了 evidence 文件”不等于“Report 正式投影已通过”。
- Provider：本轮没有调用真实 DeepSeek。Notebook/Agent 在 deterministic/server compiler 阶段已被 clarification/runtime gate 阻断；Report 在 0 个可引用事实时被 UI 禁止提交。绕过这两个门禁直接调用 provider 不属于有效验收，故 provider benchmark 保持 `NOT VERIFIED`。
- 当前未修复业务代码；保留 browser tab 和两个服务进程，供用户继续检查。
- Formal FMS：已通过 `scripts/devline_control.py append` 记录本轮 `GATE/local_example_report_blocked`（event `7d3570c8-3d87-4f99-8e1b-14fb3df0e2c1`），随后 `verify --line v1-8-9-local-first-cutover` 通过；line 保持进行中，未伪造完成状态。

## 2026-08-25 修复检测出的两个产品阻断

- 已完成 Report evidence owner/projection 修复：完成但有 INFO/WARNING 的结果现在是 `completed / available / degraded`，正式事实不会被清空；Report wire 接受 `available` 和 `degraded`，仍拒绝不可用状态和 raw fallback。
- Report/evidence focused QA 在允许本机 Unix-socket authority fixture 后通过：`198 passed, 10 warnings`。
- 已按 TDD 先加入 workflow runtime 注入红测，覆盖 joint F test、White test、quadratic stationary point 三个声明；当前红灯明确为缺少 `workflow_post_estimation_execution_port`，实现与本机 host bootstrap 接线进行中。
- 本阶段尚未重新启动服务或重新跑浏览器 example；真实 DeepSeek 尚未调用，避免在 runtime/evidence 闭环恢复前绕过门禁。

## 2026-08-25 最终本机闭环

- 修复并测试 post-estimation retry artifact identity；同一计算的不同 server workflow 不再争用同一 immutable 文件。
- 修复 Report artifact namespace：`report:<run>` / `report_evidence.json` 由 Report owner 独立消费，workflow post-estimation collector 跳过该全局记录。
- 浏览器保持打开并完成 fresh acceptance：Notebook 显示 `Execution completed with server evidence`；Agent 显示 `completed / evidence bound`；Report 显示 3 条正式 facts、`Availability=AVAILABLE`、`Completeness=DEGRADED`，Generate report 后 history 出现 1 条已保存报告。
- 本轮 browser dev logs 在 2026-08-25T15:16:00Z 之后没有 error；本机 backend 请求 Notebook/Agent execute 与 Report generation 均返回 200。
- QA：重点后端 `140 passed, 5 warnings`；workflow truth/runtime `143 passed, 49 warnings`；frontend Report boundary `14 passed`；`npm run typecheck` 通过。warnings 为现有依赖/统计数值警告，不是失败。
- 真实 DeepSeek provider 已被本机 Report 调用成功；完整 deterministic planner/provider benchmark 仍未跑完，Linux/其他宿主、full gate、release 仍保持 NOT VERIFIED。
