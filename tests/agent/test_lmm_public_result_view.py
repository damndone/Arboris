from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest


def _options() -> dict[str, object]:
    return {"subject_id": "participant_id", "time": "week", "group": "arm", "fit_method": "reml", "random_slope": True}


def _valid_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "run-a") -> Path:
    from workbench.engine.registry import MODEL_REGISTRY, ModelHandler
    from workbench.model_options import ModelOptionsBinding, ModelOptionsContract, canonical_options_hash
    from workbench.services.pinned_run_directory import (
        _new_test_lmm_execution_admission,
        open_pinned_run_directory,
        seal_executed_input_v1,
    )
    from workbench.engine.packs.linear_mixed_effects.runner import fit_linear_mixed_effects
    from workbench.contracts.model.linear_mixed_effects import LmmModelInput

    run_root = tmp_path / name
    run_root.mkdir()
    options = _options()
    binding = ModelOptionsBinding("linear_mixed_effects", "linear_mixed_effects_1", "linear_mixed_effects@1.0", "1.0", canonical_options_hash(options)).to_dict()
    (run_root / "run_inputs.json").write_text(json.dumps({"executed_payload": {"model_type": "linear_mixed_effects", "model_options": options, "model_options_binding": binding}}))
    monkeypatch.setitem(MODEL_REGISTRY, "linear_mixed_effects", ModelHandler("linear_mixed_effects", "linear_mixed_effects_1", ("continuous",), lambda *_: None, LmmModelInput.from_dict, ModelOptionsContract("linear_mixed_effects@1.0", "1.0")))
    with open_pinned_run_directory(tmp_path, name) as pinned:
        seal = seal_executed_input_v1(pinned, {"schema_version": 1, "model_type": "linear_mixed_effects", "model_options": options, "model_options_binding": binding})
        admission = _new_test_lmm_execution_admission(pinned, seal)
        try:
            fit_linear_mixed_effects(csv_path=Path(__file__).parents[1] / "fixtures" / "models" / "linear_mixed_effects" / "known_truth.csv", outcome="score", controls=["baseline_score"], options=options, run_root=run_root, sealed_execution_input=seal, pinned_run=pinned, model_options_binding=binding, lmm_execution_admission=admission)
        finally:
            admission._close_for_test()
    return run_root


def test_public_result_view_is_neutral_for_missing_run(tmp_path: Path) -> None:
    from workbench.agent.recipes.lmm_public_result_view import (
        build_repeated_measures_recipe_from_run,
    )

    assert build_repeated_measures_recipe_from_run(tmp_path, "missing") == {
        "proposal": None,
        "plan_diff": None,
        "explanation": "未提供可用于生成说明的受控 LMM 诊断。",
    }


def test_prevalidated_recipe_is_only_a_confirmation_bound_plain_dict() -> None:
    from workbench.agent.recipes.repeated_measures import (
        build_repeated_measures_recipe_from_validated_facts,
    )
    from workbench.contracts.model.linear_mixed_effects import LmmDiagnostic, LmmModelInput

    recipe = build_repeated_measures_recipe_from_validated_facts(
        LmmModelInput("subject", "time", "group", "reml", True),
        (LmmDiagnostic(
            code="LMM_RANDOM_SLOPE_NEAR_ZERO", severity="warning", status="complete",
            evidence={"slope_variance": 0.0},
            action_candidate={
                "action_id": "lmm.simplify_random_effects_v1", "operation_id": "model.rerun",
                "patch": {"model_options": {"random_slope": False}}, "required_confirmation": True,
            },
        ),),
    )
    assert set(recipe) == {"proposal", "plan_diff", "explanation"}
    assert recipe["proposal"] == {
        "operation": "model.rerun", "patch": {"model_options": {"random_slope": False}},
        "requires_confirmation": True,
    }


def test_public_result_view_reads_one_bound_run_without_side_effects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from workbench.agent.recipes.lmm_public_result_view import build_repeated_measures_recipe_from_run
    from workbench.engine.registry import MODEL_REGISTRY

    run_root = _valid_run(tmp_path, monkeypatch)
    before = dict(MODEL_REGISTRY)
    recipe = build_repeated_measures_recipe_from_run(tmp_path, "run-a")
    assert recipe["proposal"] is not None
    assert recipe["proposal"]["operation"] == "model.rerun"
    assert dict(MODEL_REGISTRY) == before
    assert (run_root / "artifacts" / "execution" / "executed_input_v1.json").is_file()


def test_public_result_view_rejects_cross_run_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from workbench.agent.recipes.lmm_public_result_view import build_repeated_measures_recipe_from_run

    source = _valid_run(tmp_path, monkeypatch, "run-a")
    replay = tmp_path / "run-b"
    replay.mkdir()
    for relative in ("artifacts", "artifacts_index.json", "run_inputs.json"):
        source_path, replay_path = source / relative, replay / relative
        if source_path.is_dir():
            import shutil
            shutil.copytree(source_path, replay_path)
        else:
            shutil.copy2(source_path, replay_path)
    assert build_repeated_measures_recipe_from_run(tmp_path, "run-b") == {
        "proposal": None, "plan_diff": None, "explanation": "未提供可用于生成说明的受控 LMM 诊断。"
    }


def _mutate_packet(run_root: Path, mutate) -> None:
    packet_path = run_root / "artifacts" / "model_results" / "linear_mixed_effects_1.result.json"
    packet = json.loads(packet_path.read_text())
    mutate(packet)
    raw = json.dumps(packet, ensure_ascii=False, sort_keys=True).encode()
    packet_path.write_bytes(raw)
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text())
    index["artifacts"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    index_path.write_text(json.dumps(index))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda packet: packet["payload"].__setitem__("status", "failed"),
        lambda packet: packet.__setitem__("producer_version", "wrong@1"),
        lambda packet: packet["payload"].__setitem__("random_effects_specification", "1"),
        lambda packet: packet["payload"].__setitem__("diagnostics", []),
    ],
)
def test_public_result_view_neutralizes_terminal_fact_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate) -> None:
    from workbench.agent.recipes.lmm_public_result_view import build_repeated_measures_recipe_from_run

    run_root = _valid_run(tmp_path, monkeypatch)
    _mutate_packet(run_root, mutate)
    assert build_repeated_measures_recipe_from_run(tmp_path, "run-a")["proposal"] is None


def test_public_result_view_neutralizes_mutated_seal_and_malformed_loaded_handler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from workbench.agent.recipes.lmm_public_result_view import build_repeated_measures_recipe_from_run
    from workbench.engine.registry import MODEL_REGISTRY, ModelHandler

    run_root = _valid_run(tmp_path, monkeypatch)
    (run_root / "artifacts" / "execution" / "executed_input_v1.json").write_text("{}")
    assert build_repeated_measures_recipe_from_run(tmp_path, "run-a")["proposal"] is None
    _valid_run(tmp_path, monkeypatch, "run-c")
    monkeypatch.setitem(MODEL_REGISTRY, "linear_mixed_effects", ModelHandler("wrong", "linear_mixed_effects_1", (), lambda *_: None, None, None))
    assert build_repeated_measures_recipe_from_run(tmp_path, "run-c")["proposal"] is None


def test_public_result_view_neutralizes_non_handler_registry_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from workbench.agent.recipes.lmm_public_result_view import build_repeated_measures_recipe_from_run
    from workbench.engine.registry import MODEL_REGISTRY

    _valid_run(tmp_path, monkeypatch)
    monkeypatch.setitem(MODEL_REGISTRY, "linear_mixed_effects", object())
    assert build_repeated_measures_recipe_from_run(tmp_path, "run-a") == {
        "proposal": None, "plan_diff": None, "explanation": "未提供可用于生成说明的受控 LMM 诊断。"
    }


def test_public_view_does_not_call_execution_or_agent_side_effects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from workbench.agent.recipes.lmm_public_result_view import build_repeated_measures_recipe_from_run
    from workbench.agent.proposals import ProposalStore
    from workbench.agent.operations import OperationRegistry
    from workbench.agent.recipes.registry import AgentRecipeRegistry
    import subprocess
    import workbench.engine.packs.loader as loader

    run_root = _valid_run(tmp_path, monkeypatch)
    watched = [run_root / "run_inputs.json", run_root / "artifacts_index.json", run_root / "artifacts" / "execution" / "executed_input_v1.json", run_root / "artifacts" / "model_results" / "linear_mixed_effects_1.result.json"]
    before = [path.read_bytes() for path in watched]
    def forbidden(*_args, **_kwargs): raise AssertionError("side effect")
    monkeypatch.setattr(ProposalStore, "create", forbidden)
    monkeypatch.setattr(OperationRegistry, "require", forbidden)
    monkeypatch.setattr(AgentRecipeRegistry, "register", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(loader, "bootstrap_builtin_packs", forbidden)
    assert build_repeated_measures_recipe_from_run(tmp_path, "run-a")["proposal"] is not None
    assert [path.read_bytes() for path in watched] == before
