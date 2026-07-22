"""Artifact contract construction and post-execution validation (spec §5).

Two rules shape everything here:

- Only dimensions the registry persists are checked (DEC-ART-001), and the
  result says so explicitly. "Artifacts fully validated" is a claim this version
  cannot make, so it is never made.
- `schema_ref` is refused at proposal time (§5.3). Accepting it and skipping the
  check would let a caller believe a payload was inspected.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from ...contracts.agent.notebook_option import (
    ARTIFACT_MATCH_DIMENSIONS,
    ArtifactContract,
    ExpectedArtifact,
)
from .errors import ArtifactNotDeclarable, ArtifactSchemaContractUnsupported
from .vocabulary import declared_type, is_declared

CONTRACT_PROFILE = "artifact-identity-type-count/v1"
NOT_EVALUATED_DIMENSIONS = ("payload_schema",)

PASSED = "passed"
PASSED_WITH_WARNINGS = "passed_with_warnings"
FAILED = "failed"

_UNSUPPORTED_EXPECTATION_KEYS = ("schema_ref", "schema", "payload_schema")


def build_artifact_contract(
    expectations: Iterable[ExpectedArtifact | Mapping[str, Any]],
) -> ArtifactContract:
    """Turn agent-supplied expectations into the locked contract, or refuse."""

    expected: list[ExpectedArtifact] = []
    for item in expectations:
        if isinstance(item, ExpectedArtifact):
            candidate = item
        else:
            unsupported = [key for key in _UNSUPPORTED_EXPECTATION_KEYS if key in item]
            if unsupported:
                raise ArtifactSchemaContractUnsupported(
                    "artifact expectations may not declare "
                    f"{', '.join(sorted(unsupported))}: v1.8.1 checks "
                    f"{', '.join(ARTIFACT_MATCH_DIMENSIONS)} only, and accepting a "
                    "payload-schema field without checking it would misrepresent "
                    "what was validated (spec §5.3)",
                    unsupported_fields=sorted(unsupported),
                )
            candidate = ExpectedArtifact(
                artifact_id=str(item["artifact_id"]),
                artifact_type=str(item["artifact_type"]),
                required=bool(item.get("required", True)),
                count=int(item.get("count", 1)),
                step=item.get("step"),
            )
        if candidate.required:
            _assert_declarable(candidate)
        expected.append(candidate)
    return ArtifactContract(expected=tuple(expected))


def _assert_declarable(candidate: ExpectedArtifact) -> None:
    if not is_declared(candidate.artifact_id):
        raise ArtifactNotDeclarable(
            f"{candidate.artifact_id!r} is not in the published artifact vocabulary, "
            "so it may not be declared required; an agent that can require an "
            "artifact nothing produces can fail a healthy run (spec §5.4)",
            artifact_id=candidate.artifact_id,
        )
    expected_type = declared_type(candidate.artifact_id)
    if candidate.artifact_type != expected_type:
        raise ArtifactNotDeclarable(
            f"{candidate.artifact_id!r} is declared as {expected_type!r}, not "
            f"{candidate.artifact_type!r}; a required expectation the system can "
            "never satisfy is not a contract",
            artifact_id=candidate.artifact_id,
            declared_artifact_type=expected_type,
        )


def _issue(code: str, severity: str, artifact_id: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "artifact_id": artifact_id,
        "detail": detail,
        **extra,
    }


def validate_produced_artifacts(
    contract: ArtifactContract,
    produced: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Match what a run registered against what the option promised.

    Returns the §5.4 shaped report. `validation_status` is separate from
    execution status on purpose: a model can fit perfectly and still not have
    produced the table the report layer would cite.
    """

    records = [dict(record) for record in produced]
    issues: list[dict[str, Any]] = []
    declared_ids = {item.artifact_id for item in contract.expected}

    for expectation in contract.expected:
        matches = [r for r in records if r.get("artifact_id") == expectation.artifact_id]
        if not matches:
            if expectation.required:
                issues.append(
                    _issue(
                        "ARTIFACT_REQUIRED_MISSING",
                        "blocking",
                        expectation.artifact_id,
                        f"required artifact {expectation.artifact_id} was not registered",
                    )
                )
            else:
                issues.append(
                    _issue(
                        "ARTIFACT_OPTIONAL_MISSING",
                        "warning",
                        expectation.artifact_id,
                        f"optional artifact {expectation.artifact_id} was not registered",
                    )
                )
            continue

        wrong_type = sorted(
            {
                str(r.get("artifact_type"))
                for r in matches
                if r.get("artifact_type") != expectation.artifact_type
            }
        )
        if wrong_type:
            issues.append(
                _issue(
                    "ARTIFACT_TYPE_MISMATCH",
                    "blocking",
                    expectation.artifact_id,
                    f"expected artifact_type {expectation.artifact_type!r}, "
                    f"found {', '.join(repr(t) for t in wrong_type)}",
                    expected_artifact_type=expectation.artifact_type,
                    observed_artifact_types=wrong_type,
                )
            )

        if expectation.step is not None:
            wrong_step = sorted(
                {str(r.get("step")) for r in matches if r.get("step") != expectation.step}
            )
            if wrong_step:
                issues.append(
                    _issue(
                        "ARTIFACT_STEP_MISMATCH",
                        "blocking",
                        expectation.artifact_id,
                        f"expected step {expectation.step!r}, "
                        f"found {', '.join(repr(s) for s in wrong_step)}",
                        expected_step=expectation.step,
                        observed_steps=wrong_step,
                    )
                )
            in_scope = [r for r in matches if r.get("step") == expectation.step]
        else:
            in_scope = matches

        if len(in_scope) != expectation.count:
            issues.append(
                _issue(
                    "ARTIFACT_COUNT_MISMATCH",
                    "blocking",
                    expectation.artifact_id,
                    f"expected {expectation.count} instance(s), found {len(in_scope)}",
                    expected_count=expectation.count,
                    observed_count=len(in_scope),
                )
            )

    undeclared = Counter(
        str(r.get("artifact_id")) for r in records if r.get("artifact_id") not in declared_ids
    )
    for artifact_id, count in sorted(undeclared.items()):
        issues.append(
            _issue(
                "ARTIFACT_UNDECLARED",
                "informational",
                artifact_id,
                f"{count} artifact(s) not named by the contract were registered",
                observed_count=count,
            )
        )

    severities = {issue["severity"] for issue in issues}
    if "blocking" in severities:
        status = FAILED
    elif "warning" in severities:
        status = PASSED_WITH_WARNINGS
    else:
        status = PASSED

    return {
        "contract_profile": CONTRACT_PROFILE,
        "validation_status": status,
        "checked_dimensions": list(ARTIFACT_MATCH_DIMENSIONS),
        "not_evaluated_dimensions": list(NOT_EVALUATED_DIMENSIONS),
        "issues": issues,
    }


COMMITTABLE_VALIDATION_STATUSES = frozenset({PASSED, PASSED_WITH_WARNINGS})


__all__ = [
    "COMMITTABLE_VALIDATION_STATUSES",
    "CONTRACT_PROFILE",
    "FAILED",
    "NOT_EVALUATED_DIMENSIONS",
    "PASSED",
    "PASSED_WITH_WARNINGS",
    "build_artifact_contract",
    "validate_produced_artifacts",
]
