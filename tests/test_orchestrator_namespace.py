"""V1.5.4.5 拓展性护栏：orchestrator 拆成包后，对外命名空间必须保持稳定。

任何 stage 用 `from ...orchestrator import X` 取用的 helper、以及测试
monkeypatch 的 run_* 名，都必须在 workbench.orchestrator 包命名空间可见。
本测试把名字集合钉死：漏掉一条 re-export（baseline 名消失）立刻变红；
出现未登记的新名也变红。新增对外 helper 时，同步更新 BASELINE_NAMES
（有意为之的改动）；新增子模块时，更新 SUBMODULE_NAMES。
"""
import workbench.orchestrator as orch

# 拆分前（V1.5.4.4 head）orchestrator 模块的全部对外名 —— 拆分后必须逐一仍可见。
BASELINE_NAMES = frozenset({
    'Any', 'Callable', 'CleaningStage', 'DataHandle', 'DiagnosticsStage',
    'EstimationStage', 'ExposureDetectionStage', 'GraphRecorder', 'GraphStore',
    'GuardrailIssue', 'ImputationStage', 'ModelingContext',
    'OptionalDependencyNotInstalled', 'Path', 'PreEstimationChecksStage',
    'ProfileStage', 'RecordingStage', 'ReliabilityStage', 'ReportStage',
    'RoleInferenceStage', 'RoutingStage', 'RunEnv', 'Severity', 'SourceStage',
    'Stage', 'StatisticalTestsStage', 'ValidationStage',
    'WorkflowValidationError', 'YTypeStage', '_BINARY_CORRELATION_INFO',
    '_BINARY_CORRELATION_WARN', '_CATEGORICAL_NAME_PATTERNS',
    '_EXPOSURE_NAME_PATTERNS', '_MODEL_METADATA', '_MODEL_TYPE_MAP',
    '_PREDICTION_MODEL_TYPES', '_ROOT_CAUSE_MAX_LENGTH',
    '_SUPPORTED_GLM_FAMILIES', '_SUSPICIOUS_NAME_PATTERNS',
    '_TREATMENT_PROXY_CORRELATION_WARN', '_Y_TYPE_TO_ATTEMPTED_MODEL',
    '_build_descriptive_stats', '_build_model_routing_summary',
    '_build_variable_importance', '_check_binary_correlations',
    '_check_categorical_candidates', '_check_dropped_variables',
    '_check_model_validity', '_check_overdispersion_issue', '_check_rare_event',
    '_check_suspicious_dtypes', '_check_treatment_proxy_correlations',
    '_coefficient_rows', '_coefficient_rows_for_models',
    '_coerce_x_columns_to_numeric', '_detect_binary_vars',
    '_detect_categorical_x_vars', '_detect_exposure_candidates',
    '_detect_suspicious_vars', '_diagnostic_family', '_engine_for_type',
    '_importance_sort_key', '_lineage', '_map_model_type',
    '_mice_imputation_fact', '_model_column_issue', '_model_failure_details',
    '_model_id_for_type', '_model_summary', '_normalized_existing',
    '_primary_model_summary', '_run_workflow', '_safe_flush_recorder',
    '_select_valid_exposure_col', '_validate_requested_model_type',
    '_variable_summary', '_write_manifest', '_write_model_result',
    'annotations', 'build_claims', 'build_diagnostic_summary',
    'classify_dataset', 'clean_frame', 'compute_diagnostics', 'create_figures',
    'create_run', 'datetime', 'detect_y_kind', 'dpf', 'export_pdf',
    'export_xlsx', 'has_blockers', 'infer_schema', 'infer_variable_roles',
    'ingest_files', 'json', 'load_config', 'normalize_column_name',
    'parse_imputation_request', 'pd', 'profile_frame', 'read_json',
    'register_artifact', 'render_html_report', 'run_batch_y_workflow',
    'run_cs_did', 'run_dcdh', 'run_did', 'run_event_study',
    'run_glm', 'run_iv_2sls', 'run_logit', 'run_mice_imputation',
    'run_negative_binomial', 'run_ols', 'run_panel_ols', 'run_poisson',
    'run_prediction_model', 'run_probit', 'run_sa_did', 'run_statistical_tests',
    'run_time_series_diagnostics', 'run_workflow', 'summarize_statistical_tests',
    'timezone', 'validate_profile', 'write_json',
    'write_statistical_test_artifacts',
})

# 包化后合法新增的私有子模块名（实现细节，不是对外契约的一部分）。
SUBMODULE_NAMES = frozenset({
    "_manifest", "_model_types", "_errors",
    "_column_checks", "_reliability_checks", "_report_build",
})

# 测试真正 monkeypatch 的 run_* 面 —— 必须留在包命名空间（见 __init__ re-export）。
MONKEYPATCH_SURFACE = ("run_panel_ols", "run_logit", "run_prediction_model", "run_batch_y_workflow")


def _public_names():
    return {n for n in dir(orch) if not n.startswith("__")}


def test_no_reexport_dropped():
    """每个拆分前的对外名，拆分后仍必须在包命名空间可见。"""
    missing = BASELINE_NAMES - _public_names()
    assert not missing, f"orchestrator 命名空间丢失（漏 re-export?）: {sorted(missing)}"


def test_no_unexpected_additions():
    """除登记的子模块名外，不得凭空多出对外名。"""
    extra = _public_names() - BASELINE_NAMES - SUBMODULE_NAMES
    assert not extra, f"orchestrator 命名空间多出未登记的名: {sorted(extra)}"


def test_monkeypatch_surface_present():
    for name in MONKEYPATCH_SURFACE:
        assert hasattr(orch, name), f"monkeypatch 面缺失: {name}"
