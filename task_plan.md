# v1.8.9 P1 执行计划

## 目标

在 P0 硬化集成基线 `afc7649c81eb54ee8adcb89edc6be14fc8378d6f` 上完成并核验 P1：数据编辑器/元数据、`.sav/.zsav/.dta` 互操作、分类 ML、复杂抽样。所有结果必须走 typed contract、服务端确认、正式 evidence；未执行的浏览器/provider/release gate 单独标记为 NOT VERIFIED。

## 阶段

- [x] 盘点已有 P1 实现、历史线和集成缺口
- [x] P1-A 数据编辑器与元数据：实现/修复并完成单元与安全测试（package-local）
- [x] P1-B 原生文件互操作：元数据、失败闭环、依赖可用性与 round-trip QA（package-local）
- [x] P1-C 分类 ML：生产路径、中央消费者、泄漏/身份/证据 QA（package-local）
- [x] P1-D 复杂抽样：GLM 接线、variance 语义和不支持组合 fail-closed（package-local）
- [x] 集成、冲突审查、全量 P1 回归、静态检查和 QA 报告

## 约束

- 只在 `.worktrees/workbench-v1.8.9-hardening-integration` 及其受控分支工作；不覆盖根目录已有 dirty 文件。
- 优先复用已完成历史线；新增代码必须先有失败测试。
- 不把 package-local、browser、provider、full-gate、release 证据混为一谈。

## 收口结论

P1 四个模块在当前 candidate worktree 的 package-local 边界已完成并通过各自 formal verify：
数据 131 backend tests、前端 31 tests 与 TypeScript；survey 146 tests；classification 联合套件 229 passed/2 skipped。
Python compileall 与 diff check 通过，黄金不变量 23 passed。

分类 review 另外修复了校准尺度问题：模型选择/search 使用 raw OOF selection threshold；最终 holdout 使用 calibrated probability 与 calibration-eval operational threshold，两个证据均带 row refs 和 probability scale。

候选完整 gate 仍未通过：backend 6702 passed/308 failed/6 skipped/1 xfailed，frontend 1785 passed/9 skipped；失败集中在既有 P0 evidence-authority、legacy Agent/Notebook/Report 兼容和宿主边界。浏览器、真实 provider、授权宿主 full gate、merge/tag、release 仍是 NOT VERIFIED/NOT READY。

# v1.8.9 本地优先收口计划

## 目标

在当前 macOS/Darwin 本机完成 P0 的本地可信闭环：跨进程 Resume、server-owned authority、host identity/bootstrap、evidence owner、本地 deterministic planner/evaluator、Agent/Notebook/Report 统一 clean cutover 和内置浏览器自动验收。Linux、其他 macOS、云宿主、真实 provider 与 release 继续单独标记为 NOT VERIFIED，不作为本机阻塞条件。

## 顺序

- [x] 建立并验证 `workflow-execution-state.v1.8.9` 版本边界；旧状态只返回 `UNSUPPORTED_VERSION`
- [x] 让 workflow/evidence authority 在本机由 backend bootstrap，且重启后可用；所有 capability 仍采用 admission-gated FD 安全写入
- [x] 持久化本机 server identity、project/session/actor 绑定，接通 evidence owner 与 Report 正式证据
- [x] 审核 deterministic planner/evaluator，固定本地正确性基线并保留真实 Provider benchmark 接口
- [x] Agent、Notebook、Report UI/API 统一调用 cutover compiler；旧执行路由显式拒绝，不保留隐式 fallback
- [x] 在内置浏览器自动完成新路径验收，再做分层 QA、formal verify 和 retrospective

## 证据边界

package-local tests 只证明代码契约；浏览器验收只证明本机 UI 路径；deterministic evaluator 与真实 provider benchmark 分开记账；未测试的其他宿主和发布流程不宣称通过。

## 2026-08-24 本机 example 全链路验收

目标：在不改业务代码的前提下，启动当前 candidate，使用真实 DeepSeek 作为自然语言规划 provider，自动验收 Notebook → Agent → Report 的本机路径。

- [completed] 核对当前 worktree、服务和 provider 配置；本机 backend/frontend 已启动，DeepSeek 配置仅以脱敏方式确认
- [completed] 启动/复用 backend 与 frontend，并建立隔离 example run `20260824_195617_395366_dbf9cf55`
- [completed] 通过 Notebook 提交自然语言请求并记录 server preview/clarification；补齐绑定字段后被 runtime capability gate 拦截
- [completed] 通过 Graph Agent 完成同一安全 cutover；补齐绑定字段后得到同一 runtime 未绑定结果，未执行
- [completed] 打开 Report，确认只读取正式 evidence，不显示 raw fallback；正式 projection schema 校验失败时 UI fail-closed
- [completed] 完成浏览器截图、run 文件和 backend 日志分层核对；真实 DeepSeek 本轮未调用，原因是 Report 无可引用事实且 planner/runtime 已安全阻断

### 本轮结论

Example 的数据摄取、OLS(robust)拟合、诊断和图形生成成功；服务端也写出了带 server identity、project/session/run/model 绑定的 evidence packet/commit。最后的 Report admission 因 `REPORT_EVIDENCE_FACTORY_FAILED` / `REPORT_EVIDENCE_SCHEMA_INVALID` 被阻断，run 正确标为 `failed`，Report 显示 `UNAVAILABLE`，不会消费 raw `model_results`。这不是完整成功验收；正式 Report 和真实 provider benchmark 仍为 NOT VERIFIED。

## 2026-08-25 检测阻断修复

- [completed] 修复 Report 对“完成但降级”证据的状态映射与导出边界；保留正式 facts/warnings/degradation reasons，继续拒绝 blocked/unavailable/raw fallback
- [completed] 运行 Report/evidence focused QA：`198 passed, 10 warnings`
- [in_progress] 接通 provider manifest 声明到本机 server-owned workflow execution port；先以 joint F/White/quadratic 三个 executor 的红测锁定注入契约
- [pending] 在 runtime 接线通过后重启本机 backend，重新生成 example run，完成 Notebook → Agent → execution → evidence → Report 的浏览器验收
- [pending] 本地 deterministic path 通过后再调用真实 DeepSeek，并把 provider benchmark 与 deterministic evaluator 分开记录

## 2026-08-25 修复完成与本机验收

- [completed] 修复 post-estimation artifact 重试命名冲突：输出 identity 同时绑定计算 fingerprint 和 server workflow identity，保持 immutable output，不覆盖旧证据。
- [completed] 修复 Report 全局 evidence 与模型 post-estimation 共用 index 时的 namespace 混淆；Report owner 记录由 Report 自己校验，模型结果收集器不再误解析 `report:<run>`。
- [completed] 内置浏览器 fresh session 验收：Notebook 通过 server compile → confirmation → execution → evidence；Agent 通过自然语言 → clarification → compile → confirmation → execution → evidence；Report 读取 3 条正式 evidence 并成功生成保存报告。
- [completed] 本机真实 DeepSeek provider 已配置且 Report 生成调用返回成功；这证明本机 provider 可用，但不等同于完整 provider benchmark 已完成。
- [completed] 后端重点回归 `140 passed`；workflow truth/runtime `143 passed`；前端 Report boundary `14 passed`；TypeScript `tsc --noEmit` 通过；浏览器本轮新增错误为 0。
- [pending] deterministic planner 全能力 benchmark、Linux/其他宿主、full gate、release 仍按边界单独验证，不能用本机闭环替代。
