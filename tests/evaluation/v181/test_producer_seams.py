"""Producer-bound checks for the two work-order requirements that only mean
something against a *real* producer, not against a synthetic packet:

* self-reference — "一批 3 条 option 生成后全部仍为 fresh" (work order §produces);
* cross-family comparability — "ETS vs ARMA-GARCH 的 AIC 比较必须被拒绝".

The adversarial checkers behind both (``scan_batch_self_reference`` and
``scan_cross_family_ic_claims``) are already proven to catch their bugs in
``test_checkers_detect_their_own_bugs.py`` against hand-built counterexamples. A
checker that has only ever seen a synthetic packet is not, by itself, evidence
that the *shipped producer* is clean — so these tests point the same checkers at
the public seams the contracts imply (``capabilities.notebook_option_batch`` and
``capabilities.ets_compare_adapter``).

Neither seam exists in the v1.8.1 contract-lock worktree: the Agent Lane has not
shipped a public option-batch generator, and there is no cross-family ETS↔ARMA
compare adapter (the shipped ``time_series_compare`` module is ARMA-GARCH only).
So every test here is ``xfail(strict=True)`` while its capability is absent — the
body still runs, still fails, and is reported as ``xfailed`` naming the lane it
waits on; it is never a vacuous pass. When the seam lands the marker stops
applying and the producer's real output must satisfy the checker on its merits.

Following ``driver.py``'s rule, the harness drives the *public* seam and reports
a signature mismatch as a contract gap; it does not read a lane's internals to
discover a private entry point (ADR §7D).
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from tests.evaluation.v181 import capabilities
from tests.evaluation.v181.checks import (
    format_findings,
    scan_batch_self_reference,
    scan_cross_family_ic_claims,
)
from tests.evaluation.v181.driver import ETSPackUnavailable, fit_ets
from tests.evaluation.v181.test_ets_known_truth import as_ets_result
from tests.fixtures.evaluation.v181 import ets_known_truth as oracle

_BATCH = capabilities.notebook_option_batch()
requires_option_batch = pytest.mark.xfail(
    not _BATCH.present, reason=_BATCH.reason, strict=True, run=True
)

_COMPARE = capabilities.ets_compare_adapter()
_ETS = capabilities.ets_model_pack()
_CROSS_FAMILY_PRESENT = _COMPARE.present and _ETS.present
requires_cross_family_adapter = pytest.mark.xfail(
    not _CROSS_FAMILY_PRESENT,
    reason=(
        f"awaiting cross-family compare: {_COMPARE.reason}"
        if not _COMPARE.present
        else _ETS.reason
    ),
    strict=True,
    run=True,
)


def _as_dict(option: Any) -> dict[str, Any]:
    """Coerce whatever the generator yields into the contract-shaped mapping."""

    if hasattr(option, "to_dict"):
        return dict(option.to_dict())
    if isinstance(option, dict):
        return dict(option)
    raise AssertionError(
        "the option-batch generator yielded an item that is neither a mapping "
        f"nor a to_dict()-bearing contract object: {type(option)!r}. The public "
        "seam does not match NotebookOptionRevision — reported as a contract gap."
    )


def _invoke_batch(generator: Any, *, notebook_id: str, count: int) -> list[Any]:
    """Call the generator through the plausible contract-named signatures.

    A generator that accepts none of these keyword shapes is a contract gap: the
    harness reports which spellings it tried rather than reading the Agent Lane's
    implementation to discover the real one.
    """

    if generator is None:  # capability absent -> strict xfail catches this
        raise ETSPackUnavailable("no public option-batch generator is importable")

    attempts: list[dict[str, Any]] = [
        {"notebook_id": notebook_id, "count": count},
        {"notebook_id": notebook_id, "n": count},
        {"notebook_id": notebook_id, "size": count},
        {"notebook_id": notebook_id},
    ]
    signature = None
    try:
        signature = inspect.signature(generator)
    except (TypeError, ValueError):
        signature = None

    last_error: Exception | None = None
    for kwargs in attempts:
        if signature is not None:
            if not all(name in signature.parameters for name in kwargs):
                continue
        try:
            result = generator(**kwargs)
        except TypeError as error:
            last_error = error
            continue
        return list(result)
    raise AssertionError(
        "the option-batch generator accepted none of the contract-named "
        f"signatures {attempts}; last error: {last_error!r}. Reported as a "
        "contract gap, not patched."
    )


@requires_option_batch
def test_real_option_batch_of_three_is_all_fresh_and_self_consistent() -> None:
    """A batch of 3 real options must all be fresh, share one context, and not
    stale themselves (spec §4.0 self-reference)."""

    generator = capabilities.notebook_option_batch().handle
    batch = _invoke_batch(generator, notebook_id="nb_eval_0001", count=3)
    options = [_as_dict(item) for item in batch]

    assert len(options) == 3, (
        f"asked for 3 options, the generator produced {len(options)}"
    )
    findings = scan_batch_self_reference(options)
    assert findings == [], format_findings(findings)


def _cross_family_compare(adapter: Any, tmp_path: Path) -> Any:
    """Drive a real cross-family compare of an ETS fit against ARMA-GARCH.

    The ETS side is a genuine pack result on a known-truth series; the ARMA-GARCH
    side is the family the compare must refuse to rank against. The exact adapter
    invocation is the seam this test pins — a signature mismatch is a contract
    gap, reported not patched.
    """

    if adapter is None:  # capability absent -> strict xfail catches this
        raise ETSPackUnavailable("no cross-family compare adapter is importable")

    truth = oracle.aadn_damped_trend()
    ets_result, _meta = fit_ets(
        truth.values, truth.spec, tmp_path=tmp_path, run_id="cross-family-ets"
    )
    left = as_ets_result(ets_result)
    right = {
        "model_type": "time_series.arma_garch",
        "aic": float(left.get("aic", 0.0)) - 150.0,
    }

    attempts = (
        {"left": left, "right": right},
        {"a": left, "b": right},
    )
    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            return adapter(**kwargs)
        except TypeError as error:
            last_error = error
            continue
    try:
        return adapter(left, right)
    except TypeError as error:
        raise AssertionError(
            "the cross-family compare adapter accepted none of the pinned "
            f"call shapes; last error: {last_error or error!r}. Reported as a "
            "contract gap."
        )


@requires_cross_family_adapter
def test_real_cross_family_compare_refuses_to_rank_ets_against_arma_garch(
    tmp_path: Path,
) -> None:
    """Contract point 3: an ETS↔ARMA-GARCH compare must return
    ``comparability: restricted`` with no superiority verdict built on AIC/BIC."""

    adapter = capabilities.ets_compare_adapter().handle
    packet = _cross_family_compare(adapter, tmp_path)
    payload = packet.to_dict() if hasattr(packet, "to_dict") else packet
    findings = scan_cross_family_ic_claims(payload, subject="real_cross_family_compare")
    assert findings == [], format_findings(findings)
