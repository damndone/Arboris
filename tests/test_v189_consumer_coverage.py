from __future__ import annotations

from workbench.evidence.consumer_adapters import default_projection_registry
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


def test_coverage_has_no_expected_count_constant_or_generic_fallback() -> None:
    report = build_consumer_coverage(load_builtin_catalog(), default_projection_registry())

    assert "expected_count" not in report.to_dict()
    assert all(row.raw_key.consumer_id != "generic" for row in report.rows)
