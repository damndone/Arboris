from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _contract_module():
    try:
        from workbench.contracts.model import repeated_measures_anova
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"repeated-measures contract is not implemented yet: {exc}")
    return repeated_measures_anova


def _pack_module():
    try:
        from workbench.engine.packs import repeated_measures_anova
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"repeated-measures pack is not implemented yet: {exc}")
    return repeated_measures_anova


def _repeated_frame() -> pd.DataFrame:
    values = {
        "s1": [10.0, 11.0, 12.5],
        "s2": [11.0, 13.0, 14.0],
        "s3": [9.0, 10.5, 11.0],
        "s4": [12.0, 13.5, 15.0],
    }
    return pd.DataFrame(
        [
            {"response": value, "subject": subject, "within": level}
            for subject, subject_values in values.items()
            for level, value in zip(("pre", "mid", "post"), subject_values)
        ]
    )


def _mixed_frame() -> pd.DataFrame:
    values = {
        "A1": ("A", [10.0, 12.0]),
        "A2": ("A", [11.0, 13.0]),
        "A3": ("A", [9.0, 10.0]),
        "B1": ("B", [20.0, 24.0]),
        "B2": ("B", [21.0, 25.0]),
        "B3": ("B", [19.0, 22.0]),
    }
    return pd.DataFrame(
        [
            {
                "response": value,
                "subject": subject,
                "within": level,
                "between": between,
            }
            for subject, (between, subject_values) in values.items()
            for level, value in zip(("pre", "post"), subject_values)
        ]
    )


def _mixed_three_level_frame() -> pd.DataFrame:
    values = {
        "A1": ("A", [10.5, 13.5, 14.5]),
        "A2": ("A", [10.5, 10.5, 14.5]),
        "A3": ("A", [9.0, 12.0, 16.0]),
        "B1": ("B", [30.5, 46.5, 31.5]),
        "B2": ("B", [30.5, 43.5, 31.5]),
        "B3": ("B", [29.0, 45.0, 33.0]),
    }
    return pd.DataFrame(
        [
            {
                "response": value,
                "subject": subject,
                "within": level,
                "between": between,
            }
            for subject, (between, subject_values) in values.items()
            for level, value in zip(("pre", "mid", "post"), subject_values)
        ]
    )


def _mixed_hf_reference_frame() -> pd.DataFrame:
    values = {
        "A1": ("A", [8.8915125487825204, 12.305726111155616, 14.302761340061863]),
        "A2": ("A", [9.8027613400618634, 11.802761340061863, 15.394477319876275]),
        "A3": ("A", [11.305726111155616, 11.89151254878252, 15.302761340061863]),
        "B1": ("B", [28.891512548782522, 45.305726111155614, 31.302761340061863]),
        "B2": ("B", [29.802761340061863, 44.802761340061863, 32.394477319876273]),
        "B3": ("B", [31.305726111155614, 44.891512548782522, 32.302761340061863]),
    }
    return pd.DataFrame(
        [
            {
                "response": value,
                "subject": subject,
                "within": level,
                "between": between,
            }
            for subject, (between, subject_values) in values.items()
            for level, value in zip(("pre", "mid", "post"), subject_values)
        ]
    )


def _fit_repeated(frame: pd.DataFrame, *, correction: str = "none", **kwargs):
    pack = _pack_module()
    return pack.fit_repeated_measures_anova(
        frame,
        operation_id=pack.REPEATED_ONLY_OPERATION_ID,
        response_column="response",
        subject_column="subject",
        within_factor_columns=["within"],
        correction=correction,
        **kwargs,
    )


def _fit_mixed(
    frame: pd.DataFrame,
    *,
    correction: str = "none",
    between_factor_column: object = "between",
    **kwargs,
):
    pack = _pack_module()
    return pack.fit_repeated_measures_anova(
        frame,
        operation_id=pack.MIXED_DESIGN_OPERATION_ID,
        response_column="response",
        subject_column="subject",
        within_factor_columns=["within"],
        between_factor_column=between_factor_column,
        correction=correction,
        **kwargs,
    )


def _r_aov_oracle(frame: pd.DataFrame, formula: str, tmp_path: Path) -> dict[str, dict[str, object]]:
    source = tmp_path / "oracle.csv"
    frame.to_csv(source, index=False)
    script = textwrap.dedent(
        f"""
        args <- commandArgs(trailingOnly=TRUE)
        d <- read.csv(args[[1]], check.names=FALSE, stringsAsFactors=FALSE)
        d$subject <- factor(d$subject, levels=unique(d$subject))
        d$within <- factor(d$within, levels=unique(d$within))
        if ("between" %in% names(d)) d$between <- factor(d$between, levels=unique(d$between))
        fit <- aov({formula}, data=d)
        summaries <- summary(fit)
        for (stratum_index in seq_along(summaries)) {{
          stratum <- names(summaries)[stratum_index]
          table <- summaries[[stratum]][[1]]
          if (is.null(dim(table))) next
          for (row_index in seq_len(nrow(table))) {{
            term <- rownames(table)[row_index]
            ss <- as.numeric(table[row_index, "Sum Sq"])
            df <- as.numeric(table[row_index, "Df"])
            ms <- as.numeric(table[row_index, "Mean Sq"])
            f_value <- as.numeric(table[row_index, "F value"])
            p_value <- as.numeric(table[row_index, "Pr(>F)"])
            encode <- function(value) ifelse(is.na(value), "NA", sprintf("%.17g", value))
            cat("ROW", stratum, term, encode(ss), encode(df), encode(ms), encode(f_value), encode(p_value), sep="\\t")
            cat("\\n")
          }}
        }}
        """
    )
    completed = subprocess.run(
        ["Rscript", "-e", script, str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    rows: dict[str, dict[str, object]] = {}
    for line in completed.stdout.splitlines():
        if not line.startswith("ROW\t"):
            continue
        _, stratum, term, ss, df, ms, f_value, p_value = line.split("\t")
        term = term.strip()
        rows[term] = {
            "stratum": stratum,
            "sum_sq": float(ss),
            "df": float(df),
            "mean_sq": float(ms),
            "f": None if f_value == "NA" else float(f_value),
            "p_value": None if p_value == "NA" else float(p_value),
        }
    return rows


def _r_mixed_sphericity_oracle(frame: pd.DataFrame, tmp_path: Path) -> dict[str, float]:
    source = tmp_path / "mixed_sphericity_oracle.csv"
    frame.to_csv(source, index=False)
    script = textwrap.dedent(
        """
        args <- commandArgs(trailingOnly=TRUE)
        d <- read.csv(args[[1]], check.names=FALSE, stringsAsFactors=FALSE)
        subject_levels <- unique(d$subject)
        within_levels <- unique(d$within)
        between_levels <- unique(d$between)
        d$subject <- factor(d$subject, levels=subject_levels)
        d$within <- factor(d$within, levels=within_levels)
        d$between <- factor(d$between, levels=between_levels)
        wide <- matrix(
          NA_real_,
          nrow=length(subject_levels),
          ncol=length(within_levels),
          dimnames=list(subject_levels, within_levels)
        )
        for (row_index in seq_len(nrow(d))) {
          wide[as.character(d$subject[row_index]), as.character(d$within[row_index])] <- d$response[row_index]
        }
        group_for_subject <- vapply(
          subject_levels,
          function(subject) unique(as.character(d$between[as.character(d$subject) == subject]))[1],
          character(1)
        )
        group_means <- t(sapply(
          between_levels,
          function(group) colMeans(wide[group_for_subject == group, , drop=FALSE])
        ))
        residual <- wide - group_means[match(group_for_subject, between_levels), ]
        contrasts <- rbind(
          c(1, -1, 0) / sqrt(2),
          c(1, 1, -2) / sqrt(6)
        )
        covariance <- cov(residual %*% t(contrasts))
        dimension <- ncol(covariance)
        trace <- sum(diag(covariance))
        trace_square <- sum(diag(covariance %*% covariance))
        epsilon_gg <- trace^2 / (dimension * trace_square)
        subjects_per_group <- sum(group_for_subject == between_levels[1])
        subject_within_df <- length(between_levels) * (subjects_per_group - 1) * dimension
        hf_reference_subjects <- subject_within_df / dimension + 1
        epsilon_hf <- (
          hf_reference_subjects * dimension * epsilon_gg - 2
        ) / (
          dimension * (hf_reference_subjects - 1 - dimension * epsilon_gg)
        )
        encode <- function(value) sprintf("%.17g", value)
        cat(
          "ORACLE",
          encode(epsilon_gg),
          encode(epsilon_hf),
          sep="\t"
        )
        cat("\n")
        """
    )
    completed = subprocess.run(
        ["Rscript", "-e", script, str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    line = next(line for line in completed.stdout.splitlines() if line.startswith("ORACLE\t"))
    _, epsilon_gg, epsilon_hf = line.split("\t")
    return {
        "epsilon_gg": float(epsilon_gg),
        "epsilon_hf": float(epsilon_hf),
    }


def _r_mauchly_test_oracle(frame: pd.DataFrame, tmp_path: Path) -> dict[str, float]:
    source = tmp_path / "mixed_mauchly_oracle.csv"
    frame.to_csv(source, index=False)
    script = textwrap.dedent(
        """
        args <- commandArgs(trailingOnly=TRUE)
        d <- read.csv(args[[1]], check.names=FALSE, stringsAsFactors=FALSE)
        subject_levels <- unique(d$subject)
        within_levels <- unique(d$within)
        between_levels <- unique(d$between)
        d$subject <- factor(d$subject, levels=subject_levels)
        d$within <- factor(d$within, levels=within_levels)
        d$between <- factor(d$between, levels=between_levels)
        wide <- matrix(
          NA_real_,
          nrow=length(subject_levels),
          ncol=length(within_levels),
          dimnames=list(subject_levels, within_levels)
        )
        for (row_index in seq_len(nrow(d))) {
          wide[as.character(d$subject[row_index]), as.character(d$within[row_index])] <- d$response[row_index]
        }
        group_for_subject <- vapply(
          subject_levels,
          function(subject) unique(as.character(d$between[as.character(d$subject) == subject]))[1],
          character(1)
        )
        group_means <- t(sapply(
          between_levels,
          function(group) colMeans(wide[group_for_subject == group, , drop=FALSE])
        ))
        residual <- wide - group_means[match(group_for_subject, between_levels), ]
        contrasts <- rbind(
          c(1, -1, 0) / sqrt(2),
          c(1, 1, -2) / sqrt(6)
        )
        object <- structure(
          list(
            SSD=crossprod(residual),
            df=length(between_levels) * (sum(group_for_subject == between_levels[1]) - 1)
          ),
          class="SSD"
        )
        trace(
          "mauchly.test.SSD",
          where=asNamespace("stats"),
          exit=quote(cat("MAUCHLY", sprintf("%.17g", exp(logW)), sprintf("%.17g", z), sprintf("%.17g", f), sprintf("%.17g", pval), sep="\t")),
          print=FALSE
        )
        result <- stats::mauchly.test(object, T=contrasts)
        untrace("mauchly.test.SSD", where=asNamespace("stats"))
        cat("\n")
        """
    )
    completed = subprocess.run(
        ["Rscript", "-e", script, str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    line = next(line for line in completed.stdout.splitlines() if line.startswith("MAUCHLY\t"))
    _, w, chi_square, df, p_value = line.split("\t")
    return {
        "w": float(w),
        "chi_square": float(chi_square),
        "df": float(df),
        "p_value": float(p_value),
    }


def test_contract_closes_operations_and_round_trips_json_safe_values() -> None:
    contract = _contract_module()
    from workbench.contracts.common.envelope import ContractError

    assert contract.REPEATED_MEASURES_ANOVA_OPERATION_IDS == frozenset(
        {
            "repeated_measures_anova.repeated_only",
            "repeated_measures_anova.mixed_design",
        }
    )
    request = contract.RepeatedMeasuresAnovaInput(
        operation_id=contract.REPEATED_ONLY_OPERATION_ID,
        response_column="response",
        subject_column="subject",
        within_factor_columns=("within",),
        between_factor_column=None,
        correction="none",
    )
    assert contract.RepeatedMeasuresAnovaInput.from_dict(request.to_dict()) == request

    envelope = contract.RepeatedMeasuresAnovaResultEnvelope(
        operation_id=contract.REPEATED_ONLY_OPERATION_ID,
        status="completed",
        reason_code=contract.REPEATED_MEASURES_ANOVA_COMPLETED,
        n_observations=12,
        columns=("response", "subject", "within"),
        result={"counts": {"n_subjects": 4}, "effects": []},
    )
    value = envelope.to_dict()
    assert contract.RepeatedMeasuresAnovaResultEnvelope.from_dict(value) == envelope
    assert json.loads(json.dumps(value, allow_nan=False)) == value

    with pytest.raises(ContractError, match="declared repeated-measures operation"):
        contract.RepeatedMeasuresAnovaInput(
            operation_id="repeated_measures_anova.not_declared",
            response_column="response",
            subject_column="subject",
            within_factor_columns=("within",),
            between_factor_column=None,
            correction="none",
        )


def test_contract_requires_matching_design_and_rejects_formula_fields() -> None:
    contract = _contract_module()
    from workbench.contracts.common.envelope import ContractError

    base = {
        "operation_id": contract.REPEATED_ONLY_OPERATION_ID,
        "response_column": "response",
        "subject_column": "subject",
        "within_factor_columns": ["within"],
        "between_factor_column": None,
        "correction": "none",
    }
    with pytest.raises(ContractError, match="unknown repeated-measures input field"):
        contract.RepeatedMeasuresAnovaInput.from_dict({**base, "formula": "response ~ within"})

    with pytest.raises(ContractError, match="between_factor_column"):
        contract.RepeatedMeasuresAnovaInput(
            **{**base, "operation_id": contract.MIXED_DESIGN_OPERATION_ID}
        )
    with pytest.raises(ContractError, match="between_factor_column"):
        contract.RepeatedMeasuresAnovaInput(
            **{**base, "between_factor_column": "between"}
        )


def test_contract_rejects_unhashable_status_and_correction_values() -> None:
    contract = _contract_module()
    from workbench.contracts.common.envelope import ContractError

    with pytest.raises(ContractError):
        contract.RepeatedMeasuresAnovaInput(
            operation_id=contract.REPEATED_ONLY_OPERATION_ID,
            response_column="response",
            subject_column="subject",
            within_factor_columns=("within",),
            between_factor_column=None,
            correction=["none"],
        )
    with pytest.raises(ContractError):
        contract.RepeatedMeasuresAnovaResultEnvelope(
            operation_id=contract.REPEATED_ONLY_OPERATION_ID,
            status=["completed"],
            reason_code=contract.REPEATED_MEASURES_ANOVA_COMPLETED,
            n_observations=1,
            columns=("response",),
            result={},
        )


def test_contract_rejects_string_result_columns_before_tuple_conversion() -> None:
    contract = _contract_module()
    from workbench.contracts.common.envelope import ContractError

    with pytest.raises(ContractError, match="columns must be an array"):
        contract.make_result_envelope(
            operation_id=contract.REPEATED_ONLY_OPERATION_ID,
            status="rejected",
            reason_code="REPEATED_MEASURES_ANOVA_BAD_INPUT",
            n_observations=0,
            columns="response",
            result={"error": {"reason_code": "REPEATED_MEASURES_ANOVA_BAD_INPUT"}},
        )


def test_repeated_only_matches_statsmodels_and_reports_explicit_error_layer() -> None:
    pack = _pack_module()
    from statsmodels.stats.anova import AnovaRM

    frame = _repeated_frame()
    result = _fit_repeated(frame)
    payload = result["result"]
    row = next(item for item in payload["anova_table"] if item["term"] == "within")
    oracle = AnovaRM(
        frame,
        depvar="response",
        subject="subject",
        within=["within"],
    ).fit().anova_table.iloc[0]

    assert result["operation_id"] == pack.REPEATED_ONLY_OPERATION_ID
    assert result["status"] == "completed"
    assert result["reason_code"] == pack.REPEATED_MEASURES_ANOVA_COMPLETED
    assert payload["design_metadata"]["design"] == "repeated_only"
    assert payload["counts"] == {
        "n_rows": 12,
        "n_subjects": 4,
        "n_within_levels": 3,
        "n_between_levels": 0,
        "subjects_per_between_level": None,
        "observations_per_subject": 3,
    }
    assert row["error_layer"] == "subject:within"
    assert row["df"] == pytest.approx(float(oracle["Num DF"]))
    assert row["df_error"] == pytest.approx(float(oracle["Den DF"]))
    assert row["f"] == pytest.approx(float(oracle["F Value"]))
    assert row["p_value"] == pytest.approx(float(oracle["Pr > F"]))
    assert row["sum_sq"] == pytest.approx(13.875)
    assert row["mean_sq"] == pytest.approx(row["sum_sq"] / row["df"])
    assert payload["error_layers"][0]["name"] == "subject:within"
    assert payload["sphericity"]["applicable"] is True
    assert set(payload["sphericity"]["epsilon"]) == {
        "greenhouse_geisser",
        "huynh_feldt",
        "selected",
    }
    assert payload["sphericity"]["mauchly"]["correction"]["policy"] == (
        "stats_mauchly_test_rho_w2"
    )
    assert payload["sphericity"]["mauchly"]["correction"]["provenance"] == (
        "repeated_only_subject_within_error_df_per_within_contrast"
    )
    assert payload["sphericity"]["mauchly"]["correction"]["residual_error_df"] == pytest.approx(6.0)
    assert payload["sphericity"]["mauchly"]["correction"]["effective_sample_df"] == pytest.approx(3.0)
    assert len(payload["effects"]) <= pack.MAX_RESULT_POSITIONS
    assert json.loads(json.dumps(result, allow_nan=False)) == result


@pytest.mark.parametrize("correction", ["greenhouse_geisser", "huynh_feldt"])
def test_repeated_only_applies_declared_sphericity_correction(correction: str) -> None:
    payload = _fit_repeated(_repeated_frame(), correction=correction)["result"]
    row = next(item for item in payload["effects"] if item["term"] == "within")
    epsilon = payload["sphericity"]["epsilon"][correction]

    assert 1 / 2 <= epsilon <= 1
    assert row["correction"]["policy"] == correction
    assert row["correction"]["applied"] is True
    assert row["df"] == pytest.approx(2 * epsilon)
    assert row["df_error"] == pytest.approx(6 * epsilon)


@pytest.mark.parametrize("correction", ["none", "greenhouse_geisser", "huynh_feldt"])
def test_two_level_within_reports_sphericity_not_applicable_and_unapplied_correction(
    correction: str,
) -> None:
    payload = _fit_mixed(_mixed_frame(), correction=correction)["result"]

    assert payload["sphericity"]["applicable"] is False
    assert payload["sphericity"]["epsilon"] == {
        "greenhouse_geisser": 1.0,
        "huynh_feldt": 1.0,
        "selected": 1.0,
    }
    for row in payload["effects"]:
        assert row["correction"]["policy"] == correction
        assert row["correction"]["applied"] is False


def test_sphericity_epsilon_uses_orthonormal_contrast_space() -> None:
    payload = _fit_repeated(_repeated_frame())["result"]
    y = (
        _repeated_frame()
        .pivot(index="subject", columns="within", values="response")
        .loc[:, ["pre", "mid", "post"]]
        .to_numpy()
    )
    helmert = np.asarray(
        [[1.0, -1.0, 0.0], [1.0, 1.0, -2.0]],
        dtype=float,
    )
    helmert[0] /= np.sqrt(2.0)
    helmert[1] /= np.sqrt(6.0)
    covariance = np.cov(y @ helmert.T, rowvar=False, ddof=1)
    expected = np.trace(covariance) ** 2 / (
        2.0 * np.trace(covariance @ covariance)
    )

    assert payload["sphericity"]["epsilon"]["greenhouse_geisser"] == pytest.approx(
        expected
    )


def test_mixed_design_uses_explicit_balanced_error_layers() -> None:
    pack = _pack_module()
    result = _fit_mixed(_mixed_frame())
    payload = result["result"]
    rows = {item["term"]: item for item in payload["anova_table"]}

    assert result["operation_id"] == pack.MIXED_DESIGN_OPERATION_ID
    assert payload["design_metadata"]["between_factor_column"] == "between"
    assert payload["counts"]["subjects_per_between_level"] == 3
    assert set(rows) == {"between", "within", "between:within"}
    assert rows["between"]["error_layer"] == "subject:between"
    assert rows["within"]["error_layer"] == "subject:within"
    assert rows["between:within"]["error_layer"] == "subject:within"
    assert rows["between"]["df"] == 1
    assert rows["between"]["df_error"] == 4
    assert rows["within"]["df"] == 1
    assert rows["within"]["df_error"] == 4
    assert rows["between:within"]["df"] == 1
    assert rows["between:within"]["df_error"] == 4
    assert rows["between"]["sum_sq"] == pytest.approx(363.0)
    assert rows["within"]["sum_sq"] == pytest.approx(21.333333333333332)
    assert rows["between:within"]["sum_sq"] == pytest.approx(3.0)
    assert len(payload["error_layers"]) == 2
    assert {item["name"] for item in payload["error_layers"]} == {
        "subject:between",
        "subject:within",
    }
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_mixed_three_level_sphericity_uses_between_adjusted_within_residual() -> None:
    from scipy.stats import f as f_distribution

    frame = _mixed_three_level_frame()
    payload = _fit_mixed(frame, correction="greenhouse_geisser")["result"]
    row = next(item for item in payload["effects"] if item["term"] == "within")

    wide = (
        frame.pivot(index="subject", columns="within", values="response")
        .loc[:, ["pre", "mid", "post"]]
    )
    subject_groups = frame.drop_duplicates("subject").set_index("subject")["between"]
    group_order = ["A", "B"]
    group_means = np.asarray(
        [
            wide.loc[subject_groups[subject_groups == group].index].mean(axis=0)
            for group in group_order
        ]
    )
    group_indices = subject_groups.loc[wide.index].map(
        {group: index for index, group in enumerate(group_order)}
    ).to_numpy()
    residual = wide.to_numpy() - group_means[group_indices]
    helmert = np.asarray(
        [[1.0, -1.0, 0.0], [1.0, 1.0, -2.0]],
        dtype=float,
    )
    helmert[0] /= np.sqrt(2.0)
    helmert[1] /= np.sqrt(6.0)
    covariance = np.cov(residual @ helmert.T, rowvar=False, ddof=1)
    expected_epsilon = np.trace(covariance) ** 2 / (
        2.0 * np.trace(covariance @ covariance)
    )
    pooled_covariance = np.cov(wide.to_numpy() @ helmert.T, rowvar=False, ddof=1)
    pooled_epsilon = np.trace(pooled_covariance) ** 2 / (
        2.0 * np.trace(pooled_covariance @ pooled_covariance)
    )
    expected_p = f_distribution.sf(
        row["f"],
        2.0 * expected_epsilon,
        8.0 * expected_epsilon,
    )

    assert expected_epsilon == pytest.approx(1.0)
    assert pooled_epsilon != pytest.approx(expected_epsilon)
    assert payload["sphericity"]["epsilon"]["greenhouse_geisser"] == pytest.approx(
        expected_epsilon
    )
    assert row["p_value"] == pytest.approx(expected_p)


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="Rscript is required for the independent Oracle")
def test_mixed_huynh_feldt_matches_subject_error_r_reference(tmp_path: Path) -> None:
    payload = _fit_mixed(
        _mixed_hf_reference_frame(),
        correction="huynh_feldt",
    )["result"]
    row = next(item for item in payload["effects"] if item["term"] == "within")
    oracle = _r_mixed_sphericity_oracle(_mixed_hf_reference_frame(), tmp_path)

    assert oracle["epsilon_gg"] == pytest.approx(0.6698581936, abs=1e-9)
    assert oracle["epsilon_hf"] == pytest.approx(0.8830979, abs=1e-7)
    assert payload["sphericity"]["epsilon"]["greenhouse_geisser"] == pytest.approx(
        oracle["epsilon_gg"], rel=1e-9, abs=1e-10
    )
    assert payload["sphericity"]["epsilon"]["huynh_feldt"] != pytest.approx(
        0.8248402258, rel=1e-8, abs=1e-10
    )
    assert payload["sphericity"]["epsilon"]["huynh_feldt"] == pytest.approx(
        oracle["epsilon_hf"], rel=1e-8, abs=1e-9
    )
    assert row["correction"]["epsilon"] == pytest.approx(oracle["epsilon_hf"])


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="Rscript is required for the independent Oracle")
def test_mauchly_evidence_matches_r_reference_df_and_p(tmp_path: Path) -> None:
    payload = _fit_mixed(_mixed_hf_reference_frame(), correction="none")["result"]
    actual = payload["sphericity"]["mauchly"]
    oracle = _r_mauchly_test_oracle(_mixed_hf_reference_frame(), tmp_path)

    assert actual["w"] == pytest.approx(oracle["w"], rel=1e-9, abs=1e-10)
    assert actual["df"] == pytest.approx(oracle["df"])
    assert actual["chi_square"] == pytest.approx(
        oracle["chi_square"], rel=1e-9, abs=1e-10
    )
    assert actual["p_value"] == pytest.approx(
        oracle["p_value"], rel=1e-9, abs=1e-10
    )
    assert actual["correction"]["policy"] == "stats_mauchly_test_rho_w2"
    assert actual["correction"]["provenance"] == (
        "mixed_subject_within_error_df_per_within_contrast"
    )
    assert actual["correction"]["residual_error_df"] == pytest.approx(8.0)
    assert actual["correction"]["effective_sample_df"] == pytest.approx(4.0)


def test_mixed_huynh_feldt_mauchly_and_effect_p_are_scale_invariant() -> None:
    frame = _mixed_hf_reference_frame()
    scaled = frame.copy()
    scaled["response"] *= 1e-8
    base_payload = _fit_mixed(frame, correction="huynh_feldt")["result"]
    scaled_payload = _fit_mixed(scaled, correction="huynh_feldt")["result"]

    assert scaled_payload["sphericity"]["epsilon"]["huynh_feldt"] == pytest.approx(
        base_payload["sphericity"]["epsilon"]["huynh_feldt"], rel=1e-9, abs=1e-10
    )
    assert scaled_payload["sphericity"]["mauchly"]["df"] == pytest.approx(
        base_payload["sphericity"]["mauchly"]["df"]
    )
    assert scaled_payload["sphericity"]["mauchly"]["p_value"] == pytest.approx(
        base_payload["sphericity"]["mauchly"]["p_value"], rel=1e-9, abs=1e-10
    )
    base_rows = {item["term"]: item for item in base_payload["effects"]}
    scaled_rows = {item["term"]: item for item in scaled_payload["effects"]}
    for term in base_rows:
        assert scaled_rows[term]["f"] == pytest.approx(base_rows[term]["f"])
        assert scaled_rows[term]["p_value"] == pytest.approx(
            base_rows[term]["p_value"], rel=1e-9, abs=1e-12
        )


@pytest.mark.parametrize("design", ["repeated_only", "mixed_design"])
def test_valid_design_scaled_to_one_e_minus_eight_remains_estimable(design: str) -> None:
    frame = _repeated_frame() if design == "repeated_only" else _mixed_frame()
    frame["response"] *= 1e-8
    result = (
        _fit_repeated(frame)
        if design == "repeated_only"
        else _fit_mixed(frame)
    )

    assert result["status"] == "completed"
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_overflowing_sphericity_epsilon_fails_closed_with_stable_reason() -> None:
    pack = _pack_module()
    y = np.asarray(
        [
            [1.0, 0.0, 2.0],
            [0.0, 2.0, -1.0],
            [3.0, -1.0, 1.0],
            [-2.0, 1.0, 0.0],
            [1.0, 3.0, -2.0],
            [2.0, -2.0, 3.0],
            [-1.0, 1.0, 4.0],
            [0.0, -3.0, 2.0],
        ],
        dtype=float,
    ) * 1e153

    with pytest.raises(pack.RepeatedMeasuresAnovaPackError) as caught:
        pack._sphericity(
            y,
            within_factor="within",
            correction="greenhouse_geisser",
        )

    assert caught.value.reason_code == "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT"


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="Rscript is required for the independent Oracle")
def test_repeated_only_matches_r_base_aov_oracle(tmp_path: Path) -> None:
    actual = {
        item["term"]: item
        for item in _fit_repeated(_repeated_frame())["result"]["anova_table"]
    }["within"]
    oracle = _r_aov_oracle(
        _repeated_frame(),
        "response ~ within + Error(subject/within)",
        tmp_path,
    )["within"]

    for key in ("sum_sq", "df", "mean_sq", "f", "p_value"):
        assert actual[key] == pytest.approx(oracle[key], rel=1e-8, abs=1e-10)


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="Rscript is required for the independent Oracle")
def test_mixed_design_matches_r_base_aov_oracle(tmp_path: Path) -> None:
    actual = {
        item["term"]: item
        for item in _fit_mixed(_mixed_frame())["result"]["anova_table"]
    }
    oracle = _r_aov_oracle(
        _mixed_frame(),
        "response ~ between*within + Error(subject/within)",
        tmp_path,
    )

    for term in ("between", "within", "between:within"):
        for key in ("sum_sq", "df", "mean_sq", "f", "p_value"):
            assert actual[term][key] == pytest.approx(
                oracle[term][key], rel=1e-8, abs=1e-10
            )


@pytest.mark.parametrize(
    ("builder", "reason"),
    [
        (lambda frame: frame.assign(response=[np.inf] + [1.0] * (len(frame) - 1)), "NON_FINITE_RESPONSE"),
        (lambda frame: frame.rename(columns={"response": "outcome"}), "MISSING_COLUMN"),
        (lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True), "DUPLICATE_CELL"),
        (lambda frame: frame.iloc[1:].reset_index(drop=True), "INCOMPLETE_BALANCE"),
        (lambda frame: frame.assign(within=frame["within"].mask(frame.index == 0, "")), "EMPTY_LEVEL"),
    ],
)
def test_repeated_only_rejects_unsafe_or_unbalanced_long_input(builder, reason: str) -> None:
    pack = _pack_module()
    frame = builder(_repeated_frame())
    with pytest.raises(pack.RepeatedMeasuresAnovaPackError, match=reason):
        _fit_repeated(frame)


def test_mixed_rejects_between_label_inconsistency_and_unbalanced_groups() -> None:
    pack = _pack_module()
    inconsistent = _mixed_frame()
    inconsistent.loc[0, "between"] = "B"
    with pytest.raises(pack.RepeatedMeasuresAnovaPackError, match="INCONSISTENT_BETWEEN_LABEL"):
        _fit_mixed(inconsistent)

    unbalanced = _mixed_frame().query("subject != 'B3'").reset_index(drop=True)
    with pytest.raises(pack.RepeatedMeasuresAnovaPackError, match="INCOMPLETE_BALANCE"):
        _fit_mixed(unbalanced)


def test_rejects_multiple_between_factors_formula_eval_and_wrong_operation_shape() -> None:
    pack = _pack_module()
    frame = _mixed_frame()
    with pytest.raises(pack.RepeatedMeasuresAnovaPackError, match="MULTIPLE_BETWEEN_FACTORS"):
        _fit_repeated(frame, between_factor_column=["between", "extra"])
    with pytest.raises(pack.RepeatedMeasuresAnovaPackError, match="UNSUPPORTED_FORMULA"):
        _fit_repeated(_repeated_frame(), formula="response ~ within")
    with pytest.raises(pack.RepeatedMeasuresAnovaPackError, match="UNSUPPORTED_FORMULA"):
        _fit_repeated(_repeated_frame(), eval="response + within")
    with pytest.raises(pack.RepeatedMeasuresAnovaPackError, match="UNSUPPORTED_WITHIN_FACTORS"):
        pack.fit_repeated_measures_anova(
            _repeated_frame(),
            operation_id=pack.REPEATED_ONLY_OPERATION_ID,
            response_column="response",
            subject_column="subject",
            within_factor_columns=["within", "subject"],
            correction="none",
        )
    with pytest.raises(pack.RepeatedMeasuresAnovaPackError, match="INVALID_DESIGN"):
        _fit_mixed(_mixed_frame(), between_factor_column=None)


def test_fail_closed_on_singular_subject_within_error_layer() -> None:
    frame = _repeated_frame()
    frame["response"] = [
        10.0,
        11.0,
        12.0,
        11.0,
        12.0,
        13.0,
        9.0,
        10.0,
        11.0,
        12.0,
        13.0,
        14.0,
    ]
    pack = _pack_module()
    with pytest.raises(pack.RepeatedMeasuresAnovaPackError, match="SINGULAR_ERROR_LAYER"):
        _fit_repeated(frame)


def test_envelope_safe_entry_returns_bounded_rejection_without_raising() -> None:
    pack = _pack_module()
    frame = pd.concat([_repeated_frame(), _repeated_frame().iloc[[0]]], ignore_index=True)
    result = pack.run_repeated_measures_anova(
        frame,
        operation_id=pack.REPEATED_ONLY_OPERATION_ID,
        response_column="response",
        subject_column="subject",
        within_factor_columns=["within"],
        correction="none",
    )

    assert result["status"] == "rejected"
    assert result["reason_code"] == "REPEATED_MEASURES_ANOVA_DUPLICATE_CELL"
    assert result["result"]["error"]["reason_code"] == result["reason_code"]
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_envelope_safe_entry_rejects_missing_required_declaration() -> None:
    pack = _pack_module()
    result = pack.run_repeated_measures_anova(
        _repeated_frame(),
        response_column="response",
        subject_column="subject",
        within_factor_columns=["within"],
    )

    assert result["status"] == "rejected"
    assert result["reason_code"] == "REPEATED_MEASURES_ANOVA_BAD_INPUT"


def test_heterogeneous_subject_labels_are_rejected_before_categorical_conversion() -> None:
    frame = _repeated_frame()
    frame["subject"] = frame["subject"].replace(
        {"s1": 1, "s2": 1.0, "s3": True, "s4": "s4"}
    )
    pack = _pack_module()

    with pytest.raises(pack.RepeatedMeasuresAnovaPackError) as caught:
        _fit_repeated(frame)

    assert caught.value.reason_code == "REPEATED_MEASURES_ANOVA_INVALID_LEVEL"


def test_envelope_safe_entry_wraps_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    pack = _pack_module()

    def raise_value_error(*args: object, **kwargs: object) -> dict[str, object]:
        raise ValueError("synthetic invalid input")

    monkeypatch.setattr(pack, "fit_repeated_measures_anova", raise_value_error)
    result = pack.run_repeated_measures_anova(
        _repeated_frame(),
        operation_id=pack.REPEATED_ONLY_OPERATION_ID,
        response_column="response",
        subject_column="subject",
        within_factor_columns=["within"],
        correction="none",
    )

    assert result["status"] == "rejected"
    assert result["reason_code"] == "REPEATED_MEASURES_ANOVA_BAD_INPUT"


def test_rejection_envelope_bounds_echoed_columns() -> None:
    pack = _pack_module()
    declared_columns = [
        f"column_{index}" for index in range(pack.MAX_ECHOED_COLUMNS + 20)
    ]
    result = pack.run_repeated_measures_anova(
        _repeated_frame(),
        operation_id=pack.REPEATED_ONLY_OPERATION_ID,
        response_column="response",
        subject_column="subject",
        within_factor_columns=declared_columns,
        correction="none",
    )

    assert result["status"] == "rejected"
    assert len(result["columns"]) <= pack.MAX_ECHOED_COLUMNS
