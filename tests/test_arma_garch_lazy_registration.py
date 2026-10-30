"""Keep capability registration separate from ARMA-GARCH execution imports."""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_fresh_metadata_bootstrap_defers_execution_imports(record_property):
    script = textwrap.dedent('''
        import importlib.abc
        import inspect
        import json
        import sys

        from workbench.engine.capabilities import build_capabilities
        from workbench.engine.packs.loader import bootstrap_builtin_packs
        from workbench.engine.registry import MODEL_REGISTRY

        capabilities = build_capabilities()
        handler = MODEL_REGISTRY['time_series.arma_garch']
        bootstrap_builtin_packs()
        assert MODEL_REGISTRY['time_series.arma_garch'] is handler
        contract = handler.model_options_contract
        snapshot = {
            'capability': next(item for item in capabilities['model_types']
                               if item['key'] == 'time_series.arma_garch'),
            'owner': {
                'model_type': handler.model_type,
                'model_id': handler.model_id,
                'serves_y_types': list(handler.serves_y_types),
                'producer_version': contract.producer_version,
                'input_contract_version': contract.input_contract_version,
                'validator_module': handler.validate_model_options.__module__,
                'validator_name': handler.validate_model_options.__qualname__,
                'normalizer_module': contract.normalize_payload.__module__,
                'normalizer_name': contract.normalize_payload.__qualname__,
            },
            'fit_module': handler.fit.__module__,
            'fit_signature': str(inspect.signature(handler.fit)),
            'execution_modules': sorted(name for name in sys.modules
                if name in {'workbench.engine.packs.arma_garch.runner',
                            'workbench.engine.packs.arma_garch.forecast'}
                or name == 'arch' or name.startswith('arch.')),
        }
        print(json.dumps(snapshot, sort_keys=True), flush=True)
        assert snapshot['execution_modules'] == [], snapshot['execution_modules']

        # The first execution must attempt the original runner import, and a
        # present import failure must remain the caller's original exception.
        failure = ImportError('original runner import refused')
        attempts = []
        class DenyRunner(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname == 'workbench.engine.packs.arma_garch.runner':
                    attempts.append(fullname)
                    raise failure
        finder = DenyRunner()
        sys.meta_path.insert(0, finder)
        try:
            try:
                handler.fit(object(), object())
            except ImportError as error:
                assert error is failure
            else:
                raise AssertionError('runner import failure was hidden')
        finally:
            sys.meta_path.remove(finder)
        assert attempts == ['workbench.engine.packs.arma_garch.runner']
    ''')
    result = subprocess.run(
        [sys.executable, '-c', script], cwd=ROOT,
        env={**os.environ, 'PYTHONPATH': str(ROOT / 'backend')},
        capture_output=True, text=True, check=False,
    )
    if result.stdout:
        snapshot = json.loads(result.stdout.splitlines()[0])
        record_property('registration_snapshot', json.dumps(snapshot, sort_keys=True))
    assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot['owner']['model_id'] == 'arma_garch_1'
    assert snapshot['owner']['serves_y_types'] == ['continuous']
    assert snapshot['capability']['requires'] == ['time', 'value']


def test_registered_handler_calls_the_original_runner_once(monkeypatch):
    from workbench.engine.packs.arma_garch import runner
    from workbench.engine.packs.loader import bootstrap_builtin_packs
    from workbench.engine.registry import MODEL_REGISTRY

    bootstrap_builtin_packs()
    handler = MODEL_REGISTRY['time_series.arma_garch']
    original = runner.fit_from_context
    assert inspect.signature(handler.fit) == inspect.signature(original)
    assert handler.fit.__module__ == 'workbench.engine.packs.arma_garch.declaration'
    ctx, env = object(), object()
    expected = ('arma_garch_1', {'unchanged': object()}, None)
    calls, inner_calls = [], []

    def fit(actual_ctx, actual_env):
        calls.append((actual_ctx, actual_env))
        return original(actual_ctx, actual_env)

    def inner(actual_ctx, actual_env):
        inner_calls.append((actual_ctx, actual_env))
        return expected

    monkeypatch.setattr(runner, 'fit_from_context', fit)
    monkeypatch.setattr(runner, '_fit_from_context', inner)
    assert handler.fit(ctx=ctx, env=env) is expected
    assert calls == [(ctx, env)] and inner_calls == [(ctx, env)]


@pytest.mark.parametrize('cancelled', [False, True], ids=['runtime-error', 'owner-cancel'])
def test_registered_handler_preserves_runner_exception_identity(monkeypatch, cancelled):
    from workbench.engine.context import RunInterruptionRequested
    from workbench.engine.packs.arma_garch import runner
    from workbench.engine.packs.loader import bootstrap_builtin_packs
    from workbench.engine.registry import MODEL_REGISTRY

    bootstrap_builtin_packs()
    original = RunInterruptionRequested('cancelled') if cancelled else RuntimeError('original fit failure')
    calls = []
    ctx, env = object(), object()

    def fail(actual_ctx, actual_env):
        calls.append((actual_ctx, actual_env))
        raise original

    monkeypatch.setattr(runner, 'fit_from_context', fail)
    with pytest.raises(type(original)) as caught:
        MODEL_REGISTRY['time_series.arma_garch'].fit(ctx, env)
    assert caught.value is original and calls == [(ctx, env)]
