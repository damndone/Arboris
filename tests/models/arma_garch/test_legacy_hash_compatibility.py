"""Old run options retain their hashes and remain comparable after rerunning.

The repository run-family fixture contains configuration, not its VIX data.
The golden contract/split/sample were captured with f7c6ba5b on the fixed
synthetic source below; this is compatibility evidence, not VIX replication.
"""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.analysis_loop.time_series_compare import build_arma_garch_compare_packet
from workbench.canonical import sha256_canonical
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.context import DataHandle, ModelingContext, RunEnv
from workbench.engine.packs.arma_garch.input import prepare_arma_garch_input
from workbench.engine.packs.arma_garch.runner import fit_from_context
from workbench.engine.packs.arma_garch.split import freeze_train_validation_split
from workbench.model_options import (
    ModelOptionsError, bind_new_model_options, verify_bound_model_options,
)
from workbench.services.run_service import merge_form_overrides


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
LEGACY_INPUTS = FIXTURES / "run_family/20260722_043812_924307_874cc62b/run_inputs.json"
REFERENCE = json.loads((FIXTURES / "arma_garch_legacy_hashes.json").read_text())


def _form():
    return json.loads(LEGACY_INPUTS.read_text())["form"]


def _source():
    return pd.DataFrame({
        "observation_date": pd.bdate_range("2025-01-01", periods=120),
        "VIXCLS": np.random.default_rng(181106).integers(20, 80, size=120).astype(float),
    })


@pytest.mark.parametrize("explicit_default", [False, True])
def test_default_contract_and_split_match_pre_classic_golden(explicit_default):
    options = _form()["model_options"]
    if explicit_default:
        options["validation"]["evaluation_mode"] = "train_validation"
    contract = ArmaGarchAnalysisContract.from_dict(options)
    assert contract.validation.evaluation_mode == "train_validation"
    assert contract.contract_hash == REFERENCE["contract_hash"]
    assert contract.to_dict() == REFERENCE["analysis_contract"]
    split = freeze_train_validation_split(prepare_arma_garch_input(_source(), contract).transformed_view, contract)
    assert split.split_hash == REFERENCE["split_hash"]
    assert split.split_hash == sha256_canonical(split.hash_payload())
    assert "evaluation_mode" not in split.hash_payload()
    assert "estimation_row_ids" not in split.hash_payload()


def test_classic_scope_still_changes_contract_and_split_identity():
    options = _form()["model_options"]
    options["validation"]["evaluation_mode"] = "classical_replication"
    contract = ArmaGarchAnalysisContract.from_dict(options)
    split = freeze_train_validation_split(prepare_arma_garch_input(_source(), contract).transformed_view, contract)
    assert contract.contract_hash != REFERENCE["contract_hash"]
    assert contract.to_dict()["validation"]["evaluation_mode"] == "classical_replication"
    assert split.split_hash != REFERENCE["split_hash"]
    assert split.hash_payload()["evaluation_mode"] == "classical_replication"
    assert split.hash_payload()["estimation_row_ids"] == list(split.estimation_row_ids)
    assert split.split_hash == sha256_canonical(split.hash_payload())


def test_old_binding_survives_rerun_and_explicit_default_is_normalized():
    form = _form()
    before = deepcopy(form)
    old = verify_bound_model_options(form["model_options"], form["model_options_binding"])
    assert old.binding.normalized_options_hash == REFERENCE["binding_hash"]
    rerun = merge_form_overrides(form, {})
    rebound = bind_new_model_options(form["model_type"], rerun["model_options"])
    assert rebound.binding.to_dict() == form["model_options_binding"]
    explicit = deepcopy(form["model_options"])
    explicit["validation"]["evaluation_mode"] = "train_validation"
    default_bound = bind_new_model_options(form["model_type"], explicit)
    assert default_bound == rebound
    assert explicit["validation"]["evaluation_mode"] == "train_validation"
    assert form == before
    classic = deepcopy(explicit)
    classic["validation"]["evaluation_mode"] = "classical_replication"
    classic_bound = bind_new_model_options(form["model_type"], classic)
    assert classic_bound.payload["validation"]["evaluation_mode"] == "classical_replication"
    assert classic_bound.binding.normalized_options_hash != REFERENCE["binding_hash"]
    # Persisted bytes must still be checked before any new-submission normalization.
    with pytest.raises(ModelOptionsError, match="normalized_options_hash"):
        verify_bound_model_options(explicit, form["model_options_binding"])


class _Recorder:
    def record_stage(self, *args, **kwargs):
        pass

    def record_edge(self, *args, **kwargs):
        pass


def test_rerun_artifacts_compare_without_split_or_sample_change(tmp_path):
    form = _form()
    rerun = merge_form_overrides(form, {})
    bound = bind_new_model_options(form["model_type"], rerun["model_options"])
    checked = verify_bound_model_options(bound.payload, bound.binding.to_dict())
    source = _source()
    (tmp_path / "artifacts_index.json").write_text('{"artifacts": []}')
    ctx = ModelingContext(
        data=DataHandle.of(source, artifact_id="cleaned_dataset", provenance=("source.csv",)),
        y_col="VIXCLS", x_cols=[], y_type="continuous",
        requested_model_type=form["model_type"],
    )
    ctx.artifacts.update({"_model_options": checked.payload, "_frames": {"source.csv": source}})
    fit_from_context(ctx, RunEnv(run_root=tmp_path, run_id="rerun", recorder=_Recorder()))
    child = {p.stem: json.loads(p.read_text())["payload"]
             for p in (tmp_path / "artifacts/time_series").glob("ts.*.json")}
    assert child["ts.report"]["reproducibility"]["contract_hash"] == REFERENCE["contract_hash"]
    assert child["ts.report"]["reproducibility"]["split_hash"] == REFERENCE["split_hash"]
    # Keep results identical to isolate old versus new persisted identity shapes.
    legacy = deepcopy(child)
    legacy["ts.analysis_contract"] = REFERENCE["analysis_contract"]
    legacy["ts.report"]["sample"] = REFERENCE["sample"]
    legacy["ts.report"]["reproducibility"].update({
        "contract_hash": REFERENCE["contract_hash"], "split_hash": REFERENCE["split_hash"],
    })
    packet = build_arma_garch_compare_packet(
        source_run_id="legacy", child_run_id="rerun", child_source_run_id="legacy",
        source_artifacts=legacy, child_artifacts=child,
    ).to_dict()
    assert packet["data_diff"]["split_contract_changed"] is False
    assert packet["data_diff"]["changed"] is False
    assert packet["parameter_diff"]["changed"] is False
