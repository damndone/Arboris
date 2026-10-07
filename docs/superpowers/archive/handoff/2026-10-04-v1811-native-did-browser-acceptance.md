# 基础 DID 原生脚本：浏览器验收

冻结提交 `60203b15`，独立工作树 `codex-v1811-native-did-review`，backend 8039 / frontend 5198，无自动重载。可见隔离 tab 9。浏览器新建项目 `local/v1811-script-browser/native-did-60203b15`，通过真实 `/runs` 上传仓库合成 `tests/fixtures/panel_cluster/staggered.csv`，完成 owner `20261005_033055_668543_33035d32`。未访问 provider、Downloads 或修改旧 owner。

选中实际 `model:did_1` 节点，勾选 `Require all steps to run natively`，Stata、R、Python 都成功生成，并明确显示 `All steps run natively`：`data.cleaning`、`data.estimation_input`、`model.did` 均为 native。切换 Stata→R→Python 后旧覆盖表和下载链接被清空，重新导出显示对应依赖。

页面产物身份与 ZIP SHA：

| 语言 | artifact id | SHA-256 |
|---|---|---|
| Stata | script_export_stata_27b59a510556fff90501bf0d | 27b59a510556fff90501bf0d2b7d71be938a29a6411f65814a8b4b83e007a1b3 |
| R | script_export_r_3c6596a430a67d80f9d17db3 | 3c6596a430a67d80f9d17db386e0066c6d48ec2e7c656b16d8e94363c772cf6e |
| Python | script_export_python_d65342cea93edc51c16c4373 | d65342cea93edc51c16c43731ee90af32afbf1902ac6099d0727b8457340bdff |

从页面所示同一公共 artifact HTTP 入口取回实际 ZIP，原字节保存在 `local/v1811-script-browser/native-did-public-artifacts-60203b15/{stata,r,python}.zip`。本轮没有使用浏览器下载事件。运行副本加只读数值追踪，保留原末尾自检，Stata/R/Python 均 exit 0，各 18 项、合计 54 项比较；最大绝对差分别 `7.105427357601002e-14`、`7.105427357601002e-15`、`8.881784197001252e-16`。未修改生产数字、原参考或原容差。精确命令、输出与配对数字在各语言目录，汇总 `summary.json`。

1280×720 页面检查 Light/Dark/System 三档，最后恢复 System。导出面板可读，原图区域对比度欠账仍未修复，按 BACKLOG 要求在发布说明披露。没有宣称本轮覆盖其他窗口尺寸。完整截图 `local/v1811-script-browser/native-did-{stata,r,python,dark,light}-60203b15.jpg`。

服务、tab 与产物均保留。记录仅认证此冻结 DID 路径的真实界面生成与本机产物实跑；不替代新交付独立复审、正式 E、17 族真机 Agent、全量 live/chaos 或宿主 full gate。VIX 原参数 GAP 与三个待批准合入仍未关闭。
