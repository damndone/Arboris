use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

use super::risk::latest_covariance;
use super::{
    residual_cash_weight, sum, INVALID_ARGUMENT, MAX_ASSETS, MAX_RISK_WINDOW, NUMERICAL, PANIC,
    RETURN, TIME_ORDER,
};

pub(super) const BPS: usize = 10_000;
pub(super) const SUMMARY: usize = 10;
const DEGENERATE: i32 = 9;
const NONCONVERGENCE: i32 = 10;
pub(super) const CANCELLED: i32 = 11;
const RANK_RTOL: f64 = 1e-10;
const EIGEN_TOL: f64 = 1e-15;
const KKT_TOL: f64 = 1e-9;
const PRIMAL_TOL: f64 = 1e-12;
const MAX_EIGEN_SWEEPS: usize = 64;
const MAX_ITERATIONS: usize = 1024;
pub(super) const NO_ROW: usize = usize::MAX;

pub(super) type Check = Option<extern "C" fn() -> i32>;
type Vector = [f64; MAX_ASSETS];

pub(super) fn checkpoint(check: Check) -> Result<(), i32> {
    if check.is_some_and(|poll| poll() != 0) {
        return Err(CANCELLED);
    }
    Ok(())
}

#[derive(Clone, Copy)]
struct Spectrum {
    minimum: f64,
    threshold: f64,
    rank: usize,
}

fn spectrum(covariance: &[f64], width: usize, check: Check) -> Result<Spectrum, i32> {
    let mut matrix = covariance.to_vec();
    for _ in 0..MAX_EIGEN_SWEEPS {
        checkpoint(check)?;
        let mut rotated = false;
        for i in 0..width {
            for j in i + 1..width {
                let cross = matrix[i * width + j];
                if cross.abs() <= EIGEN_TOL {
                    continue;
                }
                rotated = true;
                let ii = i * width + i;
                let jj = j * width + j;
                let theta = (matrix[jj] - matrix[ii]) / (2.0 * cross);
                let tangent = theta.signum() / (theta.abs() + theta.hypot(1.0));
                let cosine = 1.0 / tangent.hypot(1.0);
                let sine = tangent * cosine;
                matrix[ii] -= tangent * cross;
                matrix[jj] += tangent * cross;
                matrix[i * width + j] = 0.0;
                matrix[j * width + i] = 0.0;
                for row in 0..width {
                    if row == i || row == j {
                        continue;
                    }
                    let a = matrix[row * width + i];
                    let b = matrix[row * width + j];
                    let first = cosine * a - sine * b;
                    let second = sine * a + cosine * b;
                    matrix[row * width + i] = first;
                    matrix[i * width + row] = first;
                    matrix[row * width + j] = second;
                    matrix[j * width + row] = second;
                }
            }
        }
        if !rotated {
            let diagonal = (0..width).map(|i| matrix[i * width + i]);
            let minimum = diagonal.clone().fold(f64::INFINITY, f64::min);
            let maximum = diagonal.clone().fold(f64::NEG_INFINITY, f64::max);
            if !diagonal.clone().all(f64::is_finite) {
                return Err(NUMERICAL);
            }
            if maximum <= 0.0 {
                return Err(DEGENERATE);
            }
            let threshold = RANK_RTOL * maximum;
            if minimum < -threshold {
                return Err(NUMERICAL);
            }
            let rank = diagonal.filter(|&value| value > threshold).count();
            return Ok(Spectrum {
                minimum,
                threshold,
                rank,
            });
        }
    }
    Err(NONCONVERGENCE)
}

fn equality_solution(covariance: &[f64], support: &[bool], width: usize) -> Result<Vector, i32> {
    let mut columns = [0; MAX_ASSETS];
    let mut size = 0;
    for (i, included) in support.iter().enumerate() {
        if *included {
            columns[size] = i;
            size += 1;
        }
    }
    let mut lower = [[0.0; MAX_ASSETS]; MAX_ASSETS];
    let mut solution = [0.0; MAX_ASSETS];
    for i in 0..size {
        for j in 0..=i {
            let value = covariance[columns[i] * width + columns[j]]
                - sum((0..j).map(|k| lower[i][k] * lower[j][k]));
            if i == j && (!value.is_finite() || value <= 0.0) {
                return Err(NUMERICAL);
            }
            lower[i][j] = if i == j {
                value.sqrt()
            } else {
                value / lower[j][j]
            };
        }
        solution[i] = (1.0 - sum((0..i).map(|j| lower[i][j] * solution[j]))) / lower[i][i];
    }
    for i in (0..size).rev() {
        solution[i] =
            (solution[i] - sum((i + 1..size).map(|j| lower[j][i] * solution[j]))) / lower[i][i];
    }
    let total = sum(solution[..size].iter().copied());
    if !total.is_finite() || total <= 0.0 {
        return Err(NUMERICAL);
    }
    let mut target = [0.0; MAX_ASSETS];
    for i in 0..size {
        target[columns[i]] = solution[i] / total;
    }
    if !target[..width].iter().all(|weight| weight.is_finite()) {
        return Err(NUMERICAL);
    }
    Ok(target)
}

fn gradient(matrix: &[f64], width: usize, weights: &Vector) -> Vector {
    let mut result = [0.0; MAX_ASSETS];
    for (value, row) in result.iter_mut().zip(matrix.chunks_exact(width)) {
        *value = sum(row
            .iter()
            .zip(weights)
            .map(|(covariance, weight)| covariance * weight));
    }
    result
}

struct Solution {
    weights: Vector,
    objective: f64,
    iterations: usize,
    kkt: f64,
    sum_error: f64,
}

fn active_set(
    covariance: &[f64],
    width: usize,
    iterations: usize,
    check: Check,
) -> Result<Solution, i32> {
    let mut support = [true; MAX_ASSETS];
    let mut weights = [0.0; MAX_ASSETS];
    weights[..width].fill(1.0 / width as f64);
    for iteration in 1..=iterations {
        checkpoint(check)?;
        let target = equality_solution(covariance, &support[..width], width)?;
        let mut blocker = None;
        let mut step = 1.0;
        for i in 0..width {
            if support[i] && target[i] < 0.0 {
                let boundary = weights[i] / (weights[i] - target[i]);
                if blocker.is_none() || boundary < step {
                    step = boundary;
                    blocker = Some(i);
                }
            }
        }
        if let Some(i) = blocker {
            for j in 0..width {
                let value = weights[j] + step * (target[j] - weights[j]);
                if !value.is_finite() || value < -PRIMAL_TOL {
                    return Err(NUMERICAL);
                }
                weights[j] = value.max(0.0);
            }
            weights[i] = 0.0;
            support[i] = false;
            let total = sum(weights[..width].iter().copied());
            if !total.is_finite() || total <= 0.0 {
                return Err(NUMERICAL);
            }
            for weight in &mut weights[..width] {
                *weight /= total;
            }
            continue;
        }
        weights = target;
        let sum_error = (sum(weights[..width].iter().copied()) - 1.0).abs();
        if sum_error > PRIMAL_TOL
            || !weights[..width]
                .iter()
                .all(|weight| (0.0..=1.0).contains(weight))
        {
            return Err(NUMERICAL);
        }
        let gradient = gradient(covariance, width, &weights);
        let objective = sum(weights[..width]
            .iter()
            .zip(gradient)
            .map(|(weight, value)| weight * value));
        if !objective.is_finite() || objective <= 0.0 {
            return Err(NUMERICAL);
        }
        let mut kkt = 0.0_f64;
        let mut entering = None;
        let mut most_negative = -KKT_TOL;
        for i in 0..width {
            let reduced = gradient[i] - objective;
            let residual = if weights[i] > 0.0 {
                reduced.abs()
            } else {
                (-reduced).max(0.0)
            };
            kkt = kkt.max(residual);
            if !support[i] && reduced < most_negative {
                most_negative = reduced;
                entering = Some(i);
            }
        }
        if kkt <= KKT_TOL {
            return Ok(Solution {
                weights,
                objective,
                iterations: iteration,
                kkt,
                sum_error,
            });
        }
        let Some(index) = entering else {
            return Err(NONCONVERGENCE);
        };
        support[index] = true;
    }
    Err(NONCONVERGENCE)
}

#[derive(Default)]
pub(super) struct Funding {
    pub(super) cash: f64,
    pub(super) adjustment: f64,
}

fn exact_overweight(weights: &[f64]) -> bool {
    // Error-free partials keep the sign when ordinary compensation cancels.
    let mut partials = [0.0_f64; MAX_ASSETS + 1];
    let mut used = 0;
    for mut term in [1.0]
        .into_iter()
        .chain(weights.iter().map(|weight| -weight))
    {
        let mut kept = 0;
        for index in 0..used {
            let mut prior = partials[index];
            if term.abs() < prior.abs() {
                std::mem::swap(&mut term, &mut prior);
            }
            let rounded = term + prior;
            let residual = prior - (rounded - term);
            if residual != 0.0 {
                partials[kept] = residual;
                kept += 1;
            }
            term = rounded;
        }
        if term != 0.0 {
            partials[kept] = term;
            kept += 1;
        }
        used = kept;
    }
    partials[..used].last().is_some_and(|value| *value < 0.0)
}

pub(super) fn fund_weights(weights: &mut [f64]) -> Result<Funding, i32> {
    if !weights.iter().all(|weight| (0.0..=1.0).contains(weight)) {
        return Err(NONCONVERGENCE);
    }
    let residual = residual_cash_weight(weights);
    if residual.abs() > PRIMAL_TOL {
        return Err(NONCONVERGENCE);
    }
    if residual == 0.0 && !exact_overweight(weights) {
        return Ok(Funding::default());
    }
    let mut largest = 0;
    for i in 1..weights.len() {
        if weights[i] > weights[largest] {
            largest = i;
        }
    }
    let original = weights[largest];
    let remaining = sum([1.0].into_iter().chain(
        weights
            .iter()
            .enumerate()
            .filter(|(i, _)| *i != largest)
            .map(|(_, weight)| -weight),
    ));
    if !(0.0..=1.0).contains(&remaining) || remaining == 0.0 {
        return Err(NONCONVERGENCE);
    }
    weights[largest] = remaining;
    if residual_cash_weight(weights) < 0.0 || exact_overweight(weights) {
        weights[largest] = f64::from_bits(remaining.to_bits() - 1);
    }
    let cash = residual_cash_weight(weights);
    let adjustment = (weights[largest] - original).abs();
    if !(0.0..=f64::EPSILON).contains(&cash) || exact_overweight(weights) || adjustment > PRIMAL_TOL
    {
        return Err(NONCONVERGENCE);
    }
    Ok(Funding { cash, adjustment })
}

fn certify_funded(
    solution: &mut Solution,
    covariance: &[f64],
    width: usize,
) -> Result<Funding, i32> {
    let funding = fund_weights(&mut solution.weights[..width])?;
    let gradient = gradient(covariance, width, &solution.weights);
    let objective = sum(solution.weights[..width]
        .iter()
        .zip(gradient)
        .map(|(w, g)| w * g));
    if !objective.is_finite() || objective <= 0.0 {
        return Err(NONCONVERGENCE);
    }
    let kkt = solution.weights[..width]
        .iter()
        .zip(gradient)
        .map(|(w, g)| {
            let reduced = g - objective;
            if *w > 0.0 {
                reduced.abs()
            } else {
                (-reduced).max(0.0)
            }
        })
        .fold(0.0, f64::max);
    if kkt > KKT_TOL {
        return Err(NONCONVERGENCE);
    }
    solution.kkt = kkt;
    solution.objective = objective;
    solution.sum_error = funding.cash;
    Ok(funding)
}

pub(super) struct WindowFit {
    pub(super) funding: Funding,
    pub(super) sample_rank: usize,
    pub(super) objective_variance: f64,
    pub(super) kkt: f64,
}

fn allocation(
    times: &[i64],
    returns: &[f64],
    width: usize,
    shrinkage_bps: usize,
    output: &mut [f64],
    check: Check,
) -> Result<(), (i32, usize)> {
    let global = |code| (code, NO_ROW);
    for (row, values) in returns.chunks_exact(width).enumerate() {
        if row % 256 == 0 {
            checkpoint(check).map_err(global)?;
        }
        if row > 0 && times[row - 1] >= times[row] {
            return Err((TIME_ORDER, row));
        }
        if !values.iter().all(|value| value.is_finite()) {
            return Err((RETURN, row));
        }
    }
    solve_window(returns, width, shrinkage_bps, output, false, check).map(|_| ())
}

pub(super) fn solve_window(
    returns: &[f64],
    width: usize,
    shrinkage_bps: usize,
    output: &mut [f64],
    fund_for_replay: bool,
    check: Check,
) -> Result<WindowFit, (i32, usize)> {
    let global = |code| (code, NO_ROW);
    let (weights, matrices) = output.split_at_mut(width);
    let (raw, rest) = matrices.split_at_mut(width * width);
    let (target, evidence) = rest.split_at_mut(width * width);
    let window = returns.len() / width;
    latest_covariance(returns, width, window, raw).ok_or((NUMERICAL, window - 1))?;
    checkpoint(check).map_err(global)?;
    let scale = (0..width)
        .map(|i| raw[i * width + i])
        .fold(0.0_f64, f64::max);
    if scale <= 0.0 {
        return Err(global(DEGENERATE));
    }
    let mut q: Vec<_> = raw.iter().map(|value| value / scale).collect();
    if !q.iter().all(|value| value.is_finite()) {
        return Err(global(NUMERICAL));
    }
    let raw_spectrum = spectrum(&q, width, check).map_err(global)?;
    let effective = if shrinkage_bps == 0 {
        target.copy_from_slice(raw);
        raw_spectrum
    } else {
        let lambda = shrinkage_bps as f64 / BPS as f64;
        let trace_mean = sum((0..width).map(|i| q[i * width + i])) / width as f64;
        for i in 0..width {
            for j in 0..width {
                let index = i * width + j;
                let blended =
                    (1.0 - lambda) * q[index] + if i == j { lambda * trace_mean } else { 0.0 };
                target[index] = blended * scale;
                q[index] = target[index] / scale;
            }
        }
        if !q.iter().all(|value| value.is_finite()) {
            return Err(global(NUMERICAL));
        }
        spectrum(&q, width, check).map_err(global)?
    };
    if effective.rank != width {
        return Err(global(DEGENERATE));
    }
    let mut solution = active_set(&q, width, MAX_ITERATIONS, check).map_err(global)?;
    let funding = if fund_for_replay {
        certify_funded(&mut solution, &q, width).map_err(global)?
    } else {
        Funding::default()
    };
    let raw_variance_scaled =
        sum(raw
            .chunks_exact(width)
            .zip(solution.weights)
            .map(|(row, weight)| {
                weight
                    * sum(row
                        .iter()
                        .zip(solution.weights)
                        .map(|(value, w)| value / scale * w))
            }));
    if !raw_variance_scaled.is_finite() || raw_variance_scaled < -raw_spectrum.threshold {
        return Err(global(NUMERICAL));
    }
    let raw_variance = raw_variance_scaled.max(0.0) * scale;
    let objective_variance = solution.objective * scale;
    if !raw_variance.is_finite() || !objective_variance.is_finite() || objective_variance == 0.0 {
        return Err(global(NUMERICAL));
    }
    weights.copy_from_slice(&solution.weights[..width]);
    evidence.copy_from_slice(&[
        raw_variance,
        objective_variance,
        raw_spectrum.rank as f64,
        raw_spectrum.threshold,
        raw_spectrum.minimum,
        effective.minimum,
        scale,
        solution.iterations as f64,
        solution.kkt,
        solution.sum_error,
    ]);
    checkpoint(check).map_err(global)?;
    Ok(WindowFit {
        funding,
        sample_rank: raw_spectrum.rank,
        objective_variance,
        kkt: solution.kkt,
    })
}

pub(super) fn region<T>(pointer: *const T, length: usize) -> Option<(usize, usize)> {
    if pointer.is_null() || !pointer.is_aligned() {
        return None;
    }
    let start = pointer as usize;
    let bytes = length.checked_mul(std::mem::size_of::<T>())?;
    Some((start, start.checked_add(bytes)?))
}

/// Solves a long-only minimum-variance simplex on one completed, ordered window.
///
/// # Safety
/// The input and output pointers must refer to valid buffers for their declared
/// lengths. Inputs must remain unchanged and the callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_quant_min_variance(
    window: usize,
    width: usize,
    shrinkage_bps: usize,
    times: *const i64,
    times_len: usize,
    returns: *const f64,
    returns_len: usize,
    output: *mut f64,
    output_len: usize,
    error_row: *mut usize,
    check: Check,
) -> i32 {
    if !(2..=MAX_RISK_WINDOW).contains(&window)
        || !(2..=MAX_ASSETS).contains(&width)
        || shrinkage_bps > BPS
        || times_len != window
        || returns_len != window * width
        || output_len != width + 2 * width * width + SUMMARY
    {
        return INVALID_ARGUMENT;
    }
    let [Some(clock), Some(panel), Some(result), Some(error)] = [
        region(times, times_len),
        region(returns, returns_len),
        region(output, output_len),
        region(error_row, 1),
    ] else {
        return INVALID_ARGUMENT;
    };
    let mut regions = [clock, panel, result, error];
    regions.sort_unstable();
    if regions.windows(2).any(|pair| pair[0].1 > pair[1].0) {
        return INVALID_ARGUMENT;
    }
    unsafe { error_row.write(NO_ROW) };
    let result = catch_unwind(AssertUnwindSafe(|| unsafe {
        let mut candidate = vec![0.0; output_len];
        allocation(
            slice::from_raw_parts(times, times_len),
            slice::from_raw_parts(returns, returns_len),
            width,
            shrinkage_bps,
            &mut candidate,
            check,
        )?;
        Ok::<_, (i32, usize)>(candidate)
    }));
    match result {
        Ok(Ok(values)) => {
            unsafe { slice::from_raw_parts_mut(output, output_len) }.copy_from_slice(&values);
            0
        }
        Ok(Err((code, row))) => {
            unsafe { error_row.write(row) };
            code
        }
        Err(_) => PANIC,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exhausted_active_set_does_not_publish_candidate() {
        assert!(matches!(
            active_set(&[1.0, 2.0, 2.0, 5.0], 2, 1, None),
            Err(NONCONVERGENCE)
        ));
    }

    #[test]
    fn funding_rejects_material_deviation_and_nonoptimal_adjusted_weights() {
        let mut invalid = [0.2, 0.3];
        assert!(matches!(fund_weights(&mut invalid), Err(NONCONVERGENCE)));
        let mut rounded = [0.1; 10];
        let funding = fund_weights(&mut rounded).unwrap();
        assert!(funding.cash >= 0.0 && funding.cash <= f64::EPSILON);
        assert!(funding.adjustment > 0.0);
        assert_eq!(rounded[1..], [0.1; 9]);

        let mut weights = [0.0; MAX_ASSETS];
        weights[..2].fill(0.5);
        let mut solution = Solution {
            weights,
            objective: 0.0,
            iterations: 1,
            kkt: 0.0,
            sum_error: 0.0,
        };
        assert!(matches!(
            certify_funded(&mut solution, &[1.0, 0.0, 0.0, 0.25], 2),
            Err(NONCONVERGENCE)
        ));
    }

    #[test]
    fn funding_detects_an_overweight_hidden_by_legacy_cash_roundoff() {
        let sliver = 2.0_f64.powi(-54);
        let tiny = 2.0_f64.powi(-900);
        let mut weights = [sliver, tiny, 0.25, 0.25, 0.25, 0.25 - sliver];
        assert_eq!(residual_cash_weight(&weights), 0.0);
        let proof = fund_weights(&mut weights).unwrap();
        assert_eq!(weights[2], f64::from_bits(0.25_f64.to_bits() - 1));
        assert_eq!(weights[1], tiny);
        assert!(proof.cash > 0.0 && proof.adjustment > 0.0);
    }
}
