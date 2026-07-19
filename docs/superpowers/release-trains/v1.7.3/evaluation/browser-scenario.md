# v1.7.3 LMM 独立浏览器验收场景

状态：待候选 Integration commit 提供后执行。本文不是自动化 E2E 声明；必须使用可用的 in-app browser 逐项完成，并由独立评估者记录结果。

## 执行前置条件

- 候选 worktree 的 `HEAD` 必须等于本次记录中的候选 SHA，且 `git status --porcelain=v1 --untracked-files=all` 为空。
- 候选必须从 C1.1 `0251f0a30d984bdbb2cfab404e6c646deab60cae` 派生，且不得修改受保护路径。
- 只使用本地服务、canonical fixture 与 fake/local 流程；不得读取 API key 或调用真实 provider。
- 每张截图先保存在 worktree 外，计算 SHA-256 后才可写入 Evidence Manifest；不得记录 cookie、token、原始用户数据或 provider 输出。

## 场景

1. 启动文档规定的本地 backend 和 frontend，并记录实际启动命令、退出码和候选 SHA。
2. 上传 `tests/fixtures/models/linear_mixed_effects/known_truth.csv`，选择 **Linear Mixed Effects**。
3. 选择 `participant_id`、`week`、`arm`、REML 和 random time slope。
4. 提交初始 run，等待终态；若失败，记录终态和诊断后停止，不把失败写成通过。
5. 检查 fit method、convergence、interaction、samples、random effects、diagnostics 与 trajectory table；浏览器不得重新计算这些模型事实。
6. 使用 singular-warning fixture，确认出现 PlanDiff 以及“简化随机效应”的 confirmation-required proposal。
7. 仅确认一次，确认 child 出现且 source 未被改写；不得把 proposal 或确认本身描述为已自动执行。
8. 检查 parameter、sample、result、conclusion 四个 compare layer；REML 固定效应不同的比较必须为 restricted，且不出现 winner/better/优劣结论。
9. 使用 `missing_subject_id.csv`，确认显示解释且没有 confirmation button。
10. 截取 successful、recovery 与 blocked 三种状态；对每个文件计算 SHA-256，并在 Evidence Manifest 中记录路径、hash、候选 SHA 和观察结果。

任何一步不满足时，将对应结果写为 `failed` 或 `not_run`，并保留非 secret 的命令输出 hash。不得以浏览器未执行、截图缺失或未知候选 SHA 宣称浏览器验收通过。
