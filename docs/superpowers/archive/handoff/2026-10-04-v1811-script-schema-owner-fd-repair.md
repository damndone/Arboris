# Schema sidecar 的 owner FD 读取修复

基线 `f2c844b4`，独立审查报告的 `schema-symlink_at_read` 为真实 P2：检查路径时是 owner 内普通文件，`Path.read_bytes` 真正读取时被换成 owner 外符号链接。字节解析修复没有完整关闭这项路径窗口。

主线先复现 `local/v1811-coordination/script-schema-owner-red.txt`：1 FAIL /4.24s，返回的 g dtype 由 int64 变为 outside schema 指定的 object。被换文件保留 rename，外部 schema、攻击项目和原独立证据均未删除。

现在 `_schema_bytes(project, run_id, relative)` 通过真实项目 admission FD 打开 runs、owner 和各层父目录，均 DIRECTORY/NOFOLLOW；叶文件 NOFOLLOW/NONBLOCK，fstat 必须为 singly linked regular file。不存在的叶文件仍表示没有可选 sidecar，父目录缺失、链接或非法文件明确拒绝。读取后核对所有持有目录的 inode，同一 raw JSON 用于类型恢复与 provenance SHA。没有修改旧 owner 记录或统计行为。

新测试在**实际叶文件 os.open 窗口**安装 outside symlink，断言命中窗口且拒绝；只给 builder 的 OS 绑定一个委托原实现的调度探针，项目 admission 的共享 OS 身份和目录打开函数保持真实。第一次新探针错误地 patch 全局 os.open，被 admission 更早拒绝，`script-schema-owner-green.txt` 61 PASS /1 FAIL（未命中断言），输出保留，不算这项验证通过。

- 修正探针后 `script-schema-owner-green-r02.txt`：62 PASS /25.79s，含原路径窗口、真实 FD 窗口、已验证字节读取、公共谱系、cast、原生后估计、FD/并发完整性与50节点预算。
- `script-schema-owner-tsc.txt`：TypeScript exit0；git diffcheck exit0。

本冻结提交将交原独立审查代理复验。未将作者测试算作独立通过；未 push/merge/tag/release/delete。
