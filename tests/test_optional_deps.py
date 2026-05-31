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


def test_require_optional_dependency_preserves_nested_missing_import(
    tmp_path, monkeypatch
):
    module_path = tmp_path / "broken_optional_module.py"
    module_path.write_text(
        "import definitely_missing_internal_dependency\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(ModuleNotFoundError) as exc_info:
        require_optional_dependency(
            "broken_optional_module",
            extra="panel",
            engine="broken_optional_module",
            model_type="panel_ols",
        )

    assert exc_info.value.name == "definitely_missing_internal_dependency"
