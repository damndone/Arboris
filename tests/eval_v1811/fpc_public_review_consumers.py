"""Independent RED evidence for two remaining FPC consumer gaps."""
import ast
import subprocess
import pandas as pd
import pytest
from workbench.artifacts import read_json
from workbench.report_view_model import _survey_design_facts
from tests.eval_v1811.fpc_public_review_adversarial import FIXTURES, public_run, result


@pytest.fixture(autouse=True)
def reviewed_diagnostics_snapshot(monkeypatch):
    """Bind the reviewed committed function despite concurrent owner edits."""
    from workbench.engine.stages import diagnostics
    code = subprocess.check_output(['git', 'show',
        '9a42c15959d444b259ed2d490cb1b9257c69adcb:backend/workbench/engine/stages/diagnostics.py'], text=True)
    klass = next(node for node in ast.parse(code).body if isinstance(node, ast.ClassDef)
        and node.name == 'DiagnosticsStage')
    function = next(node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == 'run')
    namespace = dict(diagnostics.__dict__)
    exec(compile(ast.Module(body=[function], type_ignores=[]), '9a_diagnostics.py', 'exec'), namespace)
    monkeypatch.setattr(diagnostics.DiagnosticsStage, 'run', namespace['run'])


def test_report_retains_each_full_design_stratum_instead_of_only_generic_fpc_label(tmp_path):
    outcome, root = public_run(tmp_path, survey_fpc_col='population_fpc')
    assert outcome['status'] == 'completed'
    packet, _ = result(root)
    facts = '\n'.join(_survey_design_facts(root))
    missing = [row['stratum'] for row in packet['survey_design']['fpc']['strata']
        if row['stratum'] not in facts]
    assert not missing, {'missing_full_design_strata': missing, 'actual_report_facts': facts}


def test_census_owner_warning_is_available_through_shared_issues(tmp_path):
    frame = pd.read_csv(FIXTURES / 'design.csv')
    frame['review_census'] = 1.0
    source = tmp_path / 'census.csv'; frame.to_csv(source, index=False)
    outcome, root = public_run(tmp_path / 'projects', source, survey_fpc_col='review_census')
    assert outcome['status'] == 'completed'
    packet, _ = result(root)
    code = 'SURVEY_ZERO_VARIANCE_INFERENCE_UNAVAILABLE'
    assert any(warning.get('code') == code for warning in packet['warnings'])
    shared = read_json(root / 'errors.json')['issues']
    assert any(issue.get('code') == code for issue in shared), shared
