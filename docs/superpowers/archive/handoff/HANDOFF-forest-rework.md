# 交接：v1.6.1 后的「森林 UX 重做」（post-tag，未合并）

新会话从这里接上。**v1.6.1 已 ship（tag `a86d26a`），之后用户实测 → 对森林视图做了一轮大重做,全部在分支上、未合并未打标签。**

## 0. 一句话状态
- worktree `.worktrees/workbench-v1.6.1`,branch `workbench-v1.6.1` @ `1f06c52`。
- v1.6.1 tag(`a86d26a`)之上 **7 个 commit** = 这轮森林重做。**未 merge / 未 tag / 已 push 到 origin/workbench-v1.6.1。**
- **GATE PASSED:BE 1202 / golden 23 0-drift / FE 653 / tsc 0。** 无未提交。
- venv(worktree 根 `.venv`)+ 前端依赖已装。门禁 `./scripts/gate.sh`。

## 1. 这轮重做干了啥(7 commits 的弧线)
v1.6.1 原本把森林做成一个**单独的轻量 ForestCanvas + `?forest=1` 隐藏开关**。用户实测后连环否决,逐步重构成:

> **「Lineage 的 Graph 标签 = 跨 run 血缘森林」,全局默认,没有单独开关/视图,用的就是原来那个全功能 GraphCanvas。**

关键决策(都经用户拍板,别推翻):
1. **森林不另起炉灶,直接用 GraphCanvas 渲染** —— 把跨 run head-set 投影成 `GraphViewModel`(`workbench/forestModel.ts::forestToGraphViewModel`)喂进 `GraphCanvas`。于是布局切换/搜索/右键菜单/hover/变量折叠/拖拽**全部自动继承**。`GraphView` 在 forest 时渲染同一个 GraphCanvas + 顶部一条 head-version bar(`ForestHeadBar`,点版本=active-head focus/回滚)。
2. **Graph 永远是森林,无 toggle** —— `WorkbenchRouteContainer` 总是渲染 `ForestWorkbench`(走完整 shell:rail+DetailDrawer+底部面板),只有"旧 run 无血缘索引"才回退 legacy 单图。删了 forestFlag/forestMode/ForestModeContext/ForestCanvas。
3. **血缘索引无条件写** —— orchestrator 现在**总是**走 `run_pipeline_traced`(增量 flag 关时 `force_full`,字节级一致 golden 0-drift),所以 `node_index.json` 每个 run 都有 → 森林对所有 run 生效,不靠任何 flag。
4. **去重 key = `node_hash::node_id`** —— 之前纯 node_hash 把变量(var:y/var:x)和 cleaned 合并消失;现在变量保留可见。`build_headset` 把 `parent_stage_id` remap 到 key,`forestModel` 给变量补 cleaned→var 的边(否则变量飘成孤儿卡片)。
5. **model_type 下拉本来是空的** —— `op_contract._fill_model_type_options` 用注册的 model handlers 填 14 个可选。
6. **选中节点连线流动动画** —— `GraphCanvas.decoratedEdges`(镜像 decoratedNodes 的 overlay):碰到选中节点 + focus lineage 的边 `animated:true`+tint,选着就一直亮。

## 2. 关键文件(这轮动过的)
- 后端:`orchestrator/__init__.py`(总走 traced)、`lineage/headset.py`(key=hash::id + parent remap)、`lineage/op_contract.py`(model 选项)。
- 前端:`workbench/WorkbenchRouteContainer.tsx`(ForestWorkbench,总渲染森林)、`workbench/forestModel.ts`(投影+变量补边)、`workbench/ForestContext.tsx`、`workbench/views/GraphView.tsx`(GraphCanvas+ForestHeadBar)、`lineage/graph/GraphCanvas.tsx`(decoratedEdges 动画)、`lineage/detail/RerunContext.tsx`+`OperationSection.tsx`(per-node runId rerun)。
- 删了:`lineage/graph/ForestCanvas.*`、`forestGraph.*`、`workbench/forestFlag.*`、`workbench/views/ForestRouteView.*`。

## 3. 怎么验(浏览器)
- 跑着的服务:**后端 8010(无 flag 模式)+ 前端 5180**。种子项目:`/tmp/wb_forest_smoke/demo`(含 rerun 分支)、`/tmp/wb_forest_smoke/noflag`(无 flag 新建)。
- 直接看(Graph 标签默认就是森林):
  `http://127.0.0.1:5180/runs/20260624_234344_588898_1937c303?project_root=/tmp/wb_forest_smoke/noflag&tab=lineage`
- **CDP 自驱浏览器**(preview MCP 因 unicode 路径 `项目规划` spawn 失败,用不了):起 headless Chrome `--remote-debugging-port=9355 --remote-allow-origins='*' --user-data-dir=/tmp/wb_chrome_dbg`,node 24 全局 WebSocket 连 `/json/list` 的 page target,`Page.navigate`+`Runtime.evaluate`+`Page.captureScreenshot`。**坑**:`.react-flow__edge` 选择器在本版返回空(类名不同)、`innerText` 对离屏节点返空(用 `textContent`)、合成 mouse/pointer 事件常触发不了 ReactFlow 拖拽/点击(改用直接 `element.dispatchEvent` 一串 pointer+mouse 事件最稳);截图是地面真相,动画(流动)截图截不出来要肉眼看。

## 4. NEXT / 待办
1. **用户最终验收这轮重做**(尤其连线流动动画、拖拽要真鼠标确认)。OK 后:**用户授权才能** merge `workbench-v1.6.1` → main + 移/打 tag(v1.6.1 已用,可能要 v1.6.2 或 retag,问用户)。
2. 已知小事:变量少时不折叠(>阈值才折)、legacy 老 run(无 index)仍走旧图的变量折叠(那套展开有历史 bug);bottom panel 默认收起(全局历史行为)。
3. 收尾问是否清 dev 缓存(`.venv`+`node_modules`,~758M,见 [[feedback-version-cleanup]])。
4. 铁律仍在:门禁不裸 pytest / golden 0-drift 硬门禁 / 推 main·merge·tag 需用户单独授权 / 每版自己 worktree。

## 5. 铁律提醒
三级审查(Implementer→QA→Reviewer)、subagent 只吃单 loop 且 prompt 禁 push、section 检查点节奏。详见 [[lineage-v161-progress]] 与 v1.6.1 的 plan/spec。
