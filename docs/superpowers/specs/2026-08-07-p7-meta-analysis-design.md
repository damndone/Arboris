# P7 Meta-analysis 设计

## 目标

提供以 study-level effect + variance 为核心的可组合 meta-analysis pack，支持固定效应、
随机效应和异质性证据，不把不同效应量尺度静默混合。

## 输入边界

- 至少两个 study；每个 study 必须有有限 effect、严格正 variance 和稳定 study_id。
- `effect_measure` 必须显式声明；直接 `yi/vi` 只允许同一尺度。
- random-effects 方法显式选择 `derSimonian_laird` 或 `paule_mandel`；是否使用 t/HKSJ
  区间显式声明。
- alpha、prediction interval 和 leave-one-out policy 显式声明；study 数量、输出行数和
  precision 都有边界。
- effect-size conversion 只接受受支持且完整的原始摘要字段；缺字段或尺度不清直接拒绝。

## 计算与输出

- 固定/随机合并效应、SE、CI、权重、Q/df/p、tau²、I²、H²、prediction interval。
- 输出每个 study 的 contribution 和可选 leave-one-out，保留方法与尺度 provenance。
- effect conversion 与 combine 是分开的纯函数，便于未来 Agent 自然语言组合而不把
  “选效应量”与“选模型”混在一起。
- 不输出原始 study 内容，不自动删异常 study，不自动选择 fixed/random winner。

## Oracle 与安全

- 运行时用透明公式实现；测试对照 `statsmodels.stats.meta_analysis.combine_effects`。
- R base 用固定效应、DL tau²、Q/I² 的独立公式复算；不依赖未安装的 metafor/meta。
- zero/negative variance、NaN、尺度混合、k<2 均 fail closed。

## 非目标

不接文献抓取、publication-bias 自动结论、网络 meta-analysis、个体数据模型、Agent 或
frontend。
