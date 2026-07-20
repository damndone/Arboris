# Frozen Context Pack

Line: `wo-a-live-agent`
Baseline SHA: `0251f0a30d984bdbb2cfab404e6c646deab60cae`

## Objective
# WO-A live Agent integration objective

Expose the already implemented, read-only LMM public-result explanation and
recovery-advice recipe through the existing Agent capability/tool contract.
The tool must consume only `PublicModelResult` / bounded diagnostics from one
real run, never raw filesystem paths or persistence capabilities, and must not
create or apply a proposal.  It must make the browser Agent panel useful for a
completed local LMM run while preserving the existing no-LLM and malformed-run
failure behaviour.

## Boundary
- Affected paths: `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/recipes/lmm_public_result_view.py`, `backend/workbench/agent/recipes/builtin_declarations.py`, `tests/agent/test_lmm_public_result_view.py`, `tests/test_agent_context_tools.py`, `docs/superpowers/release-trains/v1.7.3/integration-foundation/wo-a-live-agent-objective.md`
- Allowed paths: `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/recipes/lmm_public_result_view.py`, `backend/workbench/agent/recipes/builtin_declarations.py`, `tests/agent/test_lmm_public_result_view.py`, `tests/test_agent_context_tools.py`, `docs/superpowers/release-trains/v1.7.3/integration-foundation/wo-a-live-agent-objective.md`
- Protected paths: none
- Dependencies: none
- Tests: none
- Known gates: `agent-lmm-smoke`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
