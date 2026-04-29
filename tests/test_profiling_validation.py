import pandas as pd

from workbench.config import WorkbenchConfig
from workbench.domain import Severity
from workbench.profiling import profile_frame
from workbench.validation import has_blockers, validate_profile


def _assert_json_safe(value):
    if isinstance(value, dict):
        for item in value.values():
            _assert_json_safe(item)
    elif isinstance(value, list):
        for item in value:
            _assert_json_safe(item)
    elif isinstance(value, float):
        assert pd.notna(value)


def test_profile_frame_records_missing_and_correlation():
    frame = pd.DataFrame(
        {"x": [1.0, 2.0, None], "y": [2.0, 4.0, 6.0], "group": ["a", "b", "b"]}
    )
    profile = profile_frame(frame)
    assert profile["row_count"] == 3
    assert profile["columns"]["x"]["missing_rate"] == 1 / 3
    assert profile["columns"]["x"]["unique_count"] == 2
    assert profile["columns"]["x"]["unique_ratio"] == 2 / 3
    assert profile["columns"]["x"]["mean"] == 1.5
    assert "x" in profile["correlations"]
    assert profile["correlations"]["x"]["y"] == 1.0


def test_profile_frame_keeps_undefined_numeric_stats_json_safe():
    frame = pd.DataFrame(
        {
            "nullable_count": pd.Series([1], dtype="Int64"),
            "empty_value": pd.Series([None], dtype="Float64"),
        }
    )

    profile = profile_frame(frame)

    assert profile["columns"]["nullable_count"]["mean"] == 1.0
    assert profile["columns"]["nullable_count"]["std"] is None
    assert profile["columns"]["empty_value"]["mean"] is None
    assert profile["columns"]["empty_value"]["std"] is None
    assert profile["correlations"]["nullable_count"]["empty_value"] is None
    _assert_json_safe(profile)


def test_profile_frame_empty_columns_have_json_safe_missing_rate():
    frame = pd.DataFrame({"x": pd.Series([], dtype="float64")})

    profile = profile_frame(frame)

    assert profile["columns"]["x"]["missing_rate"] == 0.0
    assert profile["columns"]["x"]["std"] is None
    assert profile["correlations"]["x"]["x"] is None
    _assert_json_safe(profile)


def test_validation_flags_missing_rate_warning():
    frame = pd.DataFrame({"x": [None, None, 3.0], "y": [1.0, 2.0, 3.0]})
    profile = profile_frame(frame)
    issues = validate_profile(
        profile, WorkbenchConfig(max_missing_rate=0.4, min_model_n=2)
    )
    assert any(
        issue.severity == Severity.WARNING and issue.code == "HIGH_MISSING_RATE"
        for issue in issues
    )


def test_validation_flags_insufficient_sample_blocker():
    profile = profile_frame(pd.DataFrame({"x": [1.0, 2.0]}))

    issues = validate_profile(profile, WorkbenchConfig(min_model_n=3))

    assert any(
        issue.severity == Severity.BLOCKER and issue.code == "INSUFFICIENT_SAMPLE"
        for issue in issues
    )
    assert has_blockers(issues)
