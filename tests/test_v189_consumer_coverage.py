from __future__ import annotations

from workbench.evidence.consumer_adapters import (
    default_projection_registry,
    projection_registry_from_catalog,
)
from workbench.evidence.coverage import build_consumer_coverage
from workbench.providers.catalog import load_builtin_catalog


def test_coverage_denominator_is_derived_from_declared_provider_paths() -> None:
    catalog = load_builtin_catalog()
    report = build_consumer_coverage(catalog, default_projection_registry())

    declared = sum(len(path.projection_refs) for provider in catalog.providers for path in provider.exposure_paths)
    assert len(report.rows) == declared
    assert report.rows
    assert all(row.raw_key.provider_id for row in report.rows)
    assert all(row.raw_key.exposure_path for row in report.rows)
    assert report.coverage_digest


def test_removed_consumer_projection_is_blocked_not_dropped() -> None:
    catalog = load_builtin_catalog()
    registry = default_projection_registry()
    reduced = registry.without("report")

    report = build_consumer_coverage(catalog, reduced)

    report_rows = [row for row in report.rows if row.raw_key.consumer_id == "report"]
    assert report_rows
    assert all(row.status == "blocked" for row in report_rows)
    assert all(row.reason == "projection_missing" for row in report_rows)


def test_exempt_declarations_are_blocked_with_their_reason_preserved() -> None:
    catalog = load_builtin_catalog()
    provider_index = next(
        index for index, item in enumerate(catalog.providers)
        if item.provider_id == "workbench.consumer_projection"
    )
    provider = catalog.providers[provider_index]
    exempt = tuple(
        declaration._replace(
            coverage_status="exempt",
            exemption_reason="consumer adapter is intentionally withheld",
        )
        for declaration in provider.projection_declarations
    )
    forged_provider = provider._replace(projection_declarations=exempt)
    forged_catalog = catalog._replace(
        providers=(
            *catalog.providers[:provider_index],
            forged_provider,
            *catalog.providers[provider_index + 1 :],
        )
    )

    report = build_consumer_coverage(forged_catalog, default_projection_registry())
    rows = [
        row for row in report.rows
        if row.raw_key.provider_id == "workbench.consumer_projection"
    ]
    assert rows
    assert all(row.status == "blocked" for row in rows)
    assert all(row.reason == "projection_exempt" for row in rows)
    assert all(row.coverage_status == "exempt" for row in rows)
    assert all(row.exemption_reason == "consumer adapter is intentionally withheld" for row in rows)


def test_missing_declarations_are_blocked_in_coverage_not_counted_as_covered() -> None:
    catalog = load_builtin_catalog()
    provider_index = next(
        index for index, item in enumerate(catalog.providers)
        if item.provider_id == "workbench.consumer_projection"
    )
    provider = catalog.providers[provider_index]
    forged_provider = provider._replace(projection_declarations=())
    forged_catalog = catalog._replace(
        providers=(
            *catalog.providers[:provider_index],
            forged_provider,
            *catalog.providers[provider_index + 1 :],
        )
    )

    report = build_consumer_coverage(forged_catalog, default_projection_registry())
    rows = [
        row for row in report.rows
        if row.raw_key.provider_id == "workbench.consumer_projection"
    ]
    assert rows
    assert all(row.status == "blocked" for row in rows)
    assert all(row.reason == "projection_declaration_missing" for row in rows)
    assert all(row.coverage_status == "missing" for row in rows)


def test_coverage_has_no_expected_count_constant_or_generic_fallback() -> None:
    report = build_consumer_coverage(load_builtin_catalog(), default_projection_registry())

    assert "expected_count" not in report.to_dict()
    assert all(row.raw_key.consumer_id != "generic" for row in report.rows)


def test_coverage_preserves_path_class_without_promoting_blocked_rows() -> None:
    report = build_consumer_coverage(load_builtin_catalog(), default_projection_registry())

    assert {row.raw_key.path_class for row in report.rows} == {"direct", "composable"}
    assert report.path_class_counts == {"composable": 17, "direct": 3}
    assert report.blocked_count == 0
    assert report.covered_count == 20
    assert all(row.reason == "projection_registered" for row in report.rows)


def test_generic_fallback_cannot_cover_provider_specific_same_named_consumer() -> None:
    catalog = load_builtin_catalog()
    report = build_consumer_coverage(catalog, projection_registry_from_catalog(catalog))

    classification_rows = [
        row for row in report.rows
        if row.raw_key.provider_id == "workbench.classification_ml"
    ]
    generic_rows = [
        row for row in report.rows
        if row.raw_key.provider_id == "workbench.consumer_projection"
    ]
    assert classification_rows
    assert all(row.reason == "projection_missing" for row in classification_rows)
    assert all(row.status == "blocked" for row in classification_rows)
    assert all(row.status == "covered" for row in generic_rows)
