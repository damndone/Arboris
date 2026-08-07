# P7 ROC 与分类诊断设计

## 目标

提供只消费 `y_true + score` 的分类诊断内核，不训练模型、不创建预测 split，因此不会
绕过预测研究的 P1/P2 能力层。

## 输入边界

- binary target、`positive_label`、score 列和 score semantics 必须显式声明。
- ROC score 可为任意有限实数；probability-only 指标要求 score ∈ [0,1]。
- 不猜正类、不把类别编码顺序当成正类、不删除缺失行而不计数。
- 阈值输出策略显式选择 `unique_scores` 或有界 `quantile_grid`；阈值优化必须传入
  明确成本/约束，内核默认只报告证据。
- calibration 分箱方法和 bins 数显式声明，最大阈值/分箱数量受界限保护。

## 计算与输出

- ROC points、AUC、PR curve、stepwise PR-AUC、confusion counts、sensitivity、
  specificity、PPV、NPV、F1、Brier 和 log-loss（适用时）。
- 每个点保留阈值方向、tie policy、positive/negative counts、缺失计数和 score semantics。
- 不产生“最佳阈值”结论；若调用者声明约束，输出候选排序及完整约束证据。

## Oracle 与安全

- R base 用独立 rank/trapezoid/Wilcoxon 计算 AUC 与固定阈值表；不依赖未安装的 pROC。
- 使用性质测试：AUC ∈ [0,1]、标签翻转 AUC 对称、全 tie AUC = 0.5、阈值单调性。
- 不把分类诊断说成因果效果，不接受任意代码/公式，不调用模型训练器。

## 非目标

不接 model family、prediction runner、Agent、frontend、SHAP 或自动交叉验证。
