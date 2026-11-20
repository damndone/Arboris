use std::slice;

use super::{
    accumulate_covariance, advance_impulse, append_covariance, checkpoint, coefficient_in_units,
    contraction_bound, design, dot, fit, publish_result, scales, CancellationCheck, Failure, Fit,
    Shape, CHECK_EVERY, INVALID_INPUT, MAX_HORIZON, MAX_ROWS,
};

const SERIES: usize = 2;
const MATRIX: usize = SERIES * SERIES;
const HEADER: usize = 15;
const MIN_TRAINING: usize = 8;
const MAX_ABS_MA: f64 = 0.95;
const COVARIANCE_TOLERANCE: f64 = 64.0 * f64::EPSILON;

#[derive(Clone, Copy)]
struct Specification {
    shape: Shape,
    theta: f64,
    irf_periods: usize,
    response_limit: f64,
}

impl Specification {
    fn irf_len(self) -> usize {
        if self.irf_periods == 0 {
            0
        } else {
            (self.irf_periods + 1) * 2 * MATRIX
        }
    }

    fn output_len(self) -> usize {
        HEADER + self.shape.horizon * (SERIES + MATRIX) + self.irf_len()
    }
}

fn whiten(columns: &mut [Vec<f64>], theta: f64, check: CancellationCheck) -> Result<(), Failure> {
    if theta == 0.0 {
        return Ok(());
    }
    for column in columns {
        let mut previous = 0.0;
        for (row, value) in column.iter_mut().enumerate() {
            if row % CHECK_EVERY == 0 {
                checkpoint(check)?;
            }
            *value -= theta * previous;
            previous = *value;
        }
    }
    Ok(())
}

fn likelihood(
    fit: &mut Fit,
    shape: Shape,
    response_rms: [f64; SERIES],
    scales: &[f64],
) -> Result<f64, Failure> {
    let fitted_rows = shape.fitted_rows();
    let factor = (fitted_rows - shape.predictors()) as f64 / fitted_rows as f64;
    fit.covariance.iter_mut().for_each(|value| *value *= factor);
    let left = fit.covariance[0].sqrt();
    let right = fit.covariance[3].sqrt();
    if left <= COVARIANCE_TOLERANCE * response_rms[0]
        || right <= COVARIANCE_TOLERANCE * response_rms[1]
    {
        return Err(Failure::InnovationCovariance);
    }
    let correlation = (fit.covariance[1] / left / right).abs();
    if !correlation.is_finite() || 1.0 - correlation <= COVARIANCE_TOLERANCE {
        return Err(Failure::InnovationCovariance);
    }
    let logdet = 2.0 * (left.ln() + right.ln() + scales[0].ln() + scales[1].ln())
        + (-correlation).ln_1p()
        + correlation.ln_1p();
    let log_likelihood =
        -0.5 * fitted_rows as f64 * (2.0 * (1.0 + std::f64::consts::TAU.ln()) + logdet);
    if !log_likelihood.is_finite() {
        return Err(Failure::Numeric);
    }
    Ok(log_likelihood)
}

fn ar_mean(fit: &Fit, shape: Shape, lagged: &[f64; SERIES]) -> [f64; SERIES] {
    std::array::from_fn(|outcome| {
        let mut mean = if shape.intercept == 1 {
            fit.coefficients[outcome]
        } else {
            0.0
        };
        for (source, &value) in lagged.iter().enumerate() {
            mean += fit.coefficients[(shape.intercept + source) * SERIES + outcome] * value;
        }
        mean
    })
}

fn terminal_state(
    values: &[f64],
    scales: &[f64],
    specification: Specification,
    fit: &Fit,
    check: CancellationCheck,
) -> Result<([f64; SERIES], [f64; SERIES]), Failure> {
    let shape = specification.shape;
    let mut level = [values[0] / scales[0], values[1] / scales[1]];
    let mut innovation = [0.0; SERIES];
    for row in 1..shape.training_rows {
        if (row - 1) % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let prediction = ar_mean(fit, shape, &level);
        for series in 0..SERIES {
            level[series] = values[row * SERIES + series] / scales[series];
            innovation[series] =
                level[series] - prediction[series] - specification.theta * innovation[series];
        }
    }
    if !innovation.iter().all(|value| value.is_finite()) {
        return Err(Failure::Numeric);
    }
    Ok((level, innovation))
}

fn append_irf(
    output: &mut Vec<f64>,
    impulse: &[f64; MATRIX],
    covariance: &[f64; MATRIX],
    scales: &[f64],
    step: usize,
    limit: f64,
) -> Result<(), Failure> {
    for (response, &response_scale) in scales.iter().enumerate() {
        for (shock, &shock_scale) in scales.iter().enumerate() {
            let value = coefficient_in_units(
                impulse[response * SERIES + shock],
                response_scale,
                shock_scale,
            )
            .ok_or(Failure::Forecast(step))?;
            if value.abs() > limit {
                return Err(Failure::ResponseLimit(step));
            }
            output.push(value);
        }
    }
    append_covariance(output, covariance, scales).ok_or(Failure::Forecast(step))
}

fn append_paths(
    output: &mut Vec<f64>,
    fit: &Fit,
    specification: Specification,
    scales: &[f64],
    state: ([f64; SERIES], [f64; SERIES]),
    check: CancellationCheck,
) -> Result<(), Failure> {
    let (mut level, last_innovation) = state;
    let shape = specification.shape;
    let irf_periods = specification.irf_periods;
    let steps = shape.horizon.max(irf_periods);
    let mut irf = Vec::with_capacity(specification.irf_len());
    let mut impulse = [0.0; MATRIX];
    let mut impulse_history = [0.0; MATRIX];
    let mut covariance = [0.0; MATRIX];
    let mut propagated = [0.0; MATRIX];

    for step in 0..=steps {
        checkpoint(check)?;
        if step > 0 {
            accumulate_covariance(
                &mut covariance,
                &impulse,
                &fit.covariance,
                &mut propagated,
                SERIES,
                step,
            )?;
            if step <= shape.horizon {
                level = ar_mean(fit, shape, &level);
                for (series, &scale) in scales.iter().enumerate() {
                    if step == 1 && specification.theta != 0.0 {
                        level[series] += specification.theta * last_innovation[series];
                    }
                    output.push(
                        coefficient_in_units(level[series], scale, 1.0)
                            .ok_or(Failure::Forecast(step))?,
                    );
                }
                append_covariance(output, &covariance, scales).ok_or(Failure::Forecast(step))?;
            }
        }
        let emit_irf = irf_periods > 0 && step <= irf_periods;
        if step < steps || emit_irf {
            advance_impulse(
                &mut impulse,
                &mut impulse_history,
                &fit.coefficients,
                shape,
                step,
            );
            if step == 1 && specification.theta != 0.0 {
                impulse[0] += specification.theta;
                impulse[3] += specification.theta;
                impulse_history.copy_from_slice(&impulse);
            }
        }
        if emit_irf {
            append_irf(
                &mut irf,
                &impulse,
                &covariance,
                scales,
                step,
                specification.response_limit,
            )?;
        }
    }
    output.extend(irf);
    Ok(())
}

fn compute(
    values: &[f64],
    specification: Specification,
    check: CancellationCheck,
) -> Result<Vec<f64>, Failure> {
    let shape = specification.shape;
    let scales = scales(values, shape, check)?;
    let mut columns = design(values, &scales, shape, check)?;
    whiten(&mut columns, specification.theta, check)?;
    let mut response_rms = [0.0; SERIES];
    for (series, rms) in response_rms.iter_mut().enumerate() {
        checkpoint(check)?;
        let response = &columns[shape.predictors() + series];
        *rms = (dot(response, response) / shape.fitted_rows() as f64).sqrt();
    }
    let mut fit = fit(&mut columns, shape, check)?;
    drop(columns);
    let log_likelihood = likelihood(&mut fit, shape, response_rms, &scales)?;
    let state = terminal_state(values, &scales, specification, &fit, check)?;
    let mut output = Vec::with_capacity(specification.output_len());
    output.extend([
        contraction_bound(&fit, shape),
        fit.minimum_pivot_ratio,
        log_likelihood,
    ]);
    for (outcome, &scale) in scales.iter().enumerate() {
        let intercept = if shape.intercept == 1 {
            fit.coefficients[outcome]
        } else {
            0.0
        };
        output.push(coefficient_in_units(intercept, scale, 1.0).ok_or(Failure::Numeric)?);
    }
    for (outcome, &outcome_scale) in scales.iter().enumerate() {
        for (source, &source_scale) in scales.iter().enumerate() {
            let coefficient = fit.coefficients[(shape.intercept + source) * SERIES + outcome];
            output.push(
                coefficient_in_units(coefficient, outcome_scale, source_scale)
                    .ok_or(Failure::Numeric)?,
            );
        }
    }
    append_covariance(&mut output, &fit.covariance, &scales).ok_or(Failure::Numeric)?;
    for (series, &scale) in scales.iter().enumerate() {
        output.push(coefficient_in_units(state.1[series], scale, 1.0).ok_or(Failure::Numeric)?);
    }
    append_paths(&mut output, &fit, specification, &scales, state, check)?;
    Ok(output)
}

/// # Safety
/// Input contains initialized row-major pairs and remains immutable during the call.
/// Output and error buffers are aligned, separate and writable. The optional callback
/// stays valid for the call and may not unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_varma11_fixed_ma(
    values: *const f64,
    values_len: usize,
    rows: usize,
    training_rows: usize,
    intercept: i32,
    theta: f64,
    horizon: usize,
    irf_periods: usize,
    response_limit: f64,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    if error_index.is_null() || !error_index.is_aligned() {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    if rows > MAX_ROWS
        || !(MIN_TRAINING..=rows).contains(&training_rows)
        || !(1..=MAX_HORIZON).contains(&horizon)
        || (training_rows < rows && rows - training_rows != horizon)
        || irf_periods > MAX_HORIZON
        || !response_limit.is_finite()
        || response_limit < 1.0
        || !(-MAX_ABS_MA..=MAX_ABS_MA).contains(&theta)
        || !matches!(intercept, 0 | 1)
        || values_len != rows * SERIES
        || values.is_null()
        || !values.is_aligned()
        || output.is_null()
        || !output.is_aligned()
    {
        return INVALID_INPUT;
    }
    let specification = Specification {
        shape: Shape {
            series: SERIES,
            training_rows,
            lag_order: 1,
            intercept: intercept as usize,
            horizon,
        },
        theta,
        irf_periods,
        response_limit,
    };
    if output_len != specification.output_len() {
        return INVALID_INPUT;
    }
    let values = unsafe { slice::from_raw_parts(values, values_len) };
    let result = compute(values, specification, check);
    unsafe { publish_result(result, output, output_len, error_index) }
}
