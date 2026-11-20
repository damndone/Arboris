use std::{ptr, slice};

use super::{
    append_covariance, coefficient_in_units, dot, factor_from_row, CancellationCheck, CHECK_EVERY,
    INVALID_INPUT, MAX_HORIZON, MAX_ROWS, NUMERIC_FAILURE,
};

const SERIES: usize = 2;
const MAX_DIFFERENCE_LAGS: usize = 4;
const NON_FINITE: i32 = 3;
const RANK_DEFICIENT: i32 = 4;
const CANCELLED: i32 = 5;
const FORECAST_FAILURE: i32 = 6;
const CANONICAL_UNRESOLVED: i32 = 7;
const NORMALIZATION_UNAVAILABLE: i32 = 8;
const EIGEN_TOLERANCE: f64 = 64.0 * f64::EPSILON;

#[derive(Clone, Copy)]
struct Shape {
    training: usize,
    difference_lags: usize,
    horizon: usize,
}

impl Shape {
    fn fitted_rows(self) -> usize {
        self.training - self.difference_lags - 1
    }

    fn controls(self) -> usize {
        SERIES * self.difference_lags
    }

    fn output_len(self) -> usize {
        11 + 4 * self.difference_lags + 6 * self.horizon
    }
}

enum Failure {
    Observation(usize),
    Rank(usize, usize),
    Numeric,
    Forecast(usize),
    Canonical(usize),
    Normalization,
    Cancelled,
}

struct Fit {
    coefficients: Vec<[f64; SERIES]>,
    covariance: [f64; SERIES * SERIES],
}

fn checkpoint(check: CancellationCheck) -> Result<(), Failure> {
    super::checkpoint(check).map_err(|_| Failure::Cancelled)
}

fn scales(
    values: &[f64],
    shape: Shape,
    check: CancellationCheck,
) -> Result<[f64; SERIES], Failure> {
    let mut scales = [0.0_f64; SERIES];
    for (index, &value) in values.iter().enumerate() {
        if index % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        if !value.is_finite() {
            return Err(Failure::Observation(index));
        }
        if index < SERIES * shape.training {
            scales[index % SERIES] = scales[index % SERIES].max(value.abs());
        }
    }
    for scale in &mut scales {
        if *scale == 0.0 {
            *scale = 1.0;
        }
    }
    Ok(scales)
}

fn difference(values: &[f64], row: usize, column: usize, scale: f64) -> f64 {
    let current = values[row * SERIES + column];
    let previous = values[(row - 1) * SERIES + column];
    let change = current - previous;
    if change.is_finite() {
        change / scale
    } else {
        current / scale - previous / scale
    }
}

fn fill_differences(
    columns: &mut [Vec<f64>],
    values: &[f64],
    scales: &[f64; SERIES],
    shape: Shape,
    first_control: usize,
    first_response: usize,
    check: CancellationCheck,
) -> Result<(), Failure> {
    for row in 0..shape.fitted_rows() {
        if row % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let time = row + shape.difference_lags + 1;
        for (series, &scale) in scales.iter().enumerate() {
            for lag in 1..=shape.difference_lags {
                columns[first_control + (lag - 1) * SERIES + series][row] =
                    difference(values, time - lag, series, scale);
            }
            columns[first_response + series][row] = difference(values, time, series, scale);
        }
    }
    Ok(())
}

fn factor_block(
    columns: &mut [Vec<f64>],
    width: usize,
    first_row: usize,
    stage: usize,
    check: CancellationCheck,
) -> Result<Vec<usize>, Failure> {
    factor_from_row(columns, width, first_row, check)
        .map(|(permutation, _)| permutation)
        .map_err(|failure| match failure {
            super::Failure::Rank(pivot) => Failure::Rank(stage, pivot),
            super::Failure::Cancelled => Failure::Cancelled,
            _ => Failure::Numeric,
        })
}

fn leading_canonical(cross: &[[f64; 2]; 3]) -> Result<([f64; 2], [f64; 3]), Failure> {
    let aa = cross.iter().map(|row| row[0] * row[0]).sum::<f64>();
    let ab = cross.iter().map(|row| row[0] * row[1]).sum::<f64>();
    let bb = cross.iter().map(|row| row[1] * row[1]).sum::<f64>();
    let gap = (aa - bb).hypot(2.0 * ab);
    let high = (aa + bb + gap) * 0.5;
    let low = (aa + bb - gap) * 0.5;
    if !high.is_finite()
        || high <= EIGEN_TOLERANCE
        || high >= 1.0 - EIGEN_TOLERANCE
        || low < -EIGEN_TOLERANCE
    {
        return Err(Failure::Canonical(0));
    }
    if gap <= EIGEN_TOLERANCE {
        return Err(Failure::Canonical(1));
    }

    let right = if aa >= bb {
        [high - bb, ab]
    } else {
        [ab, high - aa]
    };
    let norm = right[0].hypot(right[1]);
    let right = [right[0] / norm, right[1] / norm];
    let left = cross.map(|row| dot(&row, &right) / high.sqrt());
    Ok(([high, low.max(0.0)], left))
}

fn normalize(direction: [f64; 3]) -> Result<[f64; 3], Failure> {
    let maximum = direction
        .iter()
        .map(|value| value.abs())
        .fold(0.0, f64::max);
    if !direction.iter().all(|value| value.is_finite())
        || direction[0].abs() <= EIGEN_TOLERANCE * maximum
    {
        return Err(Failure::Normalization);
    }
    Ok([
        1.0,
        direction[1] / direction[0],
        direction[2] / direction[0],
    ])
}

fn johansen(
    columns: &mut [Vec<f64>],
    shape: Shape,
    check: CancellationCheck,
) -> Result<([f64; 2], [f64; 3]), Failure> {
    let controls = shape.controls();
    factor_block(columns, controls, 0, 0, check)?;
    let residuals = &mut columns[controls..];
    let level_permutation = factor_block(residuals, 3, controls, 1, check)?;

    let mut cross = [[0.0; SERIES]; 3];
    for (row, entries) in cross.iter_mut().enumerate() {
        for (column, value) in entries.iter_mut().enumerate() {
            *value = residuals[3 + column][controls + row];
        }
    }
    let responses = &mut residuals[3..];
    let response_permutation = factor_block(responses, SERIES, controls, 2, check)?;
    for row in &mut cross {
        let first = row[response_permutation[0]] / responses[0][controls];
        let second = (row[response_permutation[1]] - first * responses[1][controls])
            / responses[1][controls + 1];
        *row = [first, second];
    }

    let (eigenvalues, direction) = leading_canonical(&cross)?;
    let mut beta = [0.0; 3];
    for row in (0..3).rev() {
        let projected = (row + 1..3)
            .map(|column| residuals[column][controls + row] * beta[level_permutation[column]])
            .sum::<f64>();
        beta[level_permutation[row]] =
            (direction[row] - projected) / residuals[row][controls + row];
    }
    Ok((eigenvalues, normalize(beta)?))
}

fn fit_short_run(
    columns: &mut [Vec<f64>],
    shape: Shape,
    check: CancellationCheck,
) -> Result<Fit, Failure> {
    let predictors = shape.controls() + 1;
    let permutation = factor_block(columns, predictors, 0, 3, check)?;
    let mut coefficients = vec![[0.0; SERIES]; predictors];
    for series in 0..SERIES {
        for row in (0..predictors).rev() {
            let projected = (row + 1..predictors)
                .map(|column| columns[column][row] * coefficients[permutation[column]][series])
                .sum::<f64>();
            let value = (columns[predictors + series][row] - projected) / columns[row][row];
            if !value.is_finite() {
                return Err(Failure::Numeric);
            }
            coefficients[permutation[row]][series] = value;
        }
    }
    let left = &columns[predictors][predictors..];
    let right = &columns[predictors + 1][predictors..];
    let count = shape.fitted_rows() as f64;
    let aa = dot(left, left) / count;
    let ab = dot(left, right) / count;
    let bb = dot(right, right) / count;
    if aa <= 0.0
        || bb <= 0.0
        || ![aa, ab, bb].iter().all(|value| value.is_finite())
        || (ab / (aa.sqrt() * bb.sqrt())).abs() >= 1.0
    {
        return Err(Failure::Numeric);
    }
    Ok(Fit {
        coefficients,
        covariance: [aa, ab, ab, bb],
    })
}

fn forecast(
    output: &mut Vec<f64>,
    values: &[f64],
    scales: &[f64; SERIES],
    shape: Shape,
    fit: &Fit,
    beta: &[f64; 3],
    check: CancellationCheck,
) -> Result<(), Failure> {
    let dimension = SERIES * (1 + shape.difference_lags);
    let mut state = vec![0.0; dimension];
    let mut transition = vec![0.0; dimension * dimension];
    for (series, &scale) in scales.iter().enumerate() {
        state[series] = values[(shape.training - 1) * SERIES + series] / scale;
        for lag in 0..shape.difference_lags {
            state[(lag + 1) * SERIES + series] =
                difference(values, shape.training - 1 - lag, series, scale);
        }
        for column in 0..SERIES {
            let impact = fit.coefficients[0][series] * beta[column];
            let identity = if series == column { 1.0 } else { 0.0 };
            transition[series * dimension + column] = impact + identity;
            transition[(series + SERIES) * dimension + column] = impact;
        }
        for column in SERIES..dimension {
            let coefficient = fit.coefficients[column - SERIES + 1][series];
            transition[series * dimension + column] = coefficient;
            transition[(series + SERIES) * dimension + column] = coefficient;
        }
    }
    for row in 2 * SERIES..dimension {
        transition[row * dimension + row - SERIES] = 1.0;
    }

    let mut covariance = vec![0.0; dimension * dimension];
    let mut propagated = vec![0.0; dimension * dimension];
    for step in 1..=shape.horizon {
        checkpoint(check)?;
        let equilibrium = beta[0] * state[0] + beta[1] * state[1] + beta[2];
        let mut new_difference = [0.0; SERIES];
        for (series, scale) in scales.iter().enumerate() {
            let mut change = fit.coefficients[0][series] * equilibrium;
            for (column, &value) in state[SERIES..].iter().enumerate() {
                change += fit.coefficients[column + 1][series] * value;
            }
            new_difference[series] = change;
            state[series] += change;
            let raw_mean = state[series] * scale;
            if !raw_mean.is_finite() || (raw_mean == 0.0 && state[series] != 0.0) {
                return Err(Failure::Forecast(step));
            }
            output.push(raw_mean);
        }
        state.copy_within(SERIES..dimension - SERIES, 2 * SERIES);
        state[SERIES..2 * SERIES].copy_from_slice(&new_difference);

        for row in 0..dimension {
            for column in 0..dimension {
                propagated[row * dimension + column] = (0..dimension)
                    .map(|source| {
                        transition[row * dimension + source]
                            * covariance[source * dimension + column]
                    })
                    .sum();
            }
        }
        for row in 0..dimension {
            let left = &propagated[row * dimension..(row + 1) * dimension];
            for column in 0..=row {
                let right = &transition[column * dimension..(column + 1) * dimension];
                let innovation = if row < 2 * SERIES {
                    fit.covariance[(row % SERIES) * SERIES + column % SERIES]
                } else {
                    0.0
                };
                let value = dot(left, right) + innovation;
                if !value.is_finite() || (row == column && value < 0.0) {
                    return Err(Failure::Forecast(step));
                }
                covariance[row * dimension + column] = value;
                covariance[column * dimension + row] = value;
            }
        }
        let level_covariance = [
            covariance[0],
            covariance[1],
            covariance[dimension],
            covariance[dimension + 1],
        ];
        append_covariance(output, &level_covariance, scales).ok_or(Failure::Forecast(step))?;
    }
    Ok(())
}

fn compute(values: &[f64], shape: Shape, check: CancellationCheck) -> Result<Vec<f64>, Failure> {
    let scales = scales(values, shape, check)?;
    let controls = shape.controls();
    let mut columns = vec![vec![0.0; shape.fitted_rows()]; controls + 3 + SERIES];
    fill_differences(&mut columns, values, &scales, shape, 0, controls + 3, check)?;
    for row in 0..shape.fitted_rows() {
        if row % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let previous = (row + shape.difference_lags) * SERIES;
        for series in 0..SERIES {
            columns[controls + series][row] = values[previous + series] / scales[series];
        }
    }
    columns[controls + 2].fill(1.0);
    let (eigenvalues, beta) = johansen(&mut columns, shape, check)?;

    columns.truncate(controls + 1 + SERIES);
    fill_differences(&mut columns, values, &scales, shape, 1, controls + 1, check)?;
    for row in 0..shape.fitted_rows() {
        if row % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let previous = (row + shape.difference_lags) * SERIES;
        let value =
            values[previous] / scales[0] + beta[1] * (values[previous + 1] / scales[1]) + beta[2];
        if !value.is_finite() {
            return Err(Failure::Numeric);
        }
        columns[0][row] = value;
    }
    let fit = fit_short_run(&mut columns, shape, check)?;
    drop(columns);

    let mut output = Vec::with_capacity(shape.output_len());
    output.extend(eigenvalues);
    output.extend([
        1.0,
        coefficient_in_units(beta[1], scales[0], scales[1]).ok_or(Failure::Numeric)?,
        coefficient_in_units(beta[2], scales[0], 1.0).ok_or(Failure::Numeric)?,
    ]);
    for (outcome, &outcome_scale) in scales.iter().enumerate() {
        output.push(
            coefficient_in_units(fit.coefficients[0][outcome], outcome_scale, scales[0])
                .ok_or(Failure::Numeric)?,
        );
    }
    for lag in 0..shape.difference_lags {
        for (outcome, &outcome_scale) in scales.iter().enumerate() {
            for (source, &source_scale) in scales.iter().enumerate() {
                let value = fit.coefficients[1 + SERIES * lag + source][outcome];
                output.push(
                    coefficient_in_units(value, outcome_scale, source_scale)
                        .ok_or(Failure::Numeric)?,
                );
            }
        }
    }
    append_covariance(&mut output, &fit.covariance, &scales).ok_or(Failure::Numeric)?;
    forecast(&mut output, values, &scales, shape, &fit, &beta, check)?;
    Ok(output)
}

/// Fits a bivariate rank-one VECM with a restricted constant. Writes the
/// canonical roots, beta, alpha, short-run coefficients, innovation covariance,
/// and level forecasts with full covariance. Failure leaves output untouched.
///
/// # Safety
/// Nonnull pointers must refer to valid, separate buffers of the stated lengths.
/// The row-major input must be initialized and unchanged throughout the call.
/// The optional callback must remain valid and may not unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_vecm_rank1(
    values: *const f64,
    values_len: usize,
    rows: usize,
    training: usize,
    difference_lags: usize,
    horizon: usize,
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
        || !(1..=MAX_DIFFERENCE_LAGS).contains(&difference_lags)
        || !(1..=MAX_HORIZON).contains(&horizon)
        || training > rows
        || training < 3 * difference_lags + 7
        || (training < rows && rows - training != horizon)
        || values_len != SERIES * rows
        || values.is_null()
        || !values.is_aligned()
        || output.is_null()
        || !output.is_aligned()
    {
        return INVALID_INPUT;
    }
    let shape = Shape {
        training,
        difference_lags,
        horizon,
    };
    if output_len != shape.output_len() {
        return INVALID_INPUT;
    }
    let input = unsafe { slice::from_raw_parts(values, values_len) };
    match compute(input, shape, check) {
        Ok(result) if result.len() == output_len => {
            unsafe { ptr::copy_nonoverlapping(result.as_ptr(), output, output_len) };
            0
        }
        Ok(_) => INVALID_INPUT,
        Err(Failure::Observation(index)) => {
            unsafe { error_index.write(index) };
            NON_FINITE
        }
        Err(Failure::Rank(stage, pivot)) => {
            unsafe { error_index.write(16 * stage + pivot) };
            RANK_DEFICIENT
        }
        Err(Failure::Numeric) => NUMERIC_FAILURE,
        Err(Failure::Forecast(horizon)) => {
            unsafe { error_index.write(horizon) };
            FORECAST_FAILURE
        }
        Err(Failure::Canonical(code)) => {
            unsafe { error_index.write(code) };
            CANONICAL_UNRESOLVED
        }
        Err(Failure::Normalization) => NORMALIZATION_UNAVAILABLE,
        Err(Failure::Cancelled) => CANCELLED,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn near_equal_canonical_roots_do_not_select_an_arbitrary_direction() {
        let near_tie = [[0.5, 0.0], [0.0, 0.5_f64.next_up()], [0.0, 0.0]];
        assert!(matches!(
            leading_canonical(&near_tie),
            Err(Failure::Canonical(1))
        ));
    }

    #[test]
    fn perfect_canonical_correlation_is_outside_the_supported_boundary() {
        let perfect = [[1.0, 0.0], [0.0, 0.5], [0.0, 0.0]];
        assert!(matches!(
            leading_canonical(&perfect),
            Err(Failure::Canonical(0))
        ));
    }

    #[test]
    fn a_nearly_zero_first_level_coefficient_cannot_normalize_beta() {
        assert!(matches!(
            normalize([1e-20, 1.0, 0.25]),
            Err(Failure::Normalization)
        ));
    }
}
