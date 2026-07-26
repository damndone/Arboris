from __future__ import annotations

import importlib

import pytest

from workbench.capability_factory.contracts import SemanticProfile


def _control():
    try:
        return importlib.import_module("workbench.capability_factory.control")
    except ModuleNotFoundError as error:
        pytest.fail(f"CF1 control module is not implemented: {error}")


def test_append_only_control_requires_expected_sequence_and_keeps_history():
    control = _control()
    store = control.AppendOnlyControlStore()

    first = store.append(
        namespace="profile.alpha",
        value={"status": "active"},
        expected_sequence=0,
    )
    second = store.append(
        namespace="profile.alpha",
        value={"status": "revoked"},
        expected_sequence=1,
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert [item.sequence for item in store.history("profile.alpha")] == [1, 2]
    with pytest.raises(control.OptimisticConcurrencyError):
        store.append(
            namespace="profile.alpha",
            value={"status": "stale-write"},
            expected_sequence=1,
        )


def test_control_values_are_snapshotted_and_not_mutable_after_append():
    control = _control()
    value = {"status": "active", "labels": {"scope": "project"}}
    store = control.AppendOnlyControlStore()
    record = store.append(namespace="profile.alpha", value=value, expected_sequence=0)
    value["status"] = "changed-outside-store"

    assert record.value["status"] == "active"
    with pytest.raises(TypeError):
        record.value["status"] = "changed-inside-store"


def test_content_addressed_store_reuses_exact_immutable_content():
    store_module = importlib.import_module("workbench.capability_factory.store")
    store = store_module.ContentAddressedStore()
    profile = SemanticProfile(
        profile_id="profile.alpha",
        revision=1,
        input_kinds=("scalar",),
        operations=("fit",),
        output_facets=("estimate",),
        assumptions=(),
        consumers={
            "report_projection": None,
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
    )

    assert store.put(profile) == profile.content_digest
    assert store.put(profile) == profile.content_digest
    assert store.get(profile.content_digest) is profile
    assert len(store) == 1
