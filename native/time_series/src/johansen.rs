use std::{ptr, slice};

use super::{
    dot, factor_from_row, CancellationCheck, CANCELLED, CHECK_EVERY, INVALID_INPUT, MAX_ROWS,
    NON_FINITE_VALUE, NUMERIC_FAILURE, RANK_DEFICIENT,
};

const MIN_SERIES: usize = 3;
const MAX_SERIES: usize = 4;
const MAX_DIFFERENCE_LAGS: usize = 4;
const MAX_SWEEPS: usize = 32;
const CANONICAL_BOUNDARY: i32 = 7;
const ORTHOGONAL_TOLERANCE: f64 = 16.0 * f64::EPSILON;
const BOUNDARY_TOLERANCE: f64 = 64.0 * f64::EPSILON;

type Cross = [[f64; MAX_SERIES + 1]; MAX_SERIES];

#[derive(Clone, Copy)]
struct Shape {
    rows: usize,
    series: usize,
    difference_lags: usize,
}

impl Shape {
    fn levels_order(self) -> usize {
        self.difference_lags + 1
    }

    fn fitted_rows(self) -> usize {
        self.rows - self.levels_order()
    }

    fn controls(self) -> usize {
        self.series * self.difference_lags
    }

    fn level_width(self) -> usize {
        self.series + 1
    }

    fn width(self) -> usize {
        self.controls() + self.level_width() + self.series
    }
}

#[derive(Clone, Copy)]
struct Scaling {
    origin: f64,
    radius: f64,
}

enum Failure {
    Observation(usize),
    Rank(usize, usize),
    Numeric,
    Cancelled,
    Boundary,
}

fn checkpoint(check: CancellationCheck) -> Result<(), Failure> {
    super::checkpoint(check).map_err(|_| Failure::Cancelled)
}

fn scaling(
    values: &[f64],
    series: usize,
    check: CancellationCheck,
) -> Result<[Scaling; MAX_SERIES], Failure> {
    let mut minima = [f64::INFINITY; MAX_SERIES];
    let mut maxima = [f64::NEG_INFINITY; MAX_SERIES];
    for (index, &value) in values.iter().enumerate() {
        if index % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        if !value.is_finite() {
            return Err(Failure::Observation(index));
        }
        let column = index % series;
        minima[column] = minima[column].min(value);
        maxima[column] = maxima[column].max(value);
    }
    let mut scales = [Scaling {
        origin: 0.0,
        radius: 1.0,
    }; MAX_SERIES];
    for column in 0..series {
        let origin = minima[column] * 0.5 + maxima[column] * 0.5;
        let radius = (maxima[column] - origin).max(origin - minima[column]);
        scales[column] = Scaling {
            origin,
            radius: if radius > 0.0 { radius } else { 1.0 },
        };
    }
    Ok(scales)
}

fn scaled_difference(current: f64, previous: f64, radius: f64) -> f64 {
    let change = current - previous;
    if change.is_finite() {
        change / radius
    } else {
        current / radius - previous / radius
    }
}

fn design(
    values: &[f64],
    scales: &[Scaling; MAX_SERIES],
    shape: Shape,
    check: CancellationCheck,
) -> Result<Vec<Vec<f64>>, Failure> {
    let level_start = shape.controls();
    let response_start = level_start + shape.level_width();
    let mut columns = vec![vec![0.0; shape.fitted_rows()]; shape.width()];
    columns[level_start + shape.series].fill(1.0);
    for row in 0..shape.fitted_rows() {
        if row % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let time = row + shape.levels_order();
        for (column, &scale) in scales[..shape.series].iter().enumerate() {
            let level = |period| values[period * shape.series + column];
            for lag in 1..=shape.difference_lags {
                columns[(lag - 1) * shape.series + column][row] =
                    scaled_difference(level(time - lag), level(time - lag - 1), scale.radius);
            }
            columns[level_start + column][row] =
                scaled_difference(level(time - 1), scale.origin, scale.radius);
            columns[response_start + column][row] =
                scaled_difference(level(time), level(time - 1), scale.radius);
        }
    }
    Ok(columns)
}

fn factor_block(
    columns: &mut [Vec<f64>],
    width: usize,
    start: usize,
    stage: usize,
    minimum_norm: f64,
    check: CancellationCheck,
) -> Result<Vec<usize>, Failure> {
    let (permutation, _) =
        factor_from_row(columns, width, start, check).map_err(|failure| match failure {
            super::Failure::Rank(pivot) => Failure::Rank(stage, pivot),
            super::Failure::Cancelled => Failure::Cancelled,
            _ => Failure::Numeric,
        })?;
    if columns[0][start].abs() <= minimum_norm {
        return Err(Failure::Rank(stage, 0));
    }
    Ok(permutation)
}

fn canonical_cross(
    columns: &mut [Vec<f64>],
    shape: Shape,
    check: CancellationCheck,
) -> Result<Cross, Failure> {
    let controls = shape.controls();
    let level_width = shape.level_width();
    let mut response_norm = 0.0_f64;
    for column in &columns[controls + level_width..] {
        checkpoint(check)?;
        response_norm = response_norm.max(dot(column, column).sqrt());
    }
    let tolerance = shape.fitted_rows() as f64 * f64::EPSILON;
    factor_block(columns, controls, 0, 0, 0.0, check)?;
    let residuals = &mut columns[controls..];
    factor_block(
        residuals,
        level_width,
        controls,
        1,
        tolerance * (shape.fitted_rows() as f64).sqrt(),
        check,
    )?;

    let responses = &mut residuals[level_width..];
    let mut raw = [[0.0; MAX_SERIES + 1]; MAX_SERIES];
    for (destination, column) in raw.iter_mut().zip(responses.iter()) {
        destination[..level_width].copy_from_slice(&column[controls..controls + level_width]);
    }
    let permutation = factor_block(
        responses,
        shape.series,
        controls,
        2,
        tolerance * response_norm,
        check,
    )?;
    let mut cross: Cross = [[0.0; MAX_SERIES + 1]; MAX_SERIES];
    for (column, &original) in permutation.iter().enumerate() {
        for row in 0..level_width {
            let fitted = (0..column)
                .map(|previous| cross[previous][row] * responses[column][controls + previous])
                .sum::<f64>();
            let value = (raw[original][row] - fitted) / responses[column][controls + column];
            if !value.is_finite() {
                return Err(Failure::Numeric);
            }
            cross[column][row] = value;
        }
    }
    Ok(cross)
}

fn canonical_roots(mut cross: Cross, series: usize) -> Result<[f64; MAX_SERIES], Failure> {
    for _ in 0..MAX_SWEEPS {
        let mut changed = false;
        for left in 0..series - 1 {
            for right in left + 1..series {
                let a = dot(&cross[left], &cross[left]);
                let b = dot(&cross[right], &cross[right]);
                let overlap = dot(&cross[left], &cross[right]);
                if overlap.abs() <= ORTHOGONAL_TOLERANCE * a.sqrt() * b.sqrt() {
                    continue;
                }
                let gap = b - a;
                let twice = 2.0 * overlap;
                let tangent = twice / (gap.abs() + gap.hypot(twice)).copysign(gap);
                let cosine = (1.0 + tangent * tangent).sqrt().recip();
                let sine = tangent * cosine;
                for row in 0..=series {
                    let x = cross[left][row];
                    let y = cross[right][row];
                    cross[left][row] = cosine * x - sine * y;
                    cross[right][row] = sine * x + cosine * y;
                }
                changed = true;
            }
        }
        if !changed {
            let mut roots = cross.map(|column| dot(&column, &column));
            roots[..series].sort_by(|left, right| right.total_cmp(left));
            if roots[0] >= 1.0 - BOUNDARY_TOLERANCE {
                return Err(Failure::Boundary);
            }
            return Ok(roots);
        }
    }
    Err(Failure::Numeric)
}

fn compute(
    values: &[f64],
    shape: Shape,
    check: CancellationCheck,
) -> Result<[f64; 3 * MAX_SERIES], Failure> {
    let scales = scaling(values, shape.series, check)?;
    let mut columns = design(values, &scales, shape, check)?;
    let cross = canonical_cross(&mut columns, shape, check)?;
    let roots = canonical_roots(cross, shape.series)?;
    let mut output = [0.0; 3 * MAX_SERIES];
    let mut trace = 0.0;
    for rank in (0..shape.series).rev() {
        let maximum = -(shape.fitted_rows() as f64) * (-roots[rank]).ln_1p();
        trace += maximum;
        output[rank] = roots[rank];
        output[shape.series + rank] = trace;
        output[2 * shape.series + rank] = maximum;
    }
    checkpoint(check)?;
    Ok(output)
}

/// # Safety
/// Nonnull pointers must refer to valid, separate buffers of the stated lengths.
/// The row-major input must be initialized and unchanged throughout the call.
/// The optional callback must remain valid and may not unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_johansen_rank(
    values: *const f64,
    values_len: usize,
    training_rows: usize,
    series: usize,
    difference_lags: usize,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    if error_index.is_null() || !error_index.is_aligned() {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    if !(MIN_SERIES..=MAX_SERIES).contains(&series)
        || !(1..=MAX_DIFFERENCE_LAGS).contains(&difference_lags)
        || training_rows > MAX_ROWS
        || values_len != training_rows * series
        || output_len != 3 * series
        || values.is_null()
        || !values.is_aligned()
        || output.is_null()
        || !output.is_aligned()
    {
        return INVALID_INPUT;
    }
    let shape = Shape {
        rows: training_rows,
        series,
        difference_lags,
    };
    if training_rows <= shape.levels_order() + shape.width() {
        return INVALID_INPUT;
    }
    let input = unsafe { slice::from_raw_parts(values, values_len) };
    match compute(input, shape, check) {
        Ok(result) => {
            unsafe { ptr::copy_nonoverlapping(result.as_ptr(), output, output_len) };
            0
        }
        Err(Failure::Observation(index)) => {
            unsafe { error_index.write(index) };
            NON_FINITE_VALUE
        }
        Err(Failure::Rank(stage, pivot)) => {
            unsafe { error_index.write(16 * stage + pivot) };
            RANK_DEFICIENT
        }
        Err(Failure::Numeric) => NUMERIC_FAILURE,
        Err(Failure::Cancelled) => CANCELLED,
        Err(Failure::Boundary) => {
            unsafe { error_index.write(0) };
            CANONICAL_BOUNDARY
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tied_interior_roots_and_exact_zero_are_admissible() {
        let mut cross = [[0.0; MAX_SERIES + 1]; MAX_SERIES];
        cross[0][0] = 0.5;
        cross[1][1] = -0.5;
        cross[2][2] = 0.25;
        let Ok(roots) = canonical_roots(cross, 4) else {
            panic!("valid tied canonical roots");
        };
        assert_eq!(roots, [0.25, 0.25, 0.0625, 0.0]);
    }

    #[test]
    fn rotated_columns_match_two_nonzero_analytic_roots() {
        let mut cross = [[0.0; MAX_SERIES + 1]; MAX_SERIES];
        cross[0][0] = 0.5;
        cross[1][0] = 0.5;
        cross[1][1] = 0.5;
        let Ok(roots) = canonical_roots(cross, 3) else {
            panic!("valid canonical roots");
        };
        let gap = 5.0_f64.sqrt() / 4.0;
        assert!((roots[0] - (0.75 + gap) * 0.5).abs() < 2e-15);
        assert!((roots[1] - (0.75 - gap) * 0.5).abs() < 2e-15);
        assert_eq!(roots[2], 0.0);
    }
}
