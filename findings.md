# v1.8.9 P1 发现

- 当前集成 worktree 为 `workbench-v1.8.9-hardening-integration`，HEAD `afc7649c`，工作树已有 P0 dirty changes，不能 reset/checkout 覆盖。
- P1 data consumer、native interchange 基础、classification production、survey extension 的历史提交已在 HEAD 祖先中；它们仍需在当前基线做 fresh verification。
- `186d4886` 分类中央消费者切换不在当前 HEAD，需要评估并合入；`10f9c8eb` 原生 interchange metadata 提交已在候选历史中，需核对是否确实可见。
- 历史 formal line 的 COMPLETED/COMPLETED_WITH_KNOWN_GATES 只证明其自身范围，不证明当前集成、浏览器、provider 或 release。

## 当前 fresh QA 结论

- P1-A 数据编辑器/元数据：前端已使用 canonical `variable_label`，补齐 measurement level、missing policy、role、sensitivity 和新增 value label；后端 projection 保留声明字段并维持服务端确认/fail-closed。数据编辑、互操作、路由、metadata 套件 131 passed；前端相关 31 passed，tsc 通过。
- P1-B 原生互操作：SAV/ZSAV 的 admitted metadata round-trip 通过；DTA 对不支持的 measurement level/user-missing 诚实降级；Parquet 损坏读、无 artifact 写入、已有目标部分写入和 dataset-level metadata loss 均有 typed 保护与测试。fastparquet 未安装且不被 capability 宣称为可用。
- P1-C 分类 ML：修复概率 log-loss、OOF 阈值评分、解释证据中央读取和 catalog evidence budget；另修复 bounded search 固定 0.5 与正式比较阈值不一致，搜索现在消费同一 decision policy。holdout 仍由 C0 seal boundary 控制。
- P1-C 校准尺度 review：进一步分离 `selection_threshold`（完整 development OOF/raw_model_probability）与 `threshold`（disjoint development calibration eval/calibrated_probability），precision constraint 与最终 holdout 使用同一校准概率尺度，避免把 raw threshold 与 calibrated probability 混用。
- P1-D 复杂抽样：bootstrap 不再生成负 replicate weights；BRR 校验 balance/orthogonality；缺失 PSU/stratum fail-closed；variance method/source 必须显式；中央 projection 接入 Probit/Poisson。

## 已确认的非 P1 阻断

- `scripts/gate.sh --full` 当前 backend 不是全绿，主要失败在既有 evidence authority/owner host 和 v1.8.7 legacy Agent/Notebook/Report 读取测试；不能通过放宽 P1 projection 或恢复 raw fallback 来“修绿”。
- `scripts/devline_control.py verify --all` 被历史开发线 ContextPack drift 阻断；四条本轮 P1 formal line 分别 verify 通过。

## 本地优先收口新发现（2026-08-23）

- 现有 workflow state 写入没有顶层 execution-state schema gate；`WorkflowStepState` 仍会把旧 `produced_dataset` 形状归一化，因此 clean cutover 需要在 state 入口拒绝旧版本，而不是继续兼容读取。
- workflow host/evidence port 的现有实现只接受外部 supervisor-admitted endpoint；本机需要一个明确的 backend bootstrap seam，并继续复用现有 FD admission、原子写入和 authority 校验，不能在请求层接收路径、socket 或 token。
- evidence packet store 的持久文件已经有安全读写和跨进程锁，但 registry 当前主要是进程内表；本机重启 resume 需要从已校验的 packet/index 受控重建 registry，不能把磁盘 JSON 直接当 authority。
- `scripts/planner_benchmark.py` 已有 provider benchmark 机制，但 deterministic evaluator 与 provider 调用必须分成两个独立结果类别，provider 缺失不能被记成 deterministic 成功。
- 当前 Agent/Notebook 仍有旧路由/客户端调用痕迹；cutover 完成前不能把 package-local 新 compiler 测试误称为 UI 已切换。

## 2026-08-24 本机 example 验收

- 待验证：Notebook、Agent、Report 是否在同一 run/project scope 下完成自然语言 → typed preview → server confirmation → execution → formal evidence。
- 证据分类：真实 DeepSeek provider、deterministic/local backend、浏览器可见 UI、Report evidence consumption 分开记录，不互相替代。

## 2026-08-24 本机 example fresh QA

- 已验证同一新 run 的 Agent 和 Notebook 都经过 server-owned compiler；两者在补齐相同绑定字段后都明确返回 `runtime capability 尚未绑定`，没有隐式 fallback，也没有未经确认的执行。
- 已验证 example 的数据/模型阶段本身完成：30 行、4 列、OLS(HC1)、14 个 figures；分类变量 `region` 被明确记录为自动 dummy-code，而不是静默丢弃。
- 已验证 server-owned evidence 的底层产物存在并绑定本机 identity/project/session/run/model；但 Report consumer 最终拿到 `REPORT_EVIDENCE_SCHEMA_INVALID`，因此不能把底层 evidence commit 宣称成可引用 Report projection。
- 关键阻断是 reporting admission：run `errors.json` 记录 `REPORT_EVIDENCE_FACTORY_FAILED` 与 `REPORT_EVIDENCE_REQUIRED`，`run_manifest.status=failed`；浏览器 Report 同步显示 `UNAVAILABLE`、0 facts、Generate disabled。这个 fail-closed 行为符合安全边界，但说明本机完整 Report 闭环尚未通过。
- 真实 DeepSeek provider 已配置但本轮无实际请求记录；由于 Notebook/Agent runtime 未绑定且 Report 没有可引用事实，继续调用模型会绕过正确性/证据门禁，故标为 `NOT VERIFIED`。

## 2026-08-25 修复阶段根因与首轮验证

- Report 阻断的根因已锁定：`INFO/WARNING` 被 evidence owner 错误映射为 `execution_status=partial`，而正式 projection 对 partial 必须拒绝；这把“结果已完成但完整性降级”误报成“执行未完成”。修复后映射为 `completed + available + degraded`，事实、警告和降级原因都保留；`blocked/failed/insufficient` 仍 fail-closed。
- Report 导出边界同步允许 owner-issued projection 的 `status=degraded`，仍拒绝 `blocked/unavailable`，没有恢复 raw `model_results` fallback。
- 独立 Report/evidence 回归套件：`198 passed, 10 warnings`。这只证明 package-level admission/projection，尚不等于浏览器新 run 已通过。
- `joint_f_test` 的第二个根因是 provider manifest 已声明 executor，但 builtin runtime composition 没有接收或注入本机可信 workflow execution port；当前先用红测锁定这一缺口，红测结果为 3 个 binding case 均因缺少 `workflow_post_estimation_execution_port` 参数而失败。未注入时仍必须保持 unavailable，不能把声明当成可执行。

## 2026-08-25 本轮修复后的事实

- 本机 server-owned workflow execution port 已真正接通；Notebook 和 Agent 的同一 `workflow.post_estimation.joint_f_test` 均完成执行并返回正式 evidence receipt。
- 首次重试失败的真实原因不是统计计算，而是两个边界问题：post-estimation 输出路径未绑定 workflow identity，以及 `report_evidence.json` 被错误当成模型 post-estimation artifact。两者均已修复并有回归测试。
- Report 现在显示 `AVAILABLE` + `DEGRADED` 的正式 evidence，保留 warning/validation-not-applicable 语义；没有恢复 raw `model_results` fallback。Report 生成成功并保存到 history。
- 公开 provider 状态显示当前本机使用 DeepSeek、`deepseek-v4-flash`、key present；本轮 Report `/llm/chat` 返回 200。仍未把这次单次调用冒充为完整 provider benchmark。
