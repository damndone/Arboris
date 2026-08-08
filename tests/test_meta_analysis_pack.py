from __future__ import annotations

import copy
import math
import shutil
import subprocess

import numpy as np
import pytest
from scipy import stats
from statsmodels.stats import meta_analysis as sm_meta

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.meta_analysis import (
    META_ANALYSIS_CONTRACT,
    META_ANALYSIS_CONTRACT_VERSION,
    META_ANALYSIS_OPERATION_IDS,
    MetaAnalysisResultEnvelope,
    compute_meta_analysis_evidence_digest,
    make_meta_analysis_envelope,
)
from workbench.engine.packs.meta_analysis import (
    MetaAnalysisPackError,
    combine_effects,
    convert_effect_size,
)


def _direct_studies() -> list[dict[str, float | str]]:
    return [
        {"study_id": "study-a", "yi": 0.20, "vi": 0.04},
        {"study_id": "study-b", "yi": 0.80, "vi": 0.09},
        {"study_id": "study-c", "yi": 1.10, "vi": 0.16},
    ]


def test_meta_operations_are_closed_and_envelope_round_trips_with_digest() -> None:
    assert META_ANALYSIS_OPERATION_IDS == {"meta.effect_size", "meta.combine"}

    packet = combine_effects(
        _direct_studies(),
        effect_measure="direct",
        method="fixed_effect",
        alpha=0.05,
    )

    assert packet["contract"] == META_ANALYSIS_CONTRACT
    assert packet["contract_version"] == META_ANALYSIS_CONTRACT_VERSION
    assert packet["operation_id"] == "meta.combine"
    assert len(packet["evidence_digest"]) == 64
    assert packet["evidence_digest"] == compute_meta_analysis_evidence_digest(packet)
    assert MetaAnalysisResultEnvelope.from_dict(packet).to_dict() == packet

    tampered = copy.deepcopy(packet)
    tampered["result"]["pooled_effect"] += 0.01
    with pytest.raises(ContractError, match="evidence_digest"):
        MetaAnalysisResultEnvelope.from_dict(tampered)


@pytest.mark.parametrize(
    "mutation",
    [
        "negative_variance",
        "duplicate_study_id",
        "mismatched_effect_measure",
        "unstable_study_id",
        "unsafe_nested_payload",
    ],
)
def test_meta_envelope_recursively_validates_every_study_row(mutation: str) -> None:
    packet = combine_effects(
        _direct_studies(),
        effect_measure="direct",
        method="fixed_effect",
        alpha=0.05,
    )
    mutated_result = copy.deepcopy(packet["result"])
    row = mutated_result["studies"][0]
    if mutation == "negative_variance":
        row["variance"] = -0.1
    elif mutation == "duplicate_study_id":
        row["study_id"] = mutated_result["studies"][1]["study_id"]
    elif mutation == "mismatched_effect_measure":
        row["effect_measure"] = "log_odds_ratio"
    elif mutation == "unstable_study_id":
        row["study_id"] = ""
    else:
        row["unsafe_nested_payload"] = {"raw": {"unexpected": True}}

    with pytest.raises(ContractError):
        make_meta_analysis_envelope(
            operation_id=packet["operation_id"],
            status=packet["status"],
            reason_code=packet["reason_code"],
            result=mutated_result,
        )

    tampered = copy.deepcopy(packet)
    tampered["result"] = mutated_result
    tampered["evidence_digest"] = compute_meta_analysis_evidence_digest(tampered)
    with pytest.raises(ContractError):
        MetaAnalysisResultEnvelope.from_dict(tampered)


def test_direct_effect_and_variance_aliases_must_agree_when_both_are_present() -> None:
    inconsistent = [
        {"study_id": "alias-a", "yi": 0.1, "effect": 0.9, "vi": 0.1, "variance": 0.1},
        {"study_id": "alias-b", "yi": 0.2, "vi": 0.2},
    ]
    with pytest.raises(MetaAnalysisPackError, match="AMBIGUOUS_DIRECT_FIELD"):
        combine_effects(
            inconsistent,
            effect_measure="direct",
            method="fixed_effect",
            alpha=0.05,
        )

    consistent = [
        {"study_id": "alias-a", "yi": 0.1, "effect": 0.1, "vi": 0.1, "variance": 0.1},
        {"study_id": "alias-b", "yi": 0.2, "effect": 0.2, "vi": 0.2, "variance": 0.2},
    ]
    packet = combine_effects(
        consistent,
        effect_measure="direct",
        method="fixed_effect",
        alpha=0.05,
    )
    assert packet["result"]["study_count"] == 2


@pytest.mark.parametrize("measure", ["mean_difference", "standardized_mean_difference"])
def test_inapplicable_continuity_correction_is_rejected_for_mean_and_smd(measure: str) -> None:
    studies = [
        {
            "study_id": "summary-a",
            "mean1": 1.0,
            "sd1": 1.2,
            "n1": 20,
            "mean2": 0.5,
            "sd2": 1.1,
            "n2": 22,
        },
        {
            "study_id": "summary-b",
            "mean1": 1.4,
            "sd1": 1.0,
            "n1": 24,
            "mean2": 0.7,
            "sd2": 1.3,
            "n2": 26,
        },
    ]

    with pytest.raises(MetaAnalysisPackError, match="INAPPLICABLE_CORRECTION"):
        convert_effect_size(
            studies,
            effect_measure=measure,
            alpha=0.05,
            continuity_correction=0.5,
        )


def test_converted_evidence_rejects_a_conflicting_continuity_correction() -> None:
    studies = [
        {"study_id": "zero-a", "count1": 0, "nobs1": 40, "count2": 8, "nobs2": 35},
        {"study_id": "zero-b", "count1": 20, "nobs1": 50, "count2": 9, "nobs2": 45},
    ]
    converted = convert_effect_size(
        studies,
        effect_measure="log_risk_ratio",
        alpha=0.05,
        continuity_correction=0.5,
    )

    with pytest.raises(MetaAnalysisPackError, match="CORRECTION"):
        combine_effects(
            converted,
            effect_measure="log_risk_ratio",
            method="fixed_effect",
            alpha=0.05,
            continuity_correction=0.25,
        )


def test_converted_evidence_preserves_a_matching_continuity_correction() -> None:
    studies = [
        {"study_id": "zero-a", "count1": 0, "nobs1": 40, "count2": 8, "nobs2": 35},
        {"study_id": "zero-b", "count1": 20, "nobs1": 50, "count2": 9, "nobs2": 45},
    ]
    converted = convert_effect_size(
        studies,
        effect_measure="log_risk_ratio",
        alpha=0.05,
        continuity_correction=0.5,
    )

    combined = combine_effects(
        converted,
        effect_measure="log_risk_ratio",
        method="fixed_effect",
        alpha=0.05,
        zero_correction=0.5,
    )
    assert combined["result"]["conversion"]["continuity_correction"] == 0.5
    assert combined["result"]["conversion"]["input"] == "meta.effect_size_evidence"


@pytest.mark.parametrize(
    "mutation",
    [
        "ci_method",
        "ci_missing",
        "heterogeneity_missing",
        "prediction_missing",
        "prediction_unordered",
        "weights_short",
        "loo_unknown_field",
        "loo_bad_id",
        "loo_bad_scale",
        "loo_bad_value_type",
        "loo_bad_bounds",
    ],
)
def test_meta_combine_envelope_deep_validates_nested_evidence(mutation: str) -> None:
    studies = _direct_studies()
    if mutation.startswith("loo_"):
        studies = [
            *studies,
            {"study_id": "study-d", "yi": 0.4, "vi": 0.1},
        ]
    packet = combine_effects(
        studies,
        effect_measure="direct",
        method="derSimonian_laird",
        alpha=0.05,
        ci_method="t" if mutation.startswith("loo_") else "normal_z",
        leave_one_out=mutation.startswith("loo_"),
    )
    tampered = copy.deepcopy(packet)
    result = tampered["result"]
    if mutation == "ci_method":
        result["ci_method"] = "unsupported"
    elif mutation == "ci_missing":
        del result["ci"]["lower"]
    elif mutation == "heterogeneity_missing":
        del result["heterogeneity"]["Q"]
    elif mutation == "prediction_missing":
        del result["prediction_interval"]["upper"]
    elif mutation == "prediction_unordered":
        result["prediction_interval"]["lower"] = result["prediction_interval"]["upper"] + 1.0
    elif mutation == "weights_short":
        result["weights"]["fixed"] = result["weights"]["fixed"][:-1]
    elif mutation == "loo_unknown_field":
        result["leave_one_out"][0]["unsafe"] = {"nested": True}
    elif mutation == "loo_bad_id":
        result["leave_one_out"][0]["excluded_study_id"] = "not-a-study"
    elif mutation == "loo_bad_scale":
        result["leave_one_out"][0]["effect_measure"] = "log_odds_ratio"
    elif mutation == "loo_bad_value_type":
        result["leave_one_out"][0]["pooled_effect"] = "not-finite"
    else:
        result["leave_one_out"][0]["ci"]["lower"] = result["leave_one_out"][0]["ci"]["upper"] + 1.0
    tampered["evidence_digest"] = compute_meta_analysis_evidence_digest(tampered)

    with pytest.raises(ContractError):
        MetaAnalysisResultEnvelope.from_dict(tampered)


@pytest.mark.parametrize(
    ("status", "reason_code"),
    [
        ("completed", "META_ANALYSIS_REJECTED"),
        ("rejected", "META_ANALYSIS_COMPLETED"),
        ("failed", "META_ANALYSIS_REJECTED"),
    ],
)
def test_meta_status_and_reason_code_must_be_a_matching_pair(status: str, reason_code: str) -> None:
    packet = combine_effects(
        _direct_studies(),
        effect_measure="direct",
        method="fixed_effect",
        alpha=0.05,
    )
    tampered = copy.deepcopy(packet)
    tampered["status"] = status
    tampered["reason_code"] = reason_code
    tampered["evidence_digest"] = compute_meta_analysis_evidence_digest(tampered)

    with pytest.raises(ContractError):
        MetaAnalysisResultEnvelope.from_dict(tampered)


@pytest.mark.parametrize("field", ["status", "reason_code"])
def test_unhashable_meta_status_or_reason_code_raises_contract_error(field: str) -> None:
    packet = combine_effects(
        _direct_studies(),
        effect_measure="direct",
        method="fixed_effect",
        alpha=0.05,
    )
    tampered = copy.deepcopy(packet)
    tampered[field] = [] if field == "status" else {"reason": "META_ANALYSIS_COMPLETED"}
    tampered["evidence_digest"] = compute_meta_analysis_evidence_digest(tampered)

    with pytest.raises(ContractError):
        MetaAnalysisResultEnvelope.from_dict(tampered)


def test_direct_fixed_effects_expose_pooled_estimate_weights_and_heterogeneity() -> None:
    studies = _direct_studies()
    packet = combine_effects(
        studies,
        effect_measure="direct",
        method="fixed_effect",
        alpha=0.05,
    )
    result = packet["result"]

    yi = np.asarray([row["yi"] for row in studies], dtype=float)
    vi = np.asarray([row["vi"] for row in studies], dtype=float)
    weights = 1.0 / vi
    pooled = float(np.sum(weights * yi) / np.sum(weights))
    se = float(np.sqrt(1.0 / np.sum(weights)))
    q = float(np.sum(weights * (yi - pooled) ** 2))
    df = len(studies) - 1
    z = float(stats.norm.ppf(0.975))
    statsmodels_oracle = sm_meta.combine_effects(
        yi,
        vi,
        method_re="chi2",
        use_t=False,
        alpha=0.05,
    )

    assert result["effect_measure"] == "direct"
    assert result["method"] == "fixed_effect"
    assert result["pooled_effect"] == pytest.approx(pooled)
    assert result["pooled_se"] == pytest.approx(se)
    assert result["pooled_effect"] == pytest.approx(float(statsmodels_oracle.mean_effect_fe))
    assert result["pooled_se"] == pytest.approx(float(statsmodels_oracle.sd_eff_w_fe))
    assert result["ci"] == {
        "lower": pytest.approx(pooled - z * se),
        "upper": pytest.approx(pooled + z * se),
    }
    assert result["q"] == pytest.approx(q)
    assert result["heterogeneity"]["df"] == df
    assert result["heterogeneity"]["p_value"] == pytest.approx(stats.chi2.sf(q, df))
    assert result["tau2"] == 0.0
    assert result["i2"] == pytest.approx(max(0.0, (q - df) / q))
    assert result["h2"] == pytest.approx(q / df)
    assert sum(row["relative_weight"] for row in result["studies"]) == pytest.approx(1.0)
    assert result["prediction_interval"]["lower"] < result["prediction_interval"]["upper"]


@pytest.mark.parametrize("method,sm_method", [("derSimonian_laird", "chi2"), ("paule_mandel", "iterated")])
def test_direct_random_effect_methods_match_statsmodels_fixed_input_oracle(
    method: str, sm_method: str
) -> None:
    studies = [
        {"study_id": "s1", "yi": -0.25, "vi": 0.04},
        {"study_id": "s2", "yi": 0.10, "vi": 0.06},
        {"study_id": "s3", "yi": 0.95, "vi": 0.09},
        {"study_id": "s4", "yi": 1.35, "vi": 0.12},
    ]
    packet = combine_effects(
        studies,
        effect_measure="direct",
        method=method,
        alpha=0.05,
    )
    result = packet["result"]
    oracle = sm_meta.combine_effects(
        np.asarray([row["yi"] for row in studies], dtype=float),
        np.asarray([row["vi"] for row in studies], dtype=float),
        method_re=sm_method,
        use_t=False,
        alpha=0.05,
    )

    assert result["pooled_effect"] == pytest.approx(oracle.mean_effect_re, rel=2e-5, abs=2e-8)
    assert result["pooled_se"] == pytest.approx(oracle.sd_eff_w_re, rel=2e-5, abs=2e-8)
    assert result["tau2"] == pytest.approx(max(0.0, float(oracle.tau2)), rel=2e-5, abs=2e-8)


@pytest.mark.parametrize(
    ("studies", "method", "alpha", "reason_code"),
    [
        ([], "fixed_effect", 0.05, "META_TOO_FEW_STUDIES"),
        ([{"study_id": "only", "yi": 0.1, "vi": 0.1}], "fixed_effect", 0.05, "META_TOO_FEW_STUDIES"),
        ([{"study_id": "a", "yi": 0.1, "vi": 0.1}, {"study_id": "a", "yi": 0.2, "vi": 0.2}], "fixed_effect", 0.05, "META_DUPLICATE_STUDY_ID"),
        ([{"study_id": "a", "yi": 0.1, "vi": 0.0}, {"study_id": "b", "yi": 0.2, "vi": 0.2}], "fixed_effect", 0.05, "META_NONPOSITIVE_VARIANCE"),
        ([{"study_id": "a", "yi": 0.1, "vi": 0.1}, {"study_id": "b", "yi": 0.2, "vi": math.nan}], "fixed_effect", 0.05, "META_NONFINITE_VALUE"),
        (_direct_studies(), None, 0.05, "META_INVALID_METHOD"),
        (_direct_studies(), "fixed_effect", None, "META_INVALID_ALPHA"),
        (_direct_studies(), "fixed_effect", 1.0, "META_INVALID_ALPHA"),
    ],
)
def test_direct_combine_rejects_unstable_or_undeclared_inputs(
    studies: list[dict[str, object]],
    method: str | None,
    alpha: float | None,
    reason_code: str,
) -> None:
    with pytest.raises(MetaAnalysisPackError) as exc_info:
        combine_effects(
            studies,
            effect_measure="direct",
            method=method,
            alpha=alpha,
        )
    assert exc_info.value.reason_code == reason_code


def test_direct_combine_rejects_mixed_effect_scales_and_unbounded_study_count() -> None:
    mixed = _direct_studies()
    mixed[1]["effect_measure"] = "log_odds_ratio"
    with pytest.raises(MetaAnalysisPackError, match="MIXED_EFFECT_SCALE"):
        combine_effects(mixed, effect_measure="direct", method="fixed_effect", alpha=0.05)

    too_many = [
        {"study_id": f"s-{index}", "yi": 0.1, "vi": 0.1}
        for index in range(1001)
    ]
    with pytest.raises(MetaAnalysisPackError, match="STUDY_COUNT"):
        combine_effects(too_many, effect_measure="direct", method="fixed_effect", alpha=0.05)


def test_mean_difference_converter_emits_complete_effect_variance_rows() -> None:
    studies = [
        {
            "study_id": "md-a",
            "mean1": 12.0,
            "sd1": 2.0,
            "n1": 20,
            "mean2": 10.0,
            "sd2": 3.0,
            "n2": 30,
        },
        {
            "study_id": "md-b",
            "mean_treatment": 8.0,
            "sd_treatment": 1.5,
            "n_treatment": 18,
            "mean_control": 7.0,
            "sd_control": 2.5,
            "n_control": 22,
        },
    ]
    packet = convert_effect_size(
        studies,
        effect_measure="mean_difference",
        alpha=0.05,
    )
    result = packet["result"]

    assert packet["operation_id"] == "meta.effect_size"
    assert result["effect_measure"] == "mean_difference"
    assert result["conversion"]["variance_semantics"] == "unequal_group_sampling_variance"
    assert [row["effect"] for row in result["studies"]] == pytest.approx([2.0, 1.0])
    assert [row["variance"] for row in result["studies"]] == pytest.approx(
        [2.0**2 / 20 + 3.0**2 / 30, 1.5**2 / 18 + 2.5**2 / 22]
    )

    combined = combine_effects(
        packet,
        effect_measure="mean_difference",
        method="fixed_effect",
        alpha=0.05,
    )
    assert combined["result"]["effect_measure"] == "mean_difference"
    assert combined["result"]["study_count"] == 2


def test_standardized_mean_difference_matches_statsmodels_effectsize_smd() -> None:
    studies = [
        {
            "study_id": "smd-a",
            "mean1": 12.0,
            "sd1": 2.0,
            "n1": 20,
            "mean2": 10.0,
            "sd2": 3.0,
            "n2": 30,
        },
        {
            "study_id": "smd-b",
            "mean1": 8.0,
            "sd1": 1.5,
            "n1": 18,
            "mean2": 7.0,
            "sd2": 2.5,
            "n2": 22,
        },
    ]
    packet = convert_effect_size(
        studies,
        effect_measure="standardized_mean_difference",
        alpha=0.05,
    )
    result = packet["result"]
    expected_effect, expected_variance = sm_meta.effectsize_smd(
        np.asarray([12.0, 8.0]),
        np.asarray([2.0, 1.5]),
        np.asarray([20, 18]),
        np.asarray([10.0, 7.0]),
        np.asarray([3.0, 2.5]),
        np.asarray([30, 22]),
    )

    assert result["conversion"]["effect_semantics"] == "hedges_g_bias_corrected"
    assert [row["effect"] for row in result["studies"]] == pytest.approx(expected_effect.tolist())
    assert [row["variance"] for row in result["studies"]] == pytest.approx(expected_variance.tolist())


@pytest.mark.parametrize(
    ("measure", "statistic", "expected_key"),
    [
        ("log_risk_ratio", "risk-ratio", "log_risk_ratio"),
        ("log_odds_ratio", "odds-ratio", "log_odds_ratio"),
    ],
)
def test_binary_effect_converters_match_statsmodels_without_zero_cells(
    measure: str, statistic: str, expected_key: str
) -> None:
    studies = [
        {
            "study_id": "bin-a",
            "count1": 12,
            "nobs1": 40,
            "count2": 8,
            "nobs2": 35,
        },
        {
            "study_id": "bin-b",
            "count1": 20,
            "nobs1": 50,
            "count2": 9,
            "nobs2": 45,
        },
    ]
    packet = convert_effect_size(studies, effect_measure=measure, alpha=0.05)
    result = packet["result"]
    expected_effect, expected_variance = sm_meta.effectsize_2proportions(
        np.asarray([12, 20]),
        np.asarray([40, 50]),
        np.asarray([8, 9]),
        np.asarray([35, 45]),
        statistic=statistic,
    )

    assert result["effect_measure"] == expected_key
    assert result["conversion"]["continuity_correction"] is None
    assert [row["effect"] for row in result["studies"]] == pytest.approx(expected_effect.tolist())
    assert [row["variance"] for row in result["studies"]] == pytest.approx(expected_variance.tolist())


@pytest.mark.parametrize("measure", ["log_risk_ratio", "log_odds_ratio"])
def test_binary_effect_converters_require_explicit_zero_cell_correction(measure: str) -> None:
    studies = [
        {"study_id": "zero-a", "count1": 0, "nobs1": 40, "count2": 8, "nobs2": 35},
        {"study_id": "zero-b", "count1": 20, "nobs1": 50, "count2": 9, "nobs2": 45},
    ]
    with pytest.raises(MetaAnalysisPackError) as exc_info:
        convert_effect_size(studies, effect_measure=measure, alpha=0.05)
    assert exc_info.value.reason_code == "META_ZERO_CELL_REQUIRES_CORRECTION"

    packet = convert_effect_size(
        studies,
        effect_measure=measure,
        alpha=0.05,
        continuity_correction=0.5,
    )
    result = packet["result"]
    assert result["conversion"]["continuity_correction"] == 0.5
    assert result["conversion"]["correction_applied_count"] == 1
    assert all(math.isfinite(row["effect"]) and row["variance"] > 0 for row in result["studies"])
    expected_effect, expected_variance = sm_meta.effectsize_2proportions(
        np.asarray([0]),
        np.asarray([40]),
        np.asarray([8]),
        np.asarray([35]),
        statistic="risk-ratio" if measure == "log_risk_ratio" else "odds-ratio",
        zero_correction=0.5,
    )
    assert result["studies"][0]["effect"] == pytest.approx(float(expected_effect[0]))
    assert result["studies"][0]["variance"] == pytest.approx(float(expected_variance[0]))
    no_correction_effect, no_correction_variance = sm_meta.effectsize_2proportions(
        np.asarray([20]),
        np.asarray([50]),
        np.asarray([9]),
        np.asarray([45]),
        statistic="risk-ratio" if measure == "log_risk_ratio" else "odds-ratio",
    )
    assert result["studies"][1]["effect"] == pytest.approx(float(no_correction_effect[0]))
    assert result["studies"][1]["variance"] == pytest.approx(float(no_correction_variance[0]))


@pytest.mark.parametrize(
    ("measure", "study", "reason_code"),
    [
        (
            "mean_difference",
            {"study_id": "bad", "mean1": 1.0, "sd1": 1.0, "n1": 10},
            "META_MISSING_SUMMARY_FIELD",
        ),
        (
            "log_risk_ratio",
            {"study_id": "bad", "count1": 12, "nobs1": 10, "count2": 2, "nobs2": 10},
            "META_INVALID_COUNT",
        ),
        (
            "standardized_mean_difference",
            {
                "study_id": "bad",
                "mean1": 1.0,
                "sd1": 0.0,
                "n1": 10,
                "mean2": 1.0,
                "sd2": 0.0,
                "n2": 10,
            },
            "META_DEGENERATE_SUMMARY",
        ),
    ],
)
def test_converters_reject_incomplete_invalid_or_degenerate_summary_fields(
    measure: str, study: dict[str, object], reason_code: str
) -> None:
    with pytest.raises(MetaAnalysisPackError) as exc_info:
        convert_effect_size([study, {**study, "study_id": "other"}], effect_measure=measure, alpha=0.05)
    assert exc_info.value.reason_code == reason_code


def test_leave_one_out_is_explicit_bounded_and_keeps_method_scale_provenance() -> None:
    studies = [
        {"study_id": "loo-a", "yi": -0.2, "vi": 0.04},
        {"study_id": "loo-b", "yi": 0.1, "vi": 0.05},
        {"study_id": "loo-c", "yi": 0.9, "vi": 0.08},
        {"study_id": "loo-d", "yi": 1.2, "vi": 0.1},
    ]
    packet = combine_effects(
        studies,
        effect_measure="direct",
        method="derSimonian_laird",
        alpha=0.05,
        ci_method="t",
        leave_one_out=True,
    )
    result = packet["result"]
    loo = result["leave_one_out"]

    assert len(loo) == len(studies)
    assert [row["excluded_study_id"] for row in loo] == [row["study_id"] for row in studies]
    assert all(row["method"] == "derSimonian_laird" for row in loo)
    assert all(row["effect_measure"] == "direct" for row in loo)
    assert all(row["study_count"] == len(studies) - 1 for row in loo)
    assert all({"pooled_effect", "pooled_se", "ci", "tau2", "q", "i2"} <= set(row) for row in loo)
    assert result["influence"]["leave_one_out"] == loo
    assert result["ci_semantics"]["distribution"] == "student_t"


def test_leave_one_out_rejects_an_uncombinable_two_study_input_and_too_small_bound() -> None:
    studies = _direct_studies()
    with pytest.raises(MetaAnalysisPackError) as exc_info:
        combine_effects(
            studies[:2],
            effect_measure="direct",
            method="fixed_effect",
            alpha=0.05,
            leave_one_out=True,
        )
    assert exc_info.value.reason_code == "META_LOO_TOO_FEW_STUDIES"

    with pytest.raises(MetaAnalysisPackError) as exc_info:
        combine_effects(
            [*studies, {"study_id": "study-d", "yi": 0.4, "vi": 0.1}],
            effect_measure="direct",
            method="fixed_effect",
            alpha=0.05,
            leave_one_out=True,
            max_leave_one_out=2,
        )
    assert exc_info.value.reason_code == "META_OUTPUT_COUNT_EXCEEDED"


def test_hksj_t_interval_semantics_match_statsmodels_random_wls_interval() -> None:
    studies = [
        {"study_id": "hksj-a", "yi": -0.25, "vi": 0.04},
        {"study_id": "hksj-b", "yi": 0.10, "vi": 0.06},
        {"study_id": "hksj-c", "yi": 0.95, "vi": 0.09},
        {"study_id": "hksj-d", "yi": 1.35, "vi": 0.12},
    ]
    packet = combine_effects(
        studies,
        effect_measure="direct",
        method="derSimonian_laird",
        alpha=0.05,
        ci_method="hksj",
    )
    result = packet["result"]
    oracle = sm_meta.combine_effects(
        np.asarray([row["yi"] for row in studies], dtype=float),
        np.asarray([row["vi"] for row in studies], dtype=float),
        method_re="chi2",
        use_t=True,
        alpha=0.05,
    )
    oracle_ci = oracle.conf_int(alpha=0.05, use_t=True)[3]

    assert result["ci"] == {
        "lower": pytest.approx(float(oracle_ci[0]), rel=2e-5, abs=2e-8),
        "upper": pytest.approx(float(oracle_ci[1]), rel=2e-5, abs=2e-8),
    }
    assert result["ci_semantics"]["scale_estimator"] == "hksj"
    assert result["ci_semantics"]["distribution"] == "student_t"


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="base R is not installed")
def test_base_r_oracle_recalculates_fixed_dl_q_and_i2() -> None:
    studies = [
        {"study_id": "r-a", "yi": -0.25, "vi": 0.04},
        {"study_id": "r-b", "yi": 0.10, "vi": 0.06},
        {"study_id": "r-c", "yi": 0.95, "vi": 0.09},
        {"study_id": "r-d", "yi": 1.35, "vi": 0.12},
    ]
    packet = combine_effects(
        studies,
        effect_measure="direct",
        method="derSimonian_laird",
        alpha=0.05,
    )
    result = packet["result"]
    script = """
yi <- c(-0.25, 0.10, 0.95, 1.35)
vi <- c(0.04, 0.06, 0.09, 0.12)
w <- 1 / vi
mu <- sum(w * yi) / sum(w)
Q <- sum(w * (yi - mu)^2)
df <- length(yi) - 1
C <- sum(w) - sum(w^2) / sum(w)
tau2 <- max(0, (Q - df) / C)
wr <- 1 / (vi + tau2)
mur <- sum(wr * yi) / sum(wr)
I2 <- if (Q <= 0) 0 else max(0, (Q - df) / Q)
cat(sprintf("%.17g %.17g %.17g %.17g %.17g\\n", mu, Q, tau2, I2, mur))
"""
    completed = subprocess.run(
        ["Rscript", "--vanilla", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    oracle = [float(value) for value in completed.stdout.split()]

    fixed_packet = combine_effects(
        studies,
        effect_measure="direct",
        method="fixed_effect",
        alpha=0.05,
    )
    assert fixed_packet["result"]["pooled_effect"] == pytest.approx(
        oracle[0], rel=1e-12, abs=1e-12
    )
    assert fixed_packet["result"]["q"] == pytest.approx(
        oracle[1], rel=1e-12, abs=1e-12
    )
    assert result["heterogeneity"]["Q"] == pytest.approx(oracle[1], rel=1e-12, abs=1e-12)
    assert result["tau2"] == pytest.approx(oracle[2], rel=1e-12, abs=1e-12)
    assert result["i2"] == pytest.approx(oracle[3], rel=1e-12, abs=1e-12)
    assert result["pooled_effect"] == pytest.approx(oracle[4], rel=1e-12, abs=1e-12)
