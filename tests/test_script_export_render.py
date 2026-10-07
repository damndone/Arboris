"""Contract checks for the declaration-driven local script renderer."""
import importlib.util
import json
from pathlib import Path

import pytest

from workbench.script_export.plan import LANGUAGES, ScriptPlan, ScriptStep, ScriptExportRefusal

FIXTURE = Path(__file__).parent / 'fixtures/script_export/basic/plan.json'


def renderer():
    assert importlib.util.find_spec('workbench.script_export.render') is not None
    from workbench.script_export.render import export_script
    return export_script


@pytest.mark.parametrize('language', LANGUAGES)
def test_frozen_basic_invalid_subset_is_explicitly_rejected(language):
    plan = ScriptPlan.from_dict(json.loads(FIXTURE.read_text()))
    with pytest.raises(ScriptExportRefusal) as caught:
        renderer()(plan, language)
    assert caught.value.code == 'INVALID_EXPORT_INPUT'
    assert 'subset.columns' in str(caught.value)


def test_registered_operations_have_explicit_language_declarations():
    renderer()
    from workbench.script_export.exporters import EXPORTERS
    from workbench.data_operation_registry import data_operation_declarations
    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS
    from workbench.postestimation.registry import OPERATIONS
    required = {d.workflow_operation_id for d in data_operation_declarations()}
    required |= {'model.' + family for family in MODEL_FAMILY_CONTRACTS}
    required |= {'postestimation.' + operation for operation in OPERATIONS}
    assert required <= EXPORTERS.keys()
    for operation in required:
        assert set(EXPORTERS[operation].per_language) == set(LANGUAGES)
        for declaration in EXPORTERS[operation].per_language.values():
            assert declaration.status == 'native' or declaration.note
            assert declaration.renderer is not None or declaration.status == 'snapshot'


def test_require_native_reports_snapshot_steps_without_script():
    plan = ScriptPlan('p','r',(),(ScriptStep('blocked','model','model.survival_cox',{},()),),'1.8.11','0'*64)
    with pytest.raises(ScriptExportRefusal) as caught:
        renderer()(plan,'python', require_native=True)
    assert caught.value.code == 'NOT_FULLY_NATIVE'
    assert caught.value.steps == ('blocked',)


@pytest.mark.parametrize('language',LANGUAGES)
def test_unsupported_native_combination_lists_the_actual_step(language):
    step=ScriptStep('nb1','model','model.negative_binomial',{'model_type':'negative_binomial','y':'y','x':['x'],'model_options':{'dispersion':'constant'}},())
    plan=ScriptPlan('p','r',(),(step,),'1.8.11','0'*64)
    with pytest.raises(ScriptExportRefusal) as caught:renderer()(plan,language,require_native=True)
    assert caught.value.code=='NOT_FULLY_NATIVE'
    assert caught.value.steps==('nb1',)


@pytest.mark.parametrize('language',LANGUAGES)
def test_unopened_postestimation_pair_is_explicitly_rejected(language):
    from workbench.script_export.plan import ScriptSource
    model=ScriptStep('nb','model','model.negative_binomial',{'model_type':'negative_binomial','y':'y','x':['x'],'model_options':{'dispersion':'mean'}},('source',))
    post=ScriptStep('post','postestimation','postestimation.nlcom',{'models':['nb'],'expression':'exp(x)'},('nb',))
    plan=ScriptPlan('p','r',(ScriptSource('source','csv','data.csv','0'*64),),(model,post),'1.8.11','0'*64)
    with pytest.raises(ScriptExportRefusal) as caught:renderer()(plan,language)
    assert caught.value.code=='NOT_YET_VALIDATED'
