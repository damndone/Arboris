"""Strict read-only projection of persisted LMM result packets."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import ContractError, PacketEnvelope
from workbench.contracts.model.linear_mixed_effects import LmmDiagnostic
from workbench.services.pinned_run_directory import PinnedRunDirectory, PinnedRunError


_INDEX_FIELDS = {"schema_version", "artifacts"}
_ARTIFACT_FIELDS = {
    "artifact_id",
    "path",
    "artifact_type",
    "step",
    "sha256",
    "inputs",
    "config_hash",
    "code_version",
}
_PAYLOAD_FIELDS = {
    "schema_version",
    "contract_version",
    "estimator_version",
    "model_id",
    "model_type",
    "engine",
    "fit_method",
    "converged",
    "status",
    "optimizer",
    "nobs",
    "n_groups",
    "observations_per_group",
    "excluded_rows",
    "exclusion_counts",
    "fixed_effects_formula",
    "random_effects_specification",
    "reference_group",
    "comparison_group",
    "result_identity",
    "primary_target_id",
    "coefficients",
    "random_effects",
    "diagnostics",
    "figure_context",
    "warnings",
    "execution_binding",
}
_EXECUTION_BINDING_FIELDS = {"schema_version", "run_id", "executed_input_digest"}
_COEFFICIENT_FIELDS = {
    "result_id",
    "label",
    "estimate",
    "std_error",
    "p_value",
    "confidence_interval",
    "confidence_level",
    "inference_method",
    "source_id",
}
_RANDOM_EFFECT_FIELDS = {
    "intercept_variance",
    "slope_variance",
    "covariance",
    "intercept_slope_covariance",
    "residual_variance",
    "n_groups",
    "observations_per_group",
}
_DIAGNOSTIC_FIELDS = {
    "code",
    "severity",
    "status",
    "evidence",
    "action_candidate",
}
_FIGURE_FIELDS = {"chart_type", "time", "groups"}
_FIGURE_GROUP_FIELDS = {"label", "observed_mean", "fitted_mean"}
_UNBALANCED_FIGURE_EVIDENCE_FIELDS = {
    "reason",
    "group_support",
    "first_nonshared_time",
}
_UNBALANCED_GROUP_SUPPORT_FIELDS = {"label", "observed_time_sha256"}
_TERMINAL_DIAGNOSTIC_CODES = frozenset(
    {
        "LMM_RANDOM_SLOPE_NEAR_ZERO",
        "LMM_RANDOM_EFFECTS_SINGULAR",
        "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME",
        "LMM_CONVERGENCE_FAILED",
        "LMM_UNEXPECTED_FIT_EXCEPTION",
    }
)
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RANDOM_SLOPE_SPECIFICATION = re.compile(
    r"1 \+ Q\((?P<column>'(?:\\.|[^'\\\r\n])*'|\"(?:\\.|[^\"\\\r\n])*\")\)\Z"
)
_MAX_NORMALIZED_ARTIFACT_PATH_BYTES = 512
_LMM_RESULT_ARTIFACT_PATH = (
    "artifacts/model_results/linear_mixed_effects_1.result.json"
)
_OS_OPEN_SUPPORTS_DIR_FD = os.open in os.supports_dir_fd


class VersionedResultReadError(ValueError):
    """A closed, non-sensitive failure from the versioned result reader."""

    def __init__(self, code: str, artifact_path: str | None) -> None:
        self.code = code
        self.artifact_path = artifact_path
        super().__init__(code)


class _PayloadInvalid(ValueError):
    pass


class _DuplicateJsonKey(ValueError):
    pass


def _sha256_bytes(snapshot: bytes) -> str:
    return hashlib.sha256(snapshot).hexdigest()


def _fail_payload() -> NoReturn:
    raise _PayloadInvalid


def _exact_mapping(value: object, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail_payload()
    if any(type(key) is not str for key in value) or set(value) != fields:
        _fail_payload()
    return value


def _nonempty_string(value: object) -> str:
    if type(value) is not str or not value:
        _fail_payload()
    return value


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        _fail_payload()
    return value


def _positive_int(value: object) -> int:
    result = _nonnegative_int(value)
    if result == 0:
        _fail_payload()
    return result


def _finite_number(value: object) -> int | float:
    if type(value) is int:
        return value
    if type(value) is not float or not math.isfinite(value):
        _fail_payload()
    return value


def _nonnegative_number(value: object) -> int | float:
    result = _finite_number(value)
    if result < 0:
        _fail_payload()
    return result


def _count_mapping(value: object, *, allow_empty: bool) -> dict[str, int]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        _fail_payload()
    if not allow_empty and not value:
        _fail_payload()
    result: dict[str, int] = {}
    for key, item in value.items():
        _nonempty_string(key)
        result[key] = _positive_int(item)
    return result


def _exclusion_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        _fail_payload()
    result: dict[str, int] = {}
    for key, item in value.items():
        _nonempty_string(key)
        result[key] = _nonnegative_int(item)
    return result


def _has_random_slope(value: object) -> bool:
    specification = _nonempty_string(value)
    if specification == "1":
        return False
    match = _RANDOM_SLOPE_SPECIFICATION.fullmatch(specification)
    if match is None:
        _fail_payload()
    try:
        column = ast.literal_eval(match.group("column"))
    except (SyntaxError, ValueError):
        _fail_payload()
    if type(column) is not str or not column:
        _fail_payload()
    return True


def _validate_coefficient(value: object) -> None:
    coefficient = _exact_mapping(value, _COEFFICIENT_FIELDS)
    if coefficient["result_id"] != "group_time_interaction":
        _fail_payload()
    _nonempty_string(coefficient["label"])
    _finite_number(coefficient["estimate"])
    _nonnegative_number(coefficient["std_error"])
    p_value = _finite_number(coefficient["p_value"])
    if not 0 <= p_value <= 1:
        _fail_payload()
    interval = coefficient["confidence_interval"]
    if type(interval) is not list or len(interval) != 2:
        _fail_payload()
    lower = _finite_number(interval[0])
    upper = _finite_number(interval[1])
    if lower > upper:
        _fail_payload()
    if coefficient["confidence_level"] != 0.95 or type(
        coefficient["confidence_level"]
    ) not in {int, float}:
        _fail_payload()
    if coefficient["inference_method"] != "asymptotic_wald_z_v1":
        _fail_payload()
    if coefficient["source_id"] != (
        "model_results.linear_mixed_effects_1.coefficients.group_time_interaction"
    ):
        _fail_payload()


def _validate_random_effects(
    value: object,
    *,
    has_random_slope: bool,
    nobs: int,
    n_groups: int,
    observations_per_group: Mapping[str, int],
) -> None:
    random_effects = _exact_mapping(value, _RANDOM_EFFECT_FIELDS)
    _nonnegative_number(random_effects["intercept_variance"])
    _nonnegative_number(random_effects["residual_variance"])

    nullable_values = (
        random_effects["slope_variance"],
        random_effects["covariance"],
        random_effects["intercept_slope_covariance"],
    )
    if has_random_slope and all(item is not None for item in nullable_values):
        _nonnegative_number(nullable_values[0])
        _finite_number(nullable_values[1])
        _finite_number(nullable_values[2])
        if nullable_values[1] != nullable_values[2]:
            _fail_payload()
    elif not has_random_slope and all(item is None for item in nullable_values):
        pass
    else:
        _fail_payload()

    if _positive_int(random_effects["n_groups"]) != n_groups:
        _fail_payload()
    nested_counts = _count_mapping(
        random_effects["observations_per_group"], allow_empty=False
    )
    if (
        nested_counts != dict(observations_per_group)
        or sum(nested_counts.values()) != nobs
    ):
        _fail_payload()


def _validate_unbalanced_figure_evidence(
    value: object,
    *,
    reference_group: str,
    comparison_group: str,
) -> None:
    evidence = _exact_mapping(value, _UNBALANCED_FIGURE_EVIDENCE_FIELDS)
    if evidence["reason"] != "unbalanced_observed_time_support":
        _fail_payload()
    _finite_number(evidence["first_nonshared_time"])
    group_support = evidence["group_support"]
    if type(group_support) is not list or len(group_support) != 2:
        _fail_payload()
    labels: list[str] = []
    digests: list[str] = []
    for item in group_support:
        support = _exact_mapping(item, _UNBALANCED_GROUP_SUPPORT_FIELDS)
        label = _nonempty_string(support["label"])
        if not 1 <= len(label) <= 128:
            _fail_payload()
        digest = support["observed_time_sha256"]
        if type(digest) is not str or not _LOWER_SHA256.fullmatch(digest):
            _fail_payload()
        labels.append(label)
        digests.append(digest)
    if (
        len(set(labels)) != 2
        or labels != sorted(labels)
        or labels != sorted({reference_group, comparison_group})
        or digests[0] == digests[1]
    ):
        _fail_payload()


def _validate_diagnostics(
    value: object,
    *,
    has_random_slope: bool,
    reference_group: str,
    comparison_group: str,
) -> list[dict[str, object]]:
    if type(value) is not list:
        _fail_payload()
    result: list[dict[str, object]] = []
    seen_codes: set[str] = set()
    for item in value:
        diagnostic = _exact_mapping(item, _DIAGNOSTIC_FIELDS)
        try:
            parsed = LmmDiagnostic(
                code=diagnostic["code"],
                severity=diagnostic["severity"],
                status=diagnostic["status"],
                evidence=diagnostic["evidence"],
                action_candidate=diagnostic["action_candidate"],
            )
        except (ContractError, TypeError):
            _fail_payload()
        normalized = parsed.to_dict()
        code = normalized["code"]
        if code not in _TERMINAL_DIAGNOSTIC_CODES or code in seen_codes:
            _fail_payload()
        seen_codes.add(code)
        if code == "LMM_RANDOM_SLOPE_NEAR_ZERO":
            if (
                normalized["severity"] != "warning"
                or normalized["status"] != "complete"
                or normalized["action_candidate"] is None
            ):
                _fail_payload()
        elif code == "LMM_RANDOM_EFFECTS_SINGULAR":
            if (
                normalized["severity"] != "warning"
                or normalized["status"] != "complete"
                or (normalized["action_candidate"] is not None) != has_random_slope
            ):
                _fail_payload()
        elif code == "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME":
            if (
                normalized["severity"] != "warning"
                or normalized["status"] != "complete"
                or normalized["action_candidate"] is not None
            ):
                _fail_payload()
            _validate_unbalanced_figure_evidence(
                normalized["evidence"],
                reference_group=reference_group,
                comparison_group=comparison_group,
            )
        elif code == "LMM_CONVERGENCE_FAILED":
            if (
                normalized["severity"] != "error"
                or normalized["status"] != "failed"
                or normalized["action_candidate"] is not None
                or normalized["evidence"] != {"optimizer": "lbfgs"}
            ):
                _fail_payload()
        else:
            if (
                normalized["severity"] != "error"
                or normalized["status"] != "failed"
                or normalized["action_candidate"] is not None
                or normalized["evidence"] != {}
            ):
                _fail_payload()
        result.append(normalized)
    return result


def _validate_figure_context(
    value: object, *, reference_group: str, comparison_group: str
) -> None:
    figure = _exact_mapping(value, _FIGURE_FIELDS)
    if figure["chart_type"] != "lmm_group_trajectory":
        _fail_payload()
    time = figure["time"]
    if type(time) is not list or not time:
        _fail_payload()
    parsed_time = [_finite_number(item) for item in time]
    if any(left >= right for left, right in zip(parsed_time, parsed_time[1:])):
        _fail_payload()

    groups = figure["groups"]
    if type(groups) is not list or len(groups) != 2:
        _fail_payload()
    labels: list[str] = []
    for item in groups:
        group = _exact_mapping(item, _FIGURE_GROUP_FIELDS)
        label = _nonempty_string(group["label"])
        if label in labels:
            _fail_payload()
        labels.append(label)
        for field in ("observed_mean", "fitted_mean"):
            series = group[field]
            if type(series) is not list or len(series) != len(parsed_time):
                _fail_payload()
            for point in series:
                _finite_number(point)
    if labels != sorted({reference_group, comparison_group}):
        _fail_payload()


def _validate_execution_binding(value: object) -> dict[str, object]:
    binding = _exact_mapping(value, _EXECUTION_BINDING_FIELDS)
    if binding["schema_version"] != 1 or type(binding["schema_version"]) is not int:
        _fail_payload()
    _nonempty_string(binding["run_id"])
    if type(binding["executed_input_digest"]) is not str or not _LOWER_SHA256.fullmatch(binding["executed_input_digest"]):
        _fail_payload()
    return dict(binding)


def _parse_lmm_result_payload_v1(value: object) -> dict[str, object]:
    payload = _exact_mapping(value, _PAYLOAD_FIELDS)
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        _fail_payload()
    literal_fields = {
        "contract_version": "1.0",
        "estimator_version": "statsmodels_mixedlm_v1",
        "model_id": "linear_mixed_effects_1",
        "model_type": "linear_mixed_effects",
        "engine": "statsmodels",
        "optimizer": "lbfgs",
        "primary_target_id": "group_time_interaction",
    }
    if any(payload[field] != expected for field, expected in literal_fields.items()):
        _fail_payload()
    if type(payload["fit_method"]) is not str or payload["fit_method"] not in {
        "reml",
        "ml",
    }:
        _fail_payload()
    if type(payload["converged"]) is not bool:
        _fail_payload()
    if type(payload["status"]) is not str or payload["status"] not in {
        "complete",
        "failed",
    }:
        _fail_payload()
    _validate_execution_binding(payload["execution_binding"])

    nobs = _nonnegative_int(payload["nobs"])
    n_groups = _nonnegative_int(payload["n_groups"])
    observations_per_group = _count_mapping(
        payload["observations_per_group"], allow_empty=payload["status"] == "failed"
    )
    if sum(observations_per_group.values()) != nobs:
        _fail_payload()
    if len(observations_per_group) != n_groups:
        _fail_payload()
    excluded_rows = _nonnegative_int(payload["excluded_rows"])
    if sum(_exclusion_mapping(payload["exclusion_counts"]).values()) != excluded_rows:
        _fail_payload()
    _nonempty_string(payload["fixed_effects_formula"])
    has_random_slope = _has_random_slope(payload["random_effects_specification"])
    reference_group = _nonempty_string(payload["reference_group"])
    comparison_group = _nonempty_string(payload["comparison_group"])
    if reference_group == comparison_group:
        _fail_payload()
    if type(payload["result_identity"]) is not str or not _LOWER_SHA256.fullmatch(
        payload["result_identity"]
    ):
        _fail_payload()

    diagnostics = _validate_diagnostics(
        payload["diagnostics"],
        has_random_slope=has_random_slope,
        reference_group=reference_group,
        comparison_group=comparison_group,
    )
    warnings = payload["warnings"]
    if type(warnings) is not list or any(type(item) is not str for item in warnings):
        _fail_payload()
    if len(warnings) != len(set(warnings)):
        _fail_payload()
    expected_warnings = [
        diagnostic["code"]
        for diagnostic in diagnostics
        if diagnostic["severity"] == "warning"
    ]
    if warnings != expected_warnings:
        _fail_payload()

    if payload["status"] == "complete":
        if payload["converged"] is not True or nobs == 0 or n_groups == 0:
            _fail_payload()
        coefficients = _exact_mapping(
            payload["coefficients"], {"group_time_interaction"}
        )
        _validate_coefficient(coefficients["group_time_interaction"])
        _validate_random_effects(
            payload["random_effects"],
            has_random_slope=has_random_slope,
            nobs=nobs,
            n_groups=n_groups,
            observations_per_group=observations_per_group,
        )
        has_unbalanced_figure_diagnostic = (
            "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME"
            in {diagnostic["code"] for diagnostic in diagnostics}
        )
        if payload["figure_context"] is None:
            if not has_unbalanced_figure_diagnostic:
                _fail_payload()
        else:
            if has_unbalanced_figure_diagnostic:
                _fail_payload()
            _validate_figure_context(
                payload["figure_context"],
                reference_group=reference_group,
                comparison_group=comparison_group,
            )
    else:
        if payload["converged"] is not False:
            _fail_payload()
        if payload["coefficients"] != {} or payload["random_effects"] != {}:
            _fail_payload()
        if payload["figure_context"] is not None or warnings != []:
            _fail_payload()
        if not any(
            diagnostic["severity"] == "error" and diagnostic["status"] == "failed"
            for diagnostic in diagnostics
        ):
            _fail_payload()

    # The validated input is JSON-shaped; return a detached canonicalizable object.
    result = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    sha256_canonical(result)
    return result


def parse_lmm_result_payload_v1(value: object) -> dict[str, object]:
    """Validate and detach an exact ``LmmResultPayloadV1`` JSON object."""

    try:
        return _parse_lmm_result_payload_v1(value)
    except (_PayloadInvalid, TypeError, ValueError, ContractError):
        raise VersionedResultReadError("LMM_PAYLOAD_INVALID", None) from None


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_nonstandard_number(_value: str) -> NoReturn:
    raise ValueError


def _load_json(snapshot: bytes) -> object:
    return json.loads(
        snapshot,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_nonstandard_number,
    )


def _index_error() -> NoReturn:
    raise VersionedResultReadError("ARTIFACT_INDEX_INVALID", None)


def _read_index_value(run_root: Path) -> object | None:
    """Safely snapshot an index only to detect declared model-result packets.

    V1 runs may carry an unversioned, non-model artifact index.  That index is
    not an authority for a versioned result, so a reader must leave it to the
    legacy path.  This function deliberately uses the same pinned descriptor
    read as strict validation and never follows an untrusted artifact path.
    """

    try:
        return _load_json(
            _read_pinned_file(
                run_root,
                ("artifacts_index.json",),
                error_code="ARTIFACT_INDEX_INVALID",
                artifact_path=None,
            )
        )
    except VersionedResultReadError:
        # An existing index that cannot be pinned (including a symlink) is an
        # unsafe boundary, not a legacy compatibility case.
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return None


def _declares_model_result_packet(value: object) -> bool:
    """Return whether a safely parsed index explicitly declares a model packet."""

    if not isinstance(value, Mapping):
        return False
    artifacts = value.get("artifacts")
    return isinstance(artifacts, list) and any(
        isinstance(record, Mapping)
        and record.get("artifact_type") == "model_result_packet"
        for record in artifacts
    )


def _read_index(value: object) -> list[dict[str, object]]:
    if type(value) is not dict or set(value) != _INDEX_FIELDS:
        _index_error()
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        _index_error()
    artifacts = value["artifacts"]
    if type(artifacts) is not list:
        _index_error()

    result: list[dict[str, object]] = []
    artifact_ids: set[str] = set()
    for record in artifacts:
        if type(record) is not dict or set(record) != _ARTIFACT_FIELDS:
            _index_error()
        string_fields = ("artifact_id", "path", "artifact_type", "step", "code_version")
        if any(
            type(record[field]) is not str or not record[field]
            for field in string_fields
        ):
            _index_error()
        if type(record["config_hash"]) is not str:
            _index_error()
        if record["artifact_id"] in artifact_ids:
            _index_error()
        artifact_ids.add(record["artifact_id"])
        if type(record["sha256"]) is not str or not _LOWER_SHA256.fullmatch(
            record["sha256"]
        ):
            _index_error()
        inputs = record["inputs"]
        if type(inputs) is not list or any(
            type(item) is not str or not item for item in inputs
        ):
            _index_error()
        result.append(record)
    return result


def _bounded_artifact_path(path: str) -> str | None:
    try:
        encoded = path.encode("utf-8")
    except UnicodeError:
        return None
    if len(encoded) > _MAX_NORMALIZED_ARTIFACT_PATH_BYTES:
        return None
    return path


def _artifact_path_error() -> NoReturn:
    """Reject a path before it has earned safe error-path visibility."""

    raise VersionedResultReadError("ARTIFACT_PATH_INVALID", None)


def _validate_indexed_path(path: str) -> PurePosixPath:
    if _bounded_artifact_path(path) is None:
        _artifact_path_error()
    if "\\" in path or "\x00" in path:
        _artifact_path_error()
    pure = PurePosixPath(path)
    if (
        pure.is_absolute()
        or path != pure.as_posix()
        or path in {"", "."}
        or ".." in pure.parts
    ):
        _artifact_path_error()
    return pure


def _pinned_descriptor_reads_supported() -> bool:
    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and _OS_OPEN_SUPPORTS_DIR_FD
    )


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def _file_open_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _read_pinned_file(
    run_root: Path,
    parts: tuple[str, ...],
    *,
    error_code: str,
    artifact_path: str | None,
) -> bytes:
    """Read a regular file through pinned POSIX directory descriptors only."""

    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        if not parts or not _pinned_descriptor_reads_supported():
            raise OSError
        directory_fd = os.open(os.fspath(run_root), _directory_open_flags())
        for part in parts[:-1]:
            next_directory_fd = os.open(
                part,
                _directory_open_flags(),
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_directory_fd
        file_fd = os.open(
            parts[-1],
            _file_open_flags(),
            dir_fd=directory_fd,
        )
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise OSError
        with os.fdopen(file_fd, "rb", closefd=True) as opened_file:
            file_fd = None
            return opened_file.read()
    except (OSError, RuntimeError, ValueError):
        raise VersionedResultReadError(error_code, artifact_path) from None
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass


def _read_artifact_snapshot(run_root: Path, path: str) -> bytes:
    pure = _validate_indexed_path(path)
    return _read_pinned_file(
        run_root,
        pure.parts,
        error_code="ARTIFACT_PATH_INVALID",
        artifact_path=_bounded_artifact_path(path),
    )


def _validate_lmm_result_artifact_path(path: str) -> None:
    """Accept only the producer's single, versioned model-result location."""

    _validate_indexed_path(path)
    if path != _LMM_RESULT_ARTIFACT_PATH:
        raise VersionedResultReadError("LMM_MODEL_RESULT_PATH_INVALID", path)


def _parse_envelope(snapshot: bytes, artifact_path: str) -> dict[str, object]:
    try:
        value = _load_json(snapshot)
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        raise VersionedResultReadError("PACKET_JSON_INVALID", artifact_path) from None
    if type(value) is not dict:
        raise VersionedResultReadError("PACKET_JSON_INVALID", artifact_path)
    try:
        envelope = PacketEnvelope.from_dict(value)
    except (ContractError, TypeError, ValueError):
        raise VersionedResultReadError(
            "PACKET_ENVELOPE_INVALID", artifact_path
        ) from None
    if (
        envelope.contract != "linear_mixed_effects.result"
        or envelope.contract_version != "1.0"
    ):
        raise VersionedResultReadError(
            "UNKNOWN_MODEL_RESULT_PACKET_CONTRACT", artifact_path
        )
    exact_envelope = envelope.to_dict()
    try:
        exact_envelope["payload"] = _parse_lmm_result_payload_v1(
            exact_envelope["payload"]
        )
    except (_PayloadInvalid, TypeError, ValueError, ContractError):
        raise VersionedResultReadError("LMM_PAYLOAD_INVALID", artifact_path) from None
    try:
        sha256_canonical(exact_envelope)
    except (TypeError, ValueError):
        raise VersionedResultReadError(
            "PACKET_ENVELOPE_INVALID", artifact_path
        ) from None
    return exact_envelope


def read_lmm_public_results(run_root: Path) -> list[dict[str, object]]:
    """Read, verify, and project all indexed LMM result packets in ``run_root``."""

    try:
        resolved_root = Path(run_root).resolve(strict=True)
        if not resolved_root.is_dir():
            _index_error()
    except VersionedResultReadError:
        raise
    except (OSError, RuntimeError, ValueError, TypeError):
        _index_error()

    index_value = _read_index_value(resolved_root)
    if not _declares_model_result_packet(index_value):
        return []
    records = _read_index(index_value)
    projected: list[dict[str, object]] = []
    identities: set[tuple[str, str, str]] = set()
    for record in records:
        if record["artifact_type"] != "model_result_packet":
            continue
        artifact_path = record["path"]
        assert isinstance(artifact_path, str)
        _validate_lmm_result_artifact_path(artifact_path)
        snapshot = _read_artifact_snapshot(resolved_root, artifact_path)
        if _sha256_bytes(snapshot) != record["sha256"]:
            raise VersionedResultReadError(
                "ARTIFACT_SHA256_MISMATCH", artifact_path
            )
        envelope = _parse_envelope(snapshot, artifact_path)
        payload = envelope["payload"]
        assert isinstance(payload, dict)
        binding = payload["execution_binding"]
        assert isinstance(binding, dict)
        if binding["run_id"] != resolved_root.name:
            raise VersionedResultReadError(
                "LMM_EXECUTION_BINDING_RUN_ID_MISMATCH", artifact_path
            )
        identity = (
            envelope["contract"],
            envelope["contract_version"],
            payload["model_id"],
        )
        assert all(isinstance(item, str) for item in identity)
        if identity in identities:
            raise VersionedResultReadError("LMM_DUPLICATE_IDENTITY", artifact_path)
        identities.add(identity)
        projected.append(
            {
                "artifact_id": record["artifact_id"],
                "artifact_path": artifact_path,
                "artifact_sha256": record["sha256"],
                "model_id": payload["model_id"],
                "model_type": payload["model_type"],
                "source_contract": envelope["contract"],
                "source_contract_version": envelope["contract_version"],
                "source_producer_version": envelope["producer_version"],
                "source_packet_digest": sha256_canonical(envelope),
                "execution_binding": dict(payload["execution_binding"]),
                "payload": payload,
                "legacy_compatibility": "projected_from_versioned_packet",
            }
        )
    return sorted(projected, key=lambda item: item["artifact_path"])


def read_lmm_public_results_from_pinned_run(
    pinned_run: PinnedRunDirectory,
) -> list[dict[str, object]]:
    """Strict LMM projection using one caller-owned pinned run FD only."""

    if not isinstance(pinned_run, PinnedRunDirectory):
        raise VersionedResultReadError("ARTIFACT_INDEX_INVALID", None)
    try:
        index_value = _load_json(pinned_run.read_lmm_index())
    except (PinnedRunError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        raise VersionedResultReadError("ARTIFACT_INDEX_INVALID", None) from None
    if not _declares_model_result_packet(index_value):
        return []
    records = _read_index(index_value)
    projected: list[dict[str, object]] = []
    identities: set[tuple[str, str, str]] = set()
    for record in records:
        if record["artifact_type"] != "model_result_packet":
            continue
        artifact_path = record["path"]
        assert isinstance(artifact_path, str)
        _validate_lmm_result_artifact_path(artifact_path)
        try:
            snapshot = pinned_run.read_lmm_terminal_packet()
        except PinnedRunError:
            raise VersionedResultReadError("ARTIFACT_PATH_INVALID", artifact_path) from None
        if _sha256_bytes(snapshot) != record["sha256"]:
            raise VersionedResultReadError("ARTIFACT_SHA256_MISMATCH", artifact_path)
        envelope = _parse_envelope(snapshot, artifact_path)
        payload = envelope["payload"]
        assert isinstance(payload, dict)
        binding = payload["execution_binding"]
        assert isinstance(binding, dict)
        if binding["run_id"] != pinned_run.run_id:
            raise VersionedResultReadError("LMM_EXECUTION_BINDING_RUN_ID_MISMATCH", artifact_path)
        identity = (envelope["contract"], envelope["contract_version"], payload["model_id"])
        assert all(isinstance(item, str) for item in identity)
        if identity in identities:
            raise VersionedResultReadError("LMM_DUPLICATE_IDENTITY", artifact_path)
        identities.add(identity)
        projected.append({
            "artifact_id": record["artifact_id"], "artifact_path": artifact_path,
            "artifact_sha256": record["sha256"], "model_id": payload["model_id"],
            "model_type": payload["model_type"], "source_contract": envelope["contract"],
            "source_contract_version": envelope["contract_version"],
            "source_producer_version": envelope["producer_version"],
            "source_packet_digest": sha256_canonical(envelope),
            "execution_binding": dict(payload["execution_binding"]),
            "payload": payload, "legacy_compatibility": "projected_from_versioned_packet",
        })
    return sorted(projected, key=lambda item: item["artifact_path"])


__all__ = [
    "VersionedResultReadError",
    "parse_lmm_result_payload_v1",
    "read_lmm_public_results",
    "read_lmm_public_results_from_pinned_run",
]
