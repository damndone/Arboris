"""Reusable adversarial checkers for the v1.8.1 evaluation.

Every checker in this module is itself tested against a counterexample in
``test_checkers_detect_their_own_bugs.py``. A checker that has only ever seen
clean input is not evidence.

Failures are returned as structured findings, not bare booleans, because ADR
§10.2 / the work order require each failure report to carry: what was checked,
what was expected, what was observed, and the minimal evidence.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Overclaim vocabulary
# ---------------------------------------------------------------------------

# Whole-word patterns. ETS models the conditional MEAN; none of these belong in
# an ETS result, field name, or narration (ets.py docstring point 6).
#
# Lookarounds are ``(?<![A-Za-z])`` / ``(?![A-Za-z])`` rather than ``\b`` on
# purpose: ``\b`` treats ``_`` as a word character, so ``\bvolatility\b`` misses
# the field name ``conditional_volatility_forecast`` — which is precisely the
# smuggling route this scanner exists to close.
VOLATILITY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("value_at_risk", r"(?<![A-Za-z])value[ _-]?at[ _-]?risk(?![A-Za-z])"),
    ("var_acronym", r"(?<![A-Za-z_])VaR(?![A-Za-z_])"),
    ("var_field", r"(?<![A-Za-z_])var(?![A-Za-z_])"),
    ("conditional_variance", r"(?<![A-Za-z])conditional[ _-]?variance(?![A-Za-z])"),
    ("conditional_volatility", r"(?<![A-Za-z])conditional[ _-]?volatilit(y|ies)(?![A-Za-z])"),
    ("volatility", r"(?<![A-Za-z])volatilit(y|ies)(?![A-Za-z])"),
    ("garch", r"(?<![A-Za-z])g?arch(?![A-Za-z])"),
    ("expected_shortfall", r"(?<![A-Za-z])expected[ _-]?shortfall(?![A-Za-z])"),
    ("cvar", r"(?<![A-Za-z_])c[_-]?var(?![A-Za-z_])"),
    ("risk_metric", r"(?<![A-Za-z])risk[ _-]?metric(?![A-Za-z])"),
)

# Words that make a cross-family information-criterion comparison a *claim*
# rather than a display of two numbers.
SUPERIORITY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("better", r"\bbetter\b"),
    ("worse", r"\bworse\b"),
    ("outperform", r"\boutperform(s|ed|ing)?\b"),
    ("superior", r"\bsuperior\b"),
    ("preferred", r"\bpreferred\b"),
    ("beats", r"\bbeats?\b"),
    ("wins", r"\bwins?\b"),
    ("best_model", r"\bbest[ _-]?(model|fit|specification)\b"),
    ("lower_aic_means", r"\blower\s+(aic|bic)\b"),
)

_ARMA_FAMILY = {"time_series.arma_garch"}
_ETS_FAMILY = {"time_series.ets"}


@dataclass(frozen=True)
class Finding:
    """One machine-checkable violation."""

    check: str
    path: str
    expected: str
    observed: str
    evidence: str

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"[{self.check}] at {self.path}\n"
            f"  expected: {self.expected}\n"
            f"  observed: {self.observed}\n"
            f"  evidence: {self.evidence}"
        )


def format_findings(findings: Sequence[Finding]) -> str:
    return "\n".join(str(item) for item in findings)


def _walk(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def _matches(text: str, patterns: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    hits = []
    for name, pattern in patterns:
        found = re.search(pattern, text, flags=re.IGNORECASE)
        if found:
            hits.append((name, found.group(0)))
    return hits


def scan_volatility_overclaims(payload: Any, *, subject: str = "ets_result") -> list[Finding]:
    """Any VaR / volatility / conditional-variance vocabulary is a failure.

    Both keys and string values are scanned: the smuggling routes are a field
    named ``conditional_volatility`` and a narration sentence that says "Value
    at Risk" while the fields stay clean.
    """

    findings: list[Finding] = []
    for path, node in _walk(payload):
        if isinstance(node, Mapping):
            for key in node:
                for name, hit in _matches(str(key), VOLATILITY_PATTERNS):
                    findings.append(
                        Finding(
                            check="ets_no_volatility_claims",
                            path=f"{path}.{key}",
                            expected="an ETS result reports conditional-mean quantities only",
                            observed=f"field name matches {name!r}: {hit!r}",
                            evidence=f"{subject}: key {key!r}",
                        )
                    )
        elif isinstance(node, str):
            for name, hit in _matches(node, VOLATILITY_PATTERNS):
                findings.append(
                    Finding(
                        check="ets_no_volatility_claims",
                        path=path,
                        expected="an ETS result reports conditional-mean quantities only",
                        observed=f"text matches {name!r}: {hit!r}",
                        evidence=f"{subject}: {node[:200]!r}",
                    )
                )
    return findings


def _model_types(payload: Any) -> set[str]:
    found: set[str] = set()
    for _, node in _walk(payload):
        if isinstance(node, Mapping):
            value = node.get("model_type")
            if isinstance(value, str):
                found.add(value)
    return found


def scan_cross_family_ic_claims(payload: Any, *, subject: str = "compare") -> list[Finding]:
    """An ETS-vs-ARMA-GARCH AIC/BIC ranking presented as a verdict is a failure.

    Contract point 3: the only honest answer is ``comparability: restricted``
    with ``reason_code: ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE``.
    """

    families = _model_types(payload)
    if not (families & _ETS_FAMILY and families & _ARMA_FAMILY):
        return []

    findings: list[Finding] = []

    comparability = None
    reason_code = None
    for _, node in _walk(payload):
        if isinstance(node, Mapping):
            comparability = node.get("comparability", comparability)
            reason_code = node.get("reason_code", reason_code)

    if comparability != "restricted":
        findings.append(
            Finding(
                check="cross_family_ic_not_comparable",
                path="$.comparability",
                expected="'restricted' when ETS is compared with ARMA-GARCH",
                observed=repr(comparability),
                evidence=f"{subject}: model types {sorted(families)}",
            )
        )
    if reason_code != "ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE":
        findings.append(
            Finding(
                check="cross_family_ic_not_comparable",
                path="$.reason_code",
                expected="'ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE'",
                observed=repr(reason_code),
                evidence=f"{subject}: model types {sorted(families)}",
            )
        )

    for path, node in _walk(payload):
        if isinstance(node, str):
            hits = _matches(node, SUPERIORITY_PATTERNS)
            mentions_ic = re.search(r"\b(aic|bic|information criteri)", node, re.IGNORECASE)
            if hits and mentions_ic:
                findings.append(
                    Finding(
                        check="cross_family_ic_not_comparable",
                        path=path,
                        expected="no superiority claim built on a cross-family IC",
                        observed=f"superiority language {hits} alongside an IC mention",
                        evidence=f"{subject}: {node[:200]!r}",
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Option batch / self-reference
# ---------------------------------------------------------------------------


def scan_option_hash_merge(packet: Mapping[str, Any]) -> list[Finding]:
    """The two §4.0 hashes must be distinct values with distinct prefixes."""

    generation = packet.get("generation_context_hash")
    freshness = packet.get("freshness_dependency_fingerprint")
    findings: list[Finding] = []
    if generation == freshness:
        findings.append(
            Finding(
                check="hashes_not_merged",
                path="$.generation_context_hash / $.freshness_dependency_fingerprint",
                expected="two distinct values (spec §4.0)",
                observed=f"both equal {generation!r}",
                evidence=f"option {packet.get('option_id')!r} rev {packet.get('option_revision')!r}",
            )
        )
    if isinstance(generation, str) and not generation.startswith("sha256:"):
        findings.append(
            Finding(
                check="hashes_not_merged",
                path="$.generation_context_hash",
                expected="sha256: prefix",
                observed=repr(generation),
                evidence=f"option {packet.get('option_id')!r}",
            )
        )
    if isinstance(freshness, str) and not freshness.startswith("fresh1:"):
        findings.append(
            Finding(
                check="hashes_not_merged",
                path="$.freshness_dependency_fingerprint",
                expected="fresh1: prefix",
                observed=repr(freshness),
                evidence=f"option {packet.get('option_id')!r}",
            )
        )
    return findings


def scan_batch_self_reference(batch: Sequence[Mapping[str, Any]]) -> list[Finding]:
    """After a batch is generated, every option in it must still be fresh.

    Three separate ways the self-reference bug shows up:

    1. an option is already ``stale`` at birth;
    2. options in one batch disagree about the generation context they were
       produced from (the context moved *during* generation);
    3. options in one batch carry different freshness fingerprints, which means
       the dependency set was recomputed after each insertion — the compiled
       context is feeding itself.
    """

    findings: list[Finding] = []
    if not batch:
        return [
            Finding(
                check="batch_all_fresh",
                path="$",
                expected="a non-empty batch",
                observed="0 options",
                evidence="scan_batch_self_reference received an empty batch",
            )
        ]

    for packet in batch:
        status = packet.get("freshness_status")
        if status != "fresh":
            findings.append(
                Finding(
                    check="batch_all_fresh",
                    path=f"$[{packet.get('rank')}].freshness_status",
                    expected="'fresh' immediately after generation",
                    observed=repr(status),
                    evidence=(
                        f"option {packet.get('option_id')!r} in batch "
                        f"{packet.get('batch_id')!r}"
                    ),
                )
            )

    contexts = {packet.get("generation_context_id") for packet in batch}
    if len(contexts) > 1:
        findings.append(
            Finding(
                check="batch_single_generation_context",
                path="$[*].generation_context_id",
                expected="one generation context for the whole batch",
                observed=f"{sorted(map(repr, contexts))}",
                evidence=f"batch {batch[0].get('batch_id')!r}",
            )
        )

    fingerprints = {packet.get("freshness_dependency_fingerprint") for packet in batch}
    if len(fingerprints) > 1:
        findings.append(
            Finding(
                check="batch_single_freshness_fingerprint",
                path="$[*].freshness_dependency_fingerprint",
                expected=(
                    "one dependency fingerprint per batch — the options must not "
                    "enter their own dependency set"
                ),
                observed=f"{len(fingerprints)} distinct fingerprints",
                evidence=f"batch {batch[0].get('batch_id')!r}: {sorted(fingerprints)}",
            )
        )

    ranks = sorted(packet.get("rank") for packet in batch)
    if ranks != list(range(1, len(batch) + 1)):
        findings.append(
            Finding(
                check="batch_ranks_dense",
                path="$[*].rank",
                expected=f"ranks 1..{len(batch)}",
                observed=repr(ranks),
                evidence=f"batch {batch[0].get('batch_id')!r}",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# ETS result arithmetic
# ---------------------------------------------------------------------------


def check_ic_identity(result: Mapping[str, Any], *, abs_tol: float) -> list[Finding]:
    """AIC and BIC must be the same likelihood and the same k.

    ``aic = -2 llf + 2k`` and ``bic = -2 llf + k ln(n)`` imply
    ``k = (aic + 2 llf) / 2`` and ``bic - aic = k (ln n - 2)``. k must come out
    an integer. This catches a composite / hand-assembled information criterion,
    which the v1.8.0 ledger already refuses.
    """

    findings: list[Finding] = []
    try:
        aic = float(result["aic"])
        bic = float(result["bic"])
        llf = float(result["log_likelihood"])
        n_obs = int(result["n_obs"])
    except (KeyError, TypeError, ValueError) as error:
        return [
            Finding(
                check="ic_identity",
                path="$",
                expected="aic, bic, log_likelihood, n_obs present and numeric",
                observed=repr(error),
                evidence=repr(sorted(result)),
            )
        ]

    k_implied = (aic + 2.0 * llf) / 2.0
    if abs(k_implied - round(k_implied)) > 1e-6:
        findings.append(
            Finding(
                check="ic_identity",
                path="$.aic",
                expected="aic = -2*log_likelihood + 2k for integer k",
                observed=f"implied k = {k_implied!r}",
                evidence=f"aic={aic!r} log_likelihood={llf!r}",
            )
        )
    k = round(k_implied)
    expected_bic = -2.0 * llf + k * math.log(n_obs)
    if abs(expected_bic - bic) > max(abs_tol, abs(bic) * 1e-9):
        findings.append(
            Finding(
                check="ic_identity",
                path="$.bic",
                expected=f"bic = -2*log_likelihood + k*ln(n) = {expected_bic!r} (k={k}, n={n_obs})",
                observed=repr(bic),
                evidence=f"aic={aic!r} log_likelihood={llf!r} n_obs={n_obs!r}",
            )
        )
    return findings


__all__ = [
    "Finding",
    "SUPERIORITY_PATTERNS",
    "VOLATILITY_PATTERNS",
    "check_ic_identity",
    "format_findings",
    "scan_batch_self_reference",
    "scan_cross_family_ic_claims",
    "scan_option_hash_merge",
    "scan_volatility_overclaims",
]
