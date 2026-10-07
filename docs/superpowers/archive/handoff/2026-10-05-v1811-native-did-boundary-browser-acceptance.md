# DID CSV / 浮点边界：新冻结浏览器及公共 ZIP 验收

冻结生产 `6fd4f43bb06d3b60b16507374be874fa4c265aea`，从 `codex-v1811-native-did-r3-review` 无重载启动 backend 8041 / frontend 5200，可见隔离 tab 11。浏览器创建两个新合成项目；通过真实公共 `/runs` 完成，并从页面选中真实模型生成导出，不调用任意手写 plan 代替公共路径。

- newline owner `20261005_040000_716444_c34b1288`：仓库 staggered.csv 的本机副本将 cohort 写成数值相等的 `N.0_0\n`，480 行。三语言 require_native=True 的 cleaning、estimation_input、model.did 全 native；语言切换清空旧结果及下载链接。R 明确显示 jsonlite/fixest/sandwich/stats 依赖。
- extreme owner `20261005_040108_747469_ec50b5cb`：只将首个正 cohort 改成合法有限 `1e308`，其余为原数值 underscore 文本。Workbench 实际拟合完成。Stata 普通与完全原生请求都在页面显示有限值超出全精度表示范围，没有下载链接或快照降级。R/Python 完全原生请求成功。
- Light/Dark/System 可以切换，最后恢复 System。截图中记录的两个实际尺寸为 1280×720（newline）和 1208×788（extreme），导出控件和提示可读；不声称其他尺寸。既有深色面板欠账保留 BACKLOG 与发布草稿披露。

## 实际公共产物

| 场景 | 语言 | artifact id | ZIP SHA-256 | 原数值检查 passed | 最大绝对差 |
|---|---|---|---|---|---|
| newline | stata | script_export_stata_3d6e1f7137d71544784df969 | 3d6e1f7137d71544784df9697252482d56d5b54cd8c7e21498779a479b05b6d9 | 18 | 7.1054273576010019e-14 |
| newline | r | script_export_r_362a106544d504d1cf7f6aa6 | 362a106544d504d1cf7f6aa6a78114312bc174c520adc9ce233aea7303862417 | 18 | 7.1054273576010019e-15 |
| newline | python | script_export_python_9e5cc38c7ab205e8d9390518 | 9e5cc38c7ab205e8d939051805b489fe59dcfa2ec7530e26b84cdce49d883c3c | 18 | 8.8817841970012523e-16 |
| extreme | r | script_export_r_91f22a7b041c9c5812b36e79 | 91f22a7b041c9c5812b36e79791b2cf974409e4b915a3046c4a80f7c8d62aeea | 18 | 8.5265128291212022e-14 |
| extreme | python | script_export_python_945538b8fd017dd778b041d1 | 945538b8fd017dd778b041d1248a30fdb152b4b9c9ff452c39a8a59ab6ddaf68 | 18 | 8.8817841970012523e-16 |

五份 ZIP 通过页面显示的公共 artifact HTTP 接口取回，原字节和 SHA 保留在 `local/v1811-script-browser/native-did-boundary-public-artifacts-6fd4f43b/{newline,extreme}/`。运行副本只加入追踪，保留原 closing assertions 与原容差，五次 exit 0，共 90 项数值自检通过。没有将 HTTP 取回冒称浏览器下载事件。原 fixture 未改，无 provider 调用或私有 Downloads 数据外发。

截图 `local/v1811-script-browser/native-did-boundary-{newline,extreme}-*-6fd4f43b.jpg`。服务和 tab 保留。

## 页面附带发现与修复

切换语言时旧成功结果清除，但极值 Stata 的旧 refusal 提示会在切到 R 后留到下一次请求；此为旧页面状态缺口。新测试覆盖语言/路径/require_native 三种切换，3 RED / 4 PASS 后限定修复为切换同时清除旧提示。修后组件 7 PASS、tsc 通过。此修复需要自身冻结页面跟进验收，不能用上述旧 frontend 的 PASS 代替。

独立新冻结后端复验正在进行。本报告不替代正式 E、17 族、全量 live/chaos、两次 Claude 总审、用户宿主 full gate。三项候选合入批准及 VIX omega 验收仍未关闭。
