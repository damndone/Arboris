from workbench.analysis_loop.fingerprints import (
    analysis_sample_fingerprint,
    coefficient_schema_fingerprint,
    dataset_snapshot_fingerprint,
    inference_config_fingerprint,
    point_estimation_fingerprint,
)


def test_dataset_snapshot_fingerprint_is_stable_under_object_key_order():
    first = dataset_snapshot_fingerprint(
        {"columns": ["y", "x"], "dtypes": {"y": "float64", "x": "category"}, "rows": [[1, "a"]]}
    )
    second = dataset_snapshot_fingerprint(
        {"rows": [[1, "a"]], "dtypes": {"x": "category", "y": "float64"}, "columns": ["y", "x"]}
    )

    assert first == second
    assert first != dataset_snapshot_fingerprint(
        {"columns": ["y", "x"], "dtypes": {"y": "float64", "x": "category"}, "rows": [[2, "a"]]}
    )


def test_analysis_sample_fingerprint_binds_row_set_and_row_order():
    base = analysis_sample_fingerprint(row_set=["r1", "r2"], row_order=["r1", "r2"])
    assert base == analysis_sample_fingerprint(row_set=["r1", "r2"], row_order=["r1", "r2"])
    assert base == analysis_sample_fingerprint(row_set=["r2", "r1"], row_order=["r1", "r2"])
    assert base != analysis_sample_fingerprint(row_set=["r1", "r2"], row_order=["r2", "r1"])
    assert base != analysis_sample_fingerprint(row_set=["r1", "r3"], row_order=["r1", "r2"])


def _point_inputs():
    return {
        "y": [1.0, 2.0],
        "X": [[1.0, "a"], [1.0, "b"]],
        "weights": [1.0, 1.0],
        "intercept": True,
        "categorical_encoding": {"region": "treatment", "reference": "a"},
        "missing_policy": "complete_case",
        "rows": ["r1", "r2"],
        "solver_options": {"method": "qr", "tol": 1e-12},
    }


def test_point_estimation_fingerprint_is_stable_and_excludes_inference_settings():
    kwargs = _point_inputs()
    base = point_estimation_fingerprint(**kwargs)
    assert base == point_estimation_fingerprint(**kwargs)
    assert base == point_estimation_fingerprint(**{**kwargs, "solver_options": {"tol": 1e-12, "method": "qr"}})

    assert base != point_estimation_fingerprint(**{**kwargs, "intercept": False})
    assert base != point_estimation_fingerprint(**{**kwargs, "rows": ["r2", "r1"]})


def test_inference_changes_do_not_change_point_estimation_fingerprint():
    kwargs = _point_inputs()
    point = point_estimation_fingerprint(**kwargs)
    inference = inference_config_fingerprint(
        covariance="clustered",
        cluster_var="firm_id",
        cluster_group_vector=["a", "a", "b"],
        cluster_count=2,
        corrections={"small_sample": True, "degrees_of_freedom": True},
        df="record_per_target",
        use_t=False,
        confidence_level=0.95,
        engine="statsmodels",
        version="0.14",
    )
    changed_inference = inference_config_fingerprint(
        covariance="clustered",
        cluster_var="other_firm_id",
        cluster_group_vector=["a", "b", "b"],
        cluster_count=2,
        corrections={"small_sample": False, "degrees_of_freedom": False},
        df="residual",
        use_t=True,
        confidence_level=0.90,
        engine="statsmodels",
        version="0.14",
    )

    assert inference != changed_inference
    assert point == point_estimation_fingerprint(**kwargs)


def test_coefficient_schema_and_inference_fingerprints_bind_each_domain_input():
    schema = coefficient_schema_fingerprint(
        [
            {"name": "Intercept", "dtype": "float64"},
            {"name": "x", "dtype": "float64"},
        ]
    )
    assert schema == coefficient_schema_fingerprint(
        [
            {"dtype": "float64", "name": "Intercept"},
            {"dtype": "float64", "name": "x"},
        ]
    )
    assert schema != coefficient_schema_fingerprint(
        [
            {"name": "Intercept", "dtype": "float64"},
            {"name": "z", "dtype": "float64"},
        ]
    )

    base = inference_config_fingerprint(
        covariance="clustered",
        cluster_var="firm_id",
        cluster_group_vector=["a", "a", "b"],
        cluster_count=2,
        corrections={"small_sample": True},
        df="record_per_target",
        use_t=False,
        confidence_level=0.95,
        engine="statsmodels",
        version="0.14",
    )
    assert base != inference_config_fingerprint(
        covariance="HC1",
        cluster_var="firm_id",
        cluster_group_vector=["a", "a", "b"],
        cluster_count=2,
        corrections={"small_sample": True},
        df="record_per_target",
        use_t=False,
        confidence_level=0.95,
        engine="statsmodels",
        version="0.14",
    )
    assert base != inference_config_fingerprint(
        covariance="clustered",
        cluster_var="firm_id",
        cluster_group_vector=["a", "b", "b"],
        cluster_count=2,
        corrections={"small_sample": True},
        df="record_per_target",
        use_t=False,
        confidence_level=0.95,
        engine="statsmodels",
        version="0.14",
    )
