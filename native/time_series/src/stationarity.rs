use std::slice;

use super::{
    checkpoint, dot, fit, publish_result, CancellationCheck, Failure, Shape, CHECK_EVERY,
    INVALID_INPUT, MAX_ROWS,
};

const MIN_ROWS: usize = 20;
const MAX_LAG: usize = 20;
const MIN_ADF_RESIDUAL_DF: usize = 5;
const ADF: u32 = 0;
const KPSS: u32 = 1;
const CONSTANT_SERIES: i32 = 6;
const UNRESOLVED_VARIANCE: i32 = 7;

enum DiagnosticFailure {
    Kernel(Failure),
    Constant,
    Variance,
}

impl From<Failure> for DiagnosticFailure {
    fn from(failure: Failure) -> Self {
        Self::Kernel(failure)
    }
}

fn scaled_levels(
    values: &[f64],
    check: CancellationCheck,
) -> Result<(Vec<f64>, f64), DiagnosticFailure> {
    let mut minimum = f64::INFINITY;
    let mut maximum = f64::NEG_INFINITY;
    for (index, &value) in values.iter().enumerate() {
        if index % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        if !value.is_finite() {
            return Err(Failure::Observation(index).into());
        }
        minimum = minimum.min(value);
        maximum = maximum.max(value);
    }
    if minimum == maximum {
        return Err(DiagnosticFailure::Constant);
    }
    let midpoint = minimum.midpoint(maximum);
    let scale = (maximum - midpoint).max(midpoint - minimum);
    let mut levels = Vec::with_capacity(values.len());
    for block in values.chunks(CHECK_EVERY) {
        checkpoint(check)?;
        levels.extend(block.iter().map(|&value| (value - midpoint) / scale));
    }
    Ok((levels, scale))
}

fn adf(
    values: &[f64],
    levels: &[f64],
    scale: f64,
    lag: usize,
    check: CancellationCheck,
) -> Result<Vec<f64>, DiagnosticFailure> {
    let mut differences = Vec::with_capacity(values.len() - 1);
    for row in 1..values.len() {
        if (row - 1) % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let change = values[row] - values[row - 1];
        differences.push(if change.is_finite() {
            change / scale
        } else {
            levels[row] - levels[row - 1]
        });
    }
    let first_time = lag + 1;
    let shape = Shape {
        series: 1,
        training_rows: values.len(),
        lag_order: first_time,
        intercept: 1,
        horizon: 0,
    };
    let predictors = shape.predictors();
    let fitted_rows = shape.fitted_rows();
    let mut columns = vec![vec![0.0; fitted_rows]; predictors + 1];
    columns[0].fill(1.0);
    for row in 0..fitted_rows {
        if row % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let time = first_time + row;
        columns[1][row] = levels[time - 1];
        for previous in 1..=lag {
            columns[1 + previous][row] = differences[time - previous - 1];
        }
        columns[predictors][row] = differences[time - 1];
    }
    let response = &columns[predictors];
    let response_rms = (dot(response, response) / fitted_rows as f64).sqrt();
    let fitted = fit(&mut columns, shape, check)?;
    let sigma = fitted.covariance[0].sqrt();
    if sigma <= 64.0 * f64::EPSILON * response_rms {
        return Err(DiagnosticFailure::Variance);
    }

    let mut inverse_level_row = vec![0.0; predictors];
    for row in 0..predictors {
        let target = if fitted.permutation[row] == 1 {
            1.0
        } else {
            0.0
        };
        let projected = dot(&columns[row][..row], &inverse_level_row[..row]);
        inverse_level_row[row] = (target - projected) / columns[row][row];
    }
    let gamma = fitted.coefficients[1];
    let standard_error = sigma * inverse_level_row.into_iter().fold(0.0, f64::hypot);
    let tau = gamma / standard_error;
    if !tau.is_finite() || !standard_error.is_finite() || standard_error <= 0.0 {
        return Err(Failure::Numeric.into());
    }
    Ok(vec![tau, gamma, standard_error])
}

fn kpss(
    mut residuals: Vec<f64>,
    lag: usize,
    check: CancellationCheck,
) -> Result<Vec<f64>, DiagnosticFailure> {
    let count = residuals.len();
    let n = count as f64;
    let mean = residuals.iter().sum::<f64>() / n;
    let mut cumulative = 0.0;
    let mut partial_sum_squares = 0.0;
    for block in residuals.chunks_mut(CHECK_EVERY) {
        checkpoint(check)?;
        for residual in block {
            *residual -= mean;
            cumulative += *residual;
            partial_sum_squares += cumulative * cumulative;
        }
    }

    let mut window_squares = 0.0;
    for end in 0..count + lag {
        if end % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let first = end.saturating_sub(lag);
        let after_last = (end + 1).min(count);
        let window_sum = residuals[first..after_last].iter().sum::<f64>();
        window_squares += window_sum * window_sum;
    }
    if window_squares <= 0.0 || !window_squares.is_finite() {
        return Err(DiagnosticFailure::Variance);
    }
    let statistic = partial_sum_squares * (lag + 1) as f64 / (n * window_squares);
    if !statistic.is_finite() {
        return Err(Failure::Numeric.into());
    }
    Ok(vec![statistic])
}

fn compute(
    values: &[f64],
    method: u32,
    lag: usize,
    check: CancellationCheck,
) -> Result<Vec<f64>, DiagnosticFailure> {
    let (levels, scale) = scaled_levels(values, check)?;
    if method == ADF {
        adf(values, &levels, scale, lag, check)
    } else {
        kpss(levels, lag, check)
    }
}

/// # Safety
/// Pointers must refer to separate aligned buffers of the stated lengths for
/// the whole call. Input values remain initialized and immutable. The optional
/// callback stays valid for the call and must not unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_stationarity_constant_fixed(
    values: *const f64,
    count: usize,
    method: u32,
    lag: usize,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    if error_index.is_null() || !error_index.is_aligned() {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    let expected = match method {
        ADF => 3,
        KPSS => 1,
        _ => return INVALID_INPUT,
    };
    if !(MIN_ROWS..=MAX_ROWS).contains(&count)
        || lag > MAX_LAG
        || lag >= count
        || (method == ADF && count < 2 * lag + 3 + MIN_ADF_RESIDUAL_DF)
        || output_len != expected
        || values.is_null()
        || !values.is_aligned()
        || output.is_null()
        || !output.is_aligned()
    {
        return INVALID_INPUT;
    }
    let values = unsafe { slice::from_raw_parts(values, count) };
    let result = match compute(values, method, lag, check) {
        Ok(result) => Ok(result),
        Err(DiagnosticFailure::Kernel(failure)) => Err(failure),
        Err(DiagnosticFailure::Constant) => return CONSTANT_SERIES,
        Err(DiagnosticFailure::Variance) => return UNRESOLVED_VARIANCE,
    };
    unsafe { publish_result(result, output, output_len, error_index) }
}
