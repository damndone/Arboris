import pandas as pd


def test_did_handler_registered():
    """The did handler is registered in the model registry (explicit-only)."""
    from workbench.engine.stages import estimation  # ensures CORE_PACK registered
    from workbench.engine.registry import MODEL_REGISTRY
    assert "did" in MODEL_REGISTRY


def test_did_is_explicit_only_not_a_ytype_default():
    """An auto continuous run must NOT resolve to did (did is explicit-only)."""
    from workbench.engine.stages.estimation import CORE_PACK
    assert "did" not in CORE_PACK.defaults_by_y_type.values()


def test_orchestrator_reexports_run_did():
    """_fit_did calls _orch().run_did, so it must be reachable on the orchestrator."""
    from workbench import orchestrator
    assert hasattr(orchestrator, "run_did")
