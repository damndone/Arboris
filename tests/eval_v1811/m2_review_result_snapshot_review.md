# C3 result_snapshot 独立低层接口审查

被审模块提交：`821ccda5f11ef00244222aed24efd4d0acdd4820`。仅新增 owned 审查测试/原样输出/此说明，没有修改生产或中央测试；Integration 已存在的其他 dirty 文件不是本审查改动。没有 HTTP result_snapshots/payload 入口。

独立命令（cwd 为 Integration）:

```text
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest -q tests/eval_v1811/m2_review_result_snapshot_adversarial.py > tests/eval_v1811/m2_review_result_snapshot_red.txt 2>&1
```

原样结果：`2 failed, 32 passed in 0.86s`。共享 runner 保留 pytest 所有临时资产。

## P2：巨大整数校验不完整

`backend/workbench/script_export/result_snapshot.py:99` 对系数 `10**400` 执行 `math.isfinite`，泄漏 `OverflowError`，不能通过 ContractError 的正常拒绝路径。复现节点 `m2_review_result_snapshot_adversarial.py::test_large_coefficient_is_contract_refusal_not_overflow`。

同模块行116只检查 nobs 为非负 int，接受 `10**400`，无法作为有限脚本数字由三语言一致消费。复现节点 `::test_nobs_not_representable_as_finite_script_number_is_rejected`。建议统一验证整数的有限可表示性、把 conversion overflow 转为 ContractError，并明确 nobs 的跨语言整数范围。Root 已接受修复；本报告描述修复前状态，不改原 RED 输出。

## 已验证与边界

路径/控制字符/ref版本、缺字段、九种 execution binding 替换、大小、嵌套重复 JSON key、FIFO、末级符号链接以及 honest-projector 下 expected 与 actual 分离均通过。distribution 是低层不透明元数据，本测试不把任意字符串接受解释为统计操作准入。

`test_builder_currently_accepts_wrong_source_identity` 和 `test_arbitrary_projector_can_ignore_asset_and_copy_expected` 是低层前提风险演示，不是来源信任验收 PASS：当前 builder 的 binding/artifact_id/result_contract 由受信任 caller 提供，projector 为受信任 Python adapter。raw SHA 由 builder 对读到的真实字节计算，但 SHA 不证明这些字节属于声明的 run/step，不证明投影来自 artifact。

Root 明确：Integration 上游真实 artifact builder 尚未实现；未来必须验证 manifest completed、plan/run/artifact identity、结果 availability，并通过受信任 registry 取投影器，不接受客户 callback。当前不存在公开 HTTP 入口，因此这两项不报已部署入口 P1，也不能宣称完整 snapshot 来源信任已完成。S renderer 仍需独立验证 runtime SHA/actual 自检和 model→post closure，不模拟 fit/predict。
