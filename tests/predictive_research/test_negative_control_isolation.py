"""The permuted-target control draws its training labels only from the scope it is fitted in.

2026-11-06 risk review, finding 9: the target was permuted over every row before the folds were
taken, so final-holdout labels entered the control's training targets while the packet declared
development-only fitting and an isolated holdout. Changing only the holdout labels changed the
control's development CV.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from workbench.predictive_research.contracts import (
    AvailabilitySpecV1, SampleSpecV1, SamplingSpecV1, SplitPlanV1, StructureSpecV1,
)
from workbench.predictive_research.prediction_protocol import run_oos_prediction
from workbench.predictive_research.split_kernel import build_split_plan


class RecordingMean:
    fits: list[dict] = []

    def fit(self, X, y):
        self.__class__.fits.append({"rows": list(X.index), "targets": [float(v) for v in y]})
        self.value = float(np.mean(list(y)))
        return self

    def predict(self, X):
        return [self.value] * len(X)


FRAME = pd.DataFrame({"x": np.arange(12, dtype=float), "y": np.arange(12, dtype=float)},
                     index=[f"r{i}" for i in range(12)])
SPLIT = build_split_plan(row_refs=tuple(FRAME.index), strategy="iid", final_holdout_fraction=.25, cv_folds=3,
                         shuffle=False, random_seed=17)
SPEC = SampleSpecV1(
    dataset_sha256="a" * 64, sampling=SamplingSpecV1(),
    split_plan=SplitPlanV1(strategy="iid", profile_id="iid_holdout_kfold", profile_version=1,
                           effective_parameters=SPLIT.effective_parameters),
    structure=StructureSpecV1(kind="iid", provenance="user_confirmed"),
    availability=AvailabilitySpecV1(kind="declared", reservation_policy="fail_closed"))


def _run(frame):
    RecordingMean.fits = []
    result = run_oos_prediction(frame=frame, target="y", features=("x",), sample_spec=SPEC, split_receipt=SPLIT,
                                estimator_factory=RecordingMean, model_id="mean", control_seed=17)
    return result, list(RecordingMean.fits)


def test_changing_only_holdout_labels_leaves_the_control_unchanged():
    before, fits_before = _run(FRAME)
    changed = FRAME.copy()
    changed.loc[["r9", "r10", "r11"], "y"] += 10_000
    after, fits_after = _run(changed)
    control_before, control_after = before.control_packet["controls"][0], after.control_packet["controls"][0]
    assert control_before["permuted_target_cv"] == control_after["permuted_target_cv"]
    assert before.evaluation_packet["cv"] == after.evaluation_packet["cv"]
    holdout = {"r9", "r10", "r11"}
    for fit_before, fit_after in zip(fits_before, fits_after):
        if not holdout & set(fit_before["rows"]):
            assert fit_before["targets"] == fit_after["targets"]


def test_every_control_fit_draws_its_labels_from_its_own_rows():
    _, fits = _run(FRAME)
    for fit in fits:
        own = sorted(float(FRAME.loc[row, "y"]) for row in fit["rows"])
        assert sorted(fit["targets"]) == own


def test_the_control_records_its_permutation_scope_and_version():
    result, _ = _run(FRAME)
    control = result.control_packet["controls"][0]
    assert control["permutation_scope"] == "within_each_fit_scope" and control["policy_version"] == 2
    assert control["fit_scope"] == "development_only"
