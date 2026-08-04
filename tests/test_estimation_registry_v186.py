from __future__ import annotations

from workbench.engine.pack import AnalysisPack
from workbench.engine.registry import ModelHandler, ModelRegistryError
import workbench.engine.registry as registry
from workbench.engine.stages.estimation import CORE_PACK


def test_core_estimation_is_an_explicit_appendable_pack() -> None:
    handler_types = {handler.model_type for handler in CORE_PACK.model_handlers}

    assert {"ols", "logit", "panel_ols"} <= handler_types
    assert CORE_PACK.defaults_by_y_type["continuous"] == "ols"
    assert all(callable(handler.fit) for handler in CORE_PACK.model_handlers)


def test_new_family_contract_can_be_declared_as_one_additive_handler() -> None:
    handler = ModelHandler(
        model_type="v186_test_family",
        model_id="v186_test_family_1",
        serves_y_types=("continuous",),
        fit=lambda context, env: ("v186_test_family_1", {}, None),
    )
    pack = AnalysisPack(pack_id="v186_test_family", model_handlers=[handler])

    assert [item.model_type for item in pack.model_handlers] == ["v186_test_family"]
    assert not pack.defaults_by_y_type


def test_registry_rejects_duplicate_model_handler_keys_instead_of_overwriting(monkeypatch) -> None:
    monkeypatch.setattr(registry, "MODEL_REGISTRY", {})
    handler = ModelHandler(
        model_type="v186_duplicate_guard",
        model_id="v186_duplicate_guard_1",
        serves_y_types=("continuous",),
        fit=lambda context, env: ("v186_duplicate_guard_1", {}, None),
    )

    registry.register_model(handler)

    try:
        registry.register_model(handler)
    except ModelRegistryError as error:
        assert "v186_duplicate_guard" in str(error)
    else:
        raise AssertionError("duplicate model handler registration must fail closed")
