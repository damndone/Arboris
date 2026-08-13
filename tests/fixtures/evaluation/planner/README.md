# Planner evaluation fixtures

This directory contains evaluation-only data. It is never imported by
production planner code. Cases and expected operation identities are projected
from the live capability and workflow declarations at test or benchmark time.

The release runner accepts only an explicit `module:factory` provider. The
factory may expose `run_notebook(case)` for composition cases and
`run_agent_operation(case)` for direct cases, or return one callable used by
both drivers. The provider must return the normalized typed outcome (or a
`BenchmarkProviderResult` with usage metadata); credentials are never read
implicitly from the environment.
