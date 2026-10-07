# LMM 新宿主证据

用户在 macOS 宿主运行真实 canary 验证，返回 **3 passed，1 warning，2.67 秒**。

保留的 owner：`local/v1811-lmm-host/runs/20261005_024643_550779_dbe309ee`；执行证据为 `local_startup_canary`。没有绕过准入、补签旧运行或在嵌套沙箱重跑。

R/lme4 原容差保持不变：固定效应最大绝对差 `9.565332526051407e-09`，SE 最大绝对差 `7.9580113040989e-07`；随机截距方差差 `3.7404650424788244e-06`，残差方差差 `-4.73113604071429e-07`。推断仍为 z/asymptotic，df_resid=355。

主线只读复验所有 26 条索引与实际文件 SHA 一致，完成结果有 5 个固定效应及完整 5×5 kernel。实际该 owner 的 Stata/R/Python 快照脚本实跑：3 passed，2.97 秒；再次纳入 203 项相关套件通过。读取前后 owner 文件 SHA 不变。

| 文件 | SHA-256 |
|---|---|
| artifacts_index.json | 2d1bd0aa7789763de5f2dcba8101caf4de9bbdf38c408c76ed7a04180596ce8c |
| run_inputs.json | 49490985c218280b9958447c49c59ff24add373e00b2cfe8a42c336b837de352 |
| artifacts/model_results/linear_mixed_effects_1.result.json | c1e2c07d43c3ba5b40d087b62c31d763ecbb6a7cbf0da6971e2ab5ac9e748a00 |
| model_results/inference_kernels/linear_mixed_effects_1.json | 8e0c420d91deeb2b55476fc6a6fa6fc9b842a4665eada494fd23882d77686782 |
| diagnostic_summary.json | 306ea90b6d632d1b18384edaeab6453d51a7e30b91e614fce1e668be3f14409f |

历史 `20261004_193220_489952_d82e653f` 及其失配索引保留。注册顺序在 `2c76cd0e` 已修复；`f623a4ee` 只加强宿主证据复制前后完整索引验证。

本证据证明 objective §4 的宿主估计对照及新 owner 导出。它不证明 LMM Wald/lincom/nlcom、REML LR 或 margins 已验证；这些方法的可用性仍由原声明与准入约束决定。独立范围审计见 `codex-v1811-live-harness` 工作树的 `2026-10-04-v1811-lmm-postestimation-scope-audit.md`（报告提交 c70ec8be）。
