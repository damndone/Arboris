"""Full result documents are authenticated before any numeric self-check."""
import hashlib
import json
import pytest
from workbench.contracts.common.envelope import ContractError,thaw_json
from workbench.script_export.result_snapshot import read_result_snapshot,ResultSnapshotRef
from test_script_result_snapshot_contract import plan,payload,VALUES


def assets(tmp_path):
    p=plan();value=payload(p);raw=b'{"quantile":0.25,"label":"cohort 4","missing":null}'
    (tmp_path/'actual.json').write_bytes(raw)
    value['documents']={'fits':{'artifact_id':'fit_actual','filename':'actual.json','sha256':hashlib.sha256(raw).hexdigest()}}
    snapshot=json.dumps(value).encode();(tmp_path/'fit.json').write_bytes(snapshot)
    return value,ResultSnapshotRef('fit.json',hashlib.sha256(snapshot).hexdigest())


def test_declared_document_can_be_loaded_before_numbers(tmp_path):
    value,ref=assets(tmp_path)
    assert thaw_json(read_result_snapshot(tmp_path,ref,expected_binding=value['binding']))==VALUES


@pytest.mark.parametrize('attack',['bytes','missing','symlink','hardlink','path','extra'])
def test_changed_full_document_is_rejected(tmp_path,attack):
    value,ref=assets(tmp_path)
    if attack=='bytes':(tmp_path/'actual.json').write_bytes(b'{}')
    elif attack=='missing':(tmp_path/'actual.json').rename(tmp_path/'kept.json')
    elif attack=='symlink':
        (tmp_path/'actual.json').rename(tmp_path/'kept.json');(tmp_path/'actual.json').symlink_to(tmp_path/'kept.json')
    elif attack=='hardlink':
        import os
        os.link(tmp_path/'actual.json',tmp_path/'kept.json')
    else:
        if attack=='path':value['documents']['fits']['filename']='../actual.json'
        else:value['documents']['fits']['injected']=True
        snapshot=json.dumps(value).encode();(tmp_path/'fit.json').write_bytes(snapshot);ref=ResultSnapshotRef('fit.json',hashlib.sha256(snapshot).hexdigest())
    with pytest.raises(ContractError):read_result_snapshot(tmp_path,ref,expected_binding=value['binding'])
