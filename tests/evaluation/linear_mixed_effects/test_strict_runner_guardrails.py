from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from workbench.contracts.common.envelope import PacketEnvelope


REPO_ROOT = Path(__file__).parents[3]
STRICT_RUNNER = (
    REPO_ROOT / "tests" / "evaluation" / "linear_mixed_effects" / "strict_runner.py"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("v173_lmm_strict_runner", STRICT_RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result_packet() -> dict[str, object]:
    return PacketEnvelope(
        contract="linear_mixed_effects.result",
        contract_version="1.0",
        producer_version="linear_mixed_effects@1.0",
        payload={
            "model_type": "linear_mixed_effects",
            "primary_target_id": "group_time_interaction",
        },
    ).to_dict()


def test_performance_fit_consumes_a_c1_packet_and_requires_the_persisted_packet(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    packet = _result_packet()

    def fit(**kwargs: object) -> tuple[dict[str, object], SimpleNamespace]:
        run_root = kwargs["run_root"]
        assert isinstance(run_root, Path)
        (run_root / "linear_mixed_effects_contract.json").write_text(
            json.dumps(packet), encoding="utf-8"
        )
        return packet, SimpleNamespace(converged=True)

    evidence = runner._fit_once(fit, tmp_path / "known_truth.csv", tmp_path / "fit")

    assert evidence["artifact_sha256"]


def test_performance_fit_rejects_an_artifact_that_is_not_the_returned_packet(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    packet = _result_packet()

    def fit(**kwargs: object) -> tuple[dict[str, object], SimpleNamespace]:
        run_root = kwargs["run_root"]
        assert isinstance(run_root, Path)
        (run_root / "linear_mixed_effects_contract.json").write_text(
            json.dumps(packet["payload"]), encoding="utf-8"
        )
        return packet, SimpleNamespace(converged=True)

    with pytest.raises(runner.StrictEvaluationError, match="exact C1 packet"):
        runner._fit_once(fit, tmp_path / "known_truth.csv", tmp_path / "fit")


def test_strict_junit_requires_every_expected_candidate_result_without_skips(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    cases = "\n".join(
        "<testcase classname=\"tests.evaluation.linear_mixed_effects."
        f"{filename.removesuffix('.py')}\" name=\"candidate_case\"/>"
        for filename in runner.STRICT_TEST_FILES.values()
    )
    junit = tmp_path / "strict-suite.junit.xml"
    junit.write_text(f"<testsuite>{cases}</testsuite>", encoding="utf-8")

    states, counts = runner._summarize_strict_junit(junit)

    assert states == {name: "passed" for name in runner.RESULT_NAMES}
    assert counts == {name: 1 for name in runner.RESULT_NAMES}


@pytest.mark.parametrize(
    "xml, error",
    [
        ("<testsuite>", "not parseable"),
        ("<testsuite/>", "zero testcases"),
        (
            "<testsuite><testcase "
            "classname=\"tests.evaluation.linear_mixed_effects.test_contract_compatibility\" "
            "name=\"skipped_case\"><skipped/></testcase></testsuite>",
            "skip",
        ),
    ],
)
def test_strict_junit_rejects_missing_invalid_or_skipped_evidence(
    tmp_path: Path, xml: str, error: str
) -> None:
    runner = _load_runner()
    junit = tmp_path / "strict-suite.junit.xml"
    junit.write_text(xml, encoding="utf-8")

    with pytest.raises(runner.StrictEvaluationError, match=error):
        runner._summarize_strict_junit(junit)
