"""Export frames must be parsed from the bytes already bound to their owner."""
import io

import pandas as pd
import pytest

from test_script_export_lineage_builder import data_path, model_path
from test_script_export_public_integrity import clone
from workbench.artifacts import read_json
from workbench.script_export import builder
from workbench.tabular_io import read_table


@pytest.mark.parametrize('kind', ['csv', 'xlsx', 'parquet', 'dta'])
def test_same_tabular_reader_accepts_verified_byte_stream(tmp_path, kind):
    frame = pd.DataFrame({'x':[1.,2.,3.], 'group':[0.,1.,1.]})
    path = tmp_path/('original.'+kind)
    if kind == 'csv': frame.to_csv(path,index=False)
    elif kind == 'xlsx': frame.to_excel(path,index=False)
    elif kind == 'parquet': frame.to_parquet(path,index=False)
    else: frame.to_stata(path,write_index=False,value_labels={'group':{0:'control',1:'treated'}})
    expected = read_table(path)
    actual = read_table(io.BytesIO(path.read_bytes()), suffix='.'+kind)
    pd.testing.assert_frame_equal(actual,expected)


@pytest.mark.parametrize('stage', ['cleaned', 'raw'])
def test_owner_path_replacement_after_byte_verification_cannot_change_parsed_frame(model_path,tmp_path,monkeypatch,stage):
    project,run_id,data = clone(model_path,tmp_path)
    source_run = data[1]
    root = project/'runs'/source_run
    records = read_json(root/'artifacts_index.json')['artifacts']
    record = next(item for item in records if item['artifact_id']=='cleaned_dataset') if stage=='cleaned' else next(item for item in records if item['artifact_type']=='raw_data')
    path = root/record['path']
    expected = read_table(path)
    original = builder._Builder.record
    hit = []
    def replace_after_verification(self,owner,**kwargs):
        result = original(self,owner,**kwargs)
        if owner == source_run and result[0]['path']==record['path'] and not hit:
            changed = expected.copy()
            changed['x'] += 100
            changed['unverified_private_column'] = 666
            if path.suffix == '.parquet': changed.to_parquet(path,index=False)
            elif path.suffix == '.dta': changed.to_stata(path,write_index=False)
            else: changed.to_csv(path,index=False)
            hit.append(True)
        return result
    monkeypatch.setattr(builder._Builder,'record',replace_after_verification)
    instance = builder._Builder(project,source_run)
    if stage=='cleaned':
        actual = instance.frame(source_run,record['path'])
    else:
        step_id = instance.dataset(source_run,'stage:raw')
        actual = instance.frames[step_id]
        assert 'unverified_private_column' not in instance.source_columns
    assert hit == [True], 'The actual verified-byte boundary was not reached'
    pd.testing.assert_frame_equal(actual,expected)
