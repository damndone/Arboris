use std::{ptr, slice};

use super::{INVALID_INPUT, NUMERIC_FAILURE};

#[path = "var_diagnostics.rs"]
mod diagnostics;

#[path = "johansen.rs"]
mod johansen;

#[path = "vecm.rs"]
mod vecm;

#[path = "varma.rs"]
mod varma;

#[path = "stationarity.rs"]
mod stationarity;

const MAX_ROWS: usize = 20_000;
const MAX_SERIES: usize = 8;
const MAX_LAG: usize = 8;
const MAX_HORIZON: usize = 200;
const CHECK_EVERY: usize = 1024;
const NON_FINITE_VALUE: i32 = 3;
const RANK_DEFICIENT: i32 = 4;
const CANCELLED: i32 = 5;
const FORECAST_FAILURE: i32 = 6;
const RESPONSE_LIMIT: i32 = 7;
const INNOVATION_COVARIANCE_FAILURE: i32 = 8;

type CancellationCheck = Option<extern "C" fn() -> i32>;

#[derive(Clone, Copy)]
struct Shape {
    series: usize,
    training_rows: usize,
    lag_order: usize,
    intercept: usize,
    horizon: usize,
}

impl Shape {
    fn predictors(self) -> usize {
        self.series * self.lag_order + self.intercept
    }

    fn fitted_rows(self) -> usize {
        self.training_rows - self.lag_order
    }

    fn output_len(self) -> usize {
        let covariance = self.series * self.series;
        2 + self.predictors() * self.series + covariance + self.horizon * (self.series + covariance)
    }

    fn evidence_len(self) -> usize {
        let predictors = self.predictors();
        self.series
            + predictors
            + predictors * self.series
            + self.series * self.series
            + predictors * predictors
    }
}

struct Fit {
    coefficients: Vec<f64>,
    covariance: Vec<f64>,
    minimum_pivot_ratio: f64,
    permutation: Vec<usize>,
}

enum Failure {
    Observation(usize),
    Rank(usize),
    Numeric,
    Forecast(usize),
    ResponseLimit(usize),
    InnovationCovariance,
    Cancelled,
}

fn checkpoint(check: CancellationCheck) -> Result<(), Failure> {
    if check.is_some_and(|poll| poll() != 0) {
        return Err(Failure::Cancelled);
    }
    Ok(())
}

fn scales(values: &[f64], shape: Shape, check: CancellationCheck) -> Result<Vec<f64>, Failure> {
    let mut scales = vec![0.0_f64; shape.series];
    for (index, &value) in values.iter().enumerate() {
        if index % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        if !value.is_finite() {
            return Err(Failure::Observation(index));
        }
        if index < shape.training_rows * shape.series {
            let column = index % shape.series;
            scales[column] = scales[column].max(value.abs());
        }
    }
    for scale in &mut scales {
        if *scale == 0.0 {
            *scale = 1.0;
        }
    }
    Ok(scales)
}

fn design(
    values: &[f64],
    scales: &[f64],
    shape: Shape,
    check: CancellationCheck,
) -> Result<Vec<Vec<f64>>, Failure> {
    let fitted_rows = shape.fitted_rows();
    let predictors = shape.predictors();
    let mut columns = vec![vec![0.0; fitted_rows]; predictors + shape.series];
    if shape.intercept == 1 {
        columns[0].fill(1.0);
    }
    for row in 0..fitted_rows {
        if row % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let time = row + shape.lag_order;
        for lag in 1..=shape.lag_order {
            let first = shape.intercept + (lag - 1) * shape.series;
            for (series, scale) in scales.iter().enumerate() {
                columns[first + series][row] = values[(time - lag) * shape.series + series] / scale;
            }
        }
        for (series, scale) in scales.iter().enumerate() {
            columns[predictors + series][row] = values[time * shape.series + series] / scale;
        }
    }
    Ok(columns)
}

fn dot(left: &[f64], right: &[f64]) -> f64 {
    left.iter().zip(right).map(|(a, b)| a * b).sum()
}

fn factor(
    columns: &mut [Vec<f64>],
    predictors: usize,
    check: CancellationCheck,
) -> Result<(Vec<usize>, f64), Failure> {
    factor_from_row(columns, predictors, 0, check)
}

fn factor_from_row(
    columns: &mut [Vec<f64>],
    predictors: usize,
    first_row: usize,
    check: CancellationCheck,
) -> Result<(Vec<usize>, f64), Failure> {
    let fitted_rows = columns[0].len() - first_row;
    let mut permutation: Vec<_> = (0..predictors).collect();
    let tolerance = f64::EPSILON * fitted_rows as f64;
    let mut first_norm = 0.0;
    let mut minimum_pivot_ratio = 1.0_f64;

    for pivot in 0..predictors {
        checkpoint(check)?;
        let row = first_row + pivot;
        let mut best = pivot;
        let mut best_squared = 0.0;
        for (column, values) in columns[..predictors].iter().enumerate().skip(pivot) {
            let tail = &values[row..];
            let squared = dot(tail, tail);
            if squared > best_squared {
                best = column;
                best_squared = squared;
            }
        }
        let norm = best_squared.sqrt();
        if pivot == 0 {
            first_norm = norm;
        }
        if norm <= tolerance * first_norm {
            return Err(Failure::Rank(pivot));
        }
        minimum_pivot_ratio = minimum_pivot_ratio.min(norm / first_norm);
        columns.swap(pivot, best);
        permutation.swap(pivot, best);

        let (through_pivot, trailing) = columns.split_at_mut(pivot + 1);
        let reflector = &mut through_pivot[pivot][row..];
        let diagonal = -norm.copysign(reflector[0]);
        reflector[0] -= diagonal;
        let reflector_norm_squared = dot(reflector, reflector);
        for column in trailing {
            checkpoint(check)?;
            let tail = &mut column[row..];
            let weight = 2.0 * dot(reflector, tail) / reflector_norm_squared;
            for (value, direction) in tail.iter_mut().zip(reflector.iter()) {
                *value -= weight * direction;
            }
        }
        reflector[0] = diagonal;
    }

    Ok((permutation, minimum_pivot_ratio))
}

fn fit(columns: &mut [Vec<f64>], shape: Shape, check: CancellationCheck) -> Result<Fit, Failure> {
    let fitted_rows = shape.fitted_rows();
    let predictors = shape.predictors();
    let series = shape.series;
    let (permutation, minimum_pivot_ratio) = factor(columns, predictors, check)?;

    let mut coefficients = vec![0.0; predictors * series];
    for outcome in 0..series {
        for row in (0..predictors).rev() {
            let projected = (row + 1..predictors)
                .map(|column| {
                    columns[column][row] * coefficients[permutation[column] * series + outcome]
                })
                .sum::<f64>();
            let value = (columns[predictors + outcome][row] - projected) / columns[row][row];
            if !value.is_finite() {
                return Err(Failure::Numeric);
            }
            coefficients[permutation[row] * series + outcome] = value;
        }
    }

    let mut covariance = vec![0.0; series * series];
    let df = (fitted_rows - predictors) as f64;
    for left in 0..series {
        for right in 0..=left {
            let value = dot(
                &columns[predictors + left][predictors..],
                &columns[predictors + right][predictors..],
            ) / df;
            if !value.is_finite() {
                return Err(Failure::Numeric);
            }
            covariance[left * series + right] = value;
            covariance[right * series + left] = value;
        }
    }
    Ok(Fit {
        coefficients,
        covariance,
        minimum_pivot_ratio,
        permutation,
    })
}

fn representable_nonzero(value: f64) -> bool {
    value.is_finite() && value != 0.0
}

fn coefficient_in_units(value: f64, outcome_scale: f64, predictor_scale: f64) -> Option<f64> {
    if value == 0.0 {
        return Some(value);
    }
    let ratio = outcome_scale / predictor_scale;
    [
        value * ratio,
        (value * outcome_scale) / predictor_scale,
        (value / predictor_scale) * outcome_scale,
    ]
    .into_iter()
    .find(|item| representable_nonzero(*item))
}

fn covariance_in_units(value: f64, left_scale: f64, right_scale: f64) -> Option<f64> {
    if value == 0.0 {
        return Some(value);
    }
    [
        (value * left_scale) * right_scale,
        (value * right_scale) * left_scale,
    ]
    .into_iter()
    .find(|item| representable_nonzero(*item))
}

fn append_covariance(output: &mut Vec<f64>, covariance: &[f64], scales: &[f64]) -> Option<()> {
    let series = scales.len();
    for (left, &left_scale) in scales.iter().enumerate() {
        for (right, &right_scale) in scales.iter().enumerate() {
            let value = covariance[left * series + right];
            output.push(covariance_in_units(
                value,
                left_scale.min(right_scale),
                left_scale.max(right_scale),
            )?);
        }
    }
    Some(())
}

fn contraction_bound(fit: &Fit, shape: Shape) -> f64 {
    (0..shape.series)
        .map(|outcome| {
            let mut bound = 0.0;
            for predictor in shape.intercept..shape.predictors() {
                let magnitude = fit.coefficients[predictor * shape.series + outcome].abs();
                if magnitude != 0.0 {
                    bound = (bound + magnitude).next_up();
                }
            }
            bound
        })
        .fold(0.0, f64::max)
}

fn advance_impulse(
    impulse: &mut [f64],
    history: &mut [f64],
    coefficients: &[f64],
    shape: Shape,
    step: usize,
) {
    let series = shape.series;
    let matrix_size = series * series;
    impulse.fill(0.0);
    if step == 0 {
        for index in 0..series {
            impulse[index * series + index] = 1.0;
        }
    }
    for lag in 1..=shape.lag_order.min(step) {
        let first = shape.intercept + (lag - 1) * series;
        let previous = ((step - lag) % shape.lag_order) * matrix_size;
        for row in 0..series {
            for column in 0..series {
                for source in 0..series {
                    impulse[row * series + column] += coefficients[(first + source) * series + row]
                        * history[previous + source * series + column];
                }
            }
        }
    }
    let slot = (step % shape.lag_order) * matrix_size;
    history[slot..slot + matrix_size].copy_from_slice(impulse);
}

fn accumulate_covariance(
    covariance: &mut [f64],
    impulse: &[f64],
    innovation_covariance: &[f64],
    propagated: &mut [f64],
    series: usize,
    horizon: usize,
) -> Result<(), Failure> {
    for row in 0..series {
        for column in 0..series {
            propagated[row * series + column] = (0..series)
                .map(|source| {
                    impulse[row * series + source] * innovation_covariance[source * series + column]
                })
                .sum();
        }
    }
    for row in 0..series {
        let left = &propagated[row * series..(row + 1) * series];
        for column in 0..=row {
            let right = &impulse[column * series..(column + 1) * series];
            let value = covariance[row * series + column] + dot(left, right);
            if !value.is_finite() || (row == column && value < 0.0) {
                return Err(Failure::Forecast(horizon));
            }
            covariance[row * series + column] = value;
            covariance[column * series + row] = value;
        }
    }
    Ok(())
}

fn append_forecast(
    output: &mut Vec<f64>,
    values: &[f64],
    scales: &[f64],
    shape: Shape,
    fit: &Fit,
    check: CancellationCheck,
) -> Result<(), Failure> {
    let series = shape.series;
    let matrix_size = series * series;
    let mut history = Vec::with_capacity((shape.lag_order + shape.horizon) * series);
    for time in shape.training_rows - shape.lag_order..shape.training_rows {
        history.extend((0..series).map(|column| values[time * series + column] / scales[column]));
    }
    let mut impulse_history = vec![0.0; shape.lag_order * matrix_size];
    let mut impulse = vec![0.0; matrix_size];
    let mut propagated = vec![0.0; matrix_size];
    let mut covariance = vec![0.0; matrix_size];
    for step in 0..shape.horizon {
        checkpoint(check)?;
        for (outcome, scale) in scales.iter().enumerate() {
            let mut mean = if shape.intercept == 1 {
                fit.coefficients[outcome]
            } else {
                0.0
            };
            for lag in 1..=shape.lag_order {
                let first = shape.intercept + (lag - 1) * series;
                let past = (shape.lag_order + step - lag) * series;
                for source in 0..series {
                    mean += fit.coefficients[(first + source) * series + outcome]
                        * history[past + source];
                }
            }
            let mean_in_units = mean * scale;
            if !mean_in_units.is_finite() || (mean != 0.0 && mean_in_units == 0.0) {
                return Err(Failure::Forecast(step + 1));
            }
            history.push(mean);
            output.push(mean_in_units);
        }

        advance_impulse(
            &mut impulse,
            &mut impulse_history,
            &fit.coefficients,
            shape,
            step,
        );
        accumulate_covariance(
            &mut covariance,
            &impulse,
            &fit.covariance,
            &mut propagated,
            series,
            step + 1,
        )?;
        append_covariance(output, &covariance, scales).ok_or(Failure::Forecast(step + 1))?;
    }
    Ok(())
}

fn compute(
    values: &[f64],
    shape: Shape,
    include_evidence: bool,
    check: CancellationCheck,
) -> Result<Vec<f64>, Failure> {
    let scales = scales(values, shape, check)?;
    let mut columns = design(values, &scales, shape, check)?;
    let fit = fit(&mut columns, shape, check)?;
    let evidence =
        include_evidence.then(|| diagnostics::fit_evidence(&columns, &fit, &scales, shape));
    drop(columns);

    let mut output = Vec::with_capacity(shape.output_len());
    output.extend([contraction_bound(&fit, shape), fit.minimum_pivot_ratio]);
    for predictor in 0..shape.predictors() {
        let predictor_scale = if predictor < shape.intercept {
            1.0
        } else {
            scales[(predictor - shape.intercept) % shape.series]
        };
        for (outcome, &outcome_scale) in scales.iter().enumerate() {
            let value = fit.coefficients[predictor * shape.series + outcome];
            output.push(
                coefficient_in_units(value, outcome_scale, predictor_scale)
                    .ok_or(Failure::Numeric)?,
            );
        }
    }
    append_covariance(&mut output, &fit.covariance, &scales).ok_or(Failure::Numeric)?;
    append_forecast(&mut output, values, &scales, shape, &fit, check)?;
    if let Some(receipt) = evidence {
        output.extend(receipt);
    }
    Ok(output)
}

/// Writes two fit diagnostics, predictor-major coefficients, row-major
/// innovation covariance, then means and row-major covariances by horizon.
/// A nonzero status leaves the output buffer untouched.
///
/// # Safety
/// Nonnull pointers must refer to valid, separate buffers of the given lengths.
/// The row-major input must be initialized and unchanged for the whole call.
/// The optional callback must stay valid and may not unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_var_fit(
    values: *const f64,
    values_len: usize,
    rows: usize,
    series: usize,
    training_rows: usize,
    lag_order: usize,
    intercept: i32,
    horizon: usize,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    unsafe {
        run_fit(
            values,
            values_len,
            rows,
            series,
            training_rows,
            lag_order,
            intercept,
            horizon,
            output,
            output_len,
            error_index,
            check,
            false,
        )
    }
}

/// Appends compact training scales, scaled coefficients and covariance, and the
/// pivoted triangular factor to the ordinary fit output for postestimation.
///
/// # Safety
/// The pointer and cancellation contracts are those of `arboris_var_fit`.
#[no_mangle]
pub unsafe extern "C" fn arboris_var_fit_with_evidence(
    values: *const f64,
    values_len: usize,
    rows: usize,
    series: usize,
    training_rows: usize,
    lag_order: usize,
    intercept: i32,
    horizon: usize,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    unsafe {
        run_fit(
            values,
            values_len,
            rows,
            series,
            training_rows,
            lag_order,
            intercept,
            horizon,
            output,
            output_len,
            error_index,
            check,
            true,
        )
    }
}

unsafe fn run_fit(
    values: *const f64,
    values_len: usize,
    rows: usize,
    series: usize,
    training_rows: usize,
    lag_order: usize,
    intercept: i32,
    horizon: usize,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
    include_evidence: bool,
) -> i32 {
    if error_index.is_null() || !error_index.is_aligned() {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    if rows > MAX_ROWS
        || !(2..=MAX_SERIES).contains(&series)
        || !(1..=MAX_LAG).contains(&lag_order)
        || !(1..=MAX_HORIZON).contains(&horizon)
        || !matches!(intercept, 0 | 1)
        || training_rows > rows
        || training_rows <= lag_order
        || (training_rows < rows && rows - training_rows != horizon)
        || values_len != rows * series
        || values.is_null()
        || !values.is_aligned()
        || output.is_null()
        || !output.is_aligned()
    {
        return INVALID_INPUT;
    }
    let shape = Shape {
        series,
        training_rows,
        lag_order,
        intercept: intercept as usize,
        horizon,
    };
    let expected_len = shape.output_len()
        + if include_evidence {
            shape.evidence_len()
        } else {
            0
        };
    if shape.fitted_rows() <= shape.predictors() || output_len != expected_len {
        return INVALID_INPUT;
    }
    let values = unsafe { slice::from_raw_parts(values, values_len) };
    let result = compute(values, shape, include_evidence, check);
    unsafe { publish_result(result, output, output_len, error_index) }
}

unsafe fn publish_result(
    result: Result<Vec<f64>, Failure>,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
) -> i32 {
    match result {
        Ok(result) if result.len() == output_len => {
            unsafe { ptr::copy_nonoverlapping(result.as_ptr(), output, output_len) };
            0
        }
        Ok(_) => INVALID_INPUT,
        Err(Failure::Observation(index)) => {
            unsafe { error_index.write(index) };
            NON_FINITE_VALUE
        }
        Err(Failure::Rank(pivot)) => {
            unsafe { error_index.write(pivot) };
            RANK_DEFICIENT
        }
        Err(Failure::Numeric) => NUMERIC_FAILURE,
        Err(Failure::Forecast(step)) => {
            unsafe { error_index.write(step) };
            FORECAST_FAILURE
        }
        Err(Failure::ResponseLimit(step)) => {
            unsafe { error_index.write(step) };
            RESPONSE_LIMIT
        }
        Err(Failure::InnovationCovariance) => INNOVATION_COVARIANCE_FAILURE,
        Err(Failure::Cancelled) => CANCELLED,
    }
}
