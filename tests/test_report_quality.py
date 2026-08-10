from __future__ import annotations

import pytest

from workbench.report_contract import validate_report_packet
from workbench.report_quality import (
    ReportQualityError,
    ReportQualityResult,
    ReportQualityViolation,
    validate_report_quality,
    validate_report_response_quality,
)


def _journal_packet(*, excluded_fact_ids: list[str] | None = None) -> dict:
    return {
        "report_standard": "journal_full_v1",
        "required_capabilities": ["regression"],
        "fact_table": [
            {"id": "c1", "label": "estimate", "value": 2.0},
            {"id": "c2", "label": "p", "value": 0.01},
        ],
        "figures": [{"artifact_id": "coef_plot", "chart_type": "coefficient"}],
        "excluded_fact_ids": excluded_fact_ids or [],
        "capability_manifest": [
            {
                "capability_id": "regression",
                "provider_id": "evidence.regression.v1",
            }
        ],
    }


def _complete_report() -> str:
    topics = [
        "sample definition", "measurement choices", "variable coding", "missingness review",
        "model specification", "uncertainty reporting", "diagnostic scope", "lineage context",
        "comparison baseline", "outcome definition", "predictor interpretation", "data coverage",
        "reference category", "estimation assumptions", "robustness checks", "artifact provenance",
        "research question", "practical interpretation",
    ]
    filler = " ".join(
        f"The interpretation remains conditional because the supplied {topic} and {qualifier} limit what this run can establish."
        for topic in topics
        for qualifier in ("measurement choices", "evidence boundary")
    )
    return f"""# Evidence study

## Abstract
The question, data, method, result 2.0 [[c:c1]], and limitation are stated in this abstract.

## Research question and scope
This section defines the research question and scope.

## Data and sample
This section describes the data and sample [[c:c1]].

## Variables and transformations
This section describes variables and transformations.

## Methods
This section describes the regression method.

## Results
### Main estimate
The Regression module reports estimate 2.0 [[c:c1]] and p 0.01 [[c:c2]].

### Interpretation and implications
The positive association is conditional on the supplied model and should be interpreted as an empirical association.
[[fig:coef_plot]]

## Diagnostics and robustness
This section describes diagnostics and robustness.

## Limitations
This section states the limitations.

## Conclusion
This section states the evidence-bound conclusion.

{filler}
"""


def _complete_chinese_report() -> str:
    topics = [
        "样本定义", "测量选择", "变量编码", "缺失值审查", "模型设定",
        "不确定性报告", "诊断范围", "lineage上下文", "比较基线", "结果定义",
        "预测变量解释", "数据覆盖", "参考类别", "估计假设", "稳健性检查",
        "artifact来源", "研究问题", "实际解释", "分析单位", "证据边界",
    ]
    filler = "".join(
        f"本段从{topic}说明{scope}的结果只适用于本次运行，并且不能替代新的研究设计。"
        for topic in topics
        for scope in ("当前样本", "当前模型")
    )
    return """# 研究报告

## 摘要
研究问题、数据、方法、结果 2.0 [[c:c1]] 与局限性均在摘要中说明。

## 研究问题与范围
本节说明研究问题、分析范围与解释边界。

## 数据与样本
本节说明数据来源、样本与当前分析范围 [[c:c1]]。

## 变量与变换
本节说明变量定义、编码和变换过程。

## 方法
本节说明回归模型、估计方法和解释口径。

## 结果
### 主要结果
回归结果给出估计值 2.0 [[c:c1]]，并报告 p 值 0.01 [[c:c2]]。

### 结果解释
结果表明当前样本中存在条件相关关系，但不能据此断言因果关系。
[[fig:coef_plot]]

## 诊断与稳健性
本节说明诊断、稳健性检查以及哪些检查没有执行。

## 局限性
本节说明局限性、未观测因素和证据边界。

## 结论
结论只复述本次运行有证据支持的发现，并保留条件性解释。

""" + filler


def test_complete_journal_report_is_exportable() -> None:
    contract = validate_report_packet(_journal_packet())

    result = validate_report_response_quality(_complete_report(), contract)

    assert isinstance(result, ReportQualityResult)
    assert result.status == "exportable"
    assert result.violations == ()
    assert result.normalized_text == _complete_report()
    assert result.cited_fact_ids == ("c1", "c2")
    assert result.to_dict()["status"] == "exportable"


def test_journal_full_accepts_cjk_headings_and_character_length() -> None:
    contract = validate_report_packet(_journal_packet())

    result = validate_report_response_quality(_complete_chinese_report(), contract)

    assert result.status == "exportable"
    assert result.missing_sections == ()


def test_journal_full_accepts_named_top_level_sections() -> None:
    contract = validate_report_packet(_journal_packet())
    text = _complete_report().replace("## ", "# ")

    result = validate_report_response_quality(text, contract)

    assert result.status == "exportable"
    assert result.missing_sections == ()


def test_journal_full_requires_abstract_elements() -> None:
    contract = validate_report_packet(_journal_packet())
    text = _complete_report().replace(
        "The question, data, method, result 2.0 [[c:c1]], and limitation are stated in this abstract.",
        "The question and data are stated in this abstract.",
    )

    result = validate_report_response_quality(text, contract)

    assert result.status == "needs_revision"
    assert any(
        violation.code == "abstract_missing_element"
        for violation in result.violations
    )


def test_journal_full_requires_titled_results_subsections_for_multiple_findings() -> None:
    contract = validate_report_packet(_journal_packet())
    text = _complete_report().replace(
        "### Main estimate\n",
        "",
    ).replace(
        "### Interpretation and implications\n",
        "",
    )

    result = validate_report_response_quality(text, contract)

    assert result.status == "needs_revision"
    assert any(
        violation.code == "results_subsections_required"
        for violation in result.violations
    )


def test_journal_full_rejects_repeated_boilerplate() -> None:
    contract = validate_report_packet(_journal_packet())
    repeated = (
        "This exact boilerplate sentence is not a substantive research explanation. "
        * 4
    )

    result = validate_report_response_quality(_complete_report() + repeated, contract)

    assert result.status == "needs_revision"
    assert any(
        violation.code == "repeated_boilerplate"
        for violation in result.violations
    )


def test_journal_full_requires_sections_and_capability_coverage() -> None:
    contract = validate_report_packet(_journal_packet())
    text = """# Title

## Data
Data [[c:c1]].

## Methods
Method.

## Results
Estimate 2.0 [[c:c1]].

## Limitations
Limited.
"""

    result = validate_report_quality(
        text,
        fact_ids=contract.fact_ids,
        figure_ids=contract.figure_ids,
        excluded_fact_ids=contract.excluded_fact_ids,
        report_standard=contract.report_standard,
        required_capabilities=contract.required_capabilities,
        capability_manifest=contract.capability_manifest,
    )

    assert result.status == "needs_revision"
    assert any(violation.code == "missing_section" for violation in result.violations)
    assert any(
        violation.code == "missing_capability" for violation in result.violations
    )


def test_journal_full_accepts_english_estimation_and_diagnostics_terms() -> None:
    contract = validate_report_packet(_journal_packet())

    result = validate_report_quality(
        _complete_report(),
        fact_ids=contract.fact_ids,
        figure_ids=contract.figure_ids,
        excluded_fact_ids=contract.excluded_fact_ids,
        report_standard=contract.report_standard,
        required_capabilities=("model.estimation", "diagnostics.robustness"),
        capability_manifest=(
            {
                "capability_id": "model.estimation",
                "provider_id": "evidence.estimation.v1",
            },
            {
                "capability_id": "diagnostics.robustness",
                "provider_id": "evidence.diagnostics.v1",
            },
        ),
    )

    assert result.status == "exportable"
    assert result.missing_capabilities == ()


def test_journal_full_rejects_uncited_numeric_claims() -> None:
    contract = validate_report_packet(_journal_packet())
    text = _complete_report().replace("estimate 2.0 [[c:c1]]", "estimate 2.0")

    result = validate_report_response_quality(text, contract)

    assert result.status == "needs_revision"
    assert any(
        violation.code == "numeric_citation_missing"
        for violation in result.violations
    )


@pytest.mark.parametrize(
    "replacement, excluded, code",
    [
        ("[[c:c99]]", [], "unknown_fact"),
        ("[[c:c99]]", ["c99"], "excluded_fact"),
    ],
)
def test_journal_full_rejects_unknown_or_excluded_facts(
    replacement: str, excluded: list[str], code: str
) -> None:
    contract = validate_report_packet(_journal_packet(excluded_fact_ids=excluded))
    text = _complete_report().replace("[[c:c1]]", replacement, 1)

    result = validate_report_response_quality(text, contract)

    assert result.status == "needs_revision"
    assert any(violation.code == code for violation in result.violations)


@pytest.mark.parametrize(
    "figure_text, code",
    [("", "missing_figure"), ("[[fig:coef_plot]]\n[[fig:coef_plot]]", "duplicate_figure")],
)
def test_journal_full_requires_each_figure_exactly_once(
    figure_text: str, code: str
) -> None:
    contract = validate_report_packet(_journal_packet())
    text = _complete_report().replace("[[fig:coef_plot]]", figure_text)

    result = validate_report_response_quality(text, contract)

    assert result.status == "needs_revision"
    assert any(violation.code == code for violation in result.violations)


def test_empty_evidence_returns_insufficient_evidence() -> None:
    packet = _journal_packet()
    packet["fact_table"] = []
    packet["figures"] = []
    contract = validate_report_packet(packet)

    result = validate_report_response_quality(
        "Evidence is insufficient to produce a defensible report.", contract
    )

    assert result.status == "insufficient_evidence"
    assert any(
        violation.code == "insufficient_evidence" for violation in result.violations
    )
    assert result.missing_evidence


def test_unavailable_capability_returns_insufficient_evidence() -> None:
    packet = _journal_packet()
    packet["capability_manifest"] = [
        {
            "capability_id": "regression",
            "provider_id": "evidence.estimation.v1",
            "availability": "unavailable",
            "validation_level": "unverified",
            "report_modules": ["model-estimation"],
            "limitations": ["model result artifact is missing"],
        }
    ]
    contract = validate_report_packet(packet)

    result = validate_report_response_quality(_complete_report(), contract)

    assert result.status == "insufficient_evidence"
    assert result.unavailable_capabilities == ("regression",)


def test_quality_errors_have_stable_codes() -> None:
    with pytest.raises(ReportQualityError) as caught:
        validate_report_quality(
            "# Report",
            fact_ids=frozenset({"c1"}),
            figure_ids=frozenset(),
            report_standard="future_unknown_v1",
        )

    assert caught.value.code == "unsupported_report_standard"
    assert caught.value.violations
    assert isinstance(caught.value.violations[0], ReportQualityViolation)
