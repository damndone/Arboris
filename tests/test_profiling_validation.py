import pandas as pd

from workbench.config import WorkbenchConfig
from workbench.domain import Severity
from workbench.profiling import profile_frame
from workbench.validation import validate_profile


def test_profile_frame_records_missing_and_correlation():
    frame = pd.DataFrame(
        {"x": [1.0, 2.0, None], "y": [2.0, 4.0, 6.0], "group": ["a", "b", "b"]}
    )
    profile = profile_frame(frame)
    assert profile["row_count"] == 3
    assert profile["columns"]["x"]["missing_rate"] == 1 / 3
    assert "x" in profile["correlations"]


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
