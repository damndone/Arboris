# 脚本公共导出浏览器局部验收

受验后端准确冻结 `522ca2ce`，localhost 8037；前端5196，代理指向8037。backend没有 reload，因此随后新增字节读取代码不属于此浏览器结论。没有关闭旧测试服务或删除项目。

可见新标签7，项目由真实 New project 表单创建：`local/v1811-script-browser/script-public-522ca2ce`。初始源和转换由正式 HTTP/data operation/workflow入口准备，仅使用 seed18111004 的800行合成 dta；不使用或外发 Downloads 私有数据。源 run `20261004_215927_660868_dd952f29`，真实 subset 400行、x*z feature、cluster(g) OLS run `20261004_215928_913421_51ca5d66`，Wald产物 `workflow_postestimation_wald_8de0a35a7ee37fd5_62761bd4ca5130987fb82b1c`。

## 实际可见检查

- 图上区分800行HC1源模型和400行clustered新模型；选中后者，面板显示真正run/model owner、cluster变量g。
- Analysis path 可选 Model only 或 Model and Wald test。选后者、勾 Require all steps to run natively、分别选Stata/R/Python并执行Export script。
- 六步均显示native：cleaning/subset/feature_recipe/cleaning/model.ols/postestimation.wald。R显示sandwich/stats，Python显示numpy/pandas/pyreadstat/scipy/statsmodels。切换语言清除旧覆盖结果和下载链接，再次生成对应语言owner产物。
- Light/Dark/System三档均真实切换，深色脚本表单、说明和链接可见；最后恢复System。工具截图已目检。此局部检查不认证整个应用的深色对比度；已有图面板问题保留BACKLOG，发布说明仍需列出。
- 真实点击Stata下载链接，得到`~/Downloads/script_export_stata_62644e9a405525c1c4c3244e.zip`；112707bytes，SHA `62644e9a405525c1c4c3244ed99fba2e045efb30ff60316a31d64f82e84f073a`与owner登记完全相同。只读该生成文件，没有改动其他Downloads文件。
- 在新ignored目录展开下载包并直接运行原始`analysis.do`，脚本未修改。Stata exit0、日志无r(error)，30条数字断言通过，脚本SHA `58e6e2bc7ccf73b9780ed3980356691a1862f1c5892f6699da994b9e5ea7dff8`。

## 持久证据与边界

`local/v1811-script-browser/browser-owner.json`、`browser-download-check.json`、`download-execution-7c41cd96c05a4d47a74fece0f3252e61/execution.json`及公开command output；原Stata完整日志0600保留。准备命令和服务输出在`local/v1811-coordination/script-browser-*-host.txt`，原sandbox localhost被拒输出同样保留。

CUA下载等待调用虽然给了15秒timeout，却实际约4小时后才返回；因此不以这一调用耗时衡量产品导出性能。产品服务性能证据是另行真实50节点打包基准。没有把截图目检称为已保存截图文件。

浏览器标签和服务保持存活，后续继续快照/require-native拒绝、复杂族、FPC/GLM-NB、自然语言Agent及发布前完整验收。本报告仅认证上述局部公开流程。
