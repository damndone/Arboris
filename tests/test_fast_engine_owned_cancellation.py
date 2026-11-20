"""Real native cancellation, one owner, and no post-cancel IV publication."""
from __future__ import annotations

import contextvars
import threading

import numpy as np
import pandas as pd
import pytest

from workbench.engine.context import RunInterruptionRequested
from workbench.estimation_engine import native


def columns(rows=512):
    rng = np.random.default_rng(20261104)
    w, z1, z2, u = rng.normal(size=(4, rows))
    d = .6 * z1 + .4 * z2 + u
    y = 1. + .3 * w + .8 * d + u
    return y, [np.ones(rows), w], [d], [z1, z2]


@pytest.mark.parametrize('covariance', ['robust', 'unadjusted'])
def test_real_ffi_cancel_preserves_original_exception_and_clears_scope(covariance):
    original = RunInterruptionRequested('original-owner-cancel')
    calls = []
    def checkpoint():
        calls.append(threading.get_ident())
        if len(calls) == 5:
            raise original
    with pytest.raises(RunInterruptionRequested) as caught:
        native.iv_2sls(*columns(), covariance, check_cancel=checkpoint)
    assert caught.value is original
    assert len(calls) == 5
    assert set(calls) == {threading.get_ident()}
    count = len(calls)
    assert native.iv_2sls(*columns(), covariance) is not None
    assert len(calls) == count  # no callback survives its FFI scope


@pytest.mark.parametrize('covariance', ['robust', 'unadjusted'])
def test_non_cancelled_ffi_has_identical_bits_with_callback(covariance):
    expected = native.iv_2sls(*columns(), covariance)
    marker = contextvars.ContextVar('iv-owner', default=None)
    token = marker.set('same-owner-context')
    observed = []
    try:
        actual = native.iv_2sls(*columns(), covariance,
                               check_cancel=lambda: observed.append(marker.get()))
    finally:
        marker.reset(token)
    assert actual.tobytes() == expected.tobytes()
    assert observed and set(observed) == {'same-owner-context'}


def test_real_product_fast_cancel_drains_before_no_publish(tmp_path, monkeypatch):
    from workbench.estimation_engine.iv import _self_check
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    assert _self_check() is None
    y, exog, endog, instruments = columns()
    source = tmp_path / 'iv.csv'
    pd.DataFrame({'y': y, 'w': exog[1], 'd': endog[0], 'z1': instruments[0],
                  'z2': instruments[1]}).to_csv(source, index=False)
    project = create_project(tmp_path, 'owned_iv')
    entered, exited = threading.Event(), threading.Event()
    native_call = native.iv_2sls
    worker_ids = []
    callback_type = native._CANCEL
    def real_callback(function):
        @callback_type
        def callback(context):
            entered.set()  # cancellation begins inside the actual foreign-function callback
            return function(context)
        return callback
    monkeypatch.setattr(native, '_CANCEL', real_callback)
    def real_native_call(*args, **kwargs):
        worker_ids.append(threading.get_ident())
        try:
            return native_call(*args, **kwargs)
        finally:
            exited.set()
    monkeypatch.setattr(native, 'iv_2sls', real_native_call)
    with pytest.raises(RunInterruptionRequested):
        run_workflow(project.root, [source], mode='auto', model_type='iv_2sls', y='y', x=['w'],
                     iv_endog=['d'], iv_instruments=['z1', 'z2'], estimation_engine='fast',
                     stop_reason=lambda: 'cancelled' if entered.is_set() else None)
    assert entered.is_set() and exited.is_set()
    assert all(t.ident not in worker_ids for t in threading.enumerate())
    runs = list((project.root / 'runs').iterdir())
    assert len(runs) == 1
    assert not (runs[0] / 'model_results/iv_2sls_1.json').exists()
    assert not (runs[0] / 'model_results/inference_kernels/iv_2sls_1.json').exists()
    assert not (runs[0] / 'iv_diagnostics.json').exists()


def test_fast_fit_completion_race_keeps_owner_exception(tmp_path, monkeypatch):
    from workbench.engine.context import DataHandle, ModelingContext, RunEnv
    from workbench.engine.stages.estimation_fits import _fit_iv_2sls
    import workbench.orchestrator as orchestrator
    original = RunInterruptionRequested('owner-publication-race')
    completed = threading.Event()
    class OwnerEnv(RunEnv):
        def checkpoint(self, message=''):
            if completed.is_set():
                raise original
    context = ModelingContext(DataHandle.of(pd.DataFrame(), artifact_id='raw', provenance=()), 'y', ['w'],
        artifacts={'_normalized_y': 'y', '_normalized_x': ['w'], '_iv_endog': ['d'],
                   '_iv_instruments': ['z1', 'z2'], '_estimation_engine': 'fast'})
    def computed(*args, **kwargs):
        completed.set()
        return {}, object()
    monkeypatch.setattr(orchestrator, 'run_iv_2sls', computed)
    env = OwnerEnv(tmp_path, 'r', None, stop_reason=lambda: None)
    with pytest.raises(RunInterruptionRequested) as caught:
        _fit_iv_2sls(context, env)
    assert caught.value is original


def test_cancel_after_fast_fit_before_stage_publication_leaves_no_model(tmp_path, monkeypatch):
    from workbench.engine.registry import MODEL_REGISTRY
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    y, exog, endog, instruments = columns()
    source = tmp_path / 'iv.csv'
    pd.DataFrame({'y': y, 'w': exog[1], 'd': endog[0], 'z1': instruments[0],
                  'z2': instruments[1]}).to_csv(source, index=False)
    project = create_project(tmp_path, 'publish_race')
    cancelled = threading.Event()
    handler = MODEL_REGISTRY['iv_2sls']
    fit = handler.fit
    def completed(ctx, env):
        result = fit(ctx, env)  # actual completed native fit, including its owned drain
        cancelled.set()  # the race is after the helper's final checkpoint, before stage writes
        return result
    monkeypatch.setattr(handler, 'fit', completed)
    with pytest.raises(RunInterruptionRequested):
        run_workflow(project.root, [source], mode='auto', model_type='iv_2sls', y='y', x=['w'],
                     iv_endog=['d'], iv_instruments=['z1', 'z2'], estimation_engine='fast',
                     stop_reason=lambda: 'cancelled' if cancelled.is_set() else None)
    runs = list((project.root / 'runs').iterdir())
    assert len(runs) == 1
    assert not (runs[0] / 'model_results/iv_2sls_1.json').exists()
    assert not (runs[0] / 'model_results/inference_kernels/iv_2sls_1.json').exists()


def test_fast_without_stop_source_keeps_direct_legacy_native_path(tmp_path, monkeypatch):
    from workbench.checks.ar_cancellation import current_check
    from workbench.engine.context import DataHandle, ModelingContext, RunEnv
    from workbench.engine.stages.estimation_fits import _fit_iv_2sls
    import workbench.orchestrator as orchestrator
    context = ModelingContext(DataHandle.of(pd.DataFrame(), artifact_id='raw', provenance=()), 'y', ['w'],
        artifacts={'_normalized_y': 'y', '_normalized_x': ['w'], '_iv_endog': ['d'],
                   '_iv_instruments': ['z1', 'z2'], '_estimation_engine': 'fast'})
    def computed(*args, **kwargs):
        assert current_check() is None  # no native callbacks when there is no stop authority
        return {}, object()
    monkeypatch.setattr(orchestrator, 'run_iv_2sls', computed)
    _fit_iv_2sls(context, RunEnv(tmp_path, 'r', None))
