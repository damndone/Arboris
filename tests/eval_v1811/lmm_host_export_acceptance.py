"""Consume retained host evidence read-only, without another sandbox or fit."""
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from workbench.services.script_export import _prepare
from workbench.services.server_run_artifacts import read_server_owned_run_artifacts

ROOT=Path(__file__).parents[2]
HOST=ROOT/'local/v1811-lmm-host/runs/20261005_024643_550779_dbe309ee'

@dataclass(frozen=True)
class Executable:
    language:str
    filename:str
    text:str


@pytest.mark.parametrize('language',['python','r','stata'])
def test_completed_host_lmm_export_retains_full_kernel_and_random_effects(language,tmp_path,monkeypatch):
    # This is explicitly a host evidence acceptance check, not a portable unit
    # fixture. Absence must be reported; there is no nested-fit fallback.
    assert HOST.is_dir(),'Verified real host LMM owner is required'
    before={str(p.relative_to(HOST)):hashlib.sha256(p.read_bytes()).hexdigest() for p in HOST.rglob('*') if p.is_file()}
    read_server_owned_run_artifacts(HOST.parent.parent,HOST.name,required=True)
    files,summary,_=_prepare(HOST.parent.parent,HOST.name,'model:linear_mixed_effects_1',language,False)
    for name,raw in files.items():(tmp_path/name).write_bytes(raw)
    snapshots=[json.loads(raw) for name,raw in files.items() if name.endswith('.json') and b'workbench.script_result_snapshot.v1' in raw]
    assert len(snapshots)==1
    snapshot=snapshots[0]
    kernel=json.loads(files[snapshot['documents']['kernel']['filename']])
    packet=json.loads(files[snapshot['documents']['packet']['filename']])
    assert snapshot['values']['coefficients']==dict(zip(kernel['param_names'],kernel['params']))
    assert len(snapshot['values']['coefficients'])==5
    assert packet['payload']['random_effects']['intercept_variance']>0
    assert any('random_effects/intercept_variance' in key for key in snapshot['values']['statistics'])
    assert summary['coverage'][-1]['status']=='snapshot'
    monkeypatch.setenv('PYTHONPATH',str(ROOT/'backend'))
    from test_script_export_data_oracles import execute
    filename={'python':'analysis.py','r':'analysis.R','stata':'analysis.do'}[language]
    code,output=execute(Executable(language,filename,files[filename].decode()),tmp_path)
    assert code==0,output[-2500:]
    after={str(p.relative_to(HOST)):hashlib.sha256(p.read_bytes()).hexdigest() for p in HOST.rglob('*') if p.is_file()}
    assert before==after
