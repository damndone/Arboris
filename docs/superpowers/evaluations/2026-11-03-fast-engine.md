# 可选快速引擎：第一片 IV 2SLS（2026-11-03）

2026-11-04审查修订：下文保留首片实施和原测量记录。可选IV已有API/CLI及手动界面/Agent共同合同入口，仍标实验、资源验收待完成；OLS/面板仍是有限原型，“完整引擎”不是已验收结论。原性能脚本的数值/重复性漏判和构建身份检查已修复；RSS噪声仍超标，整组验收未过。当前证据在本页末追加，不追认旧失败。

用户 11 月 3 日选了“可选的快速引擎”：默认路径保持逐位一致，用户主动选 `estimation_engine=fast` 时改用原生引擎（`native/engine`，Rust），并且这个引擎事先对参考库和 R 验证过。

提交：`01f0af41`（引擎与验证）、`c34caa49`（提交时校验）、`9d597574`（测量脚本）、`4d7e4ea0`（IV 缺失值修复）、`943857f7`（统一构建）。

## 先测了哪里值得做

100 万行，一次完整运行（含诊断、检查、报告）的剖析：

| 模型族 | 整次运行 | 第三方估计库占用 | 判断 |
|---|---:|---:|---|
| OLS | 6.1 秒 | statsmodels 拟合约 0.5 秒 | 拟合本身只占一成不到，快速引擎收益小；大头是结果合同（1.1 秒，native-io 会话在做）和 Kruskal 等检验（1.6 秒，native-stats 会话在做） |
| IV 2SLS | 9.8 秒 | linearmodels 诊断 4.6 秒 + 拟合 1.0 秒 | **最值得做**：诊断里 7 次重建 `IVData`，把行标签转成 Python 列表并深拷贝，与数学无关 |
| 面板固定效应 | 3.9 秒 | linearmodels 拟合 1.0 秒 | 次之，最多省约四分之一 |

所以第一片做 IV：估计加上产品读取的全部诊断。

## 做了什么

- `native/engine` 增加库形式和 C ABI（`src/lib.rs`），Python 在进程内直接传入 NumPy 数组，不再写 CSV。
- `src/iv.rs`：2SLS（稳健 HC0 或同方差，与 linearmodels `debiased=False` 定义相同）、每个内生变量的第一阶段 Wald、Wooldridge 回归检验和过度识别检验、Sargan、Wu-Hausman。
- `backend/workbench/estimation_engine/`：选择契约（`reference` 默认、`fast` 可选）、加载器（未构建就不可用；ABI 不符报错）、结果适配器。适配器只提供产品实际读取的属性。这份清单是用代理逐个记录一次完整 IV 运行读取的属性得到的，缺了任何一个都会在端到端对比测试里报错，不会悄悄读到猜测的值。
- 选择沿运行请求传递：API、命令行、重跑、批量运行都走同一个字段。**默认运行的输入文件和结果逐字节不变**：不选或选 `reference` 时什么都不写。
- 快速引擎不覆盖的情况一律退回参考库，结果里写明原因：其他协方差、非数值列、需要公式转义的列名、秩不足（用与 linearmodels 相同的 `numpy.matrix_rank` 判断）、引擎未构建。已存在的构建损坏、自检不通过或计算错误明确报错，不作为正常不支持的回退。
- 结果里记录 `engine: arboris-engine` 和 `engine_selection`：请求了什么、实际用了什么、与参考库的一致性标准、构建的哈希；明确写着“不与参考库逐位相同”。

## 数值验证

| 对照 | 结果 |
|---|---|
| R fixest 0.14.1（`tests/fixtures/fast_engine_iv`，三种设计 × 两种协方差） | 系数、标准误、第一阶段 F、Sargan 相对差 < 1e-10。fixest 的 `iid` 方差除以 n − 1，产品除以 n，fixture 里两者都记录并写明换算 |
| linearmodels（3 种规模 × 3 种设计 × 2 种协方差 × 3 种数据形态，54 组） | 最大相对差：普通数据 5.8e-13，厚尾 7.3e-12，病态（列放大 1e6）1.4e-10 |
| 60 位十进制高精度对照（`scripts/oracles/iv_high_precision.py`） | 原脚本在列出的有限输入/字段上观测快速引擎更接近高精度值；这是有限精度对照，不是精确认证，也未独立覆盖所有协方差、标准误和尾部概率。原始差异保留，不能外推到所有输入。 |
| 一次完整 IV 运行的全部 JSON 产物 | 除引擎记录、时间戳和随数字变化的哈希外完全一致，数值最大相对差 1.8e-13 |

一致性标准：相对 1e-9，接近零时绝对 1e-12；两个 n·R² 型统计量（过度识别、Sargan）另加每行 1e-15 的绝对容差，因为参考库自身的误差随 n 增长。

## 性能（原测量，整组验收未通过）

`scripts/perf_fast_engine.py`，登记的 100 万行 IV 输入（`local/perf-inputs/iv`，SHA-256 校验），每次新进程，5 次参考库校准 + 5 对交替，每次运行逐文件记账后删除。原始记录：`local/perf-evidence/fast-engine-iv-20261103/`。

| | 参考库（中位数） | 快速引擎（中位数） | |
|---|---:|---:|---|
| 整次运行时间 | 7.84 秒 | 2.11 秒 | **快 3.71 倍**；校准噪声 3.8%，通过 5% 规则 |
| 峰值内存 | 3.74 GB | 1.31 GB | 降 65%；但参考库校准的内存噪声 7.8%，**超过 5% 规则，只作参考，不算验收** |
| 运行目录 | 139,168,551 字节 | 139,169,217 字节 | 只多出引擎记录 |

快速引擎 5 次运行结果逐位相同；与参考库的系数、标准误最大相对差 2.6e-13。

## 顺带发现并修复的问题

1. **IV 遇到缺失值整次失败**（`4d7e4ea0`）：linearmodels 的公式接口遇到结果变量、内生变量或工具变量缺失时直接报错（外生变量缺失却会删行），产品之前没有自己删行，所以任何这类数据上的 IV 都停在估计。现在按 Stata `ivregress` 和 R `ivreg` 的做法逐行删除，并给出警告写明列名和行数；没有这类缺失的运行仍走原公式路径，逐位不变。导出的 Python 脚本也先删行（R 和 Stata 原本就会删）。
2. **Wu-Hausman 实现/定义差异待核验**：原对照观测到linearmodels与fixest/控制函数结果不同。必须先对齐样本、常数项、被排除及全部工具、自由度、具体统计量与假设，再判断差异原因；不定性第三方“非标准”。两个引擎当前保持原linearmodels定义，默认数字不改。官方方法入口：[linearmodels](https://bashtage.github.io/linearmodels/iv/iv/linearmodels.iv.results.IVResults.wu_hausman.html)、[Stata](https://www.stata.com/manuals/rivregresspostestimation.pdf)。
3. **没有统一的原生构建步骤**（`943857f7`）：`scripts/build_native.py` 构建全部原生模块，`--check` 报告缺失或源码已变的构建。

## 没做 / 待定

- 原界面/Agent入口缺项已在11月4日获批单文件例外后实现，具体离线/浏览器证据见末节；未做真实Agent调用，不能由手动通过推导真实Agent会正确选择。
- 面板固定效应、OLS 的快速路径还没做（见上面的收益估计）。
- 内存结论还没通过噪声规则，要在机器更空闲时重测。

## devline 事件

原STATE_CHANGE措辞曾将高精度写成精确、将Wu-Hausman差异定性为非标准，现由审查更正；原正式事件保留，追加纠正事件而不改历史。第一片实现不等于完整正确性/资源验收完成。

## 2026-11-04 审查修复与独立验证

验收脚本现在对完整协方差/SE/统计量/p/df/NA、两引擎各次重复位模式、时间/RSS/盘及各lane噪声、固定输入/源码/binary身份、全worker宿主占用和所需图表真实交付分别判定，失败均非零。未请求图表的worker明确not_requested；正式fast比较两lane都请求全部计划图表，分别记录analysis_ready与requested_delivery。仅采样可证明的宿主占用窗口，不把它冒充内核进程生命周期审计；读取ps失败亦不视为空闲。异常日志在记账清理运行目录前单独保留。

8个模块采用schema2构建身份：完整源清单、编译命令/配置/编译器、平台ABI及实际产物SHA绑定；旧未知产物不追认。原逐8模块及汇总--check命令成功，但随后发现汇总遗漏AR moments变体，因此那次命令不能证明全部生产变体验证。末节记录修复后的9变体检查。加载前核身份，坏构建、自检、计算异常及有定义输出中的非有限值显式报错；功能不支持或缺可选库才有具名reference分流。

独立性质测试发现并修复3个真实数值问题：近共线工具基的一阶段Wald、近共线内生变量的联合内生性Wald、HC0主协方差。改在QR正交坐标形成相同统计量与协方差，再变回原坐标，默认reference未改。联合原IV和独立集162passed（6个原缺失值警告）；高精度矩条件按80/110位交叉核稳定，R4.6.0/fixest0.14.1等生成的原始fixture与环境/命令留在tests/fixtures/fast_engine_iv_independent。Stata未执行，仅核官方定义。

比较中SE不加绝对底值，cov额外按对角尺度归一化，正概率尾部同时限制相对/log差，n/df/valid精确；原1e-9/1e-12及NR²每行1e-15规则未扩大。linearmodels部分1-cdf将很小概率消成0，对照只按其已命名统计量用sf重评尾部，不修改其产品输出、不冒充独立oracle；另有R稳定尾部对照。

扩展字段后6组缩放输入共15个参考差异仍保留reference_agreement=false（reference_gaps.json）。逐项独立HP/R中fast最大相对误差约6.03e-14，reference约1.03e-9至5.82e-9；不把参考兼容失败改写为通过，性能门仍拒绝超过其固定门槛的差异。这是有限fixture正确性证据，不是所有输入的误差上界。吴检验同时保存excluded-only参考定义和R控制函数F定义，未改变默认统计量。

本批标准组集中一次2790passed/0failed/3skipped，36warnings，166.45秒，local/native-review-standard-20261104.log。新perf门首组65pass及独立审查后11个受影响节点通过；root默认优化门9pass。完整tests/full gate、实模、浏览器、取消与资源验收未由这些数字替代。下一步在源码冻结后独占A/B，原7.84/2.11和受干扰的5.299秒均不追认完整验收。


## a133fbdf：修复后独占A/B，数值/时间通过，RSS噪声仍FAIL

同一登记百万行IV输入（SHA4f18e7f8...），原CSV不复制；源manifest旧device与当前挂载不同，先核内容SHA，保留canonical原件，仅本批派生记录当前file identity。5参考校准+5交替对，所有source/build pins与全窗口host检查通过，两引擎各自重复位模式一致，数值分项差异为空。两个lane均实际完成相同7张计划图表，图表文件/注册SHA核齐；额外报告导出未请求。

|对|参考分析s|快速分析s|参考完整图表s|快速完整图表s|参考RSS bytes|快速RSS bytes|
|---:|---:|---:|---:|---:|---:|---:|
|1|7.999259875|2.122330250|9.168502125|3.264583625|2979823616|1258799104|
|2|7.951794834|2.236751250|9.120859625|3.390401958|3459088384|1240449024|
|3|7.951929250|2.141262291|9.135007750|3.310326791|3184476160|1294090240|
|4|7.911017583|2.143846125|9.088950583|3.288077792|3750215680|1239957504|
|5|7.950198334|2.305840375|9.128309917|3.473693250|3362439168|1293320192|

中位数：分析7.951795→2.143846s（3.709×）；所需图表全就绪9.128310→3.310327s（2.758×）。分析RSS观测3362439168→1258799104B，完整交付RSS3362439168→1309032448B；分析盘139168551→139173670B，完整交付盘139284287→139289406B。
参考配对RSS噪声8.627%、全部参考6.533%超5%；校准3.152%、快速2.145%，时间噪声各lane均低于5%。故CLI exit1、passed=false，失败明确保留reference_pairs/all_reference memory noise。时间收益成立于本次输入/交付范围，整组资源认证未通过，不把大幅内存下降观测当已认证，也不自动第三轮全A/B。原始report/journal/host samples、每文件SHA与代表归档均在local/perf-evidence/fast-engine-iv-review-20261104/。

随后仅一次默认reference阶段/GC/tracemalloc诊断：分析35.857s为instrumented时间，不作性能结果；traced peak2,827,334,893B、RSS4,397,039,616B。峰值位于diagnostics：tracked live约750.5MiB→peak2696.4MiB→返回758.4MiB，说明有大临时分配；不能据一次trace确认跨进程RSS波动由GC还是OS驻留引起。未强制GC、改allocator或worker环境来制造门通过；trace不覆盖全部native heaps，不能替代RSS。53文件/237,021,346B已SHA记账、校验归档后仅移除本次active，记录local/iv-rss-attribution-20261104/。

## 同批后续：生产变体、取消、共同入口和实际回执

**构建覆盖修正。** root发现`ar_exact`汇总只核row-exact、漏了生产`moments`变体；旧8行成功记录不追认。`native_build.variants`现在由构建和检查共同读取，汇总8组件/9变体，缺任一manifest或身份不符即失败。7个缺口红测转绿、相关76pass；重新构建后9项检查全过，10个二进制（含engine CLI）重建前后SHA完全相同。源码/清单记录见`local/native-variant-audit-20261104T190705838275Z/`。构建身份随builder源码变化，旧结果中的旧身份是当时的事实，不改旧回执。

**真实拥有者取消。** fast IV进入原`run_interruptible`路径，Rust仅协调线程访问Python检查点、并行线程读取消旗标，作用域线程join后再返回原异常；无拥有者的直接调用保持原路径。ABI1原入口保留，新增取消入口/独立状态5，不把取消当数值失败或reference分流。4096块检查点不改变块内累加顺序；旧a133二进制对8193/65537行、两协方差、两线程的4组输出逐位相同。相关161pass及Rust join测试1pass；独立数学受影响集82pass。NumPy单次调用、冷加载/自检和已开始的同步持久化不承诺可随时抢占。

百万行公开工作流取消5个独立worker，估计阶段开始后50ms发起停止，实际返回延迟为`0.088983125, 0.002740541, 0.002201458, 0.002472750, 0.002090375`秒，5/5通过2秒门；无残留拥有者线程、无模型/核产物发布或返回后文件变化。计时从公开阶段hook开始，不能证明每次已在Rust内层循环；小型真实FFI测试另证其取消。记录`local/perf-evidence/fast-iv-cancel-20261104/report.json`，驱动6项检查通过；不外推所有输入/阶段的取消门。

**共同手动/Agent入口。** 获批的Genesis单文件例外只新增`estimation_engine`描述、string和reference/fast枚举；共享核心校验用于草稿、谱系、Agent工作流和手动表单，保存/恢复/显式切回reference一致。分支不能偷偷覆盖引擎，fast非IV及不支持的Genesis设定在提交前明确拒绝并给修正建议；正常reference字段省略，默认合同不变。Agent提案明确实验状态和资源门开放；未经真实Agent评测不声称自主选择正确。准入/提案相关55pass、后续边界/错误呈现delta通过；Genesis/IV表单29pass。

**实际引擎来源。** 模型、表格和旧结果页共用紧凑notice；公共结果与Agent只投影该模型持久化的requested/used/reason/bit标准/build identity，不根据当前库或另一个模型猜测。旧无记录结果不补造。后端20pass、前端相关44pass及notice最终4pass；实际notice高37.109px、宽615/scroll615，无横向溢出。这里SHA是build identity，不错误称为单个binary SHA。

**真实浏览器重跑。** 96行、双内生/三工具原始fixture通过手动fast创建、保存重开、切回reference和不支持设定拒绝；`20261104_185225_834148_bbbd02c9`实际用了Rust。浏览器另发现IV旧JSON列角色未回填，已合并HTTP到原服务helper，37红绿角色案例及相关94pass；d1/d2和z1/z2/z3实际勾选恢复。手动异步提交不再写completed，沿原单一pending watcher，仅completed且已索引才聚焦；失败/未知回执留原编辑区和child链接，91项前端测试通过；独立审查再修迟到POST和manual/draft观察所有权覆盖，新增8红转绿、受影响21pass（58未选），最终tsc exit0。两个原错误容器保留长原文并允许换行，独立差异复查无具体阻断。真实`hac`重跑暴露旧库别名错误，失败`20261104_192302_461014_4c1592ab`原样保留并在界面显示`WORKFLOW_FAILED: 'hac'`；该时点尚待核心保护例外；后续获批闭环见末节。另一次unadjusted重跑`20261104_194644_943079_9320aadf`成功后才聚焦，实际引擎为arboris-engine。截图及受控产物在`local/fast-engine-ui-admission-review-20261104/`，未调用LLM。

**新增独立Stata历史实值对照。** 用原650行CSV与原Stata18 do/log/TSV，核SHA、样本/常数/工具/HC0及非small定义后，当前fast系数、完整4×4协方差、SE/z/p/联合Wald按既定规则4项通过。不是本机新执行Stata，也不扩展为HAC等验证。原JSON sidecar SHA与历史manifest不符，原归档也不符，原因未知；该sidecar标`integrity_failed_unused`，未修清单/旧证据。详见`local/fast-engine-stata-archive-review-20261104/review.json`及正式GAP。

**RSS诊断仍不等于验收。** 一次正常reference运行仅新增外部/线程20ms OS记账采样，不改allocator/GC/产品。RSS 3,338,600,448B、physical footprint生命周期峰3,348,204,904B；worker压缩峰391,528,448B。parent371/worker199样本，无API错误；不同指标并非可相加关系，压缩存在也不足以解释跨运行RSS噪声。保留原5% RSS FAIL，不换指标放行。57文件记账归档，仅清本次active；记录`local/reference-memory-diagnostic-20261104/observed/`，标not_acceptance。

本批标准组第二次集中检查为2790pass/0fail/3skip、36warnings、159.99秒（`local/native-entry-standard-20261104.log`），其后只跑上述变更的针对性delta；不能将其改写成“最新整版full tests全绿”。最终前端tsc exit0，记录`local/native-manual-owner-tsc-20261104.log`。无实模/留出集/M5/full gate/发版。

## 2026-11-04（America/New_York）：获批HAC别名修复闭环

用户精确批准`panel_iv.py` IV入口一行`hac → kernel`；实际受保护差异只这一行，与先前候选patch完全相同，after SHA `3665141a9d7dd3c96b43085c14017f3d80700b4090ed0c43ee6d6eef0f60e644`。它选择既有linearmodels kernel协方差，带宽/核/有限样本设置不改，不新增Rust/HAC算法或适用性认证。4项真实回归先红后绿；连同原默认/不覆盖路径7pass。以保存的SHA固定旧源码对真实新源码，400/650行两份原始fixture的完整coef/cov/SE/t/p/CI/第一阶段/检验与样本、残差向量等12项逐位比较全部通过，默认、robust、unadjusted不变。证据`local/fast-engine-hac-alias-review-20261104/actual_evidence.json`。

真实96行HAC重跑`20261105_014826_731949_9ae90c0e`完成，原请求仍记录hac、实际kernel记录kernel；fast请求沿原具名reference分流，界面显示实际reference及原因。旧失败`20261104_192302_461014_4c1592ab`保留，errors.json SHA仍`0541d0ebc31395cd0e993042e06d6122f65478609e9c184cccf9bf7e30d78a99`。这不是LLM/付费模型回退，没有Provider调用。

界面验收另发现导出builder把IV的这两个同义名误报为实际核不一致。通过正式CLI只扩充非保护`script_export/builder.py`路径，保护/allow列表不变；仅为IV接受kernel名称并转为脚本词汇hac，真正robust/kernel不一致、其他family和所有owner/source/kernel约束继续拒绝。2单元+1真实工作流红测复现后修正；受影响的HAC/准入/渲染50pass，执行来源/固有协方差/谱系导出回归63pass，独立差异复查无阻断。没有改三语言exporter能力：IV/HAC原生再估计仍未验证，`require_native=True`在Python/R/Stata均NOT_FULLY_NATIVE；浏览器实际Stata导出也明确拒绝，没有下载或以保存结果冒充原生复现。

提交前集中标准2790pass/0fail/3skip、36warnings、163.11秒（`standard.log`）。原保护边界以外没有其他数值核变更，无前端改动/tsc重复、性能A-B重跑、实模/留出/M5/full gate；原性能噪声FAIL不追认。浏览器/源/旧失败及模型SHA记录`actual-ui-evidence.json`，截图`hac-fixed-result.png`、`hac-native-export-refused.png`；均位于上述local证据目录。

## 后续：Wu定义缺陷修正及现代结果页闭环

先前§“实现/定义差异待核验”现已收敛：安装的linearmodels7.0及原Rust第二投影只用排除工具Q，标准Wu T₂使用全部Z=[含常数的外生变量,Q]。8行整数反例只把Q一列加1，旧F由5/4变10/3，标准/R及精确有理数仍为5/4；同工具空间不应改变检验。已读Stata官方公式及Hausman1978，未获得Wu原文全文；旧Stata18日志无estat endogenous，不能声称新Stata数值认证。来源、代码版本、原始R与Fraction链在`local/iv-definition-review-20261104/findings.json`。

用户明确批准仅新同方差IV的Wu stat/p及其派生判断/hash例外于默认逐位一致。Rust改full-Z，默认采用Arboris自有QR控制函数F，两条路径的比较与selfcheck共用定义；正常fast始终读取真实ABI槽，不以Python重算遮错。正式构建identity `1496e12b570737d8bee3bf0408b28ee350b1b7eac94c3159bd8c3d4395cf91e3`；8模块/9变体再次核验均current。12组真实旧/新ABI除Wu外逐位相同，robust整向量逐位相同，旧fixture、tape和容差原样。

支持无权重、同方差、全内生联合检验；缺增广自由度、缺独立控制方向或零残差方差具名unavailable。fast在调用ABI前按这一科学域明确转reference并记录原因，保留其可估点结果；坏ABI/非有限域内输出/意外错误硬错，不能归类为不支持。publisher写null stat/p与具体原因，完成门不接受为已核验诊断。新增unadjusted QR/rank开销和中途取消成本尚未大样本测量，旧robust A/B不能认证这个分支。

35核心/R/旧合同、37独立精度测试通过，最后checkpoint差异29项通过；后端集中标准2815pass/0fail/3skip、36warnings（168.06s）。相关前端最终29pass：旧卡与现代ModelResultView均覆盖，坏weak/AR字段在HTTP边界显式拒绝并保留主结果；最终tsc exit0。精确日志与复跑命令在上述目录及`local/test-evidence/native-review-batch-20261104/`。不把这些相互重叠的调用相加成一次全量验收。

真实现代Graph页原来没有结构化IV卡，现读取所选run/model的已注册`${modelId}.completion`，核v2合同/模型身份，缺失、错绑、坏内容和HTTP失败均明确显示；不把run级诊断盲绑兄弟模型。64行正常流程`20261105_041340_302634_2218c9bf`实际Rust、Wu F=30已显示；不足增广df的`20261105_041554_083025_6f0700dc`整条workflow完成，明确reference来源、保留系数、显示Wu不可用且无假p值。默认AR未请求现明确提示Not requested及下一步，不再暗示曾尝试全局反演。截图`wu-modern-defined.png`和`wu-modern-unavailable.png`。另一完美结构拟合`20261105_041340_835506_916ccd7b`在旧point producer联合统计量已报Singular matrix，原失败保留，未冒认为Wu不可用的成功流程。

没有真实Provider、评委、留出/M5、全量tests或full gate；参考RSS/噪声及新分支资源门仍开放。后续先剖析新unadjusted重复QR，若成本确实显著再做有版本的Rust诊断状态/计算复用，不先承诺提速。

## 2026-11-05 逐进程验收证据

验收现在将实际 iv_2sls_1.json 的 engine_selection.build 和独立验证的当前磁盘身份比对。补充拒绝重复观测标签、输入配置变动和原始宿主记录与摘要不一致。原生加载串行，加载后的完整性失败在重启前拒绝重试。

新定向 IV、验收、血缘与 API 测试 264 通过。9 个生产变体均 current。历史 15 份宿主原始记录复核有效，采样覆盖已知重任务进程。旧参考 RSS 噪声 8.627% 与 6.533% 仍 FAIL。新一轮空间预检 2.313 GB，小于 5 GB，启动 0 个 worker。输入、原日志与旧失败保留。

下一次独占窗口使用登记的 IV 输入和新输出目录，五次参考校准和五组交替对照。预检与定向结果见 local/native-followup-20261105/。

### 输入清单复核

复用既有百万行 IV 输入时，CSV 的 97,727,006 字节与登记 SHA-256 均通过，文件大小、inode 和修改时间一致，设备号由 16777232 变为 16777229。旧驱动原样复制清单会被 worker 拒绝。现仅在重新验证内容和其余文件身份后生成本轮专用清单，报告保留两份清单的 SHA-256，原清单原样保留。真实输入已通过 worker 身份校验，记录见 local/native-followup-20261105/iv-input-readiness-continuation.json。

IV 验收、OLS 归档和样本编码的定向测试 124 项通过。最新空闲空间 1.232 GB，低于 5 GB 门槛，未启动计时 worker。历史 RSS 噪声失败继续保留。

### 恢复宿主窗口后的中止记录

预检空闲 8.000 GB，首个百万行参考 worker 启动时 6.945 GB。该 worker 正常完成分析及 7 张图，随后第二个 worker 的磁盘检查读到 4.620 GB，小于 5 GB，整轮中止。原报告、58 条宿主采样、55 文件的日志与逐项 SHA、84.80 MiB 代表归档都保留。原采样把本次只读进度查询标记为重叠，首个样本不可用于正式比较。事后读取到 3 GiB 交换空间已分配，其中约 2.36 GiB 在用，缺少起跑时的交换空间快照，无法量化它对磁盘下降的贡献。没有形成 A/B 对，也未改判旧轮。记录见 local/native-followup-20261105/iv-formal-round-review.json。

验收脚本现在先保存和保留观测，再在宿主独占无法核实时立即退出。校准与 A/B 使用同一核验条件，原始进程记录仍用于判定。定向 71 项通过。

### 独占重试的部分观测

以干净提交 a59af275 开跑，固定输入 SHA、清单、源码与构建回执均核齐。预检 14.006 GB。五次参考校准和一组交替对照共 7 个 worker，均有原始宿主采样且无重叠。完成相同 7 张计划图。第二组尚无 worker 开始，报告中的空槽不计作一组。磁盘检查在 4.096 GB 处停止。原始报告、每次宿主记录、逐文件 journal 和两份校验代表归档均在 local/perf-evidence/fast-engine-iv-exclusive-20261105/，无 active 遗留。

| 单组观测 | 参考 | 快速 |
|---|---:|---:|
| 分析就绪（秒） | 10.723 | 2.443 |
| 7 图全部就绪（秒） | 12.119 | 3.796 |
| 分析峰值 RSS（字节） | 3,286,581,248 | 1,238,417,408 |
| 分析目录（字节） | 139,168,551 | 139,173,670 |

事后用正式比较函数复核保存的观测，所测数值未见超差。快速端仅一条，无法检验重复性和噪声。参考五次校准时间噪声 3.609%，RSS 噪声 5.139%，超过 5% 门槛。已实测交换空间分配 3,072→6,656 MiB，保留产物约 174 MiB，尚未归因其余磁盘变动。无完整 5 对，exit 1，正式验收仍未通过。补充复核为 local/native-followup-20261105/iv-exclusive-partial-review.json，原报告未改。两次因同一空间门中止后，暂停重复计时，等待稳定磁盘与交换空间窗口。

### 空间恢复后完整重测与缓冲区修复

提交 a59af275 在磁盘预检 75.930 GB 下完成五校准加五对。15 次宿主采样、固定输入、源码与逐次实际构建回执通过，两个引擎各自逐位重复，比较无数值超差；同样交付 7 张图。分析中位 7.869→2.079 s，完整交付 9.131→3.330 s，分析 RSS 3.918→1.328 GB。参考校准 RSS 噪声 3.048%，快速分析 RSS 噪声 5.539%，整组因后者 exit 1。原始证据见 local/perf-evidence/fast-engine-iv-restored-host-20261105/。未定位每次 RSS 波动的完整因果。

候选的完整样本以独立列连续缓冲交给 Rust，省去逐列重复制，缺失样本保持原有逐行删除。Rust QR 直接取得投影矩阵的所有权，省去第二份投影和未使用的拟合残差，缩短诊断缓冲区生命周期。以两个真实二进制比较 14 组完整 ABI 输出向量，含同一登记百万行输入的 robust/unadjusted，逐位相同。另有 231 项快速 IV/构建/验收脚本、144 项独立精度/准入/进度与取消定向测试通过。证据见 local/iv-workspace-reuse-20261105/。中断前没有启动的配对不再生成空槽，一次观测不能报告逐位重复。资源收益由下一轮新工作进程验证。

### f05e480f 独占双协方差验收

两个协方差各 5 次参考校准及 5 组交替，使用同一登记百万行 CSV，输出相同 7 张图。30 个独立 worker 全部通过输入、宿主、产物和实际 Rust 构建回执检查。两条协方差各自的引擎重复值逐位一致，跨引擎已声明分项无超差。原始结果为 local/perf-evidence/fast-engine-iv-buffer-reuse-{robust,unadjusted}-20261105/report.json。

| 协方差 | 分析秒 参考→快速 | 完整图表秒 参考→快速 | 分析 RSS GB 参考→快速 | 判定 |
|---|---:|---:|---:|---|
| unadjusted | 6.169→2.131 | 7.352→3.340 | 3.966→1.236 | 通过，快速端最高噪声 2.152% |
| robust | 7.735→1.935 | 8.929→3.119 | 3.972→1.158 | 失败，快速分析时间 5.151%、分析 RSS 6.153%、完整交付 RSS 6.226% |

三次带公开阶段回调的 robust 诊断定位高水位在估计完成、进入诊断前，期间增加 255–279 MB；分析峰值 1.132–1.169 GB。这些独立观测未复现交替样本的全部波动，不能据此判定其根因或改写原失败。诊断原件见 local/perf-evidence/iv-fast-phase-observation-20261105/。
