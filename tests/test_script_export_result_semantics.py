"""Reindexed completed documents must still match the executed model."""
import hashlib
import json
import shutil

import pytest

from test_script_export_complex_results import completed
from workbench.script_export.builder import build_script_plan
from workbench.script_export.plan import ScriptExportRefusal


@pytest.mark.parametrize('completed,attack', [
    ('quantile_regression', 'reference_fit_conflict'),
    ('quantile_regression', 'quantile_label_conflict'),
    ('quantile_regression', 'requested_fit_missing'),
    ('quantile_regression', 'interval_conflict'),
    ('time_series.ets', 'sample_size_conflict'),
    ('time_series.ets', 'endog_conflict'),
    ('time_series.ets', 'specification_conflict'),
    ('time_series.ets', 'result_identity_conflict'),
], indirect=['completed'])
def test_result_semantic_conflicts_are_refused(completed, attack, tmp_path):
    family, original, old_root, node = completed
    project = tmp_path / 'isolated-owner'
    shutil.copytree(original, project)
    root = project / 'runs' / old_root.name
    packet_path = root / node.payload_ref
    packet = json.loads(packet_path.read_text())
    if family == 'quantile_regression':
        name = next(name for name in packet['coefficients'] if name != 'Intercept')
        if attack == 'reference_fit_conflict':
            packet['fits'][str(packet['reference_quantile'])]['coefficients'][name]['estimate'] += .25
        elif attack == 'quantile_label_conflict':
            packet['fits']['0.25']['quantile'] = .75
        elif attack == 'requested_fit_missing':
            packet['fits'].pop('0.25')
        else:
            packet['confidence_intervals']['0.25'][name][0] += .25
    else:
        result = packet['result']
        if attack == 'sample_size_conflict': result['n_obs'] += 17
        elif attack == 'endog_conflict': result['endog'] = 'foreign_outcome'
        elif attack == 'specification_conflict': result['specification']['error'] = 'mul'
        else: result['result_identity'] = '0' * 64
    raw = json.dumps(packet).encode()
    packet_path.write_bytes(raw)
    index_path = root / 'artifacts_index.json'
    index = json.loads(index_path.read_text())
    record, = [item for item in index['artifacts'] if item['path'] == node.payload_ref]
    record['sha256'] = hashlib.sha256(raw).hexdigest()
    index_path.write_text(json.dumps(index))
    with pytest.raises(ScriptExportRefusal):
        build_script_plan(project, root.name, node.id)


@pytest.mark.parametrize('completed,field', [
    ('cs_did','overall'), ('cs_did','overall_se'), ('cs_did','overall_pointwise_ci'),
    ('sa_did','overall'), ('sa_did','overall_se'), ('sa_did','overall_pointwise_ci'),
    ('dcdh','estimate'), ('dcdh','se'),
], indirect=['completed'])
def test_primary_effect_document_conflicts_are_refused(completed,field,tmp_path):
    family, original, old_root, node = completed
    project=tmp_path/'effect-owner'
    shutil.copytree(original,project)
    root=project/'runs'/old_root.name
    packet=json.loads((root/node.payload_ref).read_text())
    path=root/(family+'.json')
    document=json.loads(path.read_text())
    effect=document['overall_att'] if family=='dcdh' else document['aggregations']['simple']
    assert effect['estimate' if family=='dcdh' else 'overall']==packet['coefficients']['ATT']['estimate']
    if field=='overall_pointwise_ci':effect[field][0]+=.25
    else:effect[field]+=.25
    raw=json.dumps(document).encode();path.write_bytes(raw)
    index_path=root/'artifacts_index.json'
    index=json.loads(index_path.read_text())
    record,=[item for item in index['artifacts'] if item['path']==family+'.json']
    record['sha256']=hashlib.sha256(raw).hexdigest()
    index_path.write_text(json.dumps(index))
    with pytest.raises(ScriptExportRefusal):
        build_script_plan(project,root.name,node.id)
