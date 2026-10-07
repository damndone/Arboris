"""A schema checked inside its owner cannot be reopened through an outside link."""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from test_script_export_lineage_builder import data_path, model_path
from test_script_export_public_integrity import clone
from workbench.data_operations import _read_frame, _schema_sidecar_path
from workbench.script_export import builder
from workbench.script_export.plan import ScriptExportRefusal


def schema_owner(model_path,tmp_path):
    project,run,data = clone(model_path,tmp_path)
    source_run = data[1]
    path = project/'runs'/source_run/data[2].artifact_path
    schema = _schema_sidecar_path(path)
    assert schema.is_file() and not schema.is_symlink()
    expected = _read_frame(path)
    foreign = tmp_path/'foreign-schema.json'
    foreign.write_text(json.dumps({'dtypes':{name:'object' for name in expected.columns}}))
    return project,source_run,path,schema,foreign,expected


def test_schema_checked_path_is_not_reopened_after_verification(model_path,tmp_path,monkeypatch):
    project,run,path,schema,foreign,expected = schema_owner(model_path,tmp_path)
    original = Path.read_bytes
    hits = []
    def replace_at_path_reopen(self):
        if self == schema and not hits:
            self.rename(self.with_name(self.name+'.retained'))
            self.symlink_to(foreign)
            hits.append(True)
        return original(self)
    monkeypatch.setattr(Path,'read_bytes',replace_at_path_reopen)
    actual = builder._Builder(project,run).frame(run,path.relative_to(project/'runs'/run).as_posix())
    pd.testing.assert_frame_equal(actual,expected)


def test_actual_schema_leaf_fd_rejects_link_installed_at_open(model_path,tmp_path,monkeypatch):
    project,run,path,schema,foreign,expected = schema_owner(model_path,tmp_path)
    original = os.open
    hits = []
    def replace_at_leaf(name,*args,**kwargs):
        if name == schema.name and kwargs.get('dir_fd') is not None and not hits:
            schema.rename(schema.with_name(schema.name+'.retained'))
            schema.symlink_to(foreign)
            hits.append(True)
        return original(name,*args,**kwargs)
    class BoundaryOS:
        open = staticmethod(replace_at_leaf)
        def __getattr__(self,name):
            return getattr(os,name)
    # Keep the actual project admission's OS identity intact. Instrument only
    # the builder's leaf-open boundary, not the shared os module.
    monkeypatch.setattr(builder,'os',BoundaryOS())
    with pytest.raises(ScriptExportRefusal):
        builder._Builder(project,run).frame(run,path.relative_to(project/'runs'/run).as_posix())
    assert hits == [True], 'The actual held-directory schema FD boundary was not reached'
