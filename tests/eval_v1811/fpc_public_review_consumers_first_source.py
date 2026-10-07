"""Independent RED evidence for two remaining FPC consumer gaps."""
import pandas as pd
from workbench.artifacts import read_json
from workbench.report_view_model import _survey_design_facts
from tests.eval_v1811.fpc_public_review_adversarial import FIXTURES, public_run, result


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
