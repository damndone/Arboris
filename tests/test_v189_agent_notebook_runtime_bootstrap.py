from __future__ import annotations


def test_runtime_bootstrap_module_exposes_builtin_composition() -> None:
    from workbench.agent.runtime_bootstrap import compose_builtin_agent_notebook_runtime

    assert callable(compose_builtin_agent_notebook_runtime)
