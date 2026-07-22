# Work Order D — Independent Evaluation Lane

```yaml
work_package: v181-evaluation-harness
lane: evaluation
release_baseline_commit: d86bf30195ccf315ce9e9ae3948722ac64202b28
integration_base_commit: d86bf30195ccf315ce9e9ae3948722ac64202b28
contract_lock_commit: __C1__
branch_start_commit: __C1__

owned_files:
  - tests/evaluation/v181/**
  - tests/fixtures/evaluation/v181/**
  - docs/superpowers/release-trains/v1.8.1/evidence/**

read_only_contracts:
  - backend/workbench/contracts/**
  - tests/fixtures/contracts/v181/**

forbidden_files:
  - backend/workbench/**          # 不实现、不修复被测功能
  - frontend/src/**
  - scripts/gate.sh
  - tests/test_honest_did_adversarial.py
  - tests/test_honest_did_sd_adversarial.py

produces:
  - ETS known-truth 合成数据（已知 level/trend/damping，可复现 seed）
  - 故障注入：内部缺失、不收敛、奇异、样本过短、非法规格
  - 过度主张检查：ETS 结果中出现 VaR/波动率措辞即失败
  - 跨模型可比性检查：ETS vs ARMA-GARCH 的 AIC 比较必须被拒绝
  - 自引用检查：一批 3 条 option 生成后全部仍为 fresh
  - Evaluation Evidence Manifest（ADR §12.3 结构）

acceptance:
  - 每条失败报告含：可复现命令、基线、实际、预期、最小证据、归属建议
  - 不提供功能补丁
  - manifest 一经提交不得原地改写；复验生成新 evaluation_id

non_goals:
  - 实现或修复被测功能
  - 为通过测试而修改 estimator、recipe 或 UI
  - 静默提高容差、更新 golden、删除失败用例
  - 在没有 known truth 的情况下声称模型正确
```

## 独立性要求

ADR §7D：即便由同一个 AI 系统执行，也不得共享功能实现上下文来替作者补测试
或解释失败。本 Lane 在独立 worktree 中运行，**不读其他 Lane 的实现代码**，
只依据 C1 锁定的合同与公开行为。
