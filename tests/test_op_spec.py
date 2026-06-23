from workbench.lineage.op_spec import op_spec_for_stage


def test_op_spec_stable_same_inputs():
    s1 = op_spec_for_stage("estimation", form={"model_type": "ols"}, config={"random_seed": 20260429})
    s2 = op_spec_for_stage("estimation", form={"model_type": "ols"}, config={"random_seed": 20260429})
    assert s1 == s2


def test_op_spec_excludes_volatile():
    s = op_spec_for_stage("estimation", form={"model_type": "ols", "run_id": "x", "started_at": "t"}, config={"random_seed": 20260429})
    assert "run_id" not in s and "started_at" not in s


def test_op_spec_includes_seed():
    s = op_spec_for_stage("imputation", form={}, config={"random_seed": 20260429})
    assert s.get("random_seed") == 20260429


def test_model_change_isolated_to_estimation():
    src1 = op_spec_for_stage("source", form={"model_type": "ols"}, config={"random_seed": 20260429})
    src2 = op_spec_for_stage("source", form={"model_type": "iv_2sls"}, config={"random_seed": 20260429})
    assert src1 == src2   # upstream unaffected by model_type
    est1 = op_spec_for_stage("estimation", form={"model_type": "ols"}, config={"random_seed": 20260429})
    est2 = op_spec_for_stage("estimation", form={"model_type": "iv_2sls"}, config={"random_seed": 20260429})
    assert est1 != est2
