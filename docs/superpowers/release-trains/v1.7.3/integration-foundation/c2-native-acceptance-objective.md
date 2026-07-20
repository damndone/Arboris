# C2 Native Acceptance Objective

> **状态：长期路线图输入，不属于 v1.7.3 本机产品范围。** 2026-07-20
> 的本机收尾决定删除了未接入运行时的 C2 原型代码与专属测试。本文件只保存未来在
> 部署、App 封装、插件或外部模型包边界重新立项时需要重新审查的目标；不得据此声称
> 当前产品存在 C2 执行能力。

## Objective

Turn the existing C2 policy and fake-adapter test coverage into a bounded,
native macOS Seatbelt acceptance path for the exact v1.7.3 Integration
candidate. The parent must construct every command, require a fresh canary,
write the audit receipt, and remain the only possible source of an evaluator
verdict.

## Boundary

This line adds only a reviewed native C2 adapter, host identity/probe support,
trusted canary evidence, and collector integration after its reviewed manifest
is bound to one exact candidate SHA. It must keep C1 source-only refusal
intact. It must not weaken `code.execute`, add raw host-Python fallback, admit
caller commands, or make a C2 capability serializable/public.

## Acceptance

The real local Seatbelt canary proves all seven assertions and records an
audit receipt. The exact candidate uses the reviewed collector for bounded,
parent-verified evidence. Any failed canary, policy mismatch, unsupported host,
or malformed output remains non-passing with no fallback.
