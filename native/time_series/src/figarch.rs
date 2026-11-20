use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

use super::volatility::{checkpoint, region, Check, Failure};

const MAX_ROWS: usize = 20_000;
const MAX_HORIZON: usize = 200;
const MAX_HOLDOUT: usize = 200;
const MIN_TRUNCATION: usize = 32;
const MAX_TRUNCATION: usize = 2048;
const WORK_LIMIT: usize = 40_000_000;
const SUMMARY: usize = 9;

#[derive(Default)]
struct Sum {
    total: f64,
    correction: f64,
}

impl Sum {
    fn add(&mut self, term: f64) {
        let next = self.total + term;
        self.correction += if self.total.abs() >= term.abs() {
            (self.total - next) + term
        } else {
            (term - next) + self.total
        };
        self.total = next;
    }

    fn value(&self) -> f64 {
        self.total + self.correction
    }
}

struct Parameters {
    omega: f64,
    phi: f64,
    d: f64,
    beta: f64,
}

impl Parameters {
    fn valid(&self) -> bool {
        self.omega.is_finite()
            && self.omega > 0.0
            && (0.05..=0.95).contains(&self.d)
            && (0.0..=0.5 * (1.0 - self.d)).contains(&self.phi)
            && (0.0..=self.d + self.phi).contains(&self.beta)
    }

    fn weights(&self, truncation: usize) -> Result<Vec<f64>, Failure> {
        let mut weights = Vec::with_capacity(truncation);
        let mut delta = self.d;
        let mut lambda = self.d + self.phi - self.beta;
        weights.push(lambda);
        for lag in 2..=truncation {
            let ratio = (lag as f64 - 1.0 - self.d) / lag as f64;
            lambda = self.beta * lambda + (ratio - self.phi) * delta;
            if !lambda.is_finite() || lambda < 0.0 {
                return Err(Failure::Numeric);
            }
            weights.push(lambda);
            delta *= ratio;
        }
        Ok(weights)
    }
}

fn backcast(training_squared: &[f64]) -> f64 {
    let prefix = &training_squared[..training_squared.len().min(75)];
    let scale = prefix.iter().copied().fold(0.0_f64, f64::max);
    if scale == 0.0 {
        return 0.0;
    }
    let (mut values, mut weights) = (Sum::default(), Sum::default());
    let mut weight = 1.0;
    for value in prefix {
        values.add(weight * (value / scale));
        weights.add(weight);
        weight *= 0.94;
    }
    (values.value() / weights.value()) * scale
}

fn variance(
    history: &[f64],
    weights: &[f64],
    initial: f64,
    intercept: f64,
) -> Result<f64, Failure> {
    let available = history.len().min(weights.len());
    let mut result = Sum::default();
    result.add(intercept);
    for (&coefficient, &square) in weights[..available].iter().zip(history.iter().rev()) {
        result.add(coefficient * square);
    }
    for coefficient in &weights[available..] {
        result.add(coefficient * initial);
    }
    let value = result.value();
    if !value.is_finite() || value <= 0.0 {
        return Err(Failure::Numeric);
    }
    Ok(value)
}

struct Output {
    receipt: [f64; SUMMARY],
    weights: Vec<f64>,
    forecasts: [f64; MAX_HOLDOUT + MAX_HORIZON],
}

fn filter(
    values: &[f64],
    train: usize,
    horizon: usize,
    truncation: usize,
    parameters: &Parameters,
    check: Check,
) -> Result<Output, Failure> {
    let intercept = parameters.omega / (1.0 - parameters.beta);
    if !intercept.is_finite() || intercept <= 0.0 {
        return Err(Failure::Numeric);
    }
    let weights = parameters.weights(truncation)?;
    let mut mass = Sum::default();
    for &coefficient in &weights {
        mass.add(coefficient);
    }
    let retained = mass.value();
    if !(retained > 0.0 && retained < 1.0) {
        return Err(Failure::Numeric);
    }
    let mut squared = Vec::with_capacity(values.len() + horizon);
    for (row, &value) in values.iter().enumerate() {
        if row % 512 == 0 {
            checkpoint(check)?;
        }
        if !value.is_finite() {
            return Err(Failure::Input(row));
        }
        let square = value * value;
        if !square.is_finite() || (square == 0.0 && value != 0.0) {
            return Err(Failure::Numeric);
        }
        squared.push(square);
    }
    let initial = backcast(&squared[..train]);
    let mut forecasts = [0.0; MAX_HOLDOUT + MAX_HORIZON];
    let (mut train_loss, mut holdout_loss, mut holdout_mae) =
        (Sum::default(), Sum::default(), Sum::default());
    let (mut z_mean, mut z_squared) = (Sum::default(), Sum::default());
    let holdout = values.len() - train;
    let log_two_pi = std::f64::consts::TAU.ln();
    for (row, &value) in values.iter().enumerate() {
        if row % 32 == 0 {
            checkpoint(check)?;
        }
        let h = variance(&squared[..row], &weights, initial, intercept)?;
        let z = value / h.sqrt();
        let energy = z * z;
        let loss = 0.5 * (log_two_pi + h.ln() + energy);
        if !loss.is_finite() {
            return Err(Failure::Numeric);
        }
        if row < train {
            train_loss.add(loss);
            z_mean.add(z / train as f64);
            z_squared.add(energy / train as f64);
        } else {
            forecasts[row - train] = h;
            holdout_loss.add(loss / holdout as f64);
            holdout_mae.add((squared[row] - h).abs() / holdout as f64);
        }
    }
    for step in 0..horizon {
        checkpoint(check)?;
        let prediction = variance(&squared, &weights, initial, intercept)?;
        forecasts[holdout + step] = prediction;
        squared.push(prediction);
    }
    let receipt = [
        retained,
        1.0 - retained,
        initial,
        intercept,
        -train_loss.value(),
        holdout_loss.value(),
        holdout_mae.value(),
        z_mean.value(),
        z_squared.value().sqrt(),
    ];
    if !receipt.iter().all(|value| value.is_finite()) {
        return Err(Failure::Numeric);
    }
    checkpoint(check)?;
    Ok(Output {
        receipt,
        weights,
        forecasts,
    })
}

/// Filters a fixed-parameter Gaussian FIGARCH truncation and forecasts conditional variance.
///
/// # Safety
/// Pointers must refer to valid buffers for their declared lengths. Inputs must remain
/// unchanged for the call, and the optional callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_figarch_filter(
    values: *const f64,
    rows: usize,
    train: usize,
    horizon: usize,
    truncation: usize,
    omega: f64,
    phi: f64,
    d: f64,
    beta: f64,
    summary: *mut f64,
    summary_len: usize,
    weights: *mut f64,
    weights_len: usize,
    forecasts: *mut f64,
    forecasts_len: usize,
    error_row: *mut usize,
    check: Check,
) -> i32 {
    if rows > MAX_ROWS {
        return 6;
    }
    let parameters = Parameters {
        omega,
        phi,
        d,
        beta,
    };
    if train > rows
        || !(1..=MAX_HORIZON).contains(&horizon)
        || !(MIN_TRUNCATION..=MAX_TRUNCATION).contains(&truncation)
        || summary_len != SUMMARY
        || weights_len != truncation
        || forecasts_len != rows - train + horizon
        || !parameters.valid()
    {
        return 1;
    }
    if train < 2 {
        return 3;
    }
    if rows - train > MAX_HOLDOUT || rows + horizon > WORK_LIMIT / truncation {
        return 6;
    }
    let [Some(input), Some(fit_region), Some(weights_region), Some(forecast_region), Some(error)] = [
        region(values, rows),
        region(summary, summary_len),
        region(weights, weights_len),
        region(forecasts, forecasts_len),
        region(error_row, 1),
    ] else {
        return 1;
    };
    let mut regions = [input, fit_region, weights_region, forecast_region, error];
    regions.sort_unstable();
    if regions.windows(2).any(|pair| pair[0].1 > pair[1].0) {
        return 1;
    }
    unsafe { error_row.write(usize::MAX) };
    let result = catch_unwind(AssertUnwindSafe(|| {
        let input = unsafe { slice::from_raw_parts(values, rows) };
        filter(input, train, horizon, truncation, &parameters, check)
    }));
    match result {
        Ok(Ok(output)) => {
            unsafe { slice::from_raw_parts_mut(summary, SUMMARY) }.copy_from_slice(&output.receipt);
            unsafe { slice::from_raw_parts_mut(weights, weights_len) }
                .copy_from_slice(&output.weights);
            unsafe { slice::from_raw_parts_mut(forecasts, forecasts_len) }
                .copy_from_slice(&output.forecasts[..forecasts_len]);
            0
        }
        Ok(Err(Failure::Input(row))) => {
            unsafe { error_row.write(row) };
            1
        }
        Ok(Err(Failure::Numeric)) => 2,
        Ok(Err(Failure::Cancelled)) => 7,
        _ => 8,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dyadic_boundary_has_exact_first_weights_and_known_variance() {
        let parameters = Parameters {
            omega: 0.25,
            phi: 0.25,
            d: 0.5,
            beta: 0.75,
        };
        assert!(parameters.valid());
        let kernel = parameters.weights(32).unwrap();
        assert_eq!(kernel[..4], [0.0, 0.0, 0.03125, 0.046875]);
        assert_eq!(
            variance(&[4.0, 1.0, 1.0], &kernel, 0.0, 1.0).unwrap(),
            1.125
        );
    }
}
