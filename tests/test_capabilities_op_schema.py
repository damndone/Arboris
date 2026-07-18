# Importing these modules registers built-in model and imputation handlers.
import workbench.engine.stages.estimation  # noqa: F401
import workbench.engine.stages.imputation  # noqa: F401
from workbench.engine.capabilities import build_capabilities


def test_schema_version_bumped_to_3():
    assert build_capabilities()["schema_version"] == 3


def test_editable_stages_is_model_only():
    assert build_capabilities()["editable_stages"] == ["model"]


def test_each_model_type_has_schema_id_and_params():
    caps = build_capabilities()
    for entry in caps["model_types"]:
        if entry["key"] == "auto":
            continue
        assert entry["schema_id"] == f"{entry['key']}@v1"
        assert isinstance(entry["params"], list)


def test_iv_params_declare_roles_structurally():
    caps = build_capabilities()
    iv = next(e for e in caps["model_types"] if e["key"] == "iv_2sls")
    keys = {p["key"] for p in iv["params"]}
    assert {"model_type", "iv_endog", "iv_instruments", "covariance"} <= keys
    endog = next(p for p in iv["params"] if p["key"] == "iv_endog")
    assert endog["required"] is True and endog["role"] == "endog"


def test_model_params_expose_regressors_for_rerun_editing():
    caps = build_capabilities()
    ols = next(e for e in caps["model_types"] if e["key"] == "ols")
    regressors = next(p for p in ols["params"] if p["key"] == "x")
    assert regressors["kind"] == "columns"
    assert regressors["required"] is True
    assert regressors["role"] == "x"


def test_ols_cluster_variable_is_a_scalar_text_wire_field():
    caps = build_capabilities()
    ols = next(e for e in caps["model_types"] if e["key"] == "ols")
    cluster = next(p for p in ols["params"] if p["key"] == "entity_col")

    assert cluster["kind"] == "text"
    assert cluster["required"] is False
    assert cluster["role"] == "cluster"
