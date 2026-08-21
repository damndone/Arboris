from __future__ import annotations

import pytest

from workbench.evidence.consumer_adapters import default_projection_registry
from workbench.evidence.coverage import build_consumer_coverage
from workbench.evidence.provider_projection_adapters import provider_projection_registry_from_catalog
from workbench.providers.catalog import load_builtin_catalog


def test_builtin_provider_projection_identity_sentinel() -> None:
    catalog = load_builtin_catalog()
    declared_paths = [
        (provider, path)
        for provider in catalog.providers
        for path in provider.exposure_paths
    ]

    assert len(catalog.providers) == 8
    report = build_consumer_coverage(catalog, default_projection_registry())
    expected_identity = tuple(
        (provider.provider_id, path.path_id, consumer_id, projection_ref)
        for provider, path in declared_paths
        for consumer_id, projection_ref in sorted(path.projection_refs.items())
    )
    actual_identity = tuple(
        (
            row.raw_key.provider_id,
            row.raw_key.exposure_path,
            row.raw_key.consumer_id,
            row.projection_ref,
        )
        for row in report.rows
    )

    assert len(report.rows) == 20
    assert actual_identity == expected_identity
    assert len(set(actual_identity)) == len(actual_identity)
    assert report.path_class_counts == {"composable": 17, "direct": 3}
    assert {(row.status, row.reason) for row in report.rows} == {
        ("covered", "projection_registered"),
    }


def test_value_equivalent_catalog_clone_is_not_server_owned() -> None:
    catalog = load_builtin_catalog()
    clone = catalog._replace(
        providers=tuple(catalog.providers),
        source_filenames=tuple(catalog.source_filenames),
    )

    assert clone == catalog
    assert clone is not catalog
    with pytest.raises(ValueError, match="PROJECTION_CATALOG_UNTRUSTED"):
        provider_projection_registry_from_catalog(clone)
