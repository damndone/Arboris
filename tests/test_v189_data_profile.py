from __future__ import annotations

import json
import importlib.util
from dataclasses import FrozenInstanceError

import pandas as pd
import pytest


def _profile_api():
    assert importlib.util.find_spec("workbench.data_profile") is not None
    import workbench.data_profile as data_profile

    return data_profile


def _dataset_ref(api):
    return api.DatasetRefV1(
        "run-a",
        "node-a",
        "artifact-a",
        "a" * 64,
        "schema:fixture",
        "metadata:fixture",
    )


def test_profile_keeps_observed_declared_and_inferred_metadata_distinct() -> None:
    api = _profile_api()
    profile = api.build_data_profile(
        frame=pd.DataFrame({"group": [1, 1, 2], "score": [1.0, None, 3.0]}),
        dataset_ref=_dataset_ref(api),
        declared_metadata={
            "group": {"value_labels": {"1": "control", "2": "treated"}}
        },
    )

    group = profile.column("group")

    assert group.observed.dtype == "int64"
    assert group.observed.row_count == 3
    assert group.declared.value_labels == {"1": "control", "2": "treated"}
    assert group.declared.measurement_level == "unknown"
    assert group.inferred.role_candidates
    assert group.inferred.confirmed is False
    assert group.inferred.method
    assert profile.shape == (3, 2)
    assert profile.dataset_ref.schema_revision == "schema:fixture"
    assert profile.dataset_ref.metadata_revision == "metadata:fixture"


def test_dataset_ref_rejects_implicit_v1_revisions() -> None:
    api = _profile_api()
    with pytest.raises(api.DataProfileError, match="revision"):
        api.DatasetRefV1("run-a", "node-a", "artifact-a", "a" * 64, "v1", "v1")


def test_missing_declared_metadata_stays_unknown_and_inference_is_advisory() -> None:
    api = _profile_api()
    profile = api.build_data_profile(
        frame=pd.DataFrame({"email": ["a@example.com"], "amount": [3.5]}),
        dataset_ref=_dataset_ref(api),
    )

    amount = profile.column("amount")

    assert amount.declared.variable_label == "unknown"
    assert amount.declared.value_labels is None
    assert amount.declared.measurement_level == "unknown"
    assert amount.declared.missing_policy == "unknown"
    assert amount.declared.sensitivity == "unknown"
    assert amount.inferred.confirmed is False
    assert amount.observed.sample_values == ()
    assert amount.observed.quantiles == {}
    assert amount.observed.samples_redacted is True


def test_profile_bounds_samples_and_redacts_sensitive_values() -> None:
    api = _profile_api()
    profile = api.build_data_profile(
        frame=pd.DataFrame(
            {
                "code": [f"code-{index}-long" for index in range(20)],
                "email": ["secret@example.com"] * 20,
            }
        ),
        dataset_ref=_dataset_ref(api),
        declared_metadata={"email": {"sensitivity": "restricted"}},
    )

    code = profile.column("code").observed
    email = profile.column("email").observed

    assert len(code.sample_values) <= 20
    assert len(code.examples) <= 20
    assert code.max_string_length <= 256
    assert code.max_token_count <= 64
    assert email.sample_values == ()
    assert email.examples == ()
    assert email.quantiles == {}
    assert email.samples_redacted is True
    assert "secret@example.com" not in json.dumps(
        profile.to_dict(), ensure_ascii=False
    )


def test_profile_is_immutable_and_unknown_columns_have_stable_errors() -> None:
    api = _profile_api()
    profile = api.build_data_profile(
        frame=pd.DataFrame({"x": [1, 2]}),
        dataset_ref=_dataset_ref(api),
    )

    with pytest.raises(FrozenInstanceError):
        profile.dataset_ref = _dataset_ref(api)  # type: ignore[misc]
    with pytest.raises(TypeError):
        profile.column("x").declared.value_labels["1"] = "one"  # type: ignore[index]

    with pytest.raises(api.DataProfileError) as exc_info:
        profile.column("missing")
    assert exc_info.value.code == "DATA_PROFILE_COLUMN_UNKNOWN"

    with pytest.raises(api.DataProfileError) as exc_info:
        api.build_data_profile(
            frame=pd.DataFrame({"x": [1]}),
            dataset_ref=_dataset_ref(api),
            declared_metadata={"missing": {"measurement_level": "nominal"}},
        )
    assert exc_info.value.code == "DATA_PROFILE_METADATA_COLUMN_UNKNOWN"


def test_dataset_identity_rejects_non_digest_content_fingerprints() -> None:
    api = _profile_api()

    with pytest.raises(api.DataProfileError) as exc_info:
        api.DatasetRefV1(
            "run-a",
            "node-a",
            "artifact-a",
            "sha256:truncated",
            "schema:fixture",
            "metadata:fixture",
        )

    assert exc_info.value.code == "DATA_PROFILE_DIGEST_INVALID"


def test_profile_keeps_typed_user_missing_and_weight_declarations() -> None:
    api = _profile_api()
    profile = api.build_data_profile(
        frame=pd.DataFrame({"group": [1, 2, 99], "weight": [1.0, 2.0, 1.0]}),
        dataset_ref=_dataset_ref(api),
        declared_metadata={
            "group": {
                "role": "group",
                "measurement_level": "nominal",
                "user_missing_values": [99],
            },
            "__dataset__": {
                "weight": {"column": "weight", "kind": "frequency"},
                "split": {"columns": ["group"]},
            },
        },
    )

    group = profile.column("group")
    assert group.declared.user_missing_values == (99,)
    assert group.declared.role == "group"
    assert profile.declarations.weight.column == "weight"
    assert profile.declarations.split.columns == ("group",)


def test_metadata_loss_manifest_never_claims_csv_round_trip_for_custom_metadata() -> None:
    from workbench.metadata import build_metadata_loss_manifest

    manifest = build_metadata_loss_manifest(
        source_format="workbench-json",
        target_format="csv",
        metadata={
            "score": {
                "dtype": "float64",
                "variable_label": "Outcome",
                "value_labels": {"1": "yes"},
                "measurement_level": "scale",
                "sensitivity": "public",
            }
        },
    )

    assert manifest.schema_version == "metadata-loss-manifest/v1"
    by_field = {item.field: item for item in manifest.items}
    assert by_field["score.dtype"].status == "converted"
    assert by_field["score.variable_label"].status == "dropped"
    assert by_field["score.value_labels"].status == "dropped"
    assert by_field["score.measurement_level"].status == "dropped"
    assert by_field["score.sensitivity"].status == "dropped"
    assert all(item.reason for item in manifest.items)
    assert manifest.has_loss is True


def test_metadata_loss_manifest_marks_unknown_target_format_not_supported() -> None:
    from workbench.metadata import build_metadata_loss_manifest

    manifest = build_metadata_loss_manifest(
        source_format="workbench-json",
        target_format="future-format",
        metadata={"score": {"dtype": "float64"}},
    )

    assert len(manifest.items) == 1
    assert manifest.items[0].status == "not_supported"
    assert "future-format" in manifest.items[0].reason


def test_metadata_registry_requires_server_owned_content_schema_and_index_provenance() -> None:
    from workbench.metadata import MetadataRegistryV1, metadata_revision_digest

    metadata = {"columns": {"score": {"variable_label": "caller forged"}}}
    payload = {
        "payload_schema": "workbench.data-metadata",
        "schema_version": 1,
        "confirmed": True,
        "schema_revision": "schema:server",
        "metadata_revision": metadata_revision_digest(metadata, schema_revision="schema:server"),
        "source": {
            "run_id": "run-a",
            "node_id": "node-a",
            "artifact_id": "artifact-a",
            "sha256": "f" * 64,
        },
        "schema_artifact": {
            "artifact_id": "schema-artifact",
            "sha256": "e" * 64,
        },
        "metadata_artifact": {
            "artifact_id": "metadata-artifact",
            "path": "metadata/registry.json",
            "sha256": "d" * 64,
        },
        "metadata_index": {"path": "artifacts_index.json", "sha256": "c" * 64},
        "metadata": metadata,
    }

    with pytest.raises(Exception, match="server-owned|provenance|source|artifact|index"):
        MetadataRegistryV1.from_payload(
            payload,
            source_run_id="run-a",
            source_node_id="node-a",
            source_artifact_id="artifact-a",
            source_content_sha256="a" * 64,
            schema_artifact_id="schema-artifact",
            schema_artifact_sha256="e" * 64,
            metadata_artifact_id="metadata-artifact",
            metadata_artifact_path="metadata/registry.json",
            metadata_artifact_sha256="d" * 64,
            metadata_index_sha256="c" * 64,
        )


def test_metadata_declarations_reject_value_label_and_total_payload_overflow() -> None:
    from workbench.metadata import normalize_declared_metadata

    labels = {str(index): "label" for index in range(300)}
    with pytest.raises(Exception, match="bound|label|size|exceed"):
        normalize_declared_metadata(
            {"score": {"value_labels": labels}},
            columns=("score",),
        )
