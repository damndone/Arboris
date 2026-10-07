"""Pure public-projection attacks; no fit or original asset is modified."""
import json
from workbench.agent.family_evidence import bounded_model_family_evidence


def test_ancillary_projection_limits_rows_strings_and_fields(tmp_path):
    rows = [{"name": "alpha" + "x" * 1000, "scale": "natural" + "x" * 1000,
             "estimate": .5, "std_error": .1, "conf_low": .2, "conf_high": .8,
             "raw_rows": list(range(100)), "unexpected": "private"} for _ in range(100)]
    value = bounded_model_family_evidence(tmp_path, [{"model_type": "negative_binomial",
        "alpha_estimated": True, "dispersion": "mean", "ancillary_parameters": rows,
        "overdispersion_test": {"statistic": -.01, "df": 1, "p_value": 1.,
                               "distribution": "chibar2(01)", "raw_rows": ["private"]}}])
    assert len(value["ancillary_parameters"]) == 4
    assert all(len(row["name"]) <= 128 and len(row["scale"]) <= 128 for row in value["ancillary_parameters"])
    assert "private" not in json.dumps(value)
    assert value["overdispersion_test"]["statistic"] == -.01
    json.dumps(value, allow_nan=False)


def test_projection_rejects_false_numeric_values_and_nonfinite_children(tmp_path):
    value = bounded_model_family_evidence(tmp_path, [{"model_type": "glm",
        "kernel_family": "glm:negative_binomial", "dispersion": "mean",
        "alpha_estimated": "true", "alpha_fixed_value": True,
        "ancillary_parameters": [{"name": "alpha", "estimate": float("inf"),
            "std_error": 10**1000, "conf_low": False, "conf_high": float("nan")}],
        "overdispersion_test": {"statistic": float("nan"), "p_value": True}}])
    assert value["alpha_estimated"] is None and value["alpha_fixed_value"] is None
    assert set(value["ancillary_parameters"][0]) == {"name"}
    assert not value["overdispersion_test"]
    json.dumps(value, allow_nan=False)
