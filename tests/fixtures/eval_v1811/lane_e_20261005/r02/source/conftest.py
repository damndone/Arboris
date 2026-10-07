"""Record only this formal evaluation's source paths and actual test outcomes."""
import hashlib
import json
from pathlib import Path
import subprocess
import pytest
from support import OUT,REPO,BASELINE

ROWS=[]


def pytest_runtest_logreport(report):
    if report.when=='call' or (report.when in {'setup','teardown'} and report.failed):
        ROWS.append({'nodeid':report.nodeid,'phase':report.when,'outcome':report.outcome,'duration':report.duration})


def pytest_sessionfinish(session,exitstatus):
    import workbench
    import workbench.engine.packs.arma_garch.joint_mle as joint
    import workbench.econometrics.count_models as count
    import workbench.script_export.builder as builder
    modules=[workbench,joint,count,builder]
    loaded={module.__name__:str(Path(module.__file__).resolve()) for module in modules}
    assert all(Path(value).is_relative_to(REPO/'backend') for value in loaded.values()),loaded
    paths=[Path(value) for value in loaded.values()]
    paths+=list((REPO/'tests/eval_v1811/lane_e_20261005').glob('*.py'))
    paths+=[REPO/'tests/eval_v1811/lane_e_20261005/native_glm.R',REPO/'docs/superpowers/objectives/2026-10-04-v1.8.11-objective.md',REPO/'docs/superpowers/specs/2026-10-04-v1.8.11-lane-contracts.md']
    payload={'production_baseline':BASELINE,'actual_git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        'repository':str(REPO),'loaded':loaded,'exit':int(exitstatus),'outcomes':ROWS,
        'paths_sha256':{str(p.relative_to(REPO)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    path=OUT/'run-manifest.json';assert not path.exists();path.write_text(json.dumps(payload,indent=2))
