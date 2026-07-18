# 三个产品方向拍板草案：图规模化 · artifact AI 解读 · terminal 权限模型

> 2026-07-15 用户提出三个问题,本文档固化设计讨论结论,供后续版本圈定时取用。
> 状态同步 2026-07-18：G1/G2/G3 的基础能力已随 v1.7.2 发布；v1.7.3 只做报告/运行运维 closeout 和真实 DeepSeek 验收。P-SBX2、P-CE1 以及 G2 provider-gated 真·看图仍未排入本版本。
> 本文保留为长期方向文档；对应 live backlog 见 `docs/superpowers/followups/BACKLOG.md`。

## G1 · 图爆炸:合并"投影",不合并"谱系"

**问题**:十几个变量各做一次 `data.column.cast`,产生十几个兄弟 child 节点,画布纵向堆叠爆炸。
直觉上"不该合并"是对的——但不该合并的是谱系记录(每个 cast 独立 Operation Record/artifact/审计单元),
**可以合并的是视图投影**(已有先例:"Variables (4)" 合成分组节点就是纯投影层折叠)。

三层方案(推荐组合):

1. **治本 = batch spec(V12 候选)**:`data.columns.cast` v2,一个 spec 含 N 个 column/dtype 对
   → 一次 preview(逐列列出结果)、一次 confirm、**一个** child 节点、一份 N 条 recipe、一个 diff。
   操作粒度对齐用户意图粒度("把这些列都转了"本来就是一个意图)。
   现状还有个语义缺口:12 个兄弟 child 每个只应用一个 cast,没有节点代表"全部转完的数据集"
   (链式 cast 可表达但图变深链、Operation Record 碎成 12 份)。batch 同时解决这两点。
   **加分项**:NL Agent(v1.7 优先级 6)最需要的就是这个形态——一句话映射一个 batch proposal。
2. **治标 = 投影层折叠**:同源兄弟 data-cast 节点在 canvas 折叠成 "Data operations (N)" 卡,
   点开 drawer 列全部。batch 上线后仍需要(用户总会制造扇出)。
3. **禁区**:不在 durable graph 里合并节点——会破坏 Merkle identity、per-operation verification、
   source-immutable 不变量。

## G2 · AI 解读 artifacts(图表)

**关键判断:图表是从数据渲染的,AI 解读数字优于解读像素。**

1. **第一步 ✅ 已落(2026-07-15)**:Results(Table)图库每个 figure 加 "Ask AI about this figure"。
   serve-time `figure_context.py` 把 figure→(chart_type + backing 数值 artifact)映射出来
   (coef_plot→model results / histograms 等→data_profile / correlation·scatter→correlations /
   residuals·qq→diagnostics),返回数值源 bounded safe JSON preview + guidance + guardrails;
   decorate-only(读 artifacts index),golden 0-drift 不动。route `GET /figures/ai-context`,
   `/llm/chat` 加 `workbench_figure_context_v1` mode(禁称"看到像素",要求从数值源作答)。
   真机验证:直方图网格解读引用了 data_profile 确切数字(education mean≈19.0 σ≈4.39),从数据非像素作答。
   与 BACKLOG V7 同族,共用"typed artifact reference 进 packet"的缝。
2. **第二步(可选,provider-gated)**:真·看图,base64 进多模态 provider。按 capability registry
   的 provider 能力开关 + **显式 opt-in**(突破现行 "binaries excluded" 可见性政策,把渲染后的
   数据图发外部服务,必须让用户看见并同意)。
3. **原则**:选择图表必须产生 typed artifact reference,不把文件名塞 prose(typed navigation 一致性)。

## G3 · terminal 面板:权限挂在 operation 上,不挂在输入框上

**问题**:底部面板输入框与 graph composer 同步,纯冗余;用户想要"terminal 权限更高一层
(如改代码)"但边界难界定。

**设计裁决**:
1. **去重**:收敛为一个 composer;底部面板做纯输出/检查面(transcript/events/operation records/diff)。
   或反之只留 terminal 输入、graph composer 变聚焦快捷方式——二选一,不并存两个同步框。
2. **权限层级属于 operation,不属于 UI 入口**。"换个框就多权限"审计上说不清、用户会搞混。
   macOS terminal 权限高是因为 shell 的 operation 集,不是窗口长相。
3. **"能改代码"的正确形态 = 新增 typed operation `code.execute`**:沙箱内跑脚本,输入=immutable
   artifact 副本,输出=derived artifact + 完整脚本 recipe(与 cast recipe 同构),走同一
   proposal→confirm→执行→Operation Record→verification 生命周期;永不触碰 source、不出网。
   即 roadmap v1.7 "操作环+diff留痕+沙箱" 的沙箱环。边界三条硬规则:
   ① 一切 effect 走同一 typed lifecycle;
   ② 提权 = capability registry 多注册一个 operation(自带 risk 等级与 confirm 要求);
   ③ terminal 只是该 operation 的外观(流式 stdout/mono/`❯`),语义仍是被审计的 typed operation。

### G3 进展(2026-07-15)

- ✅ **输入框去重已落**:底部 AgentPanel 移除了与 graph composer 同步的冗余输入行,变成
  纯 transcript/inspection 面(transcript + operation status + diff),留一行 hint 指向唯一输入
  (graph 下方 composer)。`agent-terminal-input`/`agent-terminal-input-row` 已删,新增
  `agent-terminal-input-moved-hint`。测试改为断言"无冗余输入 + hint 存在"。
- ✅ **沙箱 runner 已落 + 已证明(2026-07-15)**:`backend/workbench/sandbox.py`。
  backend 探测:macOS `sandbox-exec`(seatbelt)/ Linux `bwrap`;**无 backend 时拒绝执行**
  (绝不退化成裸 `exec` —— Python 层守卫不是沙箱,假装是才是真正的安全事故)。
  seatbelt profile = allow default → `deny network*` → `deny file-write*` → 仅放行输出目录与私有 tmp。
  另加 `setrlimit`(CPU/AS/FSIZE)+ wall-clock timeout + **env 洗白**(provider API key 绝不继承)。
  `tests/test_sandbox.py` 8 条**真跑真验**:网络出口被拒、输出目录外写入被拒(源文件逐字节存活)、
  目录内写入放行、CPU 死循环被杀、wall clock 生效、父进程的 `WORKBENCH_LLM_API_KEY` 不泄漏、
  无 backend 时 fail-closed。诚实边界:**读**是放行的(需要 stdlib/site-packages,且数据是用户自己的);
  威胁模型 = LLM/用户写的 transform 误删源数据/跑飞/偷偷联网,**不是**已拿到执行权的对手。
- ✅ **`code.execute` typed operation 已落 + 真机验证(2026-07-16)**。`backend/workbench/code_execution.py`。
  - **preview 语义(上一轮的未决设计题,已拍板)**:preview **在沙箱里真跑一次**,写进一次性 temp 目录,
    随后丢弃 —— 项目里一个字节都不写(有测试逐文件 sha 比对)。所以用户 confirm 的是**真实结果**而非预测。
    apply 时会重跑并**要求结果与 preview 逐字节一致** —— 这是**确定性的执行机制**:我们声称代码是
    纯变换,这把"声称"变成"校验";不确定的代码 → `NondeterministicCodeError`,**拒绝写入**。
    同一 execution key 重放 = 不重跑(幂等直接返回)。
  - ⚠️ **执行次数订正(2026-07-16 实测,纠正早前"跑第二次"的错误陈述)**:一次完整用户流程,
    用户代码实际跑 **5 遍**(preview HTTP 1 遍 + confirm HTTP 4 遍 = route 层 freshness preview
    + lifecycle prepare preview + execute preview + apply 的确定性 run)。确定性保证因此**比"两遍"更强**
    (5 次机会抓不确定),但**代价被我早前报低了 ~2.5 倍**。每遍 30s wall clock,一个 ~25s 的重转换
    在 confirm 阶段要 ~2 分钟且可能撞墙。**为何暂不优化**:这 4 遍分散在 prepare/execute 生命周期里,
    各自为 failpoint 崩溃恢复而重导状态(恢复的进程不能信任已死进程传入的 preview,必须重算)。
    **减到 2 遍 = 重写崩溃恢复契约**(把已算的 preview 带 execution key 缓存、confirm 复用),
    风险高、不该在未 review 的大堆改动末尾赶。**结论:5× 正确但昂贵,只在高风险且刻意 gated 的
    code.execute confirm 上付,单独立项优化**(BACKLOG 已记 P-CE1)。
  - **code 契约(窄接口)**:给 `df`,要求 bind `result` 为 DataFrame;**代码不做自己的文件 IO**。
    因此沙箱写权限只需覆盖一个 temp 目录,源在 OS 层不可写,derived artifact 复用 D1 的 schema
    sidecar 写入器(csv/xlsx 都走同一条路)。harness 用 `str.replace` 注入 manifest(**不用 format/f-string**:
    模板全是花括号,给安全相关的 harness 做花括号转义是 bug 农场);用户代码以 JSON 字符串**作为数据**
    传入、在子进程内 compile,无法靠引号/缩进逃逸出 harness。
  - **operation 契约**:`code.execute` v1,`risk_level=high`(它不只是 mutating:preview 和 execute
    都真跑代码)、`confirmation_policy=required`、`natural_language_enabled=False`。
  - **staleness vs 不确定性要分开报**:两者需要相反的应对(源变了→按新数据重提;源没变→代码本身不确定,
    重提也只会再失败)。故 `revalidate_preconditions` 对 code.execute **不重跑 preview**(那个 hook 每次
    尝试都跑),判定下沉到 `_prepare_code_execute_effect`,由它区分二者。
  - **真机验证(真实 seeded 项目 + 浏览器)**:UI 里跑出真 stdout(`wage mean: 34.5`)、diff `+ senior`、
    Apply → Operation Record → 刷新后子节点与 provenance 仍在;**四条边界对真实项目逐条实测**:
    删源被拒(源 sha 逐字节不变)、出网被拒、`WORKBENCH_LLM_API_KEY` 在代码里读到 `<<ABSENT>>`、
    死循环被杀;不确定代码 confirm → 409 且 derived 目录只有那个确定性的 key。
  - **顺带修**:`ProvenanceDiff` 原先只认 cast 的 `casts[]`/`column`,code.execute 的子节点只显示
    "谁创建的"、不显示改了什么 → 改为**按存在的字段渲染**(rows/added/removed/dtype_changes),
    不 branch on operation_id,下一个数据操作无需再动它。
  - ✅ **terminal 外观已落(2026-07-16)**:sandboxed 程序的 stdout 进 AgentPanel(`↳` + mono,
    `agent-operation-stdout`),数据来自 durable Operation Record 的 `outputs.stdout`(真机已核:
    `oprec_3fff18ce...` 里就是 `wage mean: 34.5\n`)。**诚实措辞**:这是**跑完后的捕获输出,不是实时流**
    ——stdout 只有 record 完成才 durable,所以 UI 不做任何"看着它跑"的暗示。真流式需要 SSE,未做。
    语义没变:权限来自注册了 `code.execute`,而非"在哪个框里输入"。

## 优先级 6 · NL Agent 生成同一份 typed proposal(2026-07-16 ✅ 真机闭环)

**范围**:只开 `data.columns.cast`(一句话=一个意图,是最佳目标形态)。**`code.execute` 保持
NL 关闭**——任意代码不该由一句话触达,roadmap G3 的"先手动稳定再谈 NL"不变。

**设计**:模型只出**意图**(run_id / node_ref / casts),后端绑定**只有它能诚实陈述的事实**:
- `artifact_id` —— 模型若能指定它,就能把已确认的操作对准用户没选的数据(resolver 的 docstring
  本来就写着"防止从显示文本**或 Agent 消息**里猜 artifact id");
- `context_fingerprint` —— 这是**preview** fingerprint,在这里对真实数据算出来。真机曾见模型自造
  fingerprint→执行期被拒:正确,但留给用户一个死 proposal。绑定后"可确认=可执行"。

**真机 smoke 抓到 4 个确定性测试抓不到的真 bug**(fake adapter 永远盖不住,与 memory 里那条铁律一致):
1. `inspect_operation_contract` 对 `data.columns.cast` 报 `OperationContractUnavailableError`
   —— lineage resolver 只答 model 节点。修:data 操作的契约由 **registry 拥有**(每个数据节点形状相同),
   回退到 registry 的 editable_schema。**故意收窄**:model.rerun 的 registry schema 是
   `additionalProperties: true` 放行式,拿它兜底等于宣称"随便填",比失败更糟 → 仍 fail-closed。
2. `_proposal_schema` 把每个 target 字段都声明成 `{"type":"string"}`,于是 `casts`(数组)**被声明成字符串**
   → 该操作**根本无法被提议**。DeepSeek 连试 5 次并正确推断"可能它接受数组而非字符串"——schema 错,模型没错。
   (此 bug 上一轮就随 V11 batch 进来了,因 NL 关闭且没人拿 proposal_schema 做校验而**休眠**。)
3. **最深的一个**:`proposal_tool_schema` 的 base = `deepcopy(model.rerun.proposal_schema)`,而
   JSON Schema 的 `oneOf` 与父级是 **AND** → 顶层仍强制 model.rerun 的 target(要 node_hash/
   forest_node_key、且 `additionalProperties:false` 拒绝 `casts`)。`graph.fork` 只是**碰巧**幸存
   (它的 target 是 model.rerun 的超集,多出的那个字段又恰好被 strip)。修:base 只留信封,
   target/preconditions/changes 交给 oneOf 分支。回归测试直接钉住 **DeepSeek 真实发出的那份 payload**。
4. Agent confirm 端点自带 allowlist,且只会重算 node-context fingerprint(`nocv1:…`)——对 cast
   而言身份是 **preview fingerprint**,且 target 根本没有 node_hash 可比。修:`_current_data_columns_cast_fingerprint`
   重跑 preview(与手动 UI 路径确认的是同一个 fingerprint),blocked→422。

**真机闭环铁证**(真 DeepSeek `deepseek-v4-pro`,真项目 `/private/tmp/wb-g3-ui`,后已迁至
`local/smoke-projects/wb-g3-ui` 防 /tmp 清理):一句"把 wage 和
education 转成字符串" → `inspect_data_schema` → typed proposal(后端绑定 `artifact_id=cleaned_dataset`
+ 真 fingerprint)→ confirm → `oprec_efba363b42c8ffeff56eb6a8` completed、verification passed、
child `data-casts:cf5ed865…`「Cast 2 columns」、sidecar 里 wage/education 确为 `string`(D1 生效,
裸 CSV 会读回 int64)、model:ols_1 转 caution、**源 sha 逐字节不变**。

**新增只读工具 `inspect_data_schema`**:给 Agent 看列名+dtype(没有它,模型只能从显示文本猜列名);
**故意不返回 artifact_id** —— 那是 canonicalization 时绑定的后端事实。

## 当前排序建议（2026-07-18）

- v1.7.3：先完成报告 marker/export 的真实 DeepSeek acceptance、timeout regression 和 release closeout；不扩大 operation 或算法范围。
- v1.8+：沿 G1 的 batch/投影模式扩展更多 typed data operations；继续保持 durable graph 不合并、只在 projection 层折叠。
- G2 provider-gated 真·看图、P-SBX2 sandbox self-test、P-CE1 `code.execute` preview 缓存：独立立项，不作为 v1.7.3 隐式范围。
