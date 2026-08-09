"""Deterministic quality checks for versioned report packets.

The legacy report contract remains responsible for the bounded citation and
figure markers.  This module adds the opt-in ``journal_full_v1`` quality
profile and returns structured results so a later route can decide whether to
retry, save a draft, or allow an export without parsing human-readable error
strings.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from .report_contract import (
    JOURNAL_FULL_REPORT_STANDARD,
    ReportContractError,
    ReportPacketContract,
    _CITE_MARKER,
    _FIGURE_MARKER,
    _SAFE_ID,
    validate_report_response,
)


ReportQualityStatus = Literal["exportable", "needs_revision", "insufficient_evidence"]

JOURNAL_REQUIRED_SECTIONS: tuple[str, ...] = (
    "Title",
    "Abstract",
    "Research question and scope",
    "Data",
    "Variables and transformations",
    "Methods",
    "Results",
    "Diagnostics and robustness",
    "Limitations",
    "Conclusion",
)
# These are language-aware floor checks, not a claim that length alone makes a
# paper publishable.  The validator chooses the dominant writing system so a
# Chinese report is not rejected merely because ``str.split()`` returns very
# few whitespace-delimited tokens.
JOURNAL_MIN_CJK_CHARACTERS = 1_200
JOURNAL_MIN_LATIN_WORDS = 700
# Compatibility aliases for callers that imported the first draft constants.
JOURNAL_MIN_CHARACTERS = JOURNAL_MIN_CJK_CHARACTERS
JOURNAL_MIN_WORDS = JOURNAL_MIN_LATIN_WORDS
JOURNAL_MIN_SECTION_CHARACTERS = 24
JOURNAL_MIN_CJK_SECTION_CHARACTERS = 16

_HEADING = re.compile(r"(?m)^(?P<marks>#{1,6})[ \t]+(?P<title>.+?)[ \t]*$")
_NUMBER = re.compile(
    r"(?<![\w.])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?%?(?![\w.])"
)
_ORDERED_LIST_PREFIX = re.compile(r"(?m)^\s*\d+[.)](?=\s+)")

_SECTION_ALIASES = {
    "title": "Title",
    "abstract": "Abstract",
    "research question": "Research question and scope",
    "research question and scope": "Research question and scope",
    "scope": "Research question and scope",
    "data": "Data",
    "data and sample": "Data",
    "variables": "Variables and transformations",
    "variables and transformations": "Variables and transformations",
    "methods": "Methods",
    "results": "Results",
    "diagnostics": "Diagnostics and robustness",
    "diagnostics and robustness": "Diagnostics and robustness",
    "limitations": "Limitations",
    "conclusion": "Conclusion",
    "标题": "Title",
    "摘要": "Abstract",
    "研究问题和范围": "Research question and scope",
    "研究问题与范围": "Research question and scope",
    "研究范围": "Research question and scope",
    "数据": "Data",
    "数据和样本": "Data",
    "数据与样本": "Data",
    "变量和变换": "Variables and transformations",
    "变量与变换": "Variables and transformations",
    "变量与转换": "Variables and transformations",
    "方法": "Methods",
    "结果": "Results",
    "诊断和稳健性": "Diagnostics and robustness",
    "诊断与稳健性": "Diagnostics and robustness",
    "局限性": "Limitations",
    "限制": "Limitations",
    "结论": "Conclusion",
}

_ABSTRACT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "question": ("question", "objective", "aim", "研究问题", "研究目的", "目的"),
    "data": ("data", "sample", "dataset", "observations", "数据", "样本"),
    "method": ("method", "model", "regression", "estimate", "方法", "模型", "回归", "估计"),
    "result": ("result", "finding", "coefficient", "association", "结果", "发现", "系数", "相关"),
    "limitation": ("limitation", "caveat", "uncertain", "限制", "局限", "不足"),
}

_CAPABILITY_SECTIONS: dict[str, tuple[str, ...]] = {
    "data": ("Data", "Research question and scope"),
    "model estimation": ("Methods", "Results"),
    "diagnostics robustness": ("Diagnostics and robustness",),
    "time series": ("Methods", "Results", "Diagnostics and robustness"),
    "post estimation": ("Results", "Diagnostics and robustness"),
}

_INTERPRETATION_TERMS = (
    "associated", "association", "suggest", "indicate", "consistent", "higher",
    "lower", "positive", "negative", "conditional", "相关", "表明", "说明",
    "意味着", "正向", "负向", "增加", "降低", "条件",
)
_LIMITATION_TERMS = (
    "limitation", "limitations", "caveat", "uncertain", "not causal", "does not establish",
    "限制", "局限", "不足", "不能", "未观测", "未执行",
)


@dataclass(frozen=True)
class ReportQualityViolation:
    """One deterministic, machine-readable quality failure."""

    code: str
    message: str
    subject: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.subject is not None:
            payload["subject"] = self.subject
        return payload


class ReportQualityError(ValueError):
    """Invalid quality-validator input, distinct from a report needing edits."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        violations: tuple[ReportQualityViolation, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.violations = tuple(violations) or (
            ReportQualityViolation(code=code, message=message),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": str(self),
            "violations": [item.to_dict() for item in self.violations],
        }


@dataclass(frozen=True)
class ReportQualityResult:
    """Stable outcome returned by the journal validator."""

    status: ReportQualityStatus
    normalized_text: str
    violations: tuple[ReportQualityViolation, ...] = ()
    missing_sections: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    missing_abstract_elements: tuple[str, ...] = ()
    unavailable_capabilities: tuple[str, ...] = ()
    results_subsection_count: int = 0
    cited_fact_ids: tuple[str, ...] = ()
    figure_counts: tuple[tuple[str, int], ...] = ()

    @property
    def is_exportable(self) -> bool:
        return self.status == "exportable"

    @property
    def ok(self) -> bool:
        return self.is_exportable

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "normalized_text": self.normalized_text,
            "violations": [item.to_dict() for item in self.violations],
            "missing_sections": list(self.missing_sections),
            "missing_capabilities": list(self.missing_capabilities),
            "missing_evidence": list(self.missing_evidence),
            "missing_abstract_elements": list(self.missing_abstract_elements),
            "unavailable_capabilities": list(self.unavailable_capabilities),
            "results_subsection_count": self.results_subsection_count,
            "cited_fact_ids": list(self.cited_fact_ids),
            "figure_counts": {
                artifact_id: count for artifact_id, count in self.figure_counts
            },
        }


def validate_report_quality(
    text: str,
    *,
    fact_ids: frozenset[str],
    figure_ids: frozenset[str],
    excluded_fact_ids: frozenset[str] = frozenset(),
    report_standard: str | None = None,
    required_capabilities: tuple[str, ...] = (),
    capability_manifest: tuple[dict[str, object], ...] = (),
    require_figure_markers: bool = True,
) -> ReportQualityResult:
    """Validate a report against the selected quality profile.

    ``report_standard=None`` deliberately performs only the legacy citation
    and figure checks.  That preserves old packet behavior while allowing the
    journal profile to be opted into explicitly by packet metadata.
    """

    if report_standard not in (None, JOURNAL_FULL_REPORT_STANDARD):
        _raise_quality_input(
            "unsupported report standard",
            code="unsupported_report_standard",
            subject=report_standard,
        )
    if not isinstance(text, str):
        _raise_quality_input(
            "report text must be a string",
            code="invalid_report_text",
        )

    normalized_fact_ids = _normalize_ids(fact_ids, field_name="fact id")
    normalized_figure_ids = _normalize_ids(figure_ids, field_name="figure id")
    normalized_excluded_ids = _normalize_ids(
        excluded_fact_ids,
        field_name="excluded fact id",
    )
    normalized_capabilities = _normalize_ids(
        required_capabilities,
        field_name="required capability",
    )

    contract = ReportPacketContract(
        fact_ids=normalized_fact_ids,
        figure_ids=normalized_figure_ids,
        report_standard=report_standard,
        required_capabilities=normalized_capabilities,
        excluded_fact_ids=normalized_excluded_ids,
        capability_manifest=tuple(capability_manifest),
    )
    normalized_text = text
    violations: list[ReportQualityViolation] = []
    try:
        normalized_text = validate_report_response(
            text,
            contract,
            require_figure_markers=require_figure_markers,
        )
    except ReportContractError as error:
        violations.extend(_contract_violations(error.violations))

    cited_fact_ids = _ordered_unique(
        match.group(1) for match in _CITE_MARKER.finditer(normalized_text)
    )
    figure_markers = [
        match.group(1) for match in _FIGURE_MARKER.finditer(normalized_text)
    ]
    figure_counts = tuple(
        (artifact_id, figure_markers.count(artifact_id))
        for artifact_id in sorted(normalized_figure_ids)
    )

    if report_standard == JOURNAL_FULL_REPORT_STANDARD:
        section_bodies = _section_bodies(normalized_text)
        missing_sections = tuple(
            section
            for section in JOURNAL_REQUIRED_SECTIONS
            if section not in section_bodies
        )
        for section in missing_sections:
            violations.append(
                ReportQualityViolation(
                    code="missing_section",
                    message=f"missing section: {section}",
                    subject=section,
                )
            )

        narrative_text = _narrative_text(normalized_text)
        cjk_characters = _count_cjk_characters(narrative_text)
        latin_words = _count_latin_words(narrative_text)
        if _is_cjk_dominant(narrative_text, cjk_characters, latin_words):
            if cjk_characters < JOURNAL_MIN_CJK_CHARACTERS:
                violations.append(
                    ReportQualityViolation(
                        code="report_too_short",
                        message=(
                            "Chinese report body must contain at least "
                            f"{JOURNAL_MIN_CJK_CHARACTERS} non-whitespace CJK characters"
                        ),
                    )
                )
        elif latin_words < JOURNAL_MIN_LATIN_WORDS:
            violations.append(
                ReportQualityViolation(
                    code="report_too_short",
                    message=(
                        f"English report body must contain at least "
                        f"{JOURNAL_MIN_LATIN_WORDS} words"
                    ),
                )
            )
        for repeated_sentence in _repeated_boilerplate_sentences(narrative_text):
            violations.append(
                ReportQualityViolation(
                    code="repeated_boilerplate",
                    message=(
                        "report repeats the same long sentence at least three "
                        "times; replace boilerplate with evidence-specific analysis"
                    ),
                    subject=repeated_sentence[:120],
                )
            )
        for section in JOURNAL_REQUIRED_SECTIONS:
            if section == "Title" or section not in section_bodies:
                continue
            section_body = section_bodies[section].strip()
            non_whitespace_length = len(re.sub(r"\s+", "", section_body))
            section_minimum = JOURNAL_MIN_SECTION_CHARACTERS
            if _count_cjk_characters(section_body) >= max(4, non_whitespace_length // 3):
                section_minimum = JOURNAL_MIN_CJK_SECTION_CHARACTERS
            if non_whitespace_length < section_minimum:
                violations.append(
                    ReportQualityViolation(
                        code="section_too_short",
                        message=(
                            f"section {section} must contain at least "
                            f"{section_minimum} characters"
                        ),
                        subject=section,
                    )
                )

        abstract_text = section_bodies.get("Abstract", "")
        missing_abstract_elements = tuple(
            element
            for element, terms in _ABSTRACT_REQUIREMENTS.items()
            if not _contains_any_term(abstract_text, terms)
        )
        for element in missing_abstract_elements:
            violations.append(
                ReportQualityViolation(
                    code="abstract_missing_element",
                    message=f"abstract is missing the {element} element",
                    subject=element,
                )
            )

        results_text = section_bodies.get("Results", "")
        result_citations = _ordered_unique(
            match.group(1) for match in _CITE_MARKER.finditer(results_text)
        )
        if not result_citations:
            violations.append(
                ReportQualityViolation(
                    code="results_missing_evidence",
                    message="Results must cite at least one supplied fact",
                )
            )
        if not _contains_any_term(results_text, _INTERPRETATION_TERMS):
            violations.append(
                ReportQualityViolation(
                    code="results_missing_interpretation",
                    message="Results must interpret the cited findings conditionally",
                )
            )
        if not _contains_any_term(
            section_bodies.get("Limitations", ""), _LIMITATION_TERMS
        ):
            violations.append(
                ReportQualityViolation(
                    code="limitations_missing_scope",
                    message="Limitations must state an evidence or interpretation boundary",
                )
            )
        results_subsection_count = _section_subheading_count(
            normalized_text, "Results"
        )
        if len(result_citations) >= 2 and results_subsection_count < 2:
            violations.append(
                ReportQualityViolation(
                    code="results_subsections_required",
                    message=(
                        "Results must contain at least two titled subsections "
                        "when it contains multiple cited findings"
                    ),
                )
            )

        for numeric_token in _uncited_numeric_tokens(normalized_text):
            violations.append(
                ReportQualityViolation(
                    code="numeric_citation_missing",
                    message=f"numeric citation missing for {numeric_token}",
                    subject=numeric_token,
                )
            )

        missing_capabilities = tuple(
            capability
            for capability in normalized_capabilities
            if not _capability_is_covered(section_bodies, capability)
        )
        for capability in missing_capabilities:
            violations.append(
                ReportQualityViolation(
                    code="missing_capability",
                    message=f"missing capability module coverage: {capability}",
                    subject=capability,
                )
                )

        unavailable_capabilities = tuple(
            str(entry.get("capability_id"))
            for entry in capability_manifest
            if entry.get("capability_id") in normalized_capabilities
            and entry.get("availability") != "available"
        )
        for capability in unavailable_capabilities:
            violations.append(
                ReportQualityViolation(
                    code="unavailable_capability",
                    message=f"capability evidence is unavailable: {capability}",
                    subject=capability,
                )
            )

        usable_fact_ids = normalized_fact_ids - normalized_excluded_ids
        if not usable_fact_ids:
            missing_evidence = _missing_evidence_reasons(
                normalized_fact_ids,
                normalized_excluded_ids,
            )
            for reason in missing_evidence:
                violations.append(
                    ReportQualityViolation(
                        code="insufficient_evidence",
                        message=f"insufficient evidence: {reason}",
                        subject=reason,
                    )
                )
        else:
            missing_evidence = ()
        if unavailable_capabilities:
            missing_evidence = tuple(
                [*missing_evidence]
                + [f"capability unavailable: {capability}" for capability in unavailable_capabilities]
            )
    else:
        missing_sections = ()
        missing_capabilities = ()
        missing_evidence = ()
        missing_abstract_elements = ()
        unavailable_capabilities = ()
        results_subsection_count = 0

    violations = _unique_violations(violations)
    if report_standard == JOURNAL_FULL_REPORT_STANDARD and (
        not (normalized_fact_ids - normalized_excluded_ids)
        or unavailable_capabilities
    ):
        status: ReportQualityStatus = "insufficient_evidence"
    elif violations:
        status = "needs_revision"
    else:
        status = "exportable"

    return ReportQualityResult(
        status=status,
        normalized_text=normalized_text,
        violations=tuple(violations),
        missing_sections=missing_sections,
        missing_capabilities=missing_capabilities,
        missing_evidence=missing_evidence,
        missing_abstract_elements=missing_abstract_elements,
        unavailable_capabilities=unavailable_capabilities,
        results_subsection_count=results_subsection_count,
        cited_fact_ids=cited_fact_ids,
        figure_counts=figure_counts,
    )


def validate_report_response_quality(
    text: str,
    contract: ReportPacketContract,
    *,
    require_figure_markers: bool = True,
) -> ReportQualityResult:
    """Quality-validator adapter for a validated packet contract."""

    if not isinstance(contract, ReportPacketContract):
        _raise_quality_input(
            "contract must be a ReportPacketContract",
            code="invalid_report_contract",
        )
    return validate_report_quality(
        text,
        fact_ids=contract.fact_ids,
        figure_ids=contract.figure_ids,
        excluded_fact_ids=contract.excluded_fact_ids,
        report_standard=contract.report_standard,
        required_capabilities=contract.required_capabilities,
        capability_manifest=contract.capability_manifest,
        require_figure_markers=require_figure_markers,
    )


def _normalize_ids(value: object, *, field_name: str) -> frozenset[str] | tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        _raise_quality_input(
            f"{field_name}s must be an iterable of ids, not a string",
            code="invalid_quality_input",
        )
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        _raise_quality_input(
            f"{field_name}s must be an iterable of ids",
            code="invalid_quality_input",
        )
    for item in values:
        if not isinstance(item, str) or not _SAFE_ID.fullmatch(item):
            _raise_quality_input(
                f"{field_name} must be a safe non-empty id",
                code="invalid_quality_input",
                subject=str(item),
            )
    if len(values) != len(set(values)):
        _raise_quality_input(
            f"duplicate {field_name}",
            code="duplicate_quality_id",
        )
    if field_name == "required capability":
        return values
    return frozenset(values)


def _raise_quality_input(
    message: str,
    *,
    code: str,
    subject: str | None = None,
) -> None:
    violation = ReportQualityViolation(code=code, message=message, subject=subject)
    raise ReportQualityError(message, code=code, violations=(violation,))


def _contract_violations(
    messages: tuple[str, ...],
) -> list[ReportQualityViolation]:
    violations: list[ReportQualityViolation] = []
    for message in messages:
        if message == "report response is empty":
            code = "empty_report"
            subject = None
        elif message.startswith("unknown citation "):
            code = "unknown_fact"
            subject = message.removeprefix("unknown citation ")
        elif message.startswith("excluded fact "):
            code = "excluded_fact"
            subject = message.removeprefix("excluded fact ")
        elif message.startswith("missing figure marker "):
            code = "missing_figure"
            subject = message.removeprefix("missing figure marker ")
        elif message.startswith("duplicate figure marker "):
            code = "duplicate_figure"
            subject = message.removeprefix("duplicate figure marker ")
        elif message.startswith("unknown figure marker "):
            code = "unknown_figure"
            subject = message.removeprefix("unknown figure marker ")
        elif message == "malformed citation marker":
            code = "malformed_citation"
            subject = None
        elif message == "malformed figure marker":
            code = "malformed_figure"
            subject = None
        else:
            code = "report_contract_violation"
            subject = None
        violations.append(
            ReportQualityViolation(code=code, message=message, subject=subject)
        )
    return violations


def _section_bodies(text: str) -> dict[str, str]:
    matches = list(_HEADING.finditer(text))
    sections: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        level = len(match.group("marks"))
        heading = _heading_key(match.group("title"))
        canonical = _canonical_section(heading, level)
        if canonical is None:
            continue
        # A Results section commonly contains ### titled subsections. Those
        # child blocks belong to Results; only the next heading at the same or
        # higher level closes the parent section.
        end = len(text)
        for next_match in matches[index + 1 :]:
            if len(next_match.group("marks")) <= level:
                end = next_match.start()
                break
        sections.setdefault(canonical, []).append(text[match.end() : end])
    return {section: "\n".join(parts) for section, parts in sections.items()}


def _heading_key(value: str) -> str:
    value = re.sub(r"[ \t]+#+[ \t]*$", "", value).strip().casefold()
    value = value.replace("&", "and")
    # ``\w`` is Unicode-aware here, so Chinese section headings remain
    # addressable instead of being reduced to an empty string.
    return re.sub(r"[\s\W_]+", " ", value).strip()


def _canonical_section(heading: str, level: int) -> str | None:
    canonical = _SECTION_ALIASES.get(heading)
    if canonical is not None:
        return canonical
    # A free-form first-level heading is the document title, but named
    # top-level sections such as ``# Abstract`` or ``# Methods`` should still
    # be recognized.  Markdown authors commonly use one heading level for all
    # report sections, so heading depth cannot be the only discriminator.
    if level == 1:
        return "Title"
    for prefix, section in _SECTION_ALIASES.items():
        if heading.startswith(f"{prefix} "):
            return section
    return None


def _section_subheading_count(text: str, section: str) -> int:
    """Count titled child headings under one canonical section."""

    matches = list(_HEADING.finditer(text))
    for index, match in enumerate(matches):
        level = len(match.group("marks"))
        if _canonical_section(_heading_key(match.group("title")), level) != section:
            continue
        count = 0
        for child in matches[index + 1 :]:
            child_level = len(child.group("marks"))
            if child_level <= level:
                break
            if child.group("title").strip():
                count += 1
        return count
    return 0


def _narrative_text(text: str) -> str:
    """Remove structural markers before applying language-aware length floors."""

    chars = list(text)
    for match in _HEADING.finditer(text):
        _mask_span(chars, match.start(), match.end())
    for marker in (*_CITE_MARKER.finditer(text), *_FIGURE_MARKER.finditer(text)):
        _mask_span(chars, marker.start(), marker.end())
    return "".join(chars)


def _count_cjk_characters(text: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text))


def _count_latin_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)*", text))


def _is_cjk_dominant(text: str, cjk_characters: int, latin_words: int) -> bool:
    # A short CJK phrase in an otherwise English paper must not switch the
    # threshold. Conversely, a Chinese report with a few English model names
    # should use the character floor.
    if cjk_characters < 20:
        return False
    return cjk_characters >= max(20, latin_words * 2)


def _repeated_boilerplate_sentences(text: str) -> tuple[str, ...]:
    """Return long, exactly repeated sentences as a conservative quality signal.

    This is intentionally not a semantic writing score.  It only catches a
    mechanical way of satisfying the length floor and leaves paraphrase or
    domain-specific editorial judgment to the user.
    """

    sentences = re.split(r"(?<=[.!?。！？])(?:\s+|(?=[^\s]))", text)
    counts: dict[str, int] = {}
    for sentence in sentences:
        normalized = re.sub(r"\s+", " ", sentence).strip().casefold()
        if len(re.sub(r"\s+", "", normalized)) < 40:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    return tuple(sentence for sentence, count in counts.items() if count >= 3)


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    folded = text.casefold()
    normalized = _search_key(text)
    for term in terms:
        if any(ord(character) > 127 for character in term):
            if term.casefold() in folded:
                return True
        elif re.search(
            rf"(?<![a-z0-9]){re.escape(term.casefold())}(?![a-z0-9])",
            normalized,
        ):
            return True
    return False


def _uncited_numeric_tokens(text: str) -> tuple[str, ...]:
    masked = list(text)
    for match in _HEADING.finditer(text):
        _mask_span(masked, match.start(), match.end())
    for marker in (*_CITE_MARKER.finditer(text), *_FIGURE_MARKER.finditer(text)):
        _mask_span(masked, marker.start(), marker.end())
    for match in _ORDERED_LIST_PREFIX.finditer(text):
        _mask_span(masked, match.start(), match.end())
    masked_text = "".join(masked)

    missing: list[str] = []
    for match in _NUMBER.finditer(masked_text):
        if not _has_adjacent_citation(text, match.end()):
            missing.append(match.group(0))
    return tuple(missing)


def _mask_span(chars: list[str], start: int, end: int) -> None:
    chars[start:end] = [" "] * (end - start)


def _has_adjacent_citation(text: str, end: int) -> bool:
    cursor = end
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    while cursor < len(text) and text[cursor] in ",;:)]":
        cursor += 1
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
    return _CITE_MARKER.match(text, cursor) is not None


def _capability_aliases(capability: str) -> tuple[str, ...]:
    full = _search_key(capability)
    suffix = _search_key(capability.rsplit(".", 1)[-1])
    aliases = [full, suffix]
    aliases.extend(
        {
            "estimation": (
                "estimate",
                "estimation",
                "model",
                "coefficient",
                "parameter",
                "regression",
                "ols",
                "logit",
                "probit",
            ),
            "regression": ("回归", "估计", "模型"),
            "diagnostics robustness": (
                "diagnostics",
                "diagnostic",
                "robustness",
                "robust",
                "residual",
                "heteroskedastic",
                "standard error",
                "confidence interval",
                "p value",
                "normality",
                "autocorrelation",
                "诊断",
                "稳健性",
            ),
            "time series": ("time series", "forecast", "arma", "时间序列", "预测"),
            "post estimation": ("post estimation", "post-estimation", "后估计", "后估计结果"),
            "data": ("数据", "样本"),
            "model estimation": (
                "model",
                "estimation",
                "estimate",
                "coefficient",
                "parameter",
                "regression",
                "ols",
                "logit",
                "probit",
                "回归",
                "估计",
                "模型",
            ),
        }.get(full, ())
    )
    return _ordered_unique(alias for alias in aliases if alias)


def _contains_capability(text: str, capability: str) -> bool:
    normalized = _search_key(text)
    folded = text.casefold()
    return any(
        (
            alias.casefold() in folded
            if any(ord(character) > 127 for character in alias)
            else re.search(
                rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized
            ) is not None
        )
        for alias in _capability_aliases(capability)
    )


def _capability_is_covered(
    section_bodies: dict[str, str], capability: str
) -> bool:
    normalized = _search_key(capability)
    sections = _CAPABILITY_SECTIONS.get(
        normalized,
        ("Results", "Diagnostics and robustness"),
    )
    return any(
        _contains_capability(section_bodies.get(section, ""), capability)
        for section in sections
    )


def _search_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _missing_evidence_reasons(
    fact_ids: frozenset[str],
    excluded_fact_ids: frozenset[str],
) -> tuple[str, ...]:
    if not fact_ids:
        return ("fact_table is empty",)
    if fact_ids <= excluded_fact_ids:
        return ("all supplied facts are excluded",)
    return ("no usable facts are available",)


def _ordered_unique(values):
    return tuple(dict.fromkeys(values))


def _unique_violations(
    violations: list[ReportQualityViolation],
) -> list[ReportQualityViolation]:
    seen: set[tuple[str, str, str | None]] = set()
    unique: list[ReportQualityViolation] = []
    for violation in violations:
        key = (violation.code, violation.message, violation.subject)
        if key in seen:
            continue
        seen.add(key)
        unique.append(violation)
    return unique


__all__ = [
    "JOURNAL_MIN_CJK_CHARACTERS",
    "JOURNAL_MIN_CJK_SECTION_CHARACTERS",
    "JOURNAL_MIN_CHARACTERS",
    "JOURNAL_MIN_LATIN_WORDS",
    "JOURNAL_MIN_SECTION_CHARACTERS",
    "JOURNAL_MIN_WORDS",
    "JOURNAL_REQUIRED_SECTIONS",
    "ReportQualityError",
    "ReportQualityResult",
    "ReportQualityStatus",
    "ReportQualityViolation",
    "validate_report_quality",
    "validate_report_response_quality",
]
