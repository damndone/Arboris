# v1.6.8 Claude review/optimization handoff

> 写于 2026-07-08。目标读者：Claude 接手做 review、优化或重构。
> 当前 checkout：`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.6.8`，branch `workbench-v1.6.8`，HEAD `2ffa430`。
> 关键状态：**有未提交代码改动**；不要误以为这是干净发布点。不要 push / merge / tag，除非用户明确授权。

---

## 0. 先读这个：当前不是原始 T11 停止点

旧 handoff `docs/superpowers/handoff/v1.6.8-graph-native-genesis-handoff.md` 仍然有价值，但它描述的是早先的停止点：T11 待修、T12-T15 待做。

现在的真实状态已经推进到：

- T11 legacy-run critical 修复已做过并提交在历史里。
- Genesis wizard、draft-only canvas、Command Palette fallback、roadmap/followups 都已经提交到 HEAD。
- 用户随后在 UI smoke 中发现新问题：Home 意义不清、Runs 历史为空、新建项目 UI 丑/越界、Browse 误导、Submit 能力迁移缺口、Variables 展开炸图/边丢失/选择错位、fork 功能看起来消失。
- 当前工作树包含一批**未提交修复**，用于回应这些 UI/能力迁移问题。

接手者应该以本文档和 `git status` 为准，不要只按旧 handoff 继续做 T12/T13。

---

## 1. 当前工作树

### 1.1 Git 状态

- branch：`workbench-v1.6.8`
- HEAD：`2ffa430 docs: close v1.6.8 roadmap and followups`
- 未提交变更规模：29 个已跟踪文件修改，3 个新增文件。
- 新增文件：
  - `frontend/src/runForm/ColumnRolePicker.tsx`
  - `frontend/src/runForm/CovarianceSelect.tsx`
  - `frontend/src/workbench/ProjectRootContext.tsx`

### 1.2 修改面概览

主要 touched files：

- 后端/API 测试：
  - `backend/workbench/api.py`
  - `tests/test_api.py`
- Launcher / project creation：
  - `frontend/src/launcher/CreateProjectModal.tsx`
  - `frontend/src/launcher/LauncherRoute.tsx`
  - `frontend/src/launcher/LauncherRoute.test.tsx`
- Workbench shell / route：
  - `frontend/src/workbench/WorkbenchRouteContainer.tsx`
  - `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`
  - `frontend/src/workbench/WorkbenchTopbar.tsx`
  - `frontend/src/workbench/WorkbenchTopbar.test.tsx`
  - `frontend/src/workbench/CommandPalette.tsx`
  - `frontend/src/workbench/views/TableView.tsx`
  - `frontend/src/workbench/ProjectRootContext.tsx`
- Genesis / Submit parity：
  - `frontend/src/lineage/drafts/GenesisWizard.tsx`
  - `frontend/src/lineage/drafts/GenesisWizard.test.tsx`
  - `frontend/src/runForm/ColumnRolePicker.tsx`
  - `frontend/src/runForm/CovarianceSelect.tsx`
- Variables / graph：
  - `frontend/src/lineage/graph/GraphCanvas.tsx`
  - `frontend/src/lineage/graph/GraphCanvas.test.tsx`
  - `frontend/src/lineage/graph/GraphNode.tsx`
  - `frontend/src/lineage/folding.ts`
  - `frontend/src/lineage/folding.test.ts`
  - `frontend/src/lineage/roles.ts`
  - `frontend/src/lineage/roles.test.ts`
  - `frontend/src/lineage/tokens/lineage.css`
  - `frontend/src/styles.css`
- Fork / rerun / detail：
  - `frontend/src/lineage/detail/DetailDrawer.tsx`
  - `frontend/src/lineage/header/DetailHeader.tsx`
  - `frontend/src/lineage/header/DetailHeader.test.tsx`
  - `frontend/src/lineage/graph/NodeActionMenu.tsx`
  - `frontend/src/lineage/graph/NodeActionMenu.test.tsx`
  - `frontend/src/lineage/runRail/RunHistoryRail.tsx`

---

## 2. 已实现、失败、遇到困难

### 2.1 已实现

#### A. `projectRoot` 传播链修补

问题：新 slug 路由 `/p/:slug/graph` 不再天然带 `?project_root=`。任何还直接读 query 的组件都会在 slug 路由下静默坏。

已做：

- 新增 `ProjectRootProvider` / `useProjectRootOptional`：`frontend/src/workbench/ProjectRootContext.tsx:1-22`
- Workbench 顶层包住 `body` 和 `genesisWizardDrawer`：`frontend/src/workbench/WorkbenchRouteContainer.tsx:609-615`
- 改为 prop/context 优先、query 兜底：
  - `NodeActionMenu`：`frontend/src/lineage/graph/NodeActionMenu.tsx:143-147`
  - `RunHistoryRail`：`frontend/src/lineage/runRail/RunHistoryRail.tsx:67-73`
  - `TableView`：`frontend/src/workbench/views/TableView.tsx:132-140`
  - `CommandPalette`：`frontend/src/workbench/CommandPalette.tsx:45-50`

剩余 query 命中分类：

- `frontend/src/App.tsx`：旧 `/runs`、旧 `/submit`、redirect/deep-link 入口，允许保留。
- `frontend/src/pipelineDrafts/DraftGraphRoute.tsx`：旧 standalone draft route，允许保留。
- `NodeActionMenu` / `RunHistoryRail` / `TableView`：已是 context/prop 优先，query 只兜底。

建议 Claude review：重点找是否还有隐式从 `window.location.search` 读 `project_root` 的组件，尤其是新增的 drawer/menu/palette 组件。

#### B. Variables 展开态修补

用户现象：

- Variables 展开后变孤立节点，前后连线没了。
- 点击 Variables 大节点内的变量卡片不能查看具体变量，反而复原成原始 Variables 节点。
- 变量多时直接铺满上沿，审阅困难。
- 多变量显示成 `X?`，看不出变量名。

已做方向：

- 把展开态改成“一个聚合面板节点 + 内部变量卡片”。
- React Flow 视角仍只有一个可连边的 group node，所以边接在聚合面板上，不再把内部变量炸成独立 layout 节点。
- 内部变量卡片显示变量名、摘要、角色 badge。
- 点击内部变量调用 `onSelect(member.id)`，drawer 选中具体变量。
- `selectedNodeId` 若是隐藏成员，映射回可见 group，避免 selected/edge highlight 找不到可见节点。

关键代码：

- `VarContainerNode`：`frontend/src/lineage/graph/GraphCanvas.tsx:198-295`
- expanded group node 生成：`frontend/src/lineage/graph/GraphCanvas.tsx:488-514`
- fold 后边重定向：`frontend/src/lineage/graph/GraphCanvas.tsx:515-538`
- selection 映射回 group：`frontend/src/lineage/graph/GraphCanvas.tsx:586-641`
- edge highlight 映射回 group：`frontend/src/lineage/graph/GraphCanvas.tsx:658-681`
- CSS：`frontend/src/lineage/tokens/lineage.css` 和 `frontend/src/styles.css`
- regression tests：`frontend/src/lineage/graph/GraphCanvas.test.tsx`，尤其 `maps selected variable members back to the visible variable panel`

设计代价：

- 内部变量不再是 React Flow node，所以它们没有独立 edge anchor、独立 drag、独立 layout。
- 这是当前最稳的止血方案，但不是最终的信息架构。最终可以升级成“面板内虚拟列表 + drawer 详情 + search/filter”。

#### C. Genesis / legacy Submit 能力迁移补齐

已把旧 Submit 的核心表单语义迁入 Genesis wizard：

- 数据文件上传：`GenesisWizard.tsx:213-240`
- 多 sheet 下拉：`GenesisWizard.tsx:497-515`
- transpose：`GenesisWizard.tsx:516-524`
- y/x：`GenesisWizard.tsx:627-650`
- 变量 role picker：`GenesisWizard.tsx:657-666`
- model type：`GenesisWizard.tsx:539-546`
- imputation：`GenesisWizard.tsx:547-551`
- covariance：`GenesisWizard.tsx:574-578`、`615-626`
- panel entity/time/covariance：`GenesisWizard.tsx:552-563`
- IV endog/instruments：`GenesisWizard.tsx:564-579`
- DID roles：`GenesisWizard.tsx:581-589`
- CS/SA controls：`GenesisWizard.tsx:590-596`
- dCDH controls：`GenesisWizard.tsx:597-603`
- prediction model/cv/sampling：`GenesisWizard.tsx:604-614`
- validate + execute as genesis：`GenesisWizard.tsx:408-439`

参数拼装集中在 `modelParams()`：`frontend/src/lineage/drafts/GenesisWizard.tsx:280-363`

补的关键测试：

- full create/patch/validate/execute happy path：`GenesisWizard.test.tsx:106-209`
- column role picker：`GenesisWizard.test.tsx:211-247`
- IV params：`GenesisWizard.test.tsx:249-326`
- covariance：`GenesisWizard.test.tsx:328-366`
- prediction 开启但没选 algorithm 阻断：`GenesisWizard.test.tsx:368-399`
- dCDH + prediction 参数名对齐 legacy Submit：`GenesisWizard.test.tsx:401-470`

明确没有迁移到 Genesis 的旧 Submit 语义：

- `auto/stepped` run mode：新 Genesis 是 draft execute，`execution_mode: "genesis"`。这不是同一个运行入口。
- 旧 Submit 的 inline progress / last-run panel：现在应由 Workbench rail、执行状态、Table/detail 视图承接。
- batch / `y_list`：仍留 `/submit` 兜底，未图内化。

#### D. Browse 回归但不伪造绝对路径

用户要求：不能直接砍 Browse；如果不可行要 warning，说明原因，提示重新选。

已做：

- `CreateProjectModal` 重新放回 Browse 按钮和 hidden directory input：`CreateProjectModal.tsx:157-175`
- `onFolderFiles()` 只读取 `webkitRelativePath` 的顶层 folder name，用于 project name hint；不再合成假的 parent absolute path：`CreateProjectModal.tsx:94-104`
- 显示 warning：浏览器不能可靠返回后端可访问的绝对父目录，用户必须输入 Parent folder：`CreateProjectModal.tsx:101-103`
- Modal 文案明确要求输入后端可访问绝对父目录：`CreateProjectModal.tsx:140-142`

根因解释给 review 者：浏览器 File API 暴露的是相对路径，不暴露真实本机绝对目录。旧逻辑把相对 folder name 拼成 `/${rootName}` 是误导，可能导致后端 500 或项目建到错误路径。

#### E. fork 功能可从 slug route 恢复 projectRoot

用户现象：fork 功能没有了。

已做：

- `NodeActionMenu` 在无 prop、无 query 的 slug route 下可从 `ProjectRootProvider` 获取 root：`NodeActionMenu.tsx:143-147`
- 测试覆盖：`NodeActionMenu.test.tsx` 的 `uses ProjectRootProvider on slug routes when no projectRoot prop or query exists`

注意：这只证明菜单能拿到 root 并创建 draft；还没有做浏览器级“用户能找到 fork 按钮”的 UX smoke。

#### F. 运行记录与 active head

已做过一些状态同步：

- `ForestWorkbench` 里 active head / pending genesis / pending focus 都集中在 `WorkbenchRouteContainer.tsx:130-617`
- Table view 使用 active head 而不是固定 URL run：`TableView.tsx:132-140`

但是用户指出 Workbench UI 中 `RUNS` 没有历史记录。自动化没有充分覆盖“真实执行后 rail 立即显示历史”的浏览器 UX，见 §4。

### 2.2 失败或没有完成

- 没有做新的浏览器真机 smoke。当前修复通过了 unit/API/type checks，但没有在 in-app browser 上重新走“新建项目 -> 上传多 sheet xlsx -> Genesis -> run -> variables 展开 -> fork”的完整路径。
- 新建项目 UI 只是做了布局/文案/Browse 逻辑修补，未做系统性视觉设计 review。用户已经明确说“奇丑无比、按键超出界面”，这块仍需要肉眼验收。
- Home 页面意义没有被产品层彻底解决。当前实现仍是 Launcher / Workbench 双入口；如果用户认为 Workbench 已能新建项目，Home 的定位应重新定义，不能只靠代码补丁解释。
- Runs 历史为空的问题还没有被我证明修复。需要 browser smoke + 后端 API 对照。
- Variables 面板的性能和大变量数 UX 没做真数据压力验证。当前只是结构上止血。
- Genesis wizard 虽补齐旧 Submit 大部分表单语义，但没有对所有模型家族跑真实后端执行 smoke。

### 2.3 遇到的困难

- `projectRoot` 从 query 迁移到 slug 后，旧组件容易静默退化。最危险的是 menu/drawer/palette 这类深层组件，它们不像 route component 那样天然拿到 root。
- Variables 是混合模型：逻辑上要能选择具体变量，视觉上又要避免每个变量成为独立大节点。之前“展开成真实节点”的方案会破坏边、布局和可读性。
- Browse 的用户期待和浏览器安全模型冲突。浏览器不能给后端绝对路径，但用户看到 Browse 会自然以为可以直接选项目父目录。
- Submit 能力迁移跨多个入口：Genesis wizard、Rerun panel、Draft editor、旧 `/submit` fallback。很容易某个模型家族漏掉参数或参数名不一致。

---

## 3. 后期维护要重点关注的关键组件

### 3.1 `WorkbenchRouteContainer.tsx`

路径：`frontend/src/workbench/WorkbenchRouteContainer.tsx`

它现在是 v1.6.8 最大承重容器：

- 取项目 forest：`useForestData(projectRoot)`，`130-132`
- legacy deep-link probe：`171-202`
- newest head / resolved run：`150-161`
- merge active drafts into graph model：`204-212`
- hydrate unexecuted drafts：`218-253`
- pending genesis execution polling：`296-320`
- legacy fallback：`326-341`
- empty / draft-only / graph shell 分流：`343-617`
- `ProjectRootProvider`：`609-615`

维护风险：这里已经承担 route、data fetching、draft registry、legacy fallback、genesis execution、rerun、shell composition。Claude review 应优先考虑是否拆分，但不要在没有测试护栏时大拆。

建议拆分方向：

- `useGenesisDraftLifecycle(projectRoot, registry, refetch)`
- `useLegacyFocusProbe(projectRoot, focusRunId, forest)`
- `WorkbenchBodyRouter` 或 `ProjectGraphShell`
- 保留 `ForestWorkbench` 只做 orchestration。

### 3.2 `GenesisWizard.tsx`

路径：`frontend/src/lineage/drafts/GenesisWizard.tsx`

职责：

- 文件预览、upload、create genesis draft：`213-240`
- resume draft：`154-176`、`242-251`
- table patch：`253-278`
- model params mapping：`280-363`
- save model validation：`379-406`
- validate/execute：`408-439`
- UI controls：`478-699`

维护风险：它复用了很多 legacy RunForm controls，但本身没有 schema-driven 表单系统。每新增模型家族，都必须同步 `modelParams()`、UI 控件、测试、后端执行参数。

### 3.3 `mergeDraftsIntoModel.ts`

路径：`frontend/src/lineage/drafts/mergeDraftsIntoModel.ts`

职责：

- 旧 rerun-child draft：锚定 source node 注入 draft model node。
- genesis draft：无父三节点岛注入 graph。

关键代码：

- genesis 判断：`46-48`
- genesis draft node：`71-87`
- genesis merge：`89-106`
- mixed merge loop：`108-135`

维护风险：这是“draft 世界”和“immutable forest 世界”的边界。任何图内新建链、拖放建链、multi-node draft 都会先撞这里。

### 3.4 `GraphCanvas.tsx` + `folding.ts`

路径：

- `frontend/src/lineage/graph/GraphCanvas.tsx`
- `frontend/src/lineage/folding.ts`

职责：

- variable folding / expanded group rendering
- React Flow layout seed
- selection / focus / search decorations
- edge suppression / role edge styling

维护风险：这是最容易肉眼回归的区域。单测能证明数据映射，但证明不了“画布好用”。变量多、缩放、横竖布局切换、drawer selection 需要 browser/screenshot 验证。

### 3.5 `ProjectRootContext.tsx`

路径：`frontend/src/workbench/ProjectRootContext.tsx`

职责：让 slug route 下的深层组件不要依赖 `?project_root=`.

维护规则：

- 新组件如果需要 project root，优先从 prop 或 `useProjectRootOptional()` 取。
- 只有 legacy route / fallback 才读 `?project_root=`.
- 不要在深层组件硬解 slug，slug decode 应保持 route 层职责。

### 3.6 `CreateProjectModal.tsx`

路径：`frontend/src/launcher/CreateProjectModal.tsx`

职责：Launcher 和 topbar project switcher 复用的新建项目 modal。

维护风险：

- Browse 只能做辅助提示，不能伪造 parent path。
- Parent folder 是后端可访问路径，不是浏览器相对路径。
- 创建失败 `[HTTP 500]` 要转成用户可理解文案，最好在后端也返回结构化原因。

---

## 4. 当前最脆弱的部分

### 4.1 最脆弱：Variables 聚合展开态

原因：

- 它把“可选择具体变量”和“只给 React Flow 一个聚合节点”混在一起。
- `selectedNodeId` 可能是隐藏成员，实际可见节点是 group。
- 边也必须用 `memberToGroup` 映射，否则选中成员时边不会亮。
- 大变量数下高度目前是 `Math.min(460, 72 + ceil(n/2)*54)`，这只是止血。

重点 review：

- 点击内部变量后 DetailDrawer 是否显示具体变量，而不是 group。
- 点击 header 是否只 collapse，不误触成员。
- 横向/纵向 layout 后 edge handles 是否仍自然。
- 变量 50+ 时是否需要滚动、搜索、虚拟列表。

### 4.2 Genesis wizard 的模型参数映射

原因：

- `modelParams()` 是手写 if/else。
- 旧 Submit 的能力多，且不同模型家族字段名不同。
- dCDH/CS/DID/IV/prediction/focal/covariance 的交互容易互相污染。

重点 review：

- `dcdh` 中 cluster var 是否应从 `x` 中排除。当前测试期望 `x` 保留 `market`，因为 legacy Submit 只排除 entity/time/treatment path，不排除 cluster。
- DID / CS / SA 的 covariance 是否应完全不发。当前 `!isDID && !usesCsParams && !isDcdh` 才发 covariance。
- `focal_x` 当前对 IV/DID/dCDH 不发，避免结构角色冲突。
- resume draft 只恢复部分字段：目前恢复 y/x/focal/model_type，但 IV/DID/CS/dCDH/prediction 的 UI state 是否完整恢复，需要 review。

### 4.3 Browse 与 project create

原因：

- 用户直觉认为 Browse 选目录就能创建项目。
- 浏览器不给绝对路径，后端又必须拿绝对 parent。
- 当前方案是 warning + 手输 parent，产品体验仍不理想。

可行升级见 §5。

### 4.4 Runs rail / history

用户明确指出 smoke 后 `RUNS` 没有历史记录。当前我没有把这个闭环证明掉。

重点 review：

- `RunHistoryRail` 是否仍从 `/runs?project_root=` 取全项目 history，而不是 graph heads。
- `projectRoot` 是否从 context 传到 rail。
- Genesis execute 后是否 `refetch()` forest 但没有刷新 run history。
- rail 是否挂在当前 shell，empty/draft-only 状态是否隐藏了 rail。

### 4.5 Home / Launcher 产品定位

当前代码上 `/` 是 Launcher，`/p/:slug/graph` 是 Workbench 项目主页。用户问“既然可以在 workbench 新建项目，那 home 页面意义何在？”这不是纯 bug，是产品结构问题。

需要 review/设计：

- Home 是否改名为 Project Launcher / Recent Projects。
- Workbench 顶栏“新建项目”是否只作为 switcher 入口，而非替代 Home。
- 新建项目成功后是否应直接打开 Genesis wizard。
- `/` 是否应展示最近项目 + create，并明显不是 marketing home。

---

## 5. 后续可升级方向

### 5.1 Project creation：从路径手输升级成受控工作区

当前：用户输入 Parent folder，Browse 只能辅助。

可升级：

- 后端配置一个默认 workspace root，例如 `WORKBENCH_PROJECTS_DIR`。
- 前端新建项目只输入 name，默认建在 workspace root。
- Browse 仅用于导入已有项目或选择数据文件，而不是选择 parent path。
- 后端提供 `/projects` registry，Launcher 不再靠 localStorage recents。

### 5.2 Genesis wizard：从手写表单升级成 schema-driven

当前：`modelParams()` 手写，UI 控件手动挂。

可升级：

- 后端 `/capabilities` 提供每个 model family 的 required/optional roles、params、constraints。
- 前端根据 schema 渲染 controls。
- `modelParams()` 变成 `buildParamsFromSchema(formState, schema)`。
- Draft editor、Genesis wizard、Rerun panel 共用同一套 form schema。

### 5.3 Variables：从聚合卡片升级成变量浏览器

当前：group panel 内部卡片，最多 460px 高。

可升级：

- 面板内搜索/filter/sort。
- role 分组 tabs：Y / focal / controls / instruments / dropped。
- 大变量数虚拟列表。
- 点击变量只切 drawer detail，不 collapse group。
- group panel 右侧提供 “pin selected variable” 或 “show only selected role”。

### 5.4 Workbench container 拆分

当前：`WorkbenchRouteContainer.tsx` 承担过多。

可升级：

- 把 legacy probe、genesis lifecycle、draft registry actions、pending focus 拆成 hooks。
- 建立 integration tests 钉住 route behavior 后再拆。
- 每个 hook 单测错误路径和 unmount cancellation。

### 5.5 Smoke harness

当前：主要靠 Vitest/Pytest；browser smoke 依赖人工。

可升级：

- Playwright smoke：创建项目、上传 xlsx、多 sheet、Genesis execute、Variables 展开、fork draft。
- 生成固定 heavy dataset fixture。
- 自动截图并做关键 DOM/assertion。
- 每次 v1.6.x closeout 必跑。

---

## 6. 眼下我最没有把握的事情

### 6.1 Variables 在真实浏览器里的视觉和交互

单测证明了数据结构和点击行为，但没证明视觉体验。React Flow、CSS、缩放、drawer、layout 都需要浏览器实测。尤其是变量很多时，面板是否仍可读、是否遮挡、是否滚动自然，我没有把握。

### 6.2 Genesis wizard 的全模型真实执行

我补了参数映射和测试，但没有用真实数据逐个跑 `panel_ols`、`iv_2sls`、`did`、`cs_did`、`sa_did`、`dcdh`、prediction。最可能漏的是某个字段名 legacy Submit 接受，但 draft execute 到 `_submit_run` 后路径不完全一致。

### 6.3 Runs history 为空的根因

我没有重新 browser smoke。可能是 `RunHistoryRail` 没刷新，可能是 Workbench shell 当前视图没挂 rail，可能是用户看的 RUNS 是另一个组件，不能只凭代码判断。

### 6.4 Browse 的产品接受度

技术上不能获取绝对路径，所以我选择 warning + 手输 parent。用户可能仍会认为 Browse 应该完成路径选择。这需要产品层决定：要么接受受限 Browse，要么后端引入 default workspace/project registry。

### 6.5 Home/Workbench 信息架构

代码能解释 `/` 和 `/p/:slug/graph` 的区别，但用户的疑问说明产品心智没有建立。这个需要 UX 设计，不是 patch 几个 button 就能彻底解决。

---

## 7. 关于当前情况，用户最大的遗漏可能是什么

这里说“遗漏”不是指用户错，而是当前系统的隐性风险容易被 UI bug 掩盖。

### 7.1 新 Genesis 不是旧 Submit 的皮肤，而是执行模型变了

旧 Submit 是一次性 `POST /runs` 表单。新 Genesis 是 upload -> draft -> patch nodes -> validate -> execute。它带来可续传、可视化、可审计，但也意味着旧 Submit 的每个字段都必须重新映射到 draft params。漏一个字段不会马上在 UI 爆炸，可能只会在执行结果里偏移。

### 7.2 `projectRoot` 是整个新路由体系的地基

slug route 让 URL 漂亮了，但任何深层组件只要还读 `?project_root=` 就会坏。这个问题会表现成“某个菜单没反应”“fork 消失”“table 空”，而不是清晰报错。

### 7.3 当前单测绿不等于可发布

这次已经有完整 Vitest/Pytest/tsc 通过，但用户发现的问题大多是 browser interaction / UX / route composition 问题。下一步 review 必须做真机 smoke，不然会继续漏。

### 7.4 Home 与项目注册表是缺失的产品层

当前 Launcher 的 recents 仍偏前端 localStorage；项目 root 仍是文件系统路径。只要没有后端 project registry，Home、Browse、新建项目、最近项目都会显得割裂。

### 7.5 fork “没有了”可能是 discoverability，不一定只是代码坏

即使 projectRoot 修好，用户也可能找不到 fork，因为功能埋在 node detail drawer/header menu 或 Rerun section。需要 review 真实交互路径，而不是只测菜单 item 存在。

---

## 8. Claude 接手建议顺序

### Step 1：只读确认

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.6.8
git status --short
git log --oneline -8
git diff --stat
```

确认：工作树 dirty，且不是旧 handoff 的 T11 停止点。

### Step 2：review 当前未提交 diff

优先看：

```bash
git diff -- frontend/src/workbench/WorkbenchRouteContainer.tsx
git diff -- frontend/src/lineage/drafts/GenesisWizard.tsx
git diff -- frontend/src/lineage/graph/GraphCanvas.tsx
git diff -- frontend/src/launcher/CreateProjectModal.tsx
git diff -- frontend/src/workbench/ProjectRootContext.tsx
```

Review 目标：

- 不要先美化。
- 先找行为回归、隐式状态错位、projectRoot 丢失、execute 后状态不刷新、selection/edge 不一致。

### Step 3：跑当前自动化

已在本 handoff 前跑过，但 Claude 接手应重新跑：

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.6.8/frontend
npx vitest run
npx tsc -p tsconfig.json --noEmit
```

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.6.8
PYTHONPATH=backend LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python -m pytest tests/test_api.py
```

### Step 4：做 browser smoke

必须覆盖：

- `/` Launcher 打开。
- 新建项目 modal：按钮不越界；Browse 出 warning；手输 parent 后 create 不 500。
- 新建项目成功后进入 Workbench，并能打开 Genesis wizard。
- 多 sheet xlsx：sheet selector 工作。
- Genesis 选 y/x、模型参数，run 成功。
- run 成功后 RUNS/rail/history 可见。
- Variables 展开：边不丢；点击内部变量 drawer 显示变量；再次 collapse 不误选。
- fork：从一个模型节点找到 fork/rerun draft 入口，确认 projectRoot 正确、draft 出现在图内。

### Step 5：再决定是否重构

如果 browser smoke 仍有行为 bug，先修 bug。等关键路径稳定后，再拆 `WorkbenchRouteContainer` 和 `GenesisWizard`。不要先大重构，否则会把现在的产品问题藏进更大 diff。

---

## 9. 当前自动化验证证据

本 handoff 写入前，当前工作树已跑过：

- `cd frontend && npx vitest run`
  - 结果：103 test files passed，906 tests passed。
  - 有 React Router future flag warning 和既有 act warning；未导致失败。
- `cd frontend && npx tsc -p tsconfig.json --noEmit`
  - 结果：exit 0。
- `PYTHONPATH=backend LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python -m pytest tests/test_api.py`
  - 结果：34 passed，1 Starlette deprecation warning。

注意：这些不是 browser smoke。不要把它们说成“用户路径已验证”。

---

## 10. 是否需要更多信息或补充

需要，建议向用户拿或现场确认：

- 用户认为 Home 应承担什么：项目列表、最近项目、模板入口、还是完全并入 Workbench？
- 用户期待 Browse 到底选择什么：项目父目录、项目目录、还是数据集目录？
- 用户最常用的多表数据格式：Excel 多 sheet、CSV + metadata、还是文件夹数据包？
- Variables 最常见规模：10、50、200、1000 个变量？这决定面板用 grid、虚拟列表还是搜索优先。
- fork 在产品语言里应叫 Fork、Rerun、Edit from here，还是 “复制此节点并修改”？
- 是否允许引入后端 project registry / default workspace root。如果允许，Home/Browse/New Project 可以根治；如果不允许，只能继续做路径输入和 warning。

---

## 11. 最短结论给 Claude

当前版本不是没做完，而是到了“功能大体拼上、交互债暴露”的阶段。请先 review 未提交 diff，再做 browser smoke；最需要盯的是 `projectRoot` 传播、Variables 聚合选择/边、Genesis 参数语义、Runs history 刷新和 Browse 的产品边界。自动化绿不代表可发布，当前还缺用户路径级验证。
