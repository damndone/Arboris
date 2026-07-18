# v1.7.3 LMM Dependency Feasibility

记录日期：2026-07-18。

## 已验证的依赖可用性

- Interpreter：`/Users/jiayuanren/项目规划/.venv/bin/python`
- `statsmodels.__version__`：`0.14.6`
- `MixedLM.__module__`：`statsmodels.regression.mixed_linear_model`

验证命令：

```bash
PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -c 'import statsmodels; from statsmodels.regression.mixed_linear_model import MixedLM; print(statsmodels.__version__); print(MixedLM.__module__)'
```

## 边界

这只证明共享环境可导入现有 MixedLM API；它**不是**统计可行性结论，也不是 Model Pack 已实现的证据。

Task 4 必须在 C1 canonical `known_truth.csv` 已生成后，用真实 REML 与 ML fit 记录：fixture SHA-256、convergence、参数标签、estimate、运行时长和准确命令。若该 fit 失败，必须停止在 Model Pack 前，请用户决定范围或依赖；不得安装、升级或修改共享依赖。
