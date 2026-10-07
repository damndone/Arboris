# 公共脚本执行参数与后估计选择入口

基线 2c76cd0e。新增 tests/test_script_export_executed_parameters.py：先保留 GLM 三种限定身份、三种权重及 target listing 的 7 项 RED，再实现；前端新增持久化后估计选择测试先 RED，再 GREEN。

完成的 owner 适配：显式 qualified wire 与 kernel 严格对应，证明后记录实际 family；旧 handler 没有 terminal payload 时，只有 sealed input 的精确显式 identity 才可使用，不猜 auto 的模型族。sampling/analysis/frequency 同时对照表单、结果包 executed 标记及 kernel，抽样参数读取已执行设计方法、df、lonely policy，并核对 strata/PSU/domain/FPC/weight。抽样协方差读取实际 kernel 的 survey variance，不读取此前 naive robust 记录。

HTTP 返回模型及该模型实际持久化的五类后估计目标身份，界面 Analysis path 选择器提交服务端身份；列表不含数字，最终导出仍做完整 owner/state/数字复算验证。

验证：
- 40 项真实公共 lineage 与参数测试 PASS /16.38s，script-executed-target-green2.txt。
- 新参数测试共18 PASS /12.93s：包括真实 GLM-binomial/poisson、analysis/frequency OLS 的三语言实跑12项，原S自检容差未改。script-executed-native-green.txt。
- 前端43 PASS，tsc exit0，script-target-ui-green.txt / script-target-ui-green-tsc.txt。
- Stata/R/Python 成功包含完整 beta、SE、nobs 自检；既有BIC/Starlette warnings未 suppress。

FPC/GLM-NB 统计 adapter 候选已独立复审通过，但仍等待用户合入批准；此交付不将旧snapshot覆盖算作新native PASS。其他族 covariance/原始特殊参数适配、型别转换路径、原生性能、浏览器、provider live、独立整体审查及gate仍未完成。跨候选旧 owner 探针发现拒绝包括旧diagnostic SHA及未持久化covariance，证据在ignored local/script-16-family-owner-probe.json；不会改写旧owner来让检查通过。
