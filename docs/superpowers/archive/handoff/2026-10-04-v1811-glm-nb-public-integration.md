# GLM-NB 公共后估计集成

批准资产 `5b82e0e2` 已合入 `8a05bbe2`；S 批准候选已合入 `b3fdfd40`。
仅开放已通过真实 R/Stata 独立复验的固定 alpha、log、最终 EIM scale=1 五种后估计。
登记 `glm_negative_binomial.*` 原生参考，不改旧 oracle 或容差；Agent 可用性继续由后估计声明推导。
公共路径验证同 owner 登记 kernel、完成状态、数据 SHA；LR 检查相同 alpha 和实际响应/共享输入。alpha/lnalpha 不是回归系数。

## TDD 与验证

- 新 `tests/test_glm_nb_public_postestimation.py` 原始 RED：10 failed、1 passed，因旧准入未开放。
- 首轮接线：107 passed、3 failed；三项失败是原生完整精度 JSON 自由度用字符串保存，测试已按数值读入，生产推断及原参考未改。
- Final：上述公共测试、作者原生参考、全后估计 registry、admission kit、family literal ratchet 共 110 passed，21.42 秒；12 项已有 statsmodels BIC 警告。
- `frontend/npx tsc --noEmit` 通过。
- 全量/gate 未跑；独立公共入口审查、GLM-NB 浏览器和真机 Agent 仍待完成，PLANNED.live_eval 保留。

当前公开原生资产的许可证字段已脱敏；完整原始日志在 ignored 本机保留。历史本地提交仍含原日志，任何 push 前需用户批准解决历史问题，当前没有 push。
