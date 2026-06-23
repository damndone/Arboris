from workbench.engine.capabilities import build_capabilities


def test_manifest_exposes_new_groups():
    caps = build_capabilities()
    assert "prediction_models" in caps
    keys = {m["key"] for m in caps["prediction_models"]}
    assert {"prediction_lasso", "prediction_ridge", "prediction_random_forest"} <= keys

    assert "sampling_methods" in caps
    skeys = {s["key"] for s in caps["sampling_methods"]}
    assert {"smote", "oversample", "undersample"} <= skeys

    assert "covariance_options" in caps
    ckeys = {c["key"] for c in caps["covariance_options"]}
    assert {"robust", "clustered"} <= ckeys


def test_manifest_entries_have_labels():
    caps = build_capabilities()
    for group in ("prediction_models", "sampling_methods", "covariance_options"):
        for entry in caps[group]:
            assert entry.get("key") and entry.get("label")


def test_manifest_backward_compatible():
    caps = build_capabilities()
    assert caps["schema_version"] == 3
    assert any(m["key"] == "auto" for m in caps["model_types"])
    assert "imputation_methods" in caps


def test_prediction_ui_matches_backend():
    # Drift guard: the hardcoded manifest lists must stay in sync with the
    # backend's actual supported sets, else the UI silently omits a capability
    # (the exact UI/backend-gap class this version exists to close).
    from workbench.prediction import (
        _SUPPORTED_PREDICTION_MODEL_TYPES,
        _SUPPORTED_SAMPLING_METHODS,
    )

    caps = build_capabilities()
    assert {m["key"] for m in caps["prediction_models"]} == set(
        _SUPPORTED_PREDICTION_MODEL_TYPES
    )
    assert {s["key"] for s in caps["sampling_methods"]} == set(
        _SUPPORTED_SAMPLING_METHODS
    )
