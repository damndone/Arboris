# v1.7.3 本机 macOS 收尾证据

## 验收结论

`v1.7.3` 的本机 macOS Workbench 范围已验收。最终产品提交为
`730ebfc21840fa801d3d0dfc093899ae376b8b01`，分支为
`integration/v1.7.3`。

这不是网页部署、签名 App、第三方不可信扩展宿主或公开发布声明；本轮没有执行
push、PR、merge 或 tag。

## 产品范围收口

- 删除未使用的 C2 运行时原型与对应测试；未来不可信代码/第三方扩展隔离留在长期路线图。
- 保留 C1 静态边界与 `local_contained` 本机执行配置。
- 新增 `scripts/run-local-contained.sh`，每次启动都显式启用本机配置。
- 应用启动先执行真实 macOS sandbox canary；失败则不提供服务。
- `/health` 可见 `execution_profile`、LMM、高风险本地代码和 canary 状态。

## 自动化证据

精确父提交 `290c35e` 的完整门：

- 后端：`2503 passed, 8 skipped, 47 warnings`。
- 黄金、不变量与快照：`23 passed`。
- 前端：`137 files / 1217 tests passed`。
- TypeScript：通过。
- `git diff --check`：通过。
- 最终输出：`>>> GATE PASSED`。

浏览器发现真实公共包比前端夹具多出冻结的 `execution_binding`，因此第一版 UI
适配测试属于假绿。修复后，最终提交 `730ebfc` 只新增前端公共投影绑定校验、真实
形状夹具和 FMS 记录；完整前端再次得到 `137 files / 1217 tests passed`，TypeScript
通过。未第三次重跑完全未受影响的 2503 项后端测试，采用上述分层最终树证据。

## 真实 LMM smoke

- 项目：`/private/tmp/wb-v173-smoke.2bVUa8/project`
- run：`20260720_170211_106313_8f12dd67`
- 数据：480 个观测，80 个组，每组 6 次观测。
- 全流程耗时：约 0.679 秒。
- 组别 × 时间：估计值 `0.9404735706546966`，标准误
  `0.030871151514025686`，95% CI
  `[0.8799672255259271, 1.000979915783466]`，p 值
  `7.703447077524316e-204`。
- 诊断：`LMM_RANDOM_EFFECTS_SINGULAR`，作为真实警告保留并显示。
- 产物：6 张图、HTML/PDF 报告、XLSX、诊断包、恢复建议包和唯一版本化模型结果包。

## 精确最终提交的浏览器验收

在最终提交 `730ebfc` 上重新载入同一个真实 run：

- Graph：显示 `linear_mixed_effects (primary)`、480 行原始/清洗数据、报告和变量节点。
- Table：实际找到 1 行
  `group_time_interaction 0.9405 0.03087 7.703e-204`。
- Table：实际找到 1 条
  `Diagnostic: LMM_RANDOM_EFFECTS_SINGULAR`。
- Report：实际找到报告范围，并显示 `113 of 113 facts included`；LMM 系数事实
  `c3` 的值为 `0.9405`。
- Agent：会话 `agent_chain_3b02ff0b72e443758db4a1e0cdf47f4f` 完整结束于
  `agent_end`（事件 82）。只读能力最终成功读取结果、诊断、节点上下文、重复测量
  配方和 analysis-loop 上下文，给出 0.9405 的关联性解释，没有创建提案或修改。

Agent 在找到正确参数前发生了多次 `ValueError` 重试；这是效率缺口，不是最终功能
失败，已经如实保留在事件流，后续应改进 tool schema 参数提示。

## Report / Operations 独立证据

独立收口记录位于
`docs/superpowers/plans/2026-07-18-v1.7.3-report-ops-closeout.md`：91 项聚焦后端、
132 个前端文件 / 1168 项测试、2126 项后端通过 / 8 项跳过、604.89 秒真实
honest-DiD 基线，以及真实 DeepSeek 报告的 8 张图、39 个验证引用、0 个裸引用
标记和 HTTP 200 导出。

## 后续但不阻塞本机 v1.7.3

- 上线或封装 App 时再实施不可信扩展隔离、多宿主与签名/公证验收。
- 优化 Agent 工具参数发现，降低同状态重试和 token 浪费。
- 下一模型线按“时间序列诊断优先、预测随后”推进；Prophet、pmdarima、arch 作为
  后续公共依赖候选，经兼容性与体积评估后接入。
