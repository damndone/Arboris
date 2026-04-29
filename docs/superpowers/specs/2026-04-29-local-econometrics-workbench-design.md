# 本地计量分析工作台设计

日期：2026-04-29

## 1. 背景与目标

目标是构建一个本地优先的数据分析工作台，让用户放入原始数据后，系统自动完成数据处理、数据分析、图表制作、报告撰写、产物归档和可追溯记录。第一版聚焦统计学与计量经济学场景，长期可扩展到量化金融、期权交易分析、波动率分析和云端协作。

第一版产品形态是本地网页应用。数据、清洗结果、模型结果、图表、报告、日志和备份都保存在用户本机项目目录中。系统架构预留任务队列和存储接口，但第一版不实现云端协作。

## 2. 第一版产品边界

第一版采用“本地计量分析工作台”方案。用户创建项目，上传单个或多个 CSV/Excel 文件，然后选择运行模式：

- 全自动模式：系统自动完成数据识别、合并建议与执行、变量角色推断、清洗、分析路径选择、模型运行、图表生成和报告导出。
- 逐步确认模式：系统在关键节点给出建议，用户确认或修改后继续，例如合并键、合并方式、因变量、自变量、时间字段、个体 ID、异常值处理、模型类型和报告格式。

全自动模式不是无条件继续。任何会影响数据含义、模型选择或结论可信度的高风险步骤，都必须允许暂停、确认、修改、回退或跳过。

第一版推荐数据规模边界：

- 单表文件不超过 2GB。
- 单表行数不超过 500 万行；使用 Parquet 中间格式时可支持更高行数，但仍受本机内存限制。
- 单个 Excel 文件不超过 20 个 sheet。
- 单次上传文件数不超过 20 个。
- 超出边界的数据集进入 WARNING 或 BLOCKER，系统给出降采样、格式转换或拆分建议。

第一版必须支持：

- 项目制目录。
- 全自动与逐步确认双模式。
- 基础计量模型。
- 主报告导出。
- 可追溯日志、产物索引和 run_manifest。
- 模板项目，包括单文件横截面、时间序列和面板数据案例。

第一版支持的方法边界：

- 支持：OLS、稳健标准误、基础固定效应、简单时间序列诊断、描述统计、相关分析。
- 暂不支持：IV / 2SLS、RDD、复杂因果推断、机器学习预测流水线、贝叶斯模型、高维稀疏模型。

第一版不做云端协作、不做复杂项目级 ETL 建模、不覆盖所有计量方法、不做多人审批、不提供平台化 API。重点是跑通“原始数据到可信报告”的闭环，并让每一步可检查、可回滚、可复现。

## 3. 主工作流

```text
创建项目
→ 导入数据
→ 数据画像与质量检查
→ 识别数据结构
→ 单表识别 / 多表合并建议
→ 用户确认关键决策
→ 清洗与版本保存
→ 生成分析计划
→ 运行模型与诊断
→ 图表表格输出
→ 报告生成（事实 / 解释 / 风险）
→ 导出
→ 保存日志、产物、可复现记录
```

在任意关键步骤，用户都可以确认、修改、回退或跳过。全自动模式遇到 BLOCKER 或高风险 WARNING 时也必须暂停或降级为用户确认。

## 4. 系统架构

第一版采用前后端分离的本地网页应用。后端负责数据处理和分析，前端负责上传、确认、查看报告和管理产物。

核心模块：

- Local Web UI：项目管理、上传数据、模式选择、确认建议、报告查看、导出管理。
- Workflow Orchestrator：管理任务步骤、状态、失败重试、时间戳、运行日志和产物索引。
- Project / Run Manager：管理项目配置、run_id、运行状态、lineage 和重新运行关系。
- Artifact Store：保存原始数据副本、清洗版本、合并结果、模型结果、图表、报告、日志、run_manifest 和产物索引。
- Schema / Metadata Registry：沉淀字段名、字段类型、语义角色、时间字段候选、ID 候选、主键候选、来源文件和转换历史，供清洗、合并、分析和报告复用。
- Data Ingestion：读取 CSV/Excel，记录原始文件哈希、字段类型、行列数、缺失情况。
- Data Profiler：生成数据画像，包括类型推断、缺失率、唯一性、分布、异常值、相关性、时间字段候选。
- Merge Advisor：多文件时推荐 join key 和 join type，依据字段名相似度、唯一性和重叠率。
- Cleaning Engine：执行类型转换、缺失值处理、重复值处理、异常值标记或处理、字段标准化。
- Analysis Router：识别数据结构，给出依据、置信度和备选路径。
- Validation & Guardrails：贯穿文件、schema、join key、样本量、缺失率、模型收敛、LLM 来源绑定和产物完整性检查。
- Econometrics Engine：执行第一版计量方法，内部包含 Model Spec Builder、Model Runner 和 Model Result Normalizer。
- Visualization Engine：生成描述统计图、相关性图、残差诊断图、时间趋势图和面板概览图。
- Report Engine：组织结构化结果，按事实层、解释层和警告层组装报告。
- Narrative Assistant：只基于结构化结果生成解释和润色，输出必须绑定 source_id，不能直接访问原始数据自由发挥。
- Export Engine：从统一报告模型导出 HTML、PDF、Excel 表格，以及后续可选的 Word、Notebook 和 LaTeX。

Econometrics Engine 的内部边界：

- Model Spec Builder：根据数据结构、用户确认和配置生成模型设定。
- Model Runner：执行 OLS、固定效应和诊断任务。
- Model Result Normalizer：把不同统计包的输出统一成结构化结果，供报告、测试和 LLM 使用。

建议技术栈：

- Python 后端，优先利用 pandas、polars 或 pyarrow、statsmodels、linearmodels、scipy、plotly、Jupyter/Quarto/LaTeX 生态。
- 轻量 React 或本地 Web UI 前端。
- 中间数据优先保存为 Parquet，报告导出时再生成 CSV/Excel 表格。

## 5. 输入与多文件合并

第一版支持两种输入：

- 单文件：系统自动猜测因变量、自变量、时间字段、个体 ID、分类变量和数值变量，用户可修改。
- 多文件：系统扫描每个文件的字段、行数、缺失率和主键候选项，再推荐合并方案。

多文件合并第一版支持：

- 用户确认 key 后执行 left、inner、outer join。
- 系统根据字段名相似度、唯一性和重叠率推荐 join key 与 join type。
- 合并前用户可确认或修改 join key、join type 和保留字段。
- 合并后保存合并数据版本、合并日志、未匹配记录摘要和 lineage。

复杂的主数据表、维度表、时间序列表和多层级项目建模不进入第一版。

## 6. 数据结构识别

系统采用两层识别。

一级结构识别：

1. 横截面
2. 时间序列
3. 面板数据
4. 重复横截面
5. 未知/混合结构

二级结构标签：

- 面板：平衡 / 非平衡
- 时间序列：规则频率 / 不规则频率
- 是否含事件时点
- 是否含层级结构
- 是否疑似交易流水 / 高频日志
- 是否可能是 pooled cross-section

识别依据包括时间列、ID 列、唯一性、同 ID 是否多期出现、时间是否连续、每期样本是否重复、ID-time 组合是否唯一、分组层级字段候选和事件时点字段候选。

未知/混合结构不强行建模。系统输出结构诊断、字段候选、风险提示和推荐用户确认路径。

## 7. 第一版分析能力

通用分析：

- 描述统计
- 缺失值摘要
- 异常值摘要
- 相关性分析
- 变量分布图

横截面：

- OLS
- 稳健标准误
- 异方差检验
- 多重共线性 VIF
- 残差诊断

时间序列：

- 时间趋势图
- 频率检测
- 平稳性检验
- 自相关 / 偏自相关
- 基础滞后模型

面板数据：

- 平衡 / 非平衡识别
- 面板结构摘要
- 固定效应基础模型
- 聚类稳健标准误
- 个体 / 时间效应诊断

重复横截面：

- 按期样本结构摘要
- 分期描述统计
- pooled OLS 候选
- 时间固定效应建议

第一版报告不自动宣称因果关系。除非用户明确提供研究设计信息，否则系统只写相关性、条件相关或模型估计结果。

## 8. 报告生成与导出

报告按三层组织：

- 事实层：统计结果、图表、模型输出、数据画像和诊断指标。
- 解释层：系统说明、模型解释、摘要和文字润色。
- 警告层：数据质量、识别不确定性、模型限制和不建议解释的结论。

用户可以选择输出格式。第一版核心里程碑优先支持：

- HTML 主报告。
- PDF 静态报告。
- Excel 导出表格。

Word、Notebook 和 LaTeX 使用同一套结构化报告模型作为后续 V1.x 增强，避免为每种格式单独实现报告逻辑。HTML 是主报告格式，因为它最适合展示可展开的清洗日志、模型诊断、图表和数据版本。

报告生成采用混合方式：

- 规则模板生成事实性结论，例如样本量、缺失率、模型系数、显著性和诊断警告。
- LLM 只基于结构化结果生成摘要、解释和润色。
- 每段正式结论必须绑定来源，例如模型结果、图表或数据质量指标。
- 数据质量存在高风险时，报告必须显示“不建议直接解释结论”的警告。

LLM 只能解释已存在的结构化结果，不能自行创造统计结论。正式报告中的每个解释性 claim 都必须绑定来源：

```json
{
  "claim": "变量 x1 与 y 在该模型中呈正相关。",
  "source_id": "model_results.regression_1.coefficients.x1",
  "confidence": 0.82
}
```

绑定失败的内容不能进入正式结论，只能进入“待核查说明”或被丢弃。

## 9. 项目目录与产物管理

每个项目是一个本地目录。所有操作写入该目录，保证检查、备份和复现。

```text
project-name/
  project.yaml
  config.yml
  data/
    raw/
  runs/
    {run_id}/
      run_manifest.json
      environment.json
      workflow_log.jsonl
      decisions.json
      errors.json
      artifacts_index.json
      raw_snapshot/
      staged/
      processed/
      model_results/
      figures/
      tables/
      reports/
        report.html
        report.pdf
      exports/
        tables.xlsx
  backups/
```

关键原则：

- 原始数据只复制保存，不直接修改。
- 每次运行生成新的 run_id，重新运行也不覆盖旧结果。
- 每次运行记录 lineage，说明输入文件、配置、上游运行和产物关系。
- `staged/` 和 `processed/` 归属于具体 run，避免不同运行互相覆盖。
- 可以提供 `latest` 指针方便 UI 访问，但真实版本源始终是 run 目录。
- 每个 run 生成 `artifacts_index.json`，记录产物路径、类型、生成步骤、hash 和上游依赖。
- 每个 run 生成 `environment.json`，记录 python_version、package_versions、app_version、os、config_hash 和 random_seed。
- 全自动模式也必须写入 decisions.json，说明系统为什么这么做。
- 逐步确认模式记录用户修改过哪些建议。
- 失败时保留已完成步骤的产物和日志，允许从失败步骤继续运行。

关键产物 lineage 示例：

```json
{
  "artifact_id": "cleaned_dataset",
  "inputs": ["raw_file_hash"],
  "step": "cleaning",
  "config_hash": "...",
  "code_version": "...",
  "output_hash": "..."
}
```

用户决策记录示例：

```json
{
  "suggestion": "Use firm_id and year as panel keys.",
  "confidence": 0.78,
  "evidence": ["firm_id repeats across years", "firm_id-year is unique"],
  "user_action": "modified",
  "final_decision": "Use gvkey and fiscal_year as panel keys."
}
```

## 10. 配置与阈值

所有影响判断的阈值都可配置，不写死在业务逻辑中。项目级 `config.yml` 可覆盖全局默认值。

示例：

```yaml
max_single_file_gb: 2
max_rows: 5000000
max_excel_sheets: 20
max_upload_files: 20
min_join_overlap: 0.7
max_missing_rate: 0.4
min_model_n: 30
max_panel_missing_cells: 0.5
min_variable_role_confidence: 0.65
```

阈值用于决定步骤是继续、警告、请求确认还是停止。

## 11. 错误分级

错误与风险分为三级：

- BLOCKER：必须停止或请求用户确认。
- WARNING：可继续，但报告和 run_manifest 中显著标记。
- INFO：记录即可。

示例：

- BLOCKER：文件无法读取、无表头、重复列无法消解、ID-time 不唯一且用户未选择处理方式、模型无法估计、LLM 结论无法绑定来源。
- WARNING：缺失率偏高、非平衡面板、时间不连续、join key 重叠率接近阈值、变量角色置信度不足但仍可人工确认。
- INFO：字段名标准化、类型自动转换、导出格式生成成功、清洗动作已执行。

总原则：

> 系统可以自动化执行低风险步骤，但任何会影响数据含义、模型选择或结论可信度的步骤，都必须可暂停、可解释、可回退、可追溯。

## 12. 用户控制

全自动模式遇到高风险步骤时仍允许暂停并请求确认。逐步确认模式中，用户可以接受建议、修改建议、跳过步骤或回退到上一步。

所有自动建议都带有置信度、依据和替代方案。所有用户决策写入 `decisions.json`。报告中清楚标记哪些结论是模型结果，哪些是系统解释，哪些是质量警告。

## 13. 测试策略

单元测试：

- 字段识别
- 数据类型推断
- 合并推荐
- 清洗规则
- 结构识别
- 报告模板
- 错误分级规则

集成测试：

- 单文件横截面
- 时间序列
- 平衡面板
- 非平衡面板
- 重复横截面
- 多文件合并

失败测试：

- 坏编码
- 缺失表头
- 重复列
- 无 join key
- 模型失败
- LLM 不可用

可追溯性测试：

- 每个报告结论都能回溯到 run_manifest、metrics、model result 或 figure。
- 每个自动清洗动作都有记录。
- 每个用户确认都写入 `decisions.json`。
- 同一输入、同一配置、同一系统版本下能复现关键输出。
- BLOCKER、WARNING、INFO 分级符合配置阈值。
- LLM 不可用时，系统仍能生成规则模板报告。
- `artifacts_index.json` 覆盖每个正式产物。
- `environment.json` 能复现运行环境、配置 hash 和随机种子。
- Metadata Registry 中的字段角色和转换历史与清洗、合并、报告产物一致。

人工验收：

- 使用 3 到 5 个真实或模拟研究数据集检查报告是否可信。
- 检查报告是否避免过度因果解释。
- 检查自动模式和逐步确认模式是否都能完成端到端流程。
- 检查三个模板项目能让新用户直接跑通单文件横截面、时间序列和面板案例。

## 14. 后续扩展方向

后续版本可以扩展：

- 事件研究型数据
- 生存 / 持续时间数据
- 多层级 / 分层模型
- 纯交易流水 / 高频日志数据
- 复杂 pooled cross-section
- 项目式数据建模与 ETL 编排
- 量化金融研究与回测
- 期权、隐含波动率、波动率曲面和 Greeks
- 云端任务队列、团队协作和权限管理
