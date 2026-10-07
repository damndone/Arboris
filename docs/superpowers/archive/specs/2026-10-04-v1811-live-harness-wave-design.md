# v1.8.11 真机评测 harness 波次冻结

本波次以主线 e86e7d1fe732b6ba8863344ecacd0c1388202f46 为代码基础；本文件提交为接口冻结提交。只修评测入口，不改变统计方法、默认值或准入。生产线与独立复审线以该冻结提交为共同生产起点，复审读取最终候选。

## 执行合同

保留原 37 个用例并追加 objective 要求的 17 个族。新增 fixture packet 用仓库现有原生参考和现有字段容差，逐例声明 input CSV、源文件 SHA、完整模型参数、oracle 路径与字段投影。不得将实际 Workbench 结果自用作原生 expected。GLM-NB 使用 integration-strict-v1811 固定 alpha=1/log/EIM/scale=1 参考；独立负二项为估计 alpha NB2。IV 最低 case 使用已在主线的单内生参考，双内生专门验收由集成方在获准合入资产后另做；不能把单内生声称为双内生。LMM 真实执行准入必须由宿主 canary 发出，没有准入则记录阻断。

请求提出模型方案后，先核对提案操作、完整参数和目标；使用实际 revision/fingerprint 真实确认；等待真实 operation/run 终态；从 authoritative execution bindings/outputs 查出结果 run/session，再在结果 session 提问和取证。提案存在、回答里的 executed=true、工具文本中的模型名均不算真实执行。逐阶段保留结果，确认前的回答不能替代执行后的回答。完整运行记录 provider/model、源与结果 SHA、完整已执行参数、实际 family、确认链、原生数值差异和回答来源。

空、未知、重复 --only 与非正 --repeat 在配置读取、建项目和 provider 调用前退出 2。实际失败/阻断/超时、缺例或零结果退出 1，全部预期唯一用例通过才退出 0。逐例异常也写结果，不覆写现有 --out，不删除失败项目。原有未指定 --only 的全量行为保留；显式空 --only 是错误。实时 provider 运行只由集成方做，先查余额；离线协议验证不能宣称真机准入。

## 所有权

生产者仅修改 scripts/agent_live_eval.py、scripts/agent_live_eval_cases.json（原项保留），新 scripts/agent_live_eval_fixtures_v1811.json、新 tests/test_agent_live_eval_v1811_harness.py、新 tests/fixtures/agent_live_eval_v1811/**、专属 docs/superpowers/handoffs/2026-10-04-v1811-agent-live-eval-report.md。不得修改中心文件、旧 oracle、容差、dev_fixtures/agent_navigation.py。集成方负责 admission 与所有中心改动、真实 DeepSeek 调用及独立复审后的合入申请。

生产者先写失败测试，使用真实 public HTTP 和存储协议；允许 provider stub 验证离线确认时序，但必须显式标为离线，不覆盖真实证据。先离线单例验证再 17 例 schema 验证；共享独占锁，不跑全量/gate，不调 LLM，不碰 Downloads，不安装或删除。相关 pytest 与 tsc 通过后提交，报告清楚未验证项与现场命令。缺少原生字段参考时明确拒绝或限定已验证字段，不宽泛放大容差。
