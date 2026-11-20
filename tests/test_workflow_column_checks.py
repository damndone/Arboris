"""A plan naming columns it cannot read is refused with the reason, at the proposal and at confirmation."""
from __future__ import annotations

import pytest

from workbench.agent.workflow_contracts import validate_workflow_steps
from workbench.contracts.common.errors import OperationValidationError


def model_step(step_id, predictors, **extra):
    return {'step_id': step_id, 'operation_id': 'model.genesis', 'spec': {
        'model_family': 'ols', 'covariance': 'robust', 'model_options': {},
        'branches': [{'branch_id': step_id, 'outcome': 'y', 'predictors': predictors}], **extra.pop('spec', {})}, **extra}


def derive(step_id='make'):
    return {'step_id': step_id, 'operation_id': 'statistical.derive_numeric',
            'spec': {'recipes': [{'input_columns': ['a', 'b'], 'operator': 'multiply', 'output_name': 'a_b'}]}}


def test_a_missing_column_names_what_is_available():
    with pytest.raises(OperationValidationError, match=r'missing column\(s\): nope.*Columns it can read: a, b, y'):
        validate_workflow_steps([model_step('fit', ['nope'])], available_columns=['a', 'b', 'y'])


def test_a_derived_column_without_its_dependency_says_how_to_fix_it():
    with pytest.raises(OperationValidationError, match=r'Add make to this step.s depends_on'):
        validate_workflow_steps([derive(), model_step('fit', ['a_b'])], available_columns=['a', 'b', 'y'])


def test_the_dependency_makes_it_valid():
    steps = [derive(), model_step('fit', ['a_b'], depends_on=['make'])]
    assert [step['step_id'] for step in validate_workflow_steps(steps, available_columns=['a', 'b', 'y'])] == ['make', 'fit']


def reshape(direction='long_to_wide'):
    spec = {'direction': direction, 'index': ['year'], 'columns': 'state', 'values': 'sales'}
    return {'step_id': 'wide', 'operation_id': 'data.reshape', 'spec': spec}


def test_columns_a_long_to_wide_makes_are_left_to_execution():
    fit = model_step('fit', ['5', '7'], depends_on=['wide'], spec={'source': {'from_step': 'wide', 'output': 'produced_dataset'}})
    ordered = validate_workflow_steps([reshape(), fit], available_columns=['year', 'state', 'sales'])
    assert [step['step_id'] for step in ordered] == ['wide', 'fit']


def test_other_steps_are_still_checked_after_a_reshape():
    fit = model_step('fit', ['nope'])
    with pytest.raises(OperationValidationError, match=r'missing column\(s\): nope'):
        validate_workflow_steps([reshape(), fit], available_columns=['year', 'state', 'sales'])


def test_a_step_depending_only_on_a_reshape_reads_it():
    """3f281a47 round: 8 of 24 refusals named the producer in depends_on and left out source."""
    ordered = validate_workflow_steps([reshape(), model_step('fit', ['5', '7'], depends_on=['wide'])],
                                      available_columns=['year', 'state', 'sales'])
    assert ordered[1]['spec']['source'] == {'from_step': 'wide', 'output': 'produced_dataset'}


def test_a_column_differing_only_by_case_is_named():
    with pytest.raises(OperationValidationError, match=r'case-sensitive: fullAfter -> fullafter'):
        validate_workflow_steps([model_step('fit', ['fullAfter'])], available_columns=['fullafter', 'y'])


def matching_request(bindings):
    options = {'propensity_policy': 'logit_mle_no_penalty', 'matching_geometry_policy': 'one_dimensional_abs_diff_logit_score',
               'support_distance_policy': 'caliper_only', 'ratio': 1, 'caliper': .2, 'replacement': False,
               'tie_policy': 'lowest_id', 'common_support_policy': 'reject', 'unmatched_policy': 'report',
               'balance_threshold': .1, 'missing_policy': 'reject'}
    return {'operation_id': 'matching.att', 'input_mode': 'frame', 'column_bindings': bindings, 'options': options}


def test_matching_without_an_identifier_uses_row_position_and_says_so():
    import numpy as np
    import pandas as pd
    from workbench.agent.p7_pack_adapters import models
    rng = np.random.default_rng(5)
    x = rng.normal(size=400)
    t = (x + rng.normal(size=400) > 0).astype(int)
    frame = pd.DataFrame({'t': t, 'x': x, 'y': x + 2 * t + rng.normal(size=400)})
    bindings = {'treatment': 't', 'outcome': 'y', 'covariates': ['x']}
    captured = {}
    def spy(source, **kwargs):
        captured.update(kwargs)
        captured['columns'] = list(source.columns)
        raise RuntimeError('stop')
    import workbench.engine.packs.matching as pack
    pack_estimate, pack.estimate_att = pack.estimate_att, spy
    try:
        with pytest.raises(RuntimeError):
            models._execute_matching_att(frame, bindings, matching_request(bindings)['options'])
    finally:
        pack.estimate_att = pack_estimate
    assert captured['id_column'] == 'row_number' and 'row_number' in captured['columns'] and 'row_number' not in frame.columns


def test_an_existing_row_number_column_is_not_overwritten():
    import pandas as pd
    from workbench.agent.p7_pack_adapters.models import _with_identifier
    source, name = _with_identifier(pd.DataFrame({'row_number': [9, 8]}), {})
    assert name == '_row_number' and source['row_number'].tolist() == [9, 8] and source[name].tolist() == [0, 1]
