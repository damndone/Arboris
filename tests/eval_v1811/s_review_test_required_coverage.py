"""Required C3 coverage gaps, separate from algorithm defects and frozen dependencies."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.config import WorkbenchConfig
from workbench.ingestion import _read_frame
from workbench.script_export.plan import LANGUAGES, ScriptPlan, ScriptSource, ScriptStep, ScriptExportRefusal
from workbench.script_export.render import export_script
from s_review_test_adversarial import directory, source


def record_attempt(target, plan, language):
    (target / 'plan.json').write_text(json.dumps(plan.to_dict(), indent=2))
    try:
        exported = export_script(plan, language, require_native=True)
    except ScriptExportRefusal as exc:
        (target / 'refusal.json').write_text(json.dumps({'code': exc.code, 'message': str(exc),
                                                     'steps': exc.steps}, indent=2))
        raise
    (target / exported.filename).write_text(exported.text)
    assert exported.fully_native


@pytest.mark.parametrize('language', LANGUAGES)
def test_workbench_supported_selected_excel_sheet_exports_natively(language):
    target = directory('reader-selected-sheet', language)
    path = target / 'data.xlsx'
    chosen = pd.DataFrame({'x': [3., 4., 5.]})
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({'x': [999.]}).to_excel(writer, sheet_name='Decoy', index=False)
        chosen.to_excel(writer, sheet_name='Chosen', index=False)
    actual = _read_frame(path, WorkbenchConfig(), sheet_name='Chosen', transpose=False)
    pd.testing.assert_frame_equal(actual, chosen, check_dtype=False)
    verified = ScriptSource('source', 'xlsx', path.name, hashlib.sha256(path.read_bytes()).hexdigest(),
                            read_options={'sheet_name': 'Chosen', 'transpose': False})
    step = ScriptStep('result', 'data_operation', 'data.subset', {'columns': ['x']}, ('source',),
                      expected={'nrows': 3, 'columns': ['x']})
    plan = ScriptPlan('review', 'selected-sheet', (verified,), (step,), '1.8.11', '6'*64)
    record_attempt(target, plan, language)


@pytest.mark.parametrize('language', LANGUAGES)
def test_workbench_supported_complete_sampling_design_is_native(language):
    target = directory('sampling-design', language)
    fixtures = Path(__file__).parents[1] / 'fixtures/survey'
    frame = pd.read_csv(fixtures / 'design.csv')
    oracle = json.loads((fixtures / 'oracle.json').read_text())['linearization']
    design = {'sampling_weight': 'weight', 'survey_strata_col': 'stratum', 'survey_psu_col': 'psu',
              'survey_fpc_col': 'fpc', 'survey_method': 'linearization', 'survey_df': 'design_minus_p'}
    params = {'model_type': 'ols', 'y': 'y', 'x': ['x1', 'x2'], 'categorical_x': [],
              'covariance': 'survey_design', 'weights': {'kind': 'sampling', 'column': 'weight'},
              'model_options': {'survey_design': design}}
    aliases = {'(Intercept)': 'Intercept', 'x1': 'x1', 'x2': 'x2'}
    expected = {'nobs': len(frame), 'coefficients': {aliases[k]: v for k, v in oracle['estimate'].items()},
                'std_errors': {aliases[k]: v for k, v in oracle['se'].items()},
                'statistics': {aliases[k]: {'value': oracle['t_value'][k], 'p_value': oracle['p_value'][k],
                                          'df': 6, 'distribution': 't'} for k in aliases}}
    step = ScriptStep('model', 'model', 'model.ols', params, ('source',), expected=expected)
    plan = ScriptPlan('review', 'sampling-design', (source(target, frame),), (step,), '1.8.11', '7'*64)
    record_attempt(target, plan, language)


@pytest.mark.parametrize('language', LANGUAGES)
def test_glm_postestimation_admission_preserves_declared_family_identity(language, monkeypatch):
    """Observe the admission identity only; no statistical admission is claimed."""
    from workbench.postestimation import registry
    calls = []
    monkeypatch.setattr(registry, 'require_validated', lambda family, operation: calls.append((family, operation)))
    params = {'model_type': 'glm', 'y': 'count', 'x': ['x'], 'covariance': 'unadjusted',
              'model_options': {'family': 'poisson'}}
    model = ScriptStep('model', 'model', 'model.glm', params, ('source',))
    post = ScriptStep('wald', 'postestimation', 'postestimation.wald',
                      {'models': ['model'], 'constraints': [{'terms': {'x': 1}, 'value': 0}]}, ('model',))
    plan = ScriptPlan('review', 'glm-identity', (ScriptSource('source', 'csv', 'data.csv', '0'*64),),
                      (model, post), '1.8.11', '8'*64)
    export_script(plan, language)
    assert calls == [('glm:poisson', 'wald')]
