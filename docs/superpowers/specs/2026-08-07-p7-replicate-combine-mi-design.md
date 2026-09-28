# P7 Replicate-and-Combine and Multiple-Imputation Design

## Goal

修正现有 MICE 流程的推断错误，并建立可被 Bootstrap、Permutation、MI 和
Survey replicate 共同复用的 `replicate-and-combine` 基础。当前问题不是
MICE 不能生成一份完成数据，而是 `m > 1` 时仍只生成一份、仍只用一份模型
结果计算标准误，导致 between-imputation variance 被丢掉。

## Evidence and root cause

仓库当前的 `run_mice_imputation(..., m=5)` 确实暴露了 `m` 参数，但它只：

- 创建一次 `statsmodels.imputation.mice.MICEData`；
- 执行 `max_iter` 次 `update_all()`；
- 写入一个 `processed/imputed_dataset.parquet`；
- 返回 `persisted_datasets=1`、`pooled_estimates=False`。

`ImputationStage` 随后只读取这一份文件并把它作为唯一的 `ctx.data`。现有
测试把这个状态锁成绿色，因此这是一个需要修正的真实统计错误，而不是单纯
的能力缺口。

同一轮核实确认：

- `iv_2sls` 模型族和 `backend/workbench/engine/iv_diagnostics.py` 已存在；
  新工作只保留 GMM/系统估计扩展。
- `backend/workbench/survey/**` 已有权重、strata、PSU、FPC、孤立 PSU 策略、
  Taylor linearization、BRR、jackknife、bootstrap 和 provided replicate
  weights；不重复建设复杂抽样设计内核。
- 现有自动统计证据已覆盖 Tukey、Bonferroni 及 `multipletests`；新工作只
  补 Scheffé、Games--Howell，并把多重性语义放进新的独立合同。

## Architecture

`replicate-and-combine` 不是把四种统计方法强行压成同一个公式，而是提供
两层可组合协议：

1. `ReplicatePlan` / `ReplicateBatch` 统一记录复制生成的边界、种类、seed、
   请求数、成功数、失败原因、顺序摘要和 digest；不返回原始复制行或完整
   复制数据。
2. 具名的 `Combiner` 策略分别实现 `rubin_pool`、`distribution_ci`、
   `permutation_null` 和 `replicate_covariance`。每个策略拥有自己的统计
   语义、自由度和失败边界，但复用同一套 provenance、预算、失败计数和
   JSON 安全约束。

运行时使用代码内的策略注册表和 typed adapter。未来 Agent 只能提交声明式
的 `replicate_kind`、`combiner_id`、统计量/模型族和预算；不能提交 Python
callback、公式字符串、import path、shell 命令或任意表达式。

## MI correction

### Generation

当 `m > 1` 时，MICE 使用显式 seed 派生出 `m` 个独立、可复现的完成数据集，
分别写入有序 artifact，例如 `imputed_dataset_0001` 到
`imputed_dataset_000m`，并写一个 manifest 绑定顺序、seed、输入摘要、列策略、
迭代次数和缺失诊断。不会再把第一份数据伪装成唯一建模数据。

`m == 1` 是明确的单次插补模式，结果必须标记为 `single_imputation`，不能
声称产生 pooled estimates。`m > 1` 但没有对应模型池化 adapter 时，流程
必须 fail closed；不能悄悄退回第一份完成数据。

### Rubin pooling

初始消费方先支持 ordinary OLS，因为它是当前 MICE 普通分析的默认路径。每
个插补数据集得到系数估计 `q_i` 和 complete-data variance `u_i=SE_i²`，然后
计算：

```text
Qbar = mean(q_i)
Ubar = mean(u_i)
B    = sample_variance(q_i)
T    = Ubar + (1 + 1/m) * B
SE   = sqrt(T)
```

结果还记录 relative increase in variance、fraction missing information、
有效自由度、置信区间方法和 `pooling_method`。p 值和区间使用显式的
Rubin small-sample t 语义；当 `Ubar`、`B` 或自由度不满足要求时稳定拒绝，
不以零或第一份结果替代。未来模型族通过同一 typed result adapter 加入，
不复制一套池化公式。

### Downstream safety

`EstimationStage` 只接受声明了 MI adapter 的模型族。每个 replicate 都在
独立的 `ModelingContext`/数据句柄上拟合，最终只写一个 pooled model result，
其 lineage inputs 列出全部 imputed artifacts。不能合并到 pooled 语义的诊断
会标记为 per-imputation 或 unavailable，绝不读取第一份 fitted object 后
冒充 pooled diagnostic。报告必须显示 `m`、池化方法、within/between/total
variance 和未支持的诊断范围。

## Missing-data diagnostics

同时新增独立的缺失诊断结果：每列缺失率、缺失行数、联合缺失 pattern 计数、
单调性摘要、可用样本量和被跳过列/原因。它是数据证据，不自动宣称 MCAR、
MAR 或 MNAR，也不自动改变插补策略。诊断和 MICE 输入共用同一份列/有限值
边界，避免“诊断看 A、插补跑 B”。

## Relationship to the four strategies

| 复制来源 | 统一层记录 | 独立合并语义 |
|---|---|---|
| Bootstrap | seed、draws、digest、失败边界 | percentile/basic/BCa 分布区间 |
| Permutation | scheme、alternative、exact/MC、draws | 零分布与 plus-one p 值 |
| MI | m、imputation seeds、model inputs | Rubin `Qbar/Ubar/B/T/df` |
| Survey replicate | replicate type、scales、failure summary | 设计方差/协方差 |

Survey 现有设计实现保持不变；后续只增加 adapter，使新 pack 能消费它。这样
PCA 加权、post-hoc 设计校正以及未来 bootstrap 都使用同一个复制执行/证据
协议，而不是再建第四套 replicate loop。

## Safety and acceptance

- 不新增依赖；运行时不调用 R、shell 或 LLM。
- 所有复制数、数据集数、输出行数、失败比例和 digest 输入均有硬上限。
- 任何生成失败、池化不适用、模型族未注册、非有限方差或自由度非法都
  产生稳定 reason code，并阻止可用结果发布。
- 先用回归红测证明现有 `m=2` 只落一份数据的错误，再实现修正。
- Oracle 使用独立 Rubin 公式/固定输入 R（若 `mice` 可用则作为额外 Oracle），
  并覆盖一个已知 intercept-SE 被 between-imputation variance 放大的 fixture。
- 绿色内核测试不代表 Agent 可达、浏览器验收、full gate、merge、push 或
  release 已完成。

