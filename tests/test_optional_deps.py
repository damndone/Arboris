import pytest

from workbench.econometrics.optional_deps import (
    OptionalDependencyNotInstalled,
    optional_dependency_error,
    require_optional_dependency,
)


def test_optional_dependency_error_payload_is_actionable():
    payload = optional_dependency_error("panel", "linearmodels", "panel_ols")

    assert payload == {
        "error_code": "OPTIONAL_DEPENDENCY_MISSING",
        "step": "estimation",
        "engine": "linearmodels",
        "model_type": "panel_ols",
        "message": 'Install the panel extra to use panel_ols: pip install -e ".[panel]"',
        "details": {
            "extra": "panel",
            "package": "linearmodels",
            "install": 'pip install -e ".[panel]"',
        },
    }


def test_require_optional_dependency_raises_structured_error_for_missing_package():
    with pytest.raises(OptionalDependencyNotInstalled) as exc_info:
        require_optional_dependency(
            "definitely_missing_workbench_package",
            extra="panel",
            engine="definitely_missing_workbench_package",
            model_type="panel_ols",
        )

    payload = exc_info.value.to_issue_details()
    assert payload["error_code"] == "OPTIONAL_DEPENDENCY_MISSING"
    assert payload["model_type"] == "panel_ols"
    assert payload["details"]["extra"] == "panel"
