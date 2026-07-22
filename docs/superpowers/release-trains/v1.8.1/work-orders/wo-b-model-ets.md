# Work Order B — Model Pack Lane：`time_series.ets`

```yaml
work_package: v181-model-ets
lane: model
release_baseline_commit: d86bf30195ccf315ce9e9ae3948722ac64202b28
integration_base_commit: d86bf30195ccf315ce9e9ae3948722ac64202b28
contract_lock_commit: __C1__
branch_start_commit: __C1__

owned_files:
  - backend/workbench/engine/packs/ets/**
  - tests/models/ets/**
  - tests/fixtures/models/ets/**

read_only_contracts:
  - backend/workbench/contracts/model/ets.py
  - backend/workbench/contracts/common/**
  - backend/workbench/engine/packs/loader.py

forbidden_files:
  - backend/workbench/engine/registry.py
  - backend/workbench/engine/capabilities.py
  - backend/workbench/engine/packs/builtin_declarations.py   # Integration 薄注册
  - backend/workbench/engine/packs/arma_garch/**
  - backend/workbench/agent/**
  - backend/workbench/graph_store.py
  - frontend/**
  - scripts/gate.sh
  - tests/test_honest_did_adversarial.py
  - tests/test_honest_did_sd_adversarial.py

consumes:
  - ETSResultContract@1.0
  - PackDeclaration / loader 扩展点

produces:
  - ets pack：input schema、validator、estimator adapter、diagnostics、
    ModelResultContract、compare adapter、RecommendedActionCandidate
  - known-truth fixture 与数值测试

preimplementation_acceptance_evidence:
  kind: failing contract test
  command: "pytest tests/models/ets/test_ets_known_truth.py -q"
  initial_observation: "pack 不存在"

acceptance:
  - known-truth：对已知参数生成的序列，估计值落在 Contract Sprint 锁定的误差范围内
  - 规格差异即不同模型：ETS(A,A,N) 与 ETS(A,Ad,N) 的 result_identity 不同
  - AIC/BIC 只在同族同样本内可比；与 ARMA-GARCH 比较必须返回
    comparability=restricted + reason_code=ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE
  - 内部缺失（interior gap）阻塞，不静默平滑跨过
  - 不收敛 = blocking diagnostic，不是"带数字的警告"
  - 绝不输出 VaR / 条件方差 / volatility 字段（契约会直接拒绝）

non_goals:
  - Agent 编排、确认 UI、自然语言
  - 从 runner 直接创建可执行 Agent operation
  - 引入新依赖（用现有 statsmodels 0.14.6 的 ETSModel，已验证可用）
  - 改动 ARMA-GARCH pack 的任何行为
```

## 为什么是 ETS

不是为了凑一个模型。Notebook 的产品前提是"Agent 给出几条可辩护的路径"，
而这只有在同一份数据上**存在至少两个可比模型**时才可验证。ETS 与既有
ARMA-GARCH 在同一条时间序列上构成真正的备选关系（均值模型 vs 均值+波动率模型），
因此 Compare 有真东西可比，Agent 的 option 也不是摆设。

`statsmodels.tsa.exponential_smoothing.ets.ETSModel` 已验证在现有环境可用
（statsmodels 0.14.6），**不得安装或升级任何依赖**。
