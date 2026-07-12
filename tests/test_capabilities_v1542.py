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


def test_covariance_default_is_explicitly_flagged():
    # U3 (v1.6.11): exactly one covariance option carries default=True, so
    # reordering COVARIANCE_UI can never silently change the default standard
    # error (the frontend reads this flag, never options[0]).
    caps = build_capabilities()
    defaults = [c["key"] for c in caps["covariance_options"] if c.get("default")]
    assert defaults == ["robust"]


def test_covariance_default_single_sources_the_model_param_value():
    # The exposed default flag and the model param's `value` derive from one
    # source (_COVARIANCE_DEFAULT), so they cannot drift apart.
    from workbench.engine.capabilities import _COMMON_MODEL_PARAMS, _COVARIANCE_DEFAULT

    cov = next(p for p in _COMMON_MODEL_PARAMS if p["key"] == "covariance")
    assert cov["value"] == _COVARIANCE_DEFAULT == "robust"


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
