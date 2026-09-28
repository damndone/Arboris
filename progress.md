# Progress

## 2026-07-18

- 初始化真实 API 运行验收计划。
- 计划、发现和进度文件均为本次未跟踪临时记录，未进入版本提交。
- 只读核验完成：选择 `panel.csv` 作为 OLS golden fixture，确认真实 DeepSeek 配置字段存在且未泄露值。
- 第一轮真实 DeepSeek Agent turn 完成但 blocked：UI focus 与 Agent context 没有绑定 exact model node，触发 repeated `ChainHeadConflict`。保留 scratch evidence，准备完整 context 的第二轮隔离测试。
- 第二轮隔离测试完成：通过真实 API 注入完整 NodeOperationContext，DeepSeek turn 约 28.9s，生成并确认 `model.rerun` proposal；child run 完成，payload hash/confirmed-executed payload 一致。
- 第二轮发现关键缺口：child 已完成且已 reconcile，但 `/analysis-loop/packets/{child_run_id}` 仍为 `status=absent`，所以 generic Agent rerun 没有完成 ValidationPacket/ComparePacket golden flow。正在只读定位接线边界，并继续采样后端和 UI 证据。
- 源码定位完成：`agent_routes.py` 的通用确认分支只调用 `orchestrator.confirm_proposal`；只有 proposal preconditions 带 `analysis_loop` binding 才调用 `confirm_analysis_loop_proposal`，terminal observer 才会构建 packet。
- 专用 Analysis Loop 控制路径在同一 `panel.csv` 上完成：PlanDiff → confirm → child → reconcile → ValidationPacket passed → ComparePacket complete，结论 `UNCERTAINTY_INCREASED`。
- 浏览器验收完成：真实 DeepSeek Ask AI 约 22s，当前事实读取正确；但 child 的 UI source/packet 显示错误，已由共享 dedup 节点的 `runs[0]` 取值和保守 provenance 条件归因。
- 性能采样完成：source workflow 约 0.676s；generic Agent DeepSeek turn 约 28.9s；generic child workflow 约 0.498s；dedicated child workflow 约 0.454s；专用 proposal HTTP 约 0.18s；reconcile HTTP 约 0.02s。服务关闭和最终 git/依赖检查待完成。

## 2026-07-18 repair follow-up

- 已修复四类真实运行阻断：通用 Agent OLS clustered 意图现在进入 canonical typed Analysis Loop proposal；异步 effect 在 reconcile 前保持 running/pending；共享 dedup forest node 使用 active-head run 解析 packet/source；run rail pseudo selection 绑定 exact model node。
- 已修复证据边界：Ask AI 对 rerun child 等待后端 Analysis Loop facts，传入 source/child/PlanDiff/Validation/Compare 的结构化证据；legacy child 在缺少 packet 时从 `rerun_of` 解析 source facts；模型不得用节点展示值自行猜 source 结果。
- 回归验证：Analysis Loop/Agent backend targeted 65 passed；frontend targeted 66 passed；后端路由/生命周期 31 passed；前端 provenance/Ask AI/Agent/section 37 passed；sandbox 相关提权测试 34 passed。
- 最终提权完整 gate 通过：backend `2111 passed, 8 skipped, 43 warnings`；golden `23 passed, 1 warning`；frontend `132 files / 1165 tests passed`；frontend typecheck passed。
- 受限默认沙箱中的 macOS `sandbox-exec` 失败已确认是环境权限限制，不是代码失败；修复验证没有再次调用真实 DeepSeek API。

## 2026-07-18 defect closure follow-up

- R3 已补齐 `event_study` / `time_trend` 的 serve-time numeric source；真实事件研究动态值与 cleaned parquet time series 均有回归测试。
- R4 已让 Figure Ask-AI 复用共享 Markdown renderer；ReportView 现会在图表 source 加载完成后才允许生成报告。
- R1/R2 已把报告 packet 的 figures 接入 LLM 提示、报告渲染和导出：HTML、Word、LaTeX zip、print-ready PDF HTML 均由 run-owned artifact 解析图表；模型不接收像素，只输出 `[[fig:artifact_id]]`。模型漏 marker 时，保存层补齐 Figures appendix。
- D1/D2 已补齐 list-runs dead-worker reconciliation、取消端点、cooperative checkpoint、honest-DiD M/event heartbeats 和默认 30 分钟超时；取消/超时最终态为 interrupted 并释放槽位。
- D4 已按模型声明的 covariate metadata 修复 CS 的误报；SA classic 不声明 X，因此仍保留真实的 VARIABLE_DROPPED。CS 三个 golden 已同步为只含 PANEL_POOLED_MODEL，SA goldens 保持原语义。
- D3 已用有界 spawn process pool 把独立 honest-DiD target/grid 分片并行化，并把 worker heartbeat 回放到父进程。60×6 CS fixture、B=1、默认 5×5 网格实测：serial 163.69s，进程并行 50.31s（约 3.25× wall-clock 改善）；结果等价测试通过。沙箱内 semaphore 限制触发 serial fallback，提权隔离实测验证了真实并行路径。
- 当前阶段：R1–R4、D1–D4 已完成；最终完整 gate、保护边界与 worktree 清理审计已通过，尚未 push/PR/merge/tag。

## 2026-07-18 cs_did_staggered real DeepSeek report acceptance

- 已读取 `docs/cs-did-howto.md` 并确认官方 example 参数：`state`、`year`、`first_treated_year`、`outcome`、`policy_intensity`；当前 v1.7.2 backend 已启动于 `127.0.0.1:8000`。
- 当前尚未提交 run；下一步通过 multipart API 提交真实 example，随后采集终态、全部 figure artifacts 和性能时间。
- 主 run `20260718_163434_852104_4c3b521c` 已完成，生成 8 张 figure；8 个 figure AI-context source 均非空。
- 第一版 DeepSeek 中文报告已生成并导出，但审查发现 `time_trend` source 是截断预览且报告出现无效 `c:source` 引用；未直接交付，正在用补充 figure facts 的第二次报告调用重生成。
- 第二次真实 DeepSeek 报告调用完成：模型 `deepseek-v4-flash`，约 31.95s；将 8 个 figure source 的数值事实加入 fact packet，并把无效数字引用规范化为真实 `cN` ID，同时移除不受证据支持的分布形状推断。
- 最终 clean report 已导出：Markdown 3158 字符、HTML 179331 bytes、DOCX 124916 bytes；8 个 `[[fig:...]]` 各出现一次，HTML 有 8 个内嵌 PNG，DOCX 有 8 个 `word/media/*.png`。
- 浏览器前端验收完成：WorkBench 页面显示 completed run、Graph/Report/Agent/Logs；ReportView 另一次真实 DeepSeek 请求成功，history 有记录，`report-body` 发现 8 个图片元素。另开临时 HTTP 页面检查 clean HTML，标题、数据、方法、ATT、event study、聚合、诊断、局限、结论和 8 张内嵌图均可见。
- 性能证据：Workbench workflow 从首个 step 到 `workflow_completed` 约 0.777s；figure context 并行获取 0.054s；8 次逐图 DeepSeek 串行合计 72.786s（单次 6.730–10.779s）；第二次总报告 DeepSeek 31.945s；HTML/DOCX 导出约 0.013/0.004s。以上为单次样本，不宣称 p95。
- 收尾完成：后端、前端、临时 HTTP 服务均已关闭，端口 8000/5173/8787 均无监听，worktree-only `frontend/node_modules` symlink 已移除；报告和运行目录保留在 `/private/tmp/wb-v172-cs-staggered-real-20260718`。
- 补充 Agent 只读验收：在当前 CS run 上通过真实 DeepSeek 创建 chain session 并完成 1 次只读 turn，墙钟 `21.788s`；会话持久化为 5 个只读 inspect tool calls、1 条最终 assistant 回复，`proposal_count=0`、session `idle`。随后后端已停止。
