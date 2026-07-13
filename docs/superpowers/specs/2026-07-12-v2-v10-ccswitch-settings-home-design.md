# v1.6.12 V2/V10 CC Switch 风格设置与 Home 整合设计

**日期：** 2026-07-12
**状态：** 已获用户确认，待实现计划
**范围：** V2 LLM 设置、V10 Home 整合
**明确延期：** V11 数据清洗/异常值/类型覆写继续留在 v1.7

## 1. 背景与问题

当前 Workbench 的 LLM 能力已经可以通过 `/llm/chat` 使用，但用户只能通过环境变量配置供应商、API Key 和模型。现有 `GET /llm/config` 只有脱敏状态查询，Ask AI 标题上的 provider badge 也只是只读提示，无法完成切换或编辑。

当前 Home/Launcher 已有最近项目、新建项目和顶栏项目切换器，但 Home 仍是独立启动页，用户进入 Workbench 后无法在同一个工作区看到项目入口、LLM 供应商和设置。此前把这些局部骨架误记成 V2/V10 已完成，本设计把剩余功能重新定义为真实可用的收尾范围。

本设计借鉴 CC Switch 的可用交互模式：供应商列表、编辑供应商全屏页、折叠高级配置、模型列表获取、模型映射和脱敏配置预览；参考仓库为 [farion1231/cc-switch](https://github.com/farion1231/cc-switch/)。只复用适合 Workbench 的交互，不复制 Claude Code 专属协议字段或无关能力。

## 2. 目标与非目标

### 2.1 目标

1. 用户可以在 Workbench 内添加、编辑、切换、检测和删除多个 LLM 供应商。
2. API Key 由设置界面写入本机配置文件；接口和界面永不回显 Key 原文。
3. 用户可以获取供应商模型列表，也可以手动输入自定义模型。
4. 用户能看到当前模型的上下文窗口能力、当前 Ask AI packet 的大小、包含内容和截断边界。
5. 模型映射支持上下文窗口和“支持 1M”能力标记；1M 是真实保存的模型能力配置，不伪造 Anthropic 专属请求头。
6. Home 成为 Workbench 内的一个视图，集中展示最近项目、新建项目、当前 LLM 状态和设置入口。
7. 现有环境变量、`/llm/config`、`/submit` 深链接和已有 Graph/Table/Report 入口保持兼容。

### 2.2 非目标

- 不在本版实现 Anthropic 原生 Messages API adapter。
- 不在本版实现 Claude 的 Sonnet/Opus/Haiku 角色映射。
- 不在本版实现 Tool Search、工具执行或 v1.7 Agent Harness。
- 不在本版把完整数据集自动塞进 Ask AI；数据层 drill-down、清洗、异常值处理和类型覆写继续属于 v1.7/V11。
- 不提供任意请求 Header/Body JSON 覆盖，避免破坏 Workbench 固定的 OpenAI-compatible Chat Completions 契约。

## 3. 产品结构

### 3.1 入口

Workbench 顶栏增加设置入口；Workbench Home 内也有 LLM 供应商状态卡片和“管理供应商”入口。两处入口打开同一个供应商管理视图，避免出现两套配置逻辑。

供应商管理视图采用 CC Switch 风格的全屏工作区，而不是窄小弹窗：

```text
< 返回       LLM 供应商

[当前供应商列表]
  DeepSeek       已启用   deepseek-chat   编辑  检测  删除
  OpenAI         可用     gpt-4o          使用  编辑  检测  删除
  [+ 添加供应商]

点击添加/编辑后：

< 返回       编辑供应商                         [保存]
┌─────────────────────────────────────────────┐
│ 图标                                         │
│ 供应商名称                  备注              │
│ 官网链接                                     │
│ API Key（掩码/显示）                         │
│ 请求地址                         [连通性检测] │
│ [高级选项 ∨]                                 │
│   API 格式：OpenAI-compatible Chat Completions│
│   认证：Authorization: Bearer                │
│   请求超时                                   │
│ 模型映射                       [获取模型列表] │
│   显示名 | 实际模型 | 上下文窗口 | 支持 1M   │
│ 上下文说明                                   │
│ 脱敏配置预览                                 │
└─────────────────────────────────────────────┘
```

### 3.2 供应商列表

列表项必须直接表达当前状态，而不是让用户打开详情页猜：

- 供应商名称和图标；
- 当前启用/未启用状态；
- Base URL；
- 当前默认模型；
- API Key 已配置/未配置；
- 最近一次检测状态（未检测、可达、失败）；
- 操作：使用、编辑、复制、连通性检测、删除。

删除当前供应商时，如果仍有其他供应商，先切换到列表中的下一个可配置供应商并刷新状态；如果没有其他供应商，则回退到环境变量配置或显示未配置空态。删除操作必须有确认步骤。

### 3.3 编辑供应商页

视觉和交互采用 CC Switch 的结构：宽内容卡片、两列基本字段、全宽 URL 字段、密码框显示/隐藏、可折叠高级区、模型映射表、底部保存动作。现有 Workbench 的主题系统继续生效，组件使用 Workbench 的颜色 token，不直接引入 CC Switch 的 Tauri/shadcn 依赖。

适用于 Workbench 的字段：

| 区块 | 字段 | 语义 |
|---|---|---|
| 基本信息 | 图标、供应商名称、备注、官网链接 | 仅用于管理和识别，不参与请求 |
| 认证 | API Key | 掩码输入；编辑已有供应商时留空表示保持原值；显式清除需要单独动作 |
| 请求 | Base URL | 后端请求 `{base_url}/chat/completions` 和 `{base_url}/models` |
| 请求 | 连通性检测 | 优先探测模型列表端点，不发送真实 Ask AI 内容 |
| 高级 | API 格式 | 当前固定为 OpenAI-compatible Chat Completions；以可读的选择器呈现，为未来 adapter 留扩展位 |
| 高级 | 认证字段 | 当前固定为 `Authorization: Bearer`，不暴露 Claude 专属认证字段 |
| 高级 | 请求超时 | 对应现有 `WORKBENCH_LLM_TIMEOUT_S`，保存到供应商配置 |
| 模型 | 获取模型列表 | 从供应商的 `/models` 获取模型 ID；失败时保留手动输入能力 |
| 模型 | 默认模型 | Chat 和 Report 当前共用的默认模型 |
| 上下文 | 上下文窗口、支持 1M | 模型能力元数据，不伪造协议能力 |
| 预览 | 脱敏配置预览 | 展示 JSON 摘要，API Key 只显示占位符，不允许任意字段覆盖 |

### 3.4 1M 上下文语义

CC Switch 截图中的 1M 设置属于 Claude Code/供应商配置语义，不能直接复制成 Anthropic 请求头。Workbench 采用以下通用语义：

- 每个模型映射项保存 `context_window_tokens`，允许用户填写供应商文档声明的容量；
- `supports_1m` 是显式能力标记，列表和当前模型状态中可见；
- Ask AI 同时显示“模型声明容量”和“本次实际发送 packet 大小”，二者不能混淆；
- 当前 Ask AI 继续只发送安全摘要和有限 artifact preview；现有默认 artifact preview 总预算为 8,000 字符，V7 的按需 drill-down 和完整数据层扩展不在本版；
- 因此勾选 1M 不会自动发送完整数据，也不会暗示 Workbench 已经拥有 1M 数据访问能力；它让模型能力可配置、可见、可用于后续上下文预算演进。

### 3.5 Ask AI 上下文可见性

Ask AI 区块新增“Context summary”，与 CC Switch 的高级信息区保持同样的可展开层级感，但内容改为 Workbench 自己的上下文契约：

- packet version；
- 当前节点 kind/stage；
- context fingerprint；
- upstream path 是否包含；
- artifact 数量；
- packet 序列化字符数/字节数；
- safe preview 总预算；
- 当前 packet 是否发生字段、表格行列或 preview 截断；
- full dataset、full report、binary artifact 是否被排除。

Home 中没有选中节点时，只展示全局上下文策略和当前供应商模型容量，不展示虚构的节点大小。

## 4. 后端配置与接口

### 4.1 持久化模型

使用本机用户配置文件：

```text
~/.config/econometrics-workbench/llm-providers.json
```

文件结构版本为 `1`，逻辑上包含：

```json
{
  "version": 1,
  "active_provider_id": "deepseek",
  "providers": [
    {
      "id": "deepseek",
      "name": "DeepSeek",
      "website_url": "https://platform.deepseek.com",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-chat",
      "timeout_s": 60,
      "models": [
        {
          "display_name": "deepseek-chat",
          "request_model": "deepseek-chat",
          "context_window_tokens": null,
          "supports_1m": false
        }
      ]
    }
  ]
}
```

API Key 属于同一 provider 的内部 secret 字段，实际落盘但不出现在任何脱敏响应、日志、异常文本或配置预览中。写入使用临时文件 + 原子替换，并尽力设置文件权限 `600`；目录不存在时创建并限制为用户可访问。

现有环境变量兼容规则：

1. 存在本地供应商文件时，使用 `active_provider_id` 指向的供应商。
2. 没有本地供应商文件且 `WORKBENCH_LLM_BASE_URL`、`WORKBENCH_LLM_API_KEY`、`WORKBENCH_LLM_MODEL` 完整时，生成一个只读的“环境变量”虚拟供应商用于兼容现有部署。
3. 用户点击“保存为供应商”后，配置转为本地供应商，后续切换不要求重启。
4. 环境变量不会被设置页反向覆盖；本地配置只影响 Workbench 自己的 LLM adapter。

### 4.2 路由契约

保留现有 `GET /llm/config`，改为返回当前 active provider 的脱敏摘要，并增加 `provider_id`、`provider_name`、`source`、`context_window_tokens`、`supports_1m` 和上下文策略字段；不破坏现有 Ask AI badge 使用的字段。

新增供应商管理接口：

- `GET /llm/providers`：返回供应商脱敏列表和 active provider id；
- `POST /llm/providers`：创建供应商；API Key 只允许写入，不在响应中返回；
- `PUT /llm/providers/{provider_id}`：更新非空字段，空 API Key 默认保持原值；
- `POST /llm/providers/{provider_id}/activate`：切换当前供应商；
- `DELETE /llm/providers/{provider_id}`：删除供应商；
- `POST /llm/providers/{provider_id}/models/refresh`：使用已保存 Key 请求 `/models`，返回模型 ID 列表并更新缓存；
- `POST /llm/providers/{provider_id}/probe`：执行不产生模型回答的可达性/配置探测。

所有错误必须脱敏：不能回传 API Key、完整 Authorization header 或包含 Key 的上游错误 body。

### 4.3 请求边界

当前 adapter 继续使用 OpenAI-compatible Chat Completions：

```text
POST {base_url}/chat/completions
Authorization: Bearer <api_key>
{ "model": <request_model>, "messages": [...], "stream": false }
```

本版不实现 Anthropic 原生 Messages API。未来若要支持，需要新增显式 adapter 和协议能力测试，不能通过表单里增加一个字段伪装支持。

## 5. V10 Home 整合

### 5.1 Workbench Home 视图

在 Workbench shell 内增加 Home 视图，内容为：

- 最近项目列表：复用现有 localStorage recents、失效检测和移除逻辑；
- 当前项目卡片：继续进入当前项目森林图；
- 新建项目按钮：复用现有 `CreateProjectModal`，创建后直接进入创世向导；
- LLM 状态卡片：当前供应商、模型、Key 状态、上下文窗口、打开设置按钮；
- 设置入口：打开供应商管理页。

最近项目、新建项目和 LLM 卡片必须是独立小组件，Launcher 和 Workbench Home 共用，避免修复只落在一个入口。

### 5.2 路由行为

- `/p/:slug/graph?view=home`：显示当前项目的 Workbench Home；
- `/p/:slug/graph?view=graph` 或无 `view`：显示项目森林图；
- `/` 有最近项目时：进入最近项目的 `view=home`；
- `/` 没有最近项目时：显示无项目的首次 Home 空态，并提供新建项目；
- 现有 `/?home=1` 作为兼容入口，重定向到上述 `view=home` 语义；
- Home/Workbench 顶部导航不再通过跳出 Workbench shell 的方式切换；
- `/submit`、`/runs/:runId` 等旧深链接继续保留。

项目图、Table、Report 的 URL 和行为保持原有语义；Home 只负责工作台入口和项目管理，不替代森林图。

## 6. 错误与状态

### 6.1 设置错误

- Base URL 为空或不是合法 URL：字段内联错误，禁止保存；
- API Key 缺失：允许保存为未配置供应商，但状态明确显示未配置；
- 模型为空：禁止将该供应商设为 active；
- 文件写入失败：保留表单内容，显示无法保存的原因，不清空 Key；
- `/models` 不支持：显示“供应商未提供模型列表接口”，允许手动输入模型；
- 探测失败：显示可读错误分类和 HTTP 状态，不显示上游密钥或完整 body。

### 6.2 Home 错误

- 最近项目路径失效：卡片标记失效并提供移除；
- 最近项目打开探测中：禁用重复点击并显示打开中状态；
- 没有项目：显示新建项目 CTA，而不是空白或无限 loading；
- LLM 配置接口失败：Home 保留项目管理功能，LLM 卡片显示配置不可用。

## 7. 测试与验收

### 7.1 后端测试

- 配置文件不存在、存在、损坏时的读取和 env fallback；
- 多供应商创建、更新、激活、删除；
- API Key 永不出现在所有 GET 响应和错误响应；
- API Key 留空更新时保持原值，显式清除时才删除；
- 文件写入为原子替换并设置用户私有权限；
- `/models` 成功、401、404、超时和非标准 body；
- probe 不调用真实 chat completion；
- active provider 切换后下一次 `/llm/chat` 使用新配置；
- 1M/context window 字段正确保存和返回；
- 旧 `GET /llm/config` 字段保持兼容。

### 7.2 前端测试

- 供应商列表显示 active、Key 状态、模型和操作按钮；
- 编辑页基本字段、掩码 Key、显示/隐藏、留空保持、显式清除；
- 获取模型列表成功和失败状态；
- 模型映射支持默认模型、context window 和 1M 标记；
- 上下文摘要显示 packet 大小、截断边界和可见性声明；
- Home 显示最近项目、新建项目、LLM 状态卡片；
- Home/Workbench 内打开同一个供应商管理页；
- `/`、`/?home=1`、`?view=home` 和 `?view=graph` 路由行为；
- `/submit` 仍可访问，Graph/Table/Report 无回归。

### 7.3 真机验收

在真实浏览器中完成：

1. 从 Workbench Home 打开供应商管理；
2. 添加一个供应商并保存 API Key；
3. 关闭并重新打开设置，确认 Key 只显示已配置；
4. 获取模型列表或手动输入模型；
5. 切换 active provider；
6. 在 Ask AI 中确认 provider、模型和上下文摘要已更新；
7. 从 Home 打开最近项目、新建项目并进入创世向导；
8. 返回 Graph/Table/Report，确认视图和 URL 正常。

## 8. 文档收尾

实现和 gate 通过后，更新以下文档的真实状态：

- `docs/superpowers/followups/v1.6.9-followups.md`：V2/V10 标为完成并给出真实 commit/验证入口，V11 保持 v1.7；
- `docs/v1.6.12-release-notes.md`：改为描述可编辑供应商管理、模型映射、上下文可见性和 Workbench Home；
- `docs/superpowers/plans/`：补充执行计划和验证记录；
- 如旧 spec/handoff 仍声称 V2 只有只读 badge，改成链接到本设计和最终实现。

## 9. 验收结论

V2 只有在用户无需手动编辑 `WORKBENCH_LLM_*`、可以切换多个供应商、选择模型、看到 Key 状态和 Ask AI 上下文摘要，并且真机 Ask AI 使用新配置时才算完成。

V10 只有在 Home 的项目管理和 LLM 状态进入 Workbench shell、Home/Workbench 不再依赖跳出工作区的独立启动流程，同时旧深链接仍可用时才算完成。
