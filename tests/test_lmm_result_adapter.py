from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import pytest

from workbench.analysis_loop.canonical import sha256_canonical
from workbench.domain import ArtifactRecord
from workbench.services import lmm_result_adapter
from workbench.services.lmm_result_adapter import (
    VersionedResultReadError,
    parse_lmm_result_payload_v1,
    read_lmm_public_results,
    read_lmm_public_results_from_pinned_run,
)
from workbench.services.pinned_run_directory import open_pinned_run_directory


_LMM_RESULT_PATH = "artifacts/model_results/linear_mixed_effects_1.result.json"


def _complete_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_version": "1.0",
        "estimator_version": "statsmodels_mixedlm_v1",
        "model_id": "linear_mixed_effects_1",
        "model_type": "linear_mixed_effects",
        "engine": "statsmodels",
        "fit_method": "reml",
        "converged": True,
        "status": "complete",
        "optimizer": "lbfgs",
        "nobs": 6,
        "n_groups": 2,
        "observations_per_group": {"control": 3, "treated": 3},
        "excluded_rows": 1,
        "exclusion_counts": {"score": 1},
        "fixed_effects_formula": "score ~ group * week",
        "random_effects_specification": "1 + Q('week')",
        "reference_group": "control",
        "comparison_group": "treated",
        "result_identity": "a" * 64,
        "primary_target_id": "group_time_interaction",
        "coefficients": {
            "group_time_interaction": {
                "result_id": "group_time_interaction",
                "label": "treated x week",
                "estimate": 0.8,
                "std_error": 0.2,
                "p_value": 0.01,
                "confidence_interval": [0.4, 1.2],
                "confidence_level": 0.95,
                "inference_method": "asymptotic_wald_z_v1",
                "source_id": (
                    "model_results.linear_mixed_effects_1.coefficients."
                    "group_time_interaction"
                ),
            }
        },
        "random_effects": {
            "intercept_variance": 1.1,
            "slope_variance": 0.3,
            "covariance": -0.1,
            "intercept_slope_covariance": -0.1,
            "residual_variance": 0.7,
            "n_groups": 2,
            "observations_per_group": {"control": 3, "treated": 3},
        },
        "diagnostics": [
            {
                "code": "LMM_RANDOM_SLOPE_NEAR_ZERO",
                "severity": "warning",
                "status": "complete",
                "evidence": {"slope_variance": 0.3},
                "action_candidate": {
                    "action_id": "lmm.simplify_random_effects_v1",
                    "operation_id": "model.rerun",
                    "patch": {"model_options": {"random_slope": False}},
                    "required_confirmation": True,
                },
            }
        ],
        "figure_context": {
            "chart_type": "lmm_group_trajectory",
            "time": [0.0, 1.0, 2.0],
            "groups": [
                {
                    "label": "control",
                    "observed_mean": [2.0, 2.2, 2.4],
                    "fitted_mean": [2.0, 2.1, 2.3],
                },
                {
                    "label": "treated",
                    "observed_mean": [2.1, 2.8, 3.7],
                    "fitted_mean": [2.1, 2.9, 3.6],
                },
            ],
        },
        "warnings": ["LMM_RANDOM_SLOPE_NEAR_ZERO"],
        "execution_binding": {
            "schema_version": 1,
            "run_id": "run-1",
            "executed_input_digest": "b" * 64,
        },
    }


def _failed_payload() -> dict[str, object]:
    payload = _complete_payload()
    payload.update(
        {
            "converged": False,
            "status": "failed",
            "nobs": 0,
            "n_groups": 0,
            "observations_per_group": {},
            "coefficients": {},
            "random_effects": {},
            "diagnostics": [
                {
                    "code": "LMM_CONVERGENCE_FAILED",
                    "severity": "error",
                    "status": "failed",
                    "evidence": {"optimizer": "lbfgs"},
                    "action_candidate": None,
                }
            ],
            "figure_context": None,
            "warnings": [],
        }
    )
    return payload


def test_pinned_reader_rejects_cross_run_terminal_packet_replay(tmp_path: Path) -> None:
    run_root = tmp_path / "run-a"
    run_root.mkdir()
    payload = _complete_payload()
    payload["execution_binding"] = {
        "schema_version": 1,
        "run_id": "run-b",
        "executed_input_digest": "b" * 64,
    }
    _write_indexed_packet(run_root, _envelope(payload))
    with open_pinned_run_directory(tmp_path, "run-a") as pinned:
        with pytest.raises(VersionedResultReadError, match="LMM_EXECUTION_BINDING_RUN_ID_MISMATCH"):
            read_lmm_public_results_from_pinned_run(pinned)


def test_generic_reader_rejects_cross_run_terminal_packet_replay(tmp_path: Path) -> None:
    payload = _complete_payload()
    payload["execution_binding"] = {
        "schema_version": 1,
        "run_id": "different-run",
        "executed_input_digest": "b" * 64,
    }
    _write_indexed_packet(tmp_path, _envelope(payload))
    with pytest.raises(VersionedResultReadError, match="LMM_EXECUTION_BINDING_RUN_ID_MISMATCH"):
        read_lmm_public_results(tmp_path)


def _unbalanced_complete_payload() -> dict[str, object]:
    payload = _complete_payload()
    payload["figure_context"] = None
    payload["diagnostics"] = [
        {
            "code": "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME",
            "severity": "warning",
            "status": "complete",
            "evidence": {
                "reason": "unbalanced_observed_time_support",
                "group_support": [
                    {
                        "label": "control",
                        "observed_time_sha256": sha256_canonical([0.0, 1.0, 2.0]),
                    },
                    {
                        "label": "treated",
                        "observed_time_sha256": sha256_canonical([0.0, 1.0]),
                    },
                ],
                "first_nonshared_time": 2.0,
            },
            "action_candidate": None,
        }
    ]
    payload["warnings"] = ["LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME"]
    return payload


def _envelope(payload: dict[str, object]) -> dict[str, object]:
    return {
        "contract": "linear_mixed_effects.result",
        "contract_version": "1.0",
        "producer_version": "linear_mixed_effects@1.0",
        "payload": payload,
    }


def _write_indexed_packet(
    run_root: Path,
    envelope: dict[str, object],
    *,
    artifact_path: str = _LMM_RESULT_PATH,
    indexed_sha256: str | None = None,
) -> bytes:
    # Default fixture packets are produced for the exact temporary run root.
    # Explicit replay tests provide a different ID and retain it unchanged.
    payload = envelope.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("execution_binding"), dict):
        if payload["execution_binding"].get("run_id") == "run-1":
            payload["execution_binding"]["run_id"] = run_root.name
    packet_path = run_root / artifact_path
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = json.dumps(
        envelope, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    packet_path.write_bytes(snapshot)
    digest = indexed_sha256 or hashlib.sha256(snapshot).hexdigest()
    record = ArtifactRecord(
        artifact_id="lmm-result",
        path=artifact_path,
        artifact_type="model_result_packet",
        step="linear_mixed_effects",
        sha256=digest,
        inputs=("clean-data",),
        config_hash="config-v1",
        code_version="1.7.3",
    )
    (run_root / "artifacts_index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": [record.to_dict()],
            }
        ),
        encoding="utf-8",
    )
    return snapshot


def test_reads_valid_complete_packet_without_recalculating_payload(
    tmp_path: Path,
) -> None:
    envelope = _envelope(_complete_payload())
    snapshot = _write_indexed_packet(tmp_path, envelope)

    assert read_lmm_public_results(tmp_path) == [
        {
            "artifact_id": "lmm-result",
            "artifact_path": _LMM_RESULT_PATH,
            "artifact_sha256": hashlib.sha256(snapshot).hexdigest(),
            "model_id": "linear_mixed_effects_1",
            "model_type": "linear_mixed_effects",
            "source_contract": "linear_mixed_effects.result",
            "source_contract_version": "1.0",
            "source_producer_version": "linear_mixed_effects@1.0",
                "source_packet_digest": sha256_canonical(envelope),
                "execution_binding": envelope["payload"]["execution_binding"],
                "payload": envelope["payload"],
            "legacy_compatibility": "projected_from_versioned_packet",
        }
    ]


def test_reads_valid_terminal_failed_packet(tmp_path: Path) -> None:
    payload = _failed_payload()
    _write_indexed_packet(tmp_path, _envelope(payload))

    result = read_lmm_public_results(tmp_path)

    assert result[0]["payload"] == payload


@pytest.mark.parametrize(
    "artifact_path",
    [
        "model/lmm_result.json",
        "artifacts/model_results/linear_mixed_effects_2.result.json",
    ],
)
def test_rejects_declared_lmm_result_outside_the_single_controlled_path(
    tmp_path: Path, artifact_path: str
) -> None:
    _write_indexed_packet(
        tmp_path,
        _envelope(_failed_payload()),
        artifact_path=artifact_path,
    )

    with pytest.raises(VersionedResultReadError) as raised:
        read_lmm_public_results(tmp_path)

    assert raised.value.code == "LMM_MODEL_RESULT_PATH_INVALID"
    assert raised.value.artifact_path == artifact_path


def test_reads_complete_packet_with_the_exact_unbalanced_figure_warning(
    tmp_path: Path,
) -> None:
    payload = _unbalanced_complete_payload()
    _write_indexed_packet(tmp_path, _envelope(payload))

    assert read_lmm_public_results(tmp_path)[0]["payload"] == payload


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["diagnostics"].__setitem__(0, {  # type: ignore[index]
            "code": "LMM_UNRECOGNIZED_TERMINAL",
            "severity": "error",
            "status": "failed",
            "evidence": {},
            "action_candidate": None,
        }),
        lambda payload: payload["diagnostics"].__setitem__(0, {  # type: ignore[index]
            "code": "LMM_CONVERGENCE_FAILED",
            "severity": "warning",
            "status": "complete",
            "evidence": {"optimizer": "lbfgs"},
            "action_candidate": None,
        }),
        lambda payload: payload["diagnostics"].__setitem__(0, {  # type: ignore[index]
            "code": "LMM_UNEXPECTED_FIT_EXCEPTION",
            "severity": "error",
            "status": "failed",
            "evidence": {"leaked": "detail"},
            "action_candidate": None,
        }),
    ],
)
def test_rejects_unknown_or_malformed_terminal_failure_diagnostics(
    mutate: object,
) -> None:
    payload = _failed_payload()
    assert callable(mutate)
    mutate(payload)

    with pytest.raises(VersionedResultReadError) as raised:
        parse_lmm_result_payload_v1(payload)

    assert raised.value.code == "LMM_PAYLOAD_INVALID"


@pytest.mark.parametrize("case", ["malformed_evidence", "duplicate"])
def test_rejects_malformed_or_duplicate_unbalanced_figure_diagnostic(case: str) -> None:
    payload = _unbalanced_complete_payload()
    diagnostics = payload["diagnostics"]
    assert isinstance(diagnostics, list)
    if case == "malformed_evidence":
        diagnostic = diagnostics[0]
        assert isinstance(diagnostic, dict)
        diagnostic["evidence"] = {"reason": "unbalanced_observed_time_support"}
    else:
        diagnostics.append(dict(diagnostics[0]))
        payload["warnings"] = [
            "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME",
            "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME",
        ]

    with pytest.raises(VersionedResultReadError) as raised:
        parse_lmm_result_payload_v1(payload)

    assert raised.value.code == "LMM_PAYLOAD_INVALID"


@pytest.mark.parametrize(
    "case",
    ["equal_digest", "label_too_long", "reversed_labels", "nonfinite_first_difference"],
)
def test_rejects_unbalanced_evidence_outside_its_bounded_wire_contract(
    case: str,
) -> None:
    payload = _unbalanced_complete_payload()
    diagnostics = payload["diagnostics"]
    assert isinstance(diagnostics, list)
    diagnostic = diagnostics[0]
    assert isinstance(diagnostic, dict)
    evidence = diagnostic["evidence"]
    assert isinstance(evidence, dict)
    group_support = evidence["group_support"]
    assert isinstance(group_support, list)
    first, second = group_support
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    if case == "equal_digest":
        second["observed_time_sha256"] = first["observed_time_sha256"]
    elif case == "label_too_long":
        first["label"] = "a" * 129
    elif case == "reversed_labels":
        evidence["group_support"] = [second, first]
    else:
        evidence["first_nonshared_time"] = math.inf

    with pytest.raises(VersionedResultReadError) as raised:
        parse_lmm_result_payload_v1(payload)

    assert raised.value.code == "LMM_PAYLOAD_INVALID"


def test_reads_genuine_artifact_record_index_with_config_hash(tmp_path: Path) -> None:
    _write_indexed_packet(tmp_path, _envelope(_complete_payload()))
    index = json.loads((tmp_path / "artifacts_index.json").read_text(encoding="utf-8"))

    assert index["artifacts"][0]["config_hash"] == "config-v1"
    assert read_lmm_public_results(tmp_path)[0]["artifact_id"] == "lmm-result"


def test_rejects_artifact_hash_mismatch(tmp_path: Path) -> None:
    _write_indexed_packet(
        tmp_path, _envelope(_complete_payload()), indexed_sha256="0" * 64
    )

    with pytest.raises(VersionedResultReadError) as raised:
        read_lmm_public_results(tmp_path)

    assert raised.value.code == "ARTIFACT_SHA256_MISMATCH"
    assert raised.value.artifact_path == _LMM_RESULT_PATH


def test_rejects_old_series_figure_context() -> None:
    payload = _complete_payload()
    payload["figure_context"] = {
        "chart_type": "lmm_group_trajectory",
        "series": [
            {
                "group": "control",
                "time": [0.0, 1.0],
                "fitted_marginal_mean": [2.0, 2.1],
            }
        ],
    }

    with pytest.raises(VersionedResultReadError) as raised:
        parse_lmm_result_payload_v1(payload)

    assert raised.value.code == "LMM_PAYLOAD_INVALID"
    assert raised.value.artifact_path is None


def test_rejects_covariance_alias_mismatch() -> None:
    payload = _complete_payload()
    random_effects = payload["random_effects"]
    assert isinstance(random_effects, dict)
    random_effects["covariance"] = -0.2

    with pytest.raises(VersionedResultReadError) as raised:
        parse_lmm_result_payload_v1(payload)

    assert raised.value.code == "LMM_PAYLOAD_INVALID"


def test_accepts_intercept_only_specification_with_null_slope_facts() -> None:
    payload = _complete_payload()
    payload["random_effects_specification"] = "1"
    random_effects = payload["random_effects"]
    assert isinstance(random_effects, dict)
    random_effects.update(
        {
            "slope_variance": None,
            "covariance": None,
            "intercept_slope_covariance": None,
        }
    )

    assert parse_lmm_result_payload_v1(payload) == payload


@pytest.mark.parametrize(
    ("specification", "nullable_value"),
    [
        ("1", 0.1),
        ("1 + Q('week')", None),
    ],
)
def test_rejects_random_effects_specification_slope_fact_inconsistency(
    specification: str,
    nullable_value: float | None,
) -> None:
    payload = _complete_payload()
    payload["random_effects_specification"] = specification
    random_effects = payload["random_effects"]
    assert isinstance(random_effects, dict)
    random_effects.update(
        {
            "slope_variance": nullable_value,
            "covariance": nullable_value,
            "intercept_slope_covariance": nullable_value,
        }
    )

    with pytest.raises(VersionedResultReadError) as raised:
        parse_lmm_result_payload_v1(payload)

    assert raised.value.code == "LMM_PAYLOAD_INVALID"


def test_rejects_unknown_random_effects_specification() -> None:
    payload = _complete_payload()
    payload["random_effects_specification"] = "1 + week | participant_id"

    with pytest.raises(VersionedResultReadError) as raised:
        parse_lmm_result_payload_v1(payload)

    assert raised.value.code == "LMM_PAYLOAD_INVALID"


def test_rejects_path_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-lmm-result.json"
    outside.write_text(json.dumps(_envelope(_complete_payload())), encoding="utf-8")
    record = ArtifactRecord(
        artifact_id="lmm-result",
        path="../outside-lmm-result.json",
        artifact_type="model_result_packet",
        step="linear_mixed_effects",
        sha256="0" * 64,
        inputs=(),
        config_hash="config-v1",
        code_version="1.7.3",
    )
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": [record.to_dict()],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(VersionedResultReadError) as raised:
        read_lmm_public_results(tmp_path)

    assert raised.value.code == "ARTIFACT_PATH_INVALID"
    assert raised.value.artifact_path is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract", "future_model.result"),
        ("contract_version", "2.0"),
    ],
)
def test_unknown_declared_model_result_packet_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    envelope = _envelope(_complete_payload())
    envelope[field] = value
    _write_indexed_packet(tmp_path, envelope)

    with pytest.raises(VersionedResultReadError) as raised:
        read_lmm_public_results(tmp_path)

    assert raised.value.code == "UNKNOWN_MODEL_RESULT_PACKET_CONTRACT"


def test_bare_payload_declared_as_model_result_packet_fails_closed(
    tmp_path: Path,
) -> None:
    _write_indexed_packet(tmp_path, _complete_payload())

    with pytest.raises(VersionedResultReadError) as raised:
        read_lmm_public_results(tmp_path)

    assert raised.value.code == "PACKET_ENVELOPE_INVALID"


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-symlink-lmm-result.json"
    snapshot = json.dumps(_envelope(_complete_payload())).encode("utf-8")
    outside.write_bytes(snapshot)
    link = tmp_path / _LMM_RESULT_PATH
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    record = ArtifactRecord(
        artifact_id="lmm-result",
        path=_LMM_RESULT_PATH,
        artifact_type="model_result_packet",
        step="linear_mixed_effects",
        sha256=hashlib.sha256(snapshot).hexdigest(),
        inputs=("clean-data",),
        config_hash="config-v1",
        code_version="1.7.3",
    )
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": [record.to_dict()]}),
        encoding="utf-8",
    )

    with pytest.raises(VersionedResultReadError) as raised:
        read_lmm_public_results(tmp_path)

    assert raised.value.code == "ARTIFACT_PATH_INVALID"
    assert raised.value.artifact_path == _LMM_RESULT_PATH


def test_rejects_final_component_symlink_swap_during_pinned_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_indexed_packet(tmp_path, _envelope(_complete_payload()))
    packet_path = tmp_path / _LMM_RESULT_PATH
    outside = tmp_path.parent / "swapped-outside-lmm-result.json"
    outside.write_bytes(packet_path.read_bytes())
    original_open = os.open
    swapped = False

    def swap_before_final_open(
        path: str | bytes | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "linear_mixed_effects_1.result.json" and dir_fd is not None and not swapped:
            swapped = True
            packet_path.unlink()
            packet_path.symlink_to(outside)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(lmm_result_adapter, "os", os, raising=False)
    monkeypatch.setattr(lmm_result_adapter.os, "open", swap_before_final_open)

    with pytest.raises(VersionedResultReadError) as raised:
        read_lmm_public_results(tmp_path)

    assert swapped is True
    assert raised.value.code == "ARTIFACT_PATH_INVALID"
    assert raised.value.artifact_path == _LMM_RESULT_PATH


def test_rejects_huge_artifact_path_without_echoing_it(tmp_path: Path) -> None:
    hostile_path = "a" * 513
    record = ArtifactRecord(
        artifact_id="lmm-result",
        path=hostile_path,
        artifact_type="model_result_packet",
        step="linear_mixed_effects",
        sha256="0" * 64,
        inputs=(),
        config_hash="config-v1",
        code_version="1.7.3",
    )
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": [record.to_dict()]}),
        encoding="utf-8",
    )

    with pytest.raises(VersionedResultReadError) as raised:
        read_lmm_public_results(tmp_path)

    assert raised.value.code == "ARTIFACT_PATH_INVALID"
    assert raised.value.artifact_path is None


def test_rejects_symlinked_artifact_index(tmp_path: Path) -> None:
    outside_index = tmp_path.parent / "outside-artifacts-index.json"
    outside_index.write_text(
        json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8"
    )
    (tmp_path / "artifacts_index.json").symlink_to(outside_index)

    with pytest.raises(VersionedResultReadError) as raised:
        read_lmm_public_results(tmp_path)

    assert raised.value.code == "ARTIFACT_INDEX_INVALID"
    assert raised.value.artifact_path is None


@pytest.mark.parametrize("case", ["empty_time", "mismatched_means", "nonfinite_time"])
def test_rejects_invalid_canonical_figure_vectors(case: str) -> None:
    payload = _complete_payload()
    figure = payload["figure_context"]
    assert isinstance(figure, dict)
    groups = figure["groups"]
    assert isinstance(groups, list)
    first_group = groups[0]
    assert isinstance(first_group, dict)
    if case == "empty_time":
        figure["time"] = []
    elif case == "mismatched_means":
        first_group["observed_mean"] = [2.0, 2.2]
    else:
        figure["time"] = [0.0, math.inf, 2.0]

    with pytest.raises(VersionedResultReadError) as raised:
        parse_lmm_result_payload_v1(payload)

    assert raised.value.code == "LMM_PAYLOAD_INVALID"


def test_parses_verified_snapshot_even_if_artifact_mutates_after_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_payload = _complete_payload()
    _write_indexed_packet(tmp_path, _envelope(original_payload))
    packet_path = tmp_path / _LMM_RESULT_PATH
    mutated_payload = _complete_payload()
    coefficients = mutated_payload["coefficients"]
    assert isinstance(coefficients, dict)
    target = coefficients["group_time_interaction"]
    assert isinstance(target, dict)
    target["estimate"] = 99.0
    mutated_snapshot = json.dumps(
        _envelope(mutated_payload), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    original_sha256_bytes = lmm_result_adapter._sha256_bytes

    def hash_then_mutate(snapshot: bytes) -> str:
        digest = original_sha256_bytes(snapshot)
        packet_path.write_bytes(mutated_snapshot)
        return digest

    monkeypatch.setattr(lmm_result_adapter, "_sha256_bytes", hash_then_mutate)

    result = read_lmm_public_results(tmp_path)

    assert result[0]["payload"] == original_payload
    assert packet_path.read_bytes() == mutated_snapshot


def test_duplicate_identity_is_rejected(tmp_path: Path) -> None:
    envelope = _envelope(_complete_payload())
    first_snapshot = _write_indexed_packet(tmp_path, envelope)
    index = json.loads((tmp_path / "artifacts_index.json").read_text(encoding="utf-8"))
    second_record = ArtifactRecord(
        artifact_id="lmm-result-second",
        path=_LMM_RESULT_PATH,
        artifact_type="model_result_packet",
        step="linear_mixed_effects",
        sha256=hashlib.sha256(first_snapshot).hexdigest(),
        inputs=("clean-data",),
        config_hash="config-v1",
        code_version="1.7.3",
    )
    index["artifacts"].append(second_record.to_dict())
    (tmp_path / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(VersionedResultReadError) as raised:
        read_lmm_public_results(tmp_path)

    assert raised.value.code == "LMM_DUPLICATE_IDENTITY"
