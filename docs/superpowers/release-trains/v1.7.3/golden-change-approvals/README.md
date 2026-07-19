# v1.7.3 LMM Golden 变更审批记录

Feature Lane 不能修改 golden。Evaluation 可以提出请求，但不能批准自己的请求；Integration 只能在独立审批记录和新的候选 Evidence Manifest 都存在后合并 golden 更新。

每一个拟议 golden 变更必须创建一个独立、不可覆写的记录，并且完整填写以下事实：

- request id
- target file and test
- old value or old artifact SHA-256
- proposed value or proposed artifact SHA-256
- fixture path and fixture SHA-256
- cause classified as `contract change`、`verified bug fix` 或 `numerical environment change`
- candidate commit
- independent evaluator commit
- reviewer identity and approval timestamp

记录还必须包含实际复现命令、退出码、持续时间、非 secret 输出 artifact hash，以及说明为什么 canonical fixture 未被改写。若任一字段未知、候选 SHA 不精确、审核人就是请求的独立评估者，或 protected-file audit 失败，则请求不得批准。

若没有必要更新 golden，本目录只保留本说明；不要创建含占位 SHA、`TBD` 或虚构成功结果的记录。
