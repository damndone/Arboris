use std::slice;

use super::{
    accumulate_covariance, advance_impulse, append_covariance, checkpoint, coefficient_in_units,
    covariance_in_units, dot, factor, publish_result, CancellationCheck, Failure, Fit, Shape,
    INVALID_INPUT, MAX_HORIZON, MAX_LAG, MAX_ROWS, MAX_SERIES,
};

const GRANGER_WIDTH: usize = 6;

pub(super) fn fit_evidence(
    columns: &[Vec<f64>],
    fit: &Fit,
    scales: &[f64],
    shape: Shape,
) -> Vec<f64> {
    let mut evidence = Vec::with_capacity(shape.evidence_len());
    evidence.extend_from_slice(scales);
    evidence.extend(fit.permutation.iter().map(|&index| index as f64));
    evidence.extend_from_slice(&fit.coefficients);
    evidence.extend_from_slice(&fit.covariance);
    let predictors = shape.predictors();
    for row in 0..predictors {
        for (column, values) in columns.iter().enumerate().take(predictors) {
            evidence.push(if column < row { 0.0 } else { values[row] });
        }
    }
    evidence
}

struct Evidence<'a> {
    scales: &'a [f64],
    permutation: Vec<usize>,
    coefficients: &'a [f64],
    covariance: &'a [f64],
    triangular: &'a [f64],
}

fn covariance_valid(covariance: &[f64], series: usize) -> bool {
    let mut scale = 0.0_f64;
    for row in 0..series {
        let diagonal = covariance[row * series + row];
        if diagonal < 0.0 {
            return false;
        }
        scale = scale.max(diagonal);
        for column in 0..row {
            if covariance[row * series + column] != covariance[column * series + row] {
                return false;
            }
        }
    }
    if scale == 0.0 {
        return covariance.iter().all(|&value| value == 0.0);
    }

    let tolerance = 64.0 * f64::EPSILON * series as f64;
    let mut reduced: Vec<_> = covariance.iter().map(|value| value / scale).collect();
    if reduced.iter().any(|value| value.abs() > 1.0 + tolerance) {
        return false;
    }
    for first in 0..series {
        let pivot = (first + 1..series).fold(first, |best, candidate| {
            if reduced[candidate * series + candidate] > reduced[best * series + best] {
                candidate
            } else {
                best
            }
        });
        let diagonal = reduced[pivot * series + pivot];
        if diagonal <= tolerance {
            return (first..series).all(|row| {
                (first..series).all(|column| reduced[row * series + column].abs() <= tolerance)
            });
        }
        for index in 0..series {
            reduced.swap(first * series + index, pivot * series + index);
        }
        for index in 0..series {
            reduced.swap(index * series + first, index * series + pivot);
        }
        for row in first + 1..series {
            for column in row..series {
                let correction =
                    reduced[row * series + first] * reduced[column * series + first] / diagonal;
                reduced[row * series + column] -= correction;
                reduced[column * series + row] = reduced[row * series + column];
            }
        }
    }
    true
}

impl<'a> Evidence<'a> {
    fn parse(raw: &'a [f64], shape: Shape) -> Option<Self> {
        if raw.len() != shape.evidence_len() || !raw.iter().all(|value| value.is_finite()) {
            return None;
        }
        let series = shape.series;
        let predictors = shape.predictors();
        let (scales, remaining) = raw.split_at(series);
        let (wire_permutation, remaining) = remaining.split_at(predictors);
        let (coefficients, remaining) = remaining.split_at(predictors * series);
        let (covariance, triangular) = remaining.split_at(series * series);
        if scales.iter().any(|value| *value <= 0.0) || !covariance_valid(covariance, series) {
            return None;
        }
        let mut seen = vec![false; predictors];
        let mut permutation = Vec::with_capacity(predictors);
        for &wire_index in wire_permutation {
            if wire_index < 0.0 || wire_index >= predictors as f64 || wire_index.fract() != 0.0 {
                return None;
            }
            let index = wire_index as usize;
            if seen[index] {
                return None;
            }
            seen[index] = true;
            permutation.push(index);
        }
        for row in 0..predictors {
            let line = &triangular[row * predictors..(row + 1) * predictors];
            if line[row] == 0.0 || line[..row].iter().any(|&value| value != 0.0) {
                return None;
            }
        }
        Some(Self {
            scales,
            permutation,
            coefficients,
            covariance,
            triangular,
        })
    }
}

fn block_test(
    evidence: Evidence<'_>,
    shape: Shape,
    fitted_rows: usize,
    effect: usize,
    excluded: u32,
    check: CancellationCheck,
) -> Result<Vec<f64>, Failure> {
    let predictors = shape.predictors();
    let series = shape.series;
    let denominator = fitted_rows - predictors;
    let variance = evidence.covariance[effect * series + effect];
    if variance <= (f64::EPSILON * fitted_rows as f64).powi(2) {
        return Err(Failure::Numeric);
    }

    let numerator = shape.lag_order * excluded.count_ones() as usize;
    let mut contrasts = Vec::with_capacity(numerator);
    let mut selected = Vec::with_capacity(numerator);
    for (pivot, &predictor) in evidence.permutation.iter().enumerate() {
        if predictor < shape.intercept
            || excluded & (1 << ((predictor - shape.intercept) % series)) == 0
        {
            continue;
        }
        checkpoint(check)?;
        let mut column = vec![0.0; predictors];
        for row in pivot..predictors {
            let rhs = if row == pivot { 1.0 } else { 0.0 };
            let previous = (pivot..row)
                .map(|prior| evidence.triangular[prior * predictors + row] * column[prior])
                .sum::<f64>();
            column[row] = (rhs - previous) / evidence.triangular[row * predictors + row];
        }
        if !column.iter().all(|value| value.is_finite()) {
            return Err(Failure::Numeric);
        }
        let scale = column.iter().map(|value| value.abs()).fold(0.0, f64::max);
        let coefficient = evidence.coefficients[predictor * series + effect] / scale;
        if scale <= 0.0 || !coefficient.is_finite() {
            return Err(Failure::Numeric);
        }
        column.iter_mut().for_each(|value| *value /= scale);
        contrasts.push(column);
        selected.push(coefficient);
    }

    let (permutation, _) = factor(&mut contrasts, numerator, check)?;
    let mut solved = vec![0.0; numerator];
    for row in 0..numerator {
        solved[row] = (selected[permutation[row]] - dot(&contrasts[row][..row], &solved[..row]))
            / contrasts[row][row];
    }
    let explained = dot(&solved, &solved);
    let statistic = (explained / numerator as f64) / variance;
    let unrestricted = variance * denominator as f64;
    if !statistic.is_finite() || !unrestricted.is_finite() {
        return Err(Failure::Numeric);
    }
    let scale = evidence.scales[effect];
    Ok(vec![
        statistic,
        numerator as f64,
        denominator as f64,
        covariance_in_units(unrestricted, scale, scale).ok_or(Failure::Numeric)?,
        covariance_in_units(unrestricted + explained, scale, scale).ok_or(Failure::Numeric)?,
        covariance_in_units(explained, scale, scale).ok_or(Failure::Numeric)?,
    ])
}

fn impulse_responses(
    evidence: Evidence<'_>,
    shape: Shape,
    limit: f64,
    check: CancellationCheck,
) -> Result<Vec<f64>, Failure> {
    let series = shape.series;
    let matrix_size = series * series;
    let mut history = vec![0.0; shape.lag_order * matrix_size];
    let mut impulse = vec![0.0; matrix_size];
    let mut propagated = vec![0.0; matrix_size];
    let mut covariance = vec![0.0; matrix_size];
    let mut output = Vec::with_capacity((shape.horizon + 1) * 2 * matrix_size);
    for step in 0..=shape.horizon {
        checkpoint(check)?;
        advance_impulse(
            &mut impulse,
            &mut history,
            evidence.coefficients,
            shape,
            step,
        );
        for (response, &response_scale) in evidence.scales.iter().enumerate() {
            for (shock, &shock_scale) in evidence.scales.iter().enumerate() {
                let value = coefficient_in_units(
                    impulse[response * series + shock],
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
        append_covariance(&mut output, &covariance, evidence.scales)
            .ok_or(Failure::Forecast(step))?;
        if step < shape.horizon {
            accumulate_covariance(
                &mut covariance,
                &impulse,
                evidence.covariance,
                &mut propagated,
                series,
                step + 1,
            )?;
        }
    }
    Ok(output)
}

fn diagnostic_shape(
    series: usize,
    lag_order: usize,
    intercept: i32,
    horizon: usize,
) -> Option<Shape> {
    if !(2..=MAX_SERIES).contains(&series)
        || !(1..=MAX_LAG).contains(&lag_order)
        || !matches!(intercept, 0 | 1)
        || horizon > MAX_HORIZON
    {
        return None;
    }
    Some(Shape {
        series,
        lag_order,
        intercept: intercept as usize,
        horizon,
        training_rows: 0,
    })
}

fn valid_buffers(evidence: *const f64, output: *mut f64) -> bool {
    !evidence.is_null() && evidence.is_aligned() && !output.is_null() && output.is_aligned()
}

/// Tests one response equation against the selected lagged predictor block.
/// The receipt and fitted row count must come from the same verified fit.
///
/// # Safety
/// Nonnull pointers must refer to valid, separate buffers of the given lengths.
/// The receipt must be initialized and unchanged for the whole call. The
/// optional callback must stay valid and may not unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_var_granger_block(
    evidence: *const f64,
    evidence_len: usize,
    series: usize,
    lag_order: usize,
    intercept: i32,
    fitted_rows: usize,
    effect: usize,
    excluded: u32,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    if error_index.is_null() || !error_index.is_aligned() {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    let Some(shape) = diagnostic_shape(series, lag_order, intercept, 0) else {
        return INVALID_INPUT;
    };
    if fitted_rows <= shape.predictors()
        || fitted_rows > MAX_ROWS - lag_order
        || effect >= series
        || excluded == 0
        || excluded >> series != 0
        || excluded & (1 << effect) != 0
        || evidence_len != shape.evidence_len()
        || output_len != GRANGER_WIDTH
        || !valid_buffers(evidence, output)
    {
        return INVALID_INPUT;
    }
    let raw = unsafe { slice::from_raw_parts(evidence, evidence_len) };
    let Some(evidence) = Evidence::parse(raw, shape) else {
        return INVALID_INPUT;
    };
    let result = block_test(evidence, shape, fitted_rows, effect, excluded, check);
    unsafe { publish_result(result, output, output_len, error_index) }
}

/// Writes one reduced-form response matrix and forecast error covariance for
/// each horizon from zero through the declared limit. Matrices are row-major.
///
/// # Safety
/// The pointer and cancellation contracts are those of `arboris_var_granger_block`.
#[no_mangle]
pub unsafe extern "C" fn arboris_var_irf(
    evidence: *const f64,
    evidence_len: usize,
    series: usize,
    lag_order: usize,
    intercept: i32,
    horizon: usize,
    limit: f64,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    if error_index.is_null() || !error_index.is_aligned() {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    let Some(shape) = diagnostic_shape(series, lag_order, intercept, horizon) else {
        return INVALID_INPUT;
    };
    if !limit.is_finite()
        || limit < 1.0
        || evidence_len != shape.evidence_len()
        || output_len != (horizon + 1) * 2 * series * series
        || !valid_buffers(evidence, output)
    {
        return INVALID_INPUT;
    }
    let raw = unsafe { slice::from_raw_parts(evidence, evidence_len) };
    let Some(evidence) = Evidence::parse(raw, shape) else {
        return INVALID_INPUT;
    };
    let result = impulse_responses(evidence, shape, limit, check);
    unsafe { publish_result(result, output, output_len, error_index) }
}
