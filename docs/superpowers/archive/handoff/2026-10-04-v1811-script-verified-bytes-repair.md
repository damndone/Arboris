# 已验证数据字节读取修复

基线 `522ca2ce`。本次只修复脚本 builder 的读取一致性，不更改任何统计口径、默认值或 oracle 容差。

## 问题与方案

builder 原先先读取并验证 owner 的原始文件/数据 artifact SHA，然后按同一路径第二次解析。两次读取之间替换路径，解析结果会与打包的 source 字节及 provenance digest 不符。真实失败测试在 `_Builder.record` 返回已验证字节的边界替换实际 owner 文件，分别覆盖 cleaned parquet 与原始 dta；旧代码读入新增列及改变后的 x。

修复直接以该次已验证字节的 BytesIO 解析。`tabular_io` 的同一个 CSV/Excel/parquet/pyreadstat 分发器增加显式格式的 binary stream 输入，文件路径调用行为不变。原始 ingestion 仍使用原有解析器、行数/Excel 页数限制、transpose、numeric datetime 规则和原始统计标签数值。没有为原生读取另存临时副本，没有新依赖、删除或清理。

数据 schema sidecar 只读取一次：同一 raw JSON 同时用于类型恢复、完整类型校验和 provenance digest；拒绝符号链接或逃逸 owner 的 sidecar。已有转换不成功时仍拒绝，未扩大类型容差。

## RED / GREEN

- `local/v1811-coordination/script-verified-bytes-red.txt`：6 FAIL /4.85s。四个相同解析器 binary stream 用例原先 TypeError，两项真实路径替换读入错误数据；探针命中实际验证边界。
- `script-verified-bytes-related-green.txt`：95 PASS /40.67s，含原四种 tabular 字节解析、上述两项替换、SPSS/Stata 文件真实运行、ingestion metadata、公共谱系、cast 接续、全部原生后估计及完整性回归。
- `script-verified-bytes-tsc.txt`：TypeScript exit 0；`git diff --check` exit 0。

这批读取修复尚待独立复验。

## 前一冻结交付的独立结果

`9dfcb907..522ca2ce` 已独立 **PASS**，审查提交 `fe3e4c8611da9963b86c4e9b6a6223c11ad979a4`。报告保留在 `.worktrees/codex-v1811-script-integrity-r2/docs/superpowers/handoffs/2026-10-04-v1811-script-owner-index-independent-recheck.md`。三项 P2 关闭；独立 99 项集成、五个真实索引 writer、动态异常引用及 LMM/predictive 共22额外检查通过；42次三语言原生执行、1026项数字自检通过；tsc通过，50节点完整导出0.370644秒。该结论只认证冻结522，不把本次新增字节读取代码计作独立通过。

复杂族路径、DID 内部列、待批准 adapter、自然语言 Agent 导出、17族 provider live、E、宿主 gate 与发版继续推进。
