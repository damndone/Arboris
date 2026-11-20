import ctypes


DOUBLE = ctypes.POINTER(ctypes.c_double)
SIZE = ctypes.c_size_t
CHECKPOINT = ctypes.CFUNCTYPE(ctypes.c_int32)
_INDEX = ctypes.POINTER(SIZE)
_INT = ctypes.c_int32
_SCALAR = ctypes.c_double
_FIT_OUTPUTS = [DOUBLE, SIZE, DOUBLE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT]
_VAR_FIT = [DOUBLE, SIZE, SIZE, SIZE, SIZE, SIZE, _INT, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT]


def bind_time_series_symbols(library):
    signatures = {
        'arboris_local_level': [DOUBLE, SIZE, *([_SCALAR] * 4), DOUBLE, SIZE, DOUBLE, _INDEX],
        'arboris_local_level_fit_scale': [DOUBLE, SIZE, *([_SCALAR] * 3), DOUBLE, SIZE, _INDEX],
        'arboris_correlogram': [DOUBLE, SIZE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT],
        'arboris_stationarity_constant_fixed': [DOUBLE, SIZE, ctypes.c_uint32, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT],
        'arboris_arima_fit': [DOUBLE, *([SIZE] * 4), _INT, SIZE, *_FIT_OUTPUTS],
        'arboris_arima_fit_with_whiteness': [
            DOUBLE, *([SIZE] * 4), _INT, SIZE, SIZE, DOUBLE, SIZE, DOUBLE, SIZE,
            DOUBLE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT,
        ],
        'arboris_sarima_fit': [DOUBLE, *([SIZE] * 8), _INT, SIZE, *_FIT_OUTPUTS],
        'arboris_arimax_fit': [DOUBLE, SIZE, DOUBLE, SIZE, DOUBLE, SIZE, *([SIZE] * 4), _INT, SIZE, *_FIT_OUTPUTS],
        'arboris_sarimax_fit': [DOUBLE, SIZE, DOUBLE, SIZE, DOUBLE, SIZE, *([SIZE] * 8), _INT, SIZE, *_FIT_OUTPUTS],
        'arboris_holt_winters_fit_joint': [DOUBLE, SIZE, SIZE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT],
        'arboris_holt_winters_additive': [
            DOUBLE, SIZE, SIZE, SIZE, *([_SCALAR] * 3), DOUBLE, SIZE, _INDEX, CHECKPOINT,
        ],
        'arboris_holt_winters_fit_alpha': [
            DOUBLE, SIZE, SIZE, SIZE, *([_SCALAR] * 2), DOUBLE, SIZE, _INDEX, CHECKPOINT,
        ],
        'arboris_ets_trend_fit': [DOUBLE, SIZE, _SCALAR, _SCALAR, _SCALAR, SIZE, DOUBLE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT],
        'arboris_ets_trend_fit_auto': [
            DOUBLE, SIZE, _INT, _SCALAR, _INT, _SCALAR, _SCALAR, SIZE,
            DOUBLE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT,
        ],
        'arboris_volatility_fit': [DOUBLE, SIZE, SIZE, SIZE, SIZE, DOUBLE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT],
        'arboris_var_fit': _VAR_FIT,
        'arboris_var_fit_with_evidence': _VAR_FIT,
        'arboris_var_granger_block': [
            DOUBLE, SIZE, SIZE, SIZE, _INT, SIZE, SIZE, ctypes.c_uint32, DOUBLE, SIZE, _INDEX, CHECKPOINT,
        ],
        'arboris_var_irf': [DOUBLE, SIZE, SIZE, SIZE, _INT, SIZE, _SCALAR, DOUBLE, SIZE, _INDEX, CHECKPOINT],
        'arboris_johansen_rank': [DOUBLE, SIZE, SIZE, SIZE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT],
        'arboris_vecm_rank1': [DOUBLE, SIZE, SIZE, SIZE, SIZE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT],
        'arboris_egarch_fit': [DOUBLE, SIZE, SIZE, SIZE, DOUBLE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT],
        'arboris_markov_switching_fit': [DOUBLE, SIZE, SIZE, SIZE, *_FIT_OUTPUTS],
        'arboris_arfima_fit': [DOUBLE, SIZE, SIZE, _INT, _SCALAR, _INT, DOUBLE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT],
        'arboris_igarch_fit': [DOUBLE, SIZE, SIZE, SIZE, DOUBLE, SIZE, DOUBLE, SIZE, _INDEX, CHECKPOINT],
        'arboris_figarch_filter': [DOUBLE, *([SIZE] * 4), *([_SCALAR] * 4), *_FIT_OUTPUTS],
        'arboris_varma11_fixed_ma': [
            DOUBLE, SIZE, SIZE, SIZE, _INT, _SCALAR, SIZE, SIZE, _SCALAR, DOUBLE, SIZE, _INDEX, CHECKPOINT,
        ],
    }
    for name, arguments in signatures.items():
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = _INT
