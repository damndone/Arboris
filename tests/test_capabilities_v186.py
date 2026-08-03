from __future__ import annotations

from workbench.engine.capabilities import V186_MODEL_CAPABILITY_METADATA, build_capabilities


def test_v186_capability_manifest_declares_model_option_fields() -> None:
    payload = build_capabilities()
    entries = {entry["key"]: entry for entry in payload["model_types"]}

    for model_type, metadata in V186_MODEL_CAPABILITY_METADATA.items():
        entry = entries[model_type]
        assert entry["label"] == metadata["label"]
        assert entry["group"] == metadata["group"]
        params = {param["key"]: param for param in entry["params"]}
        assert {"model_type", "x", "model_options"} <= set(params)
        assert params["model_options"]["options"] == metadata["model_options_fields"]


def test_v186_capability_metadata_is_closed_and_has_four_families() -> None:
    assert set(V186_MODEL_CAPABILITY_METADATA) == {
        "ordinal_logit",
        "multinomial_logit",
        "survival_cox",
        "quantile_regression",
    }
    assert V186_MODEL_CAPABILITY_METADATA["survival_cox"]["model_options_required"] == [
        "event_column"
    ]
