# DID float 文本修复：新冻结版本浏览器验收

冻结生产 `cb296ba305cc1b3fe2cf0cf595d3bba5fc609a66`，服务从 `codex-v1811-native-did-r2-review` 启动，backend 8040 / frontend 5199，无重载。可见隔离 tab 10。

浏览器新建 `local/v1811-script-browser/native-did-float-cb296ba3`；仓库 `panel_cluster/staggered.csv` 只在本机副本中将 first_treat 改写为数值相同的 `N.0_0` 合法文本，原 fixture 未改。真实 `/runs` 完成 owner `20261005_034133_622208_b03e7096`。界面模型数字与原普通数字 cohort 相同，ATT 0.6821、SE 0.1637；精确值由实际模型及导出原自检核对，不从页面四舍五入值生成参考。

页面勾选 `Require all steps to run natively`，Stata/R/Python 均成功生成，覆盖表包含 cleaning、estimation_input、model.did 三个 native，语言切换清空旧结果与链接。Light/Dark/System 可以切换，最后恢复 System。既有对比度欠账未修复，发布草稿已披露。只检查 1280×720，不声称其他尺寸已验收。

## 实际公共产物

| 语言 | artifact id | ZIP SHA-256 | 数值自检 | 最大绝对差 |
|---|---|---|---|---|
| Stata | script_export_stata_f0668e43045de7432896eda1 | f0668e43045de7432896eda157ebd3b55e1862675ba5a5627fa7778ee6d41d9b | 18 passed | 7.105427357601002e-14 |
| R | script_export_r_272b63c058809e84a5f854e4 | 272b63c058809e84a5f854e45b7d57519e97326078daa2bbc7756127e77abf02 | 18 passed | 7.105427357601002e-15 |
| Python | script_export_python_71ab9d59a8b26fee89b0924e | 71ab9d59a8b26fee89b0924eac792ea0834fa9e70835ea4917be134492000692 | 18 passed | 8.881784197001252e-16 |

同一页面链接的公共 artifact HTTP 接口取回 ZIP，原字节保留在 `local/v1811-script-browser/native-did-float-public-artifacts-cb296ba3/{stata,r,python}.zip`，各语言运行副本仅加数值追踪，原 closing assertions 保留，均 exit 0。未使用浏览器下载事件，不混称浏览器下载实跑。命令、配对数值、程序日志与 `summary.json` 均在上述目录。

截图 `local/v1811-script-browser/native-did-float-{stata,r,python,dark,light}-cb296ba3.jpg`，服务和 tab 保留。旧 `60203b15` 普通场景的 PASS、随后发现的特殊文本 RED 都保留，未改写成新修复认证。

此次验收只认证所述冻结公共路径与实际产物，不替代独立新冻结复验、正式 E、17 族及全量 live/chaos、Claude 两次总审、宿主 full gate。VIX 参数 GAP 及三项待批准合入仍未关闭。
