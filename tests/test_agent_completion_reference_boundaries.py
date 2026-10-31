"""Generic recorded-shape binding/claim regressions, with no provider or task truth."""
import asyncio
import copy
import json
from pathlib import Path

import pytest

from workbench.artifacts import initialize_artifact_index,register_artifact
from workbench.agent import completion
from workbench.agent.context_tools_support.coefficients import _public_requested_model_coefficients


def artifact(project,run,name,kind,payload,inputs=()):
    root=project/'runs'/run;root.mkdir(parents=True,exist_ok=True)
    if not (root/'artifacts_index.json').exists():initialize_artifact_index(root)
    path=root/(name+'.json');path.write_text(json.dumps(payload))
    record=register_artifact(root,name,path,kind,'test',list(inputs))
    return {'run_id':run,'artifact_id':name},record.sha256


def products(tmp_path):
    source,sha=artifact(tmp_path,'sample','cleaned_dataset','processed_data',{'rows':'synthetic'})
    model={'model_id':'fit_1','model_type':'ols','nobs':80,
           'coefficients':{'x':{'estimate':2.,'std_error':.2,'p_value':.01}},
           'point_estimation_fingerprint':'a'*64,'analysis_sample_fingerprint':'b'*64}
    ref,_=artifact(tmp_path,'sample','fit_1','model_result',model,['cleaned_dataset'])
    contract={'scope':'question','playbooks':[],'source':{**source,'sha256':sha}}
    return contract,ref,model


def test_coefficients_publish_registered_completion_reference_separate_from_numeric_alias(tmp_path):
    contract,ref,model=products(tmp_path)
    public=_public_requested_model_coefficients(run_id='sample',run_root=tmp_path/'runs/sample',result=model,requested_terms=('x',))
    receipt=public['evidence_ref']
    assert receipt['result_ref']=='model_results:fit_1'
    assert receipt['artifact_id']=='fit_1' and receipt['completion_ref']==ref
    assert len(receipt['registered_sha256'])==64 and receipt['binding_status']=='registered'
    assert completion.evaluate(tmp_path,contract,{'results':[receipt['completion_ref']]})['status']=='requirements_met'


def test_unregistered_projection_has_no_receipt_and_changed_bytes_fail_the_gate(tmp_path):
    contract,ref,model=products(tmp_path)
    changed=copy.deepcopy(model);changed['model_id']='unregistered_model'
    public=_public_requested_model_coefficients(run_id='sample',run_root=tmp_path/'runs/sample',result=changed,requested_terms=('x',))
    assert public['evidence_ref'].get('completion_ref') is None
    assert public['evidence_ref'].get('artifact_id') is None
    (tmp_path/'runs/sample/fit_1.json').write_text('{}')
    public=_public_requested_model_coefficients(run_id='sample',run_root=tmp_path/'runs/sample',result=model,requested_terms=('x',))
    assert public['evidence_ref']['binding_status']=='registered'
    assert completion.evaluate(tmp_path,contract,{'results':[ref]})['status']=='partial'
    with pytest.raises(completion.CompletionEvidenceError):
        completion.validate_completion_evidence(tmp_path,contract,{'results':[ref]})


def test_plan_evidence_boundary_rejects_alias_with_explicit_verified_replacement(tmp_path):
    contract,ref,_=products(tmp_path)
    bad={'results':[{'run_id':'sample','artifact_id':'model_results:fit_1'}]}
    before=copy.deepcopy(bad)
    with pytest.raises(completion.CompletionEvidenceError) as caught:
        completion.validate_completion_evidence(tmp_path,contract,bad)
    assert caught.value.code=='COMPLETION_EVIDENCE_UNRESOLVED'
    assert caught.value.corrections[0]['replacement_ref']==ref
    assert bad==before
    assert completion.evaluate(tmp_path,contract,bad)['status']=='partial'
    assert completion.validate_completion_evidence(tmp_path,contract,{'results':[ref]})=={'results':[ref]}


def test_question_partial_reports_actionable_binding_repair_without_accepting_alias(tmp_path):
    contract,ref,_=products(tmp_path)
    bad={'results':[{'run_id':'sample','artifact_id':'model_results:fit_1'}]}
    checked=completion.evaluate(tmp_path,contract,bad,options=True)
    assert checked['status']=='partial' and checked['missing']==['question:computed_source_bound_result']
    assert checked['repair_steps'][0]['replacement_ref']==ref
    text=completion.publication('Estimate 2.0 from the existing result. 问题导向完成（scope=question）。',checked,'zh')
    assert 'Estimate 2.0' in text and '问题导向完成' not in text
    # Repair instructions go to the Agent (repair_steps); the reader gets plain language.
    assert 'update_plan' not in text and '下一步' in text
    assert checked['scientific_validity']=='not_certified'


@pytest.mark.parametrize('variant',['unregistered','foreign','duplicate'])
def test_unknown_foreign_or_ambiguous_refs_never_receive_a_replacement_or_pass(tmp_path,variant):
    contract,ref,model=products(tmp_path)
    if variant=='unregistered':
        given={'run_id':'sample','artifact_id':'invented'}
    elif variant=='foreign':
        artifact(tmp_path,'other','cleaned_dataset','processed_data',{'rows':'other'})
        given,_=artifact(tmp_path,'other','fit_1','model_result',model,['cleaned_dataset'])
    else:
        index=tmp_path/'runs/sample/artifacts_index.json';data=json.loads(index.read_text())
        data['artifacts'].append(next(row.copy() for row in data['artifacts'] if row['artifact_id']=='fit_1'))
        index.write_text(json.dumps(data));given={'run_id':'sample','artifact_id':'model_results:fit_1'}
    with pytest.raises(completion.CompletionEvidenceError) as caught:
        completion.validate_completion_evidence(tmp_path,contract,{'results':[given]})
    assert not caught.value.corrections
    assert completion.evaluate(tmp_path,contract,{'results':[given]})['status']=='partial'


@pytest.mark.parametrize('claim',['✅ 问题导向完成（scope=question）','问题已完成。','本问题全部满足。','✅ 全部满足（scope=question）',
                                  'Focused question complete.','Question requirements satisfied.'])
def test_partial_gate_removes_focused_completion_claim_and_keeps_useful_takeover(claim):
    check={'status':'partial','missing':['question:computed_source_bound_result'],
           'verified_artifacts':[{'run_id':'sample','artifact_id':'cleaned_dataset','sha256':'a'*64}],
           'next_step':'Call update_plan with the registered result artifact; retain earlier computed results.'}
    text=completion.publication('Existing source remains verified.\n'+claim,check,'zh')
    assert claim not in text
    assert text.startswith('Existing source remains verified') and 'cleaned_dataset' not in text
    assert 'update_plan' not in text and '部分完成' in text


def test_completed_step_or_explicit_partial_scope_is_not_a_global_completion_claim():
    for content in ('分组描述步骤已完成；回答仍待核验。','该问题尚未完成。','Question is not complete.'):
        assert not completion.claims_completion(content)


def test_actual_update_plan_rejects_wrong_alias_without_saving_and_accepts_corrected_ref(tmp_path):
    from tests.test_read_only_analysis import _Fixture
    fixture=_Fixture(tmp_path)
    root=fixture.project_root;run=fixture.run_id
    model={'model_id':'fit_1','model_type':'ols','nobs':80,'coefficients':{'x':{'estimate':2.,'std_error':.2}}}
    ref,_=artifact(root,run,'fit_1','model_result',model,[fixture.artifact_id])
    source=completion.source_receipt(root,{'run_id':run,'artifact_id':fixture.artifact_id})
    registry=fixture.orchestrator.tool_registry('chain-a')
    args={'question':'Explain the existing estimate','criteria':['Use recorded evidence'],
          'steps':[{'step_id':'interpret','title':'Interpret','operation_ids':['model.rerun']}],
          'completion':{'scope':'question','playbooks':[],'source':source},
          'completion_evidence':{'results':[{'run_id':run,'artifact_id':'model_results:fit_1'}]}}
    def update():return asyncio.run(registry.execute({'tool_call_id':'plan','tool_id':'update_plan','arguments':args},session_id='chain-session'))
    bad=update()
    assert bad.ok and bad.output['saved'] is False
    assert bad.output['error_code']=='COMPLETION_EVIDENCE_UNRESOLVED'
    assert bad.output['evidence_corrections'][0]['replacement_ref']==ref
    assert fixture.orchestrator.plan_store.current('chain-session') is None
    args['completion_evidence']={'results':[ref]}
    good=update()
    assert good.ok and good.output['saved'] is True
    assert fixture.orchestrator.plan_store.current('chain-session').completion_evidence=={'results':[ref]}


@pytest.mark.parametrize('content',['问题已完成一半，仍待核验。','The focused question completely lacks a verified result.',
                                    'Question requirements satisfied only partially.'])
def test_explicitly_partial_progress_is_not_a_completion_claim(content):
    assert not completion.claims_completion(content)


def test_registry_identity_does_not_claim_to_verify_projected_numbers(tmp_path):
    artifact(tmp_path,'sample','cleaned_dataset','processed_data',{'rows':'synthetic'})
    model={'model_id':'fit_1','model_type':'ols','nobs':80,
           'coefficients':{'x':{'estimate':1.0,'std_error':.2}}}
    artifact(tmp_path,'sample','fit_1','model_result',model,['cleaned_dataset'])
    changed=copy.deepcopy(model);changed['coefficients']['x']['estimate']=True
    public=_public_requested_model_coefficients(run_id='sample',run_root=tmp_path/'runs/sample',result=changed,requested_terms=('x',))
    assert public['evidence_ref']['binding_status']=='registered'
    assert 'artifact_sha256' not in public['evidence_ref']


def test_real_coefficient_context_consumer_emits_canonical_completion_binding(tmp_path):
    from workbench.agent.context_tools import NodeOperationContextProvider,InspectProjectModelCoefficientsRequest
    source,_=artifact(tmp_path,'sample','cleaned_dataset','processed_data',{'rows':'synthetic'})
    root=tmp_path/'runs/sample'
    model={'model_id':'fit_1','model_type':'ols','nobs':80,'coefficients':{'x':{'estimate':2.,'std_error':.2}}}
    path=root/'model_results/fit_1.json';path.parent.mkdir();path.write_text(json.dumps(model))
    register_artifact(root,'fit_1',path,'model_result','test',['cleaned_dataset'])
    output=NodeOperationContextProvider(tmp_path).inspect_project_model_coefficients(
        InspectProjectModelCoefficientsRequest(run_ids=('sample',),terms=('x',)))
    [projected]=output['models']
    assert projected['evidence_ref']['completion_ref']=={'run_id':'sample','artifact_id':'fit_1'}
    assert projected['evidence_ref']['result_ref']=='model_results:fit_1'


def test_distinct_registered_owners_with_same_model_id_remain_ambiguous(tmp_path):
    contract,ref,model=products(tmp_path)
    artifact(tmp_path,'sample','second_owner','model_result',model,['cleaned_dataset'])
    public=_public_requested_model_coefficients(run_id='sample',run_root=tmp_path/'runs/sample',result=model,requested_terms=('x',))
    assert public['evidence_ref'].get('completion_ref') is None
    with pytest.raises(completion.CompletionEvidenceError) as caught:
        completion.validate_completion_evidence(tmp_path,contract,{'results':[{'run_id':'sample','artifact_id':'model_results:fit_1'}]})
    assert not caught.value.corrections


def test_canonical_model_reference_does_not_relax_full_analysis_or_scientific_gate(tmp_path):
    contract,ref,_=products(tmp_path)
    question=completion.evaluate(tmp_path,contract,{'results':[ref]})
    assert question['status']=='requirements_met' and question['scientific_validity']=='not_certified'
    full=completion.evaluate(tmp_path,{**contract,'scope':'analysis','playbooks':['ols']},{'models':[ref]})
    assert full['status']=='partial'
    assert any('diagnostics:' in item for item in full['missing'])
    assert any('sensitivity:' in item for item in full['missing'])
    assert 'report:registered_nonempty' in full['missing']


def test_context_reference_is_registered_identity_without_rereading_model_bytes(tmp_path,monkeypatch):
    from workbench.agent.context_compiler import registered_model_completion_ref
    _,ref,model=products(tmp_path)
    read=Path.read_bytes
    def observed(path):
        if path.name=='fit_1.json':raise AssertionError('context binding must reuse loaded projection, not reread model')
        return read(path)
    monkeypatch.setattr(Path,'read_bytes',observed)
    receipt=registered_model_completion_ref(tmp_path/'runs/sample',model)
    assert receipt['artifact_id']==ref['artifact_id']
    assert receipt['binding_status']=='registered'


@pytest.mark.parametrize('content',['本问题的全部要求已满足一半，其余仍待核验。',
                                    'Question requirements satisfied in part; results still await verification.'])
def test_requirement_progress_does_not_lose_honest_partial_context(content):
    assert not completion.claims_completion(content)
    checked={'status':'partial','missing':['question:computed_source_bound_result']}
    assert content in completion.publication(content,checked,'zh')


def test_alias_repair_verifies_only_exact_registered_candidate_not_unrelated_models(tmp_path,monkeypatch):
    contract,ref,model=products(tmp_path)
    unrelated=copy.deepcopy(model);unrelated['model_id']='unrelated'
    artifact(tmp_path,'sample','unrelated','model_result',unrelated,['cleaned_dataset'])
    load=completion._Products.load
    seen=[]
    def bounded(products,requested):
        if isinstance(requested,dict):
            seen.append(requested.get('artifact_id'))
            assert requested.get('artifact_id')!='unrelated','alias repair loaded an unrelated model'
        return load(products,requested)
    monkeypatch.setattr(completion._Products,'load',bounded)
    with pytest.raises(completion.CompletionEvidenceError) as caught:
        completion.validate_completion_evidence(tmp_path,contract,{'results':[{'run_id':'sample','artifact_id':'model_results:fit_1'}]})
    assert caught.value.corrections[0]['replacement_ref']==ref
    assert 'fit_1' in seen and 'unrelated' not in seen


def test_recorded_shape_judgment_completion_line_cannot_survive_partial_binding_gate(tmp_path):
    contract,ref,_=products(tmp_path)
    checked=completion.evaluate(tmp_path,contract,{'results':[{'run_id':'sample','artifact_id':'model_results:fit_1'}]},options=True)
    draft=('Existing estimate: 2.0; source sample/fit_1.\n'
           '✅ 判断标准全部满足：HC1、点估计/CI/p/R²均已给出。\n'
           'Keep the computed result and correct its registered binding before rechecking.')
    text=completion.publication(draft,checked,'zh')
    assert '判断标准全部满足' not in text
    assert 'Existing estimate: 2.0; source sample/fit_1.' in text
    assert 'Keep the computed result' in text and 'update_plan' not in text
    assert '部分完成' in text and checked['status']=='partial'
    for partial in ('当前仅一个诊断子步骤的判断标准全部满足，其余仍待核验。',
                    '判断标准尚未全部满足，结果仍待核验。'):
        assert not completion.claims_completion(partial)
        assert partial in completion.publication(partial,checked,'zh')


@pytest.mark.parametrize('slot',['diagnostics','sensitivity','report'])
def test_partial_delivery_refs_do_not_block_saving_verified_primary(tmp_path,slot):
    contract,ref,_=products(tmp_path)
    contract={**contract,'scope':'analysis','playbooks':['ols']}
    pending={'run_id':'sample','artifact_id':'anticipated_delivery'}
    evidence={'models':[ref],slot:pending if slot=='report' else [pending]}
    assert completion.validate_completion_evidence(tmp_path,contract,evidence)==evidence
    # Saving a partial plan does not certify an anticipated report or companion.
    checked=completion.evaluate(tmp_path,contract,evidence)
    assert checked['status']=='partial' and 'report:registered_nonempty' in checked['missing']
    evidence[slot]={'run_id':'sample','artifact_id':'model_results:fit_1'} if slot=='report' else [
        {'run_id':'sample','artifact_id':'model_results:fit_1'}]
    with pytest.raises(completion.CompletionEvidenceError) as caught:
        completion.validate_completion_evidence(tmp_path,contract,evidence)
    assert not caught.value.corrections  # A model is not a report/diagnostic replacement.


def test_cross_line_claim_filter_preserves_separate_verified_lines():
    checked={'status':'partial','missing':['report:registered_nonempty']}
    draft='Verified source sample/fit_1\nThe analysis\nis complete.\nThe comparison is still pending.'
    text=completion.publication(draft,checked,'en')
    assert 'analysis' not in text.split('Interim findings (still require verification)')[-1]
    assert 'Verified source sample/fit_1' in text and 'The comparison is still pending.' in text
    chinese='已核验引用 sample/fit_1\n✅ 判断标准全部满足：交付完成。\n仍缺比较报告。'
    text=completion.publication(chinese,checked,'zh')
    assert '已核验引用 sample/fit_1' in text and '仍缺比较报告。' in text
    assert '判断标准全部满足' not in text
