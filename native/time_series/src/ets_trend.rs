use std::{ptr, slice};

const MAX_ROWS: usize = 100_000;
const MAX_HORIZON: usize = 200;
const CHECK_EVERY: usize = 512;
const FIT_LENGTH: usize = 7;
const LOWER_GAIN: f64 = 0.0001;
const UPPER_GAIN: f64 = 0.9999;

type Checkpoint = Option<extern "C" fn() -> i32>;

#[derive(Clone, Copy)]
struct Smoothing {
    alpha: f64,
    beta: f64,
    phi: f64,
}

#[derive(Clone, Copy, Default)]
struct State {
    level: f64,
    slope: f64,
}

impl State {
    fn predict(self, smoothing: Smoothing) -> f64 {
        smoothing.phi.mul_add(self.slope, self.level)
    }

    fn update(self, smoothing: Smoothing, predicted: f64, innovation: f64) -> Self {
        Self {
            level: smoothing.alpha.mul_add(innovation, predicted),
            slope: smoothing
                .beta
                .mul_add(innovation, smoothing.phi * self.slope),
        }
    }
}

struct Fit {
    summary: [f64; FIT_LENGTH],
    forecast: Vec<[f64; 2]>,
}

enum Failure {
    NonFinite(usize),
    Numeric,
    Degenerate,
    Cancelled,
}

fn checkpoint(check: Checkpoint) -> Result<(), Failure> {
    if check.is_some_and(|poll| poll() != 0) {
        return Err(Failure::Cancelled);
    }
    Ok(())
}

fn normalize(values: &[f64], check: Checkpoint) -> Result<(f64, f64), Failure> {
    let mut low = f64::INFINITY;
    let mut high = f64::NEG_INFINITY;
    for (index, &value) in values.iter().enumerate() {
        if index % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        if !value.is_finite() {
            return Err(Failure::NonFinite(index));
        }
        low = low.min(value);
        high = high.max(value);
    }
    if low == high {
        return Err(Failure::Degenerate);
    }
    let offset = low.midpoint(high);
    let scale = (high - offset).max(offset - low);
    Ok((offset, scale))
}

#[derive(Default)]
struct InitialQr {
    upper: [[f64; 3]; 2],
}

impl InitialQr {
    fn add(&mut self, mut row: [f64; 3]) {
        for (column, upper) in self.upper.iter_mut().enumerate() {
            let radius = upper[column].hypot(row[column]);
            if radius == 0.0 {
                continue;
            }
            let cosine = upper[column] / radius;
            let sine = row[column] / radius;
            upper[column] = radius;
            for (stored, live) in upper[column + 1..].iter_mut().zip(&mut row[column + 1..]) {
                let rotated = cosine.mul_add(*stored, sine * *live);
                *live = (-sine).mul_add(*stored, cosine * *live);
                *stored = rotated;
            }
        }
    }

    fn solve(self) -> Result<State, Failure> {
        let [[r00, r01, z0], [_, r11, z1]] = self.upper;
        let scale = r00.max(r01.abs()).max(r11);
        if r00.min(r11) <= 64.0 * f64::EPSILON * scale {
            return Err(Failure::Degenerate);
        }
        let slope = z1 / r11;
        let level = (-r01).mul_add(slope, z0) / r00;
        if !level.is_finite() || !slope.is_finite() {
            return Err(Failure::Numeric);
        }
        Ok(State { level, slope })
    }
}

fn fit_initial(
    values: &[f64],
    offset: f64,
    scale: f64,
    smoothing: Smoothing,
    check: Checkpoint,
) -> Result<State, Failure> {
    let mut zero = State::default();
    let mut sensitivity = [
        State {
            level: 1.0,
            slope: 0.0,
        },
        State {
            level: 0.0,
            slope: 1.0,
        },
    ];
    let mut qr = InitialQr::default();
    for (index, &value) in values.iter().enumerate() {
        if index % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let prediction = zero.predict(smoothing);
        let innovation = (value - offset) / scale - prediction;
        let design = sensitivity.map(|state| state.predict(smoothing));
        qr.add([design[0], design[1], innovation]);
        zero = zero.update(smoothing, prediction, innovation);
        for (state, derivative) in sensitivity.iter_mut().zip(design) {
            *state = state.update(smoothing, derivative, -derivative);
        }
    }
    qr.solve()
}

#[derive(Clone, Copy)]
struct Profile {
    initial: State,
    state: State,
    relative_deviation: f64,
    gradient: [f64; 2],
}

fn profile<const GRADIENT: bool>(
    values: &[f64],
    offset: f64,
    scale: f64,
    smoothing: Smoothing,
    check: Checkpoint,
) -> Result<Profile, Failure> {
    let initial = fit_initial(values, offset, scale, smoothing, check)?;
    let mut state = initial;
    let mut squared_innovations = 0.0;
    let mut derivatives = [State::default(); 2];
    let mut gradient = [0.0; 2];
    for (index, &value) in values.iter().enumerate() {
        if index % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let prediction = state.predict(smoothing);
        let innovation = (value - offset) / scale - prediction;
        squared_innovations = innovation.mul_add(innovation, squared_innovations);
        state = state.update(smoothing, prediction, innovation);
        if GRADIENT {
            for (derivative, sum) in derivatives.iter_mut().zip(&mut gradient) {
                let projection = derivative.predict(smoothing);
                *sum = (-innovation).mul_add(projection, *sum);
                *derivative = derivative.update(smoothing, projection, -projection);
            }
            derivatives[0].level += innovation;
            derivatives[1].slope += innovation;
        }
    }
    let relative_deviation = (squared_innovations / values.len() as f64).sqrt();
    if relative_deviation <= 128.0 * f64::EPSILON {
        return Err(Failure::Degenerate);
    }
    let gradient = gradient.map(|value| 2.0 * value / squared_innovations);
    if !relative_deviation.is_finite() || gradient.iter().any(|value| !value.is_finite()) {
        return Err(Failure::Numeric);
    }
    Ok(Profile {
        initial,
        state,
        relative_deviation,
        gradient,
    })
}

fn fit(
    values: &[f64],
    smoothing: Smoothing,
    horizon: usize,
    check: Checkpoint,
) -> Result<Fit, Failure> {
    let (offset, scale) = normalize(values, check)?;
    let result = profile::<false>(values, offset, scale, smoothing, check)?;
    forecast(
        result,
        offset,
        scale,
        smoothing,
        values.len(),
        horizon,
        check,
    )
}

fn forecast(
    profile: Profile,
    offset: f64,
    scale: f64,
    smoothing: Smoothing,
    rows: usize,
    horizon: usize,
    check: Checkpoint,
) -> Result<Fit, Failure> {
    let Profile {
        initial,
        state,
        relative_deviation,
        ..
    } = profile;
    let n = rows as f64;
    let variance = (scale * relative_deviation).powi(2);
    if !variance.is_normal() {
        return Err(Failure::Numeric);
    }
    let summary = [
        scale.mul_add(initial.level, offset),
        scale * initial.slope,
        scale.mul_add(state.level, offset),
        scale * state.slope,
        variance,
        -0.5 * n * (std::f64::consts::TAU.ln() + 1.0 + variance.ln()),
        n,
    ];
    if summary.iter().any(|value| !value.is_finite()) {
        return Err(Failure::Numeric);
    }

    let mut forecast = Vec::with_capacity(horizon);
    let mut damping = 1.0;
    let mut damped_steps = 0.0;
    let mut variance_multiplier = 1.0;
    for _ in 0..horizon {
        checkpoint(check)?;
        damping *= smoothing.phi;
        damped_steps += damping;
        let mean = scale.mul_add(damped_steps.mul_add(state.slope, state.level), offset);
        let forecast_variance = variance * variance_multiplier;
        if !mean.is_finite() || !forecast_variance.is_finite() {
            return Err(Failure::Numeric);
        }
        forecast.push([mean, forecast_variance]);
        let loading = smoothing.beta.mul_add(damped_steps, smoothing.alpha);
        variance_multiplier = loading.mul_add(loading, variance_multiplier);
    }
    checkpoint(check)?;
    Ok(Fit { summary, forecast })
}

fn region<T>(pointer: *const T, length: usize) -> Option<(usize, usize)> {
    let start = pointer as usize;
    let bytes = length.checked_mul(size_of::<T>())?;
    if pointer.is_null() || !pointer.is_aligned() || bytes > isize::MAX as usize {
        return None;
    }
    Some((start, start.checked_add(bytes)?))
}

fn valid_phi(phi: f64) -> bool {
    phi == 1.0 || (0.8..=0.98).contains(&phi)
}

fn valid_buffers(
    values: *const f64,
    rows: usize,
    estimates: *mut f64,
    estimates_len: usize,
    forecasts: *mut f64,
    forecasts_len: usize,
    error_index: *mut usize,
) -> bool {
    let [Some(input), Some(estimate), Some(forecast), Some(error)] = [
        region(values, rows),
        region(estimates, estimates_len),
        region(forecasts, forecasts_len),
        region(error_index, 1),
    ] else {
        return false;
    };
    let mut regions = [input, estimate, forecast, error];
    regions.sort_unstable();
    !regions.windows(2).any(|pair| pair[0].1 > pair[1].0)
}

/// # Safety
/// Buffers must be valid for their stated lengths. The callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_ets_trend_fit(
    values: *const f64,
    rows: usize,
    alpha: f64,
    beta: f64,
    phi: f64,
    horizon: usize,
    estimates: *mut f64,
    estimates_len: usize,
    forecasts: *mut f64,
    forecasts_len: usize,
    error_index: *mut usize,
    check: Checkpoint,
) -> i32 {
    if rows > MAX_ROWS
        || !(LOWER_GAIN..=UPPER_GAIN).contains(&alpha)
        || !(LOWER_GAIN..=alpha).contains(&beta)
        || !valid_phi(phi)
    {
        return 6;
    }
    if rows < 4 {
        return 3;
    }
    if !(1..=MAX_HORIZON).contains(&horizon)
        || estimates_len != FIT_LENGTH
        || forecasts_len != 2 * horizon
    {
        return 1;
    }
    if !valid_buffers(
        values,
        rows,
        estimates,
        estimates_len,
        forecasts,
        forecasts_len,
        error_index,
    ) {
        return 1;
    }

    let input = unsafe { slice::from_raw_parts(values, rows) };
    match fit(input, Smoothing { alpha, beta, phi }, horizon, check) {
        Ok(fit) => {
            unsafe {
                ptr::copy_nonoverlapping(fit.summary.as_ptr(), estimates, estimates_len);
                ptr::copy_nonoverlapping(fit.forecast.as_ptr().cast(), forecasts, forecasts_len);
            }
            0
        }
        Err(Failure::NonFinite(row)) => {
            unsafe { error_index.write(row) };
            1
        }
        Err(Failure::Numeric) => 2,
        Err(Failure::Degenerate) => 4,
        Err(Failure::Cancelled) => 7,
    }
}

#[cfg(test)]
mod tests;

mod auto;
