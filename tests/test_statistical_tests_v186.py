from __future__ import annotations

import pytest
import pandas as pd
import workbench.statistical_tests as statistical_tests

from workbench.statistical_tests import (
    StatisticalTestContractError,
    cohens_d,
    eta_squared,
    one_sample_t_test,
    omega_squared,
    paired_t_test,
    posthoc_anova,
    variance_and_normality_tests,
    wilcoxon_signed_rank,
    run_statistical_tests,
)


GROUPS = {
    "control": [1.0, 1.2, 0.9, 1.1, 1.0],
    "treatment_a": [2.0, 2.1, 1.9, 2.2, 2.0],
    "treatment_b": [3.0, 3.1, 2.9, 3.2, 3.0],
}


def assert_evidence_shape(result: dict[str, object]) -> None:
    assert result["test_version"] == 1
    assert "assumptions" in result
    assert "warnings" in result
    assert "effect_size" in result
    assert "statistic" in result
    assert "p_value" in result


def test_posthoc_anova_supports_tukey_and_bonferroni_with_correction_scope() -> None:
    tukey = posthoc_anova(GROUPS, correction="tukey")
    bonferroni = posthoc_anova(GROUPS, correction="bonferroni")

    assert_evidence_shape(tukey)
    assert_evidence_shape(bonferroni)
    assert tukey["test_type"] == "anova_posthoc"
    assert tukey["correction"] == "tukey"
    assert bonferroni["correction"] == "bonferroni"
    assert len(tukey["comparisons"]) == 3
    assert tukey["family"] == "all_group_pairs"


def test_effect_sizes_are_typed_and_nonzero_for_known_difference() -> None:
    d = cohens_d(GROUPS["control"], GROUPS["treatment_a"])
    eta = eta_squared(GROUPS)
    omega = omega_squared(GROUPS)

    assert d["effect_size_name"] == "cohens_d"
    assert d["value"] < 0
    assert eta["effect_size_name"] == "eta_squared"
    assert eta["value"] > 0
    assert omega["effect_size_name"] == "omega_squared"
    assert omega["value"] > 0


def test_one_sample_paired_and_signed_rank_tests_share_evidence_schema() -> None:
    one = one_sample_t_test([1.0, 1.2, 0.8, 1.1], population_mean=0.0)
    paired = paired_t_test([1.0, 1.1, 0.9, 1.2], [1.2, 1.3, 1.1, 1.4])
    signed = wilcoxon_signed_rank([1.0, 1.1, 0.9, 1.2], [1.2, 1.3, 1.1, 1.4])

    for result in (one, paired, signed):
        assert_evidence_shape(result)
        assert result["nobs"] == 4
    assert one["test_type"] == "one_sample_t_test"
    assert paired["test_type"] == "paired_t_test"
    assert signed["test_type"] == "wilcoxon_signed_rank"


def test_variance_and_normality_results_include_assumptions_and_warnings() -> None:
    results = variance_and_normality_tests(GROUPS)

    assert {result["test_type"] for result in results} == {
        "levene",
        "bartlett",
        "shapiro_wilk",
    }
    assert all("assumptions" in result and "warnings" in result for result in results)


def test_new_statistics_fail_closed_on_empty_or_nonfinite_input() -> None:
    with pytest.raises(ValueError, match="finite"):
        one_sample_t_test([1.0, float("nan")], population_mean=0.0)
    with pytest.raises(ValueError, match="at least two"):
        posthoc_anova({"only": [1.0]}, correction="tukey")


def test_statistics_evidence_packet_is_typed_and_keeps_independent_results() -> None:
    results = [
        one_sample_t_test([1.0, 1.2, 0.8, 1.1], population_mean=0.0),
        *variance_and_normality_tests(GROUPS),
    ]

    builder = getattr(statistical_tests, "build_statistics_evidence_packet", None)
    assert callable(builder), "statistics evidence packet producer is missing"
    packet = builder(
        results,
        dataset_sha256="a" * 64,
        lineage_parent="prediction:dataset_snapshot",
    )

    assert packet["payload_schema"] == "workbench.statistics.evidence-packet"
    assert packet["schema_version"] == 1
    assert packet["dataset_ref"] == {"dataset_sha256": "a" * 64}
    assert packet["lineage_parent"] == "prediction:dataset_snapshot"
    assert {row["test_type"] for row in packet["results"]} == {
        "one_sample_t_test",
        "levene",
        "bartlett",
        "shapiro_wilk",
    }
    assert all("effect_size" in row and "assumptions" in row for row in packet["results"])


def test_normal_statistical_loop_exposes_advanced_evidence_family() -> None:
    frame = pd.DataFrame(
        {
            "y": [1.0, 1.2, 0.9, 2.0, 2.2, 1.8, 3.0, 3.1, 2.9],
            "region": ["north"] * 3 + ["south"] * 3 + ["west"] * 3,
        }
    )

    results = run_statistical_tests(
        frame,
        analysis_columns=["y", "region"],
        dataset_sha256="a" * 64,
        lineage_parent="cleaned_dataset",
    )

    evidence = results["evidence"]
    assert evidence["payload_schema"] == "workbench.statistics.evidence-packet"
    test_types = {row["test_type"] for row in evidence["results"]}
    assert {"anova_posthoc", "cohens_d", "levene", "bartlett", "shapiro_wilk"} <= test_types
    assert all("assumptions" in row and "warnings" in row for row in evidence["results"])


def test_reference_and_pairing_semantics_are_required_for_special_tests() -> None:
    frame = pd.DataFrame(
        {
            "before": [1.0, 1.2, 0.9, 1.1],
            "after": [1.2, 1.3, 1.1, 1.4],
        }
    )
    without_semantics = run_statistical_tests(
        frame,
        analysis_columns=["before", "after"],
        dataset_sha256="b" * 64,
        lineage_parent="cleaned_dataset",
    )
    without_types = {row["test_type"] for row in without_semantics["evidence"]["results"]}
    assert not {"one_sample_t_test", "paired_t_test", "wilcoxon_signed_rank"} & without_types

    with_semantics = run_statistical_tests(
        frame,
        analysis_columns=["before", "after"],
        dataset_sha256="b" * 64,
        lineage_parent="cleaned_dataset",
        reference_means={"before": 0.0},
        paired_columns=[("before", "after")],
    )
    with_types = {row["test_type"] for row in with_semantics["evidence"]["results"]}
    assert {"one_sample_t_test", "paired_t_test", "wilcoxon_signed_rank"} <= with_types


def test_paired_test_request_fails_closed_when_pair_columns_are_not_declared() -> None:
    frame = pd.DataFrame({"before": [1.0, 1.2, 0.9], "after": [1.2, 1.3, 1.1]})

    with pytest.raises(StatisticalTestContractError, match="paired column"):
        run_statistical_tests(
            frame,
            analysis_columns=["before", "after"],
            paired_columns=[("before", "missing_id")],
        )
