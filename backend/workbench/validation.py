from __future__ import annotations

from .config import WorkbenchConfig
from .domain import GuardrailIssue, Severity


def validate_profile(profile: dict, config: WorkbenchConfig) -> list[GuardrailIssue]:
    issues: list[GuardrailIssue] = []
    if profile["row_count"] < config.min_model_n:
        issues.append(
            GuardrailIssue(
                Severity.BLOCKER,
                "INSUFFICIENT_SAMPLE",
                "Sample size is below the configured modeling minimum.",
                {"row_count": profile["row_count"]},
            )
        )
    for name, column in profile["columns"].items():
        if column["missing_rate"] > config.max_missing_rate:
            issues.append(
                GuardrailIssue(
                    Severity.WARNING,
                    "HIGH_MISSING_RATE",
                    f"Column {name} exceeds missing-rate threshold.",
                    {"column": name, "missing_rate": column["missing_rate"]},
                )
            )
    return issues


def has_blockers(issues: list[GuardrailIssue]) -> bool:
    return any(issue.severity == Severity.BLOCKER for issue in issues)
