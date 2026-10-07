# C3 result_snapshot 独立修复复验

被审修复 tip：`511616d55dc92acbc0ef891ca9c5a7eca55cdc93`；原被审 tip：`821ccda5f11ef00244222aed24efd4d0acdd4820`。此次只新增本 recheck、GREEN 原样输出和新 manifest，没有覆写旧 RED、旧 manifest 或旧报告，没有修改两 worktree 的生产。

原34个独立攻击节点原样执行，`34 passed in 0.99s`；原测试 SHA 与 RED 身份 manifest 一致。原两个 bigint P2 已关闭：巨大系数通过有限数检查正常抛 ContractError；nobs 被限制在 `0 <= nobs <= 2**53-1` 的跨语言精确整数范围。没有改测试期待、添加 skip/xfail 或放宽统计容差。

```text
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest -q tests/eval_v1811/m2_review_result_snapshot_adversarial.py > tests/eval_v1811/m2_review_result_snapshot_green.txt 2>&1
```

命令 cwd 为 Integration，经过共享独占锁与 retention=all；只复验原34节点，没有扩到全量/gate/LLM。

此 PASS 的边界仍是低层 trusted-projector 接口；34节点中 source-identity、expected-copy 的两个通过节点是前提风险演示，不是 provenance 安全验收。上游 builder 必须校验真实 artifact 的 completed、plan/run/artifact 身份和结果 availability，从 Integration registry 取可信投影器且禁止客户 callback。该上游尚未验证；现模块并非公开 HTTP 输入入口。S renderer 的 runtime actual 自检、snapshot dependency closure、原 None 行为和原生后续执行仍由 S 独立验收，本次不代替。
