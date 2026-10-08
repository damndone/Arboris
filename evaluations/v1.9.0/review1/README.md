# v1.9.0 用户评审 1 之后的修改（2026-10-08）

用户反馈：Home 仍是旧的 Notebook/Graph/Data/Table/Report 与旧顶栏；中间面板打开后无法收起并遮挡左侧；整体离合格差距大。

| 问题 | 修改 | 证据 |
|---|---|---|
| Home、启动页风格不一致 | 项目首页、无运行的项目（新的起始页，先给 Import data）、启动页（Projects）都用工作台顶栏；外层旧导航在新外壳下不再出现 | `project-home.jpg`、`launcher.jpg` |
| 舞台收不起、遮挡地图 | 舞台只在打开了步骤时出现；标签栏右侧一键收起，地图恢复整幅并自动适配，右上角 Show details 找回；选另一个步骤自动展开 | `stage-folded-full-map.jpg` |
| 280px 地图列里是被截断的整图 | 改为卡片树：Data 一组（链不缩进、分叉缩进），Analyses 一组（模型及其报告、诊断） | `result-view-results-first.jpg` |
| Data / Tables / Report / Plans 左边挂着截断的图 | 这些视图默认不显示地图列，左上角按钮可打开卡片树 | — |
| 舞台里没有结果本身 | 新的结果视图：状态与待确认选择、关键估计值与区间、区间图、系数表、拟合统计、检查；推断口径一行；本页目录可跳到各段；内部 ID、重复的复核横幅、Ask AI（已并入 Agent 列）、Agent analysis loop 不再显示 | `result-view-results-first.jpg`、`result-view-lineage-dark.jpg` |
| 满屏饱和蓝按钮 | 普通按钮改为中性描边，主要操作用 `data-variant="primary"` | — |
| Agent 列像终端 | 改为对话：无等宽字体、用户消息气泡、工具步骤为灰色状态行、焦点标签、卡片式输入框 | `result-view-results-first.jpg` |

对比度审计：结果视图在两种布局 × 两种主题下 0 处不达标。前端 223 个文件 / 1845 个测试通过，`tsc` 无错误。
