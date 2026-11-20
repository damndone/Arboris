use std::mem::{align_of, size_of};
use std::{ptr, slice};

#[path = "arima/optimizer.rs"]
mod optimizer;

#[path = "arima/regression.rs"]
mod regression;

#[path = "arima/seasonal.rs"]
mod seasonal;

#[path = "arima/whiteness.rs"]
mod whiteness;

#[cfg(test)]
#[path = "arima/tests.rs"]
mod tests;

const MAX_ORDER: usize = 5;
const MAX_DYNAMICS: usize = 6;
const MAX_DIFFERENCE: usize = 2;
const MAX_STATE: usize = MAX_ORDER + 1 + MAX_DIFFERENCE;
const MAX_OBSERVATIONS: usize = 20_000;
const MAX_HORIZON: usize = 200;
const FIT_HEADER: usize = 6;
const RESIDUAL_LAGS: usize = 12;
const RESIDUAL_LENGTH: usize = 2 + 2 * RESIDUAL_LAGS;
const CHECK_EVERY: usize = 512;
const STATIONARY_COVARIANCE_MAX_ITERATIONS: usize = 32;

type StateVector<const N: usize> = [f64; N];
type Matrix<const N: usize> = [StateVector<N>; N];
type Coefficients = [f64; MAX_ORDER];
type CancellationCheck = Option<extern "C" fn() -> i32>;

#[derive(Clone, Copy, PartialEq)]
enum Trend {
    None,
    Mean,
    Drift,
}

impl Trend {
    fn from_code(value: i32) -> Option<Self> {
        match value {
            0 => Some(Self::None),
            1 => Some(Self::Mean),
            2 => Some(Self::Drift),
            _ => None,
        }
    }

    fn at(self, time: usize) -> f64 {
        match self {
            Self::None => 0.0,
            Self::Mean => 1.0,
            Self::Drift => time as f64,
        }
    }
}

#[derive(Debug)]
enum Failure {
    Input(usize),
    Numeric,
    Insufficient,
    Degenerate,
    Convergence,
    Unsupported,
    Cancelled,
    MissingAnchor(usize),
    InvalidTrainingRegressor(usize),
    InvalidFutureRegressor(usize),
}

fn checkpoint(check: CancellationCheck) -> Result<(), Failure> {
    if check.is_some_and(|poll| poll() != 0) {
        return Err(Failure::Cancelled);
    }
    Ok(())
}

#[derive(Clone, Copy, Default)]
struct Row {
    terms: [(usize, f64); 7],
    len: usize,
}

impl Row {
    fn add(&mut self, column: usize, weight: f64) {
        if weight != 0.0 {
            self.terms[self.len] = (column, weight);
            self.len += 1;
        }
    }

    fn apply(&self, vector: &[f64]) -> f64 {
        self.terms[..self.len]
            .iter()
            .map(|&(column, weight)| weight * vector[column])
            .sum()
    }
}

struct State<const N: usize, const X: usize = 0> {
    level: StateVector<N>,
    design: StateVector<N>,
    regressors: [StateVector<N>; X],
    covariance: Matrix<N>,
}

impl<const N: usize, const X: usize> State<N, X> {
    fn zero_level_variance(&mut self, width: usize) {
        self.covariance[0] = [0.0; N];
        for row in &mut self.covariance[1..width] {
            row[0] = 0.0;
        }
    }

    fn apply_second_diffuse_anchor(
        &mut self,
        level: f64,
        regressors: [f64; X],
        span: usize,
        width: usize,
    ) {
        let weight = 1.0 / span as f64;
        self.level[1] += weight * (level - self.level[0]);
        self.level[0] = level;
        for (state, observed) in self.regressors.iter_mut().zip(regressors) {
            state[1] += weight * (observed - state[0]);
            state[0] = observed;
        }
        self.covariance[1][1] +=
            weight * (weight * self.covariance[0][0] - 2.0 * self.covariance[0][1]);
        for column in 2..width {
            let value = self.covariance[1][column] - weight * self.covariance[0][column];
            self.covariance[1][column] = value;
            self.covariance[column][1] = value;
        }
        self.zero_level_variance(width);
    }

    fn observe(
        &mut self,
        width: usize,
        level: f64,
        design: f64,
        regressors: [f64; X],
    ) -> Result<(f64, f64, [f64; X], f64), Failure> {
        let variance = self.covariance[0][0];
        if !variance.is_finite() || variance < 0.99 {
            return Err(Failure::Numeric);
        }
        let level_error = level - self.level[0];
        let design_error = design - self.design[0];
        let errors: [f64; X] = std::array::from_fn(|i| regressors[i] - self.regressors[i][0]);
        let deviation = variance.sqrt();
        for row in 1..width {
            let gain = self.covariance[row][0] / variance;
            self.level[row] += gain * level_error;
            self.design[row] += gain * design_error;
            for (state, error) in self.regressors.iter_mut().zip(errors) {
                state[row] += gain * error;
            }
            for column in row..width {
                let value = self.covariance[row][column] - gain * self.covariance[0][column];
                self.covariance[row][column] = value;
                self.covariance[column][row] = value;
            }
        }
        self.level[0] = level;
        self.design[0] = design;
        for (state, observed) in self.regressors.iter_mut().zip(regressors) {
            state[0] = observed;
        }
        self.zero_level_variance(width);
        Ok((
            level_error / deviation,
            design_error / deviation,
            errors.map(|error| error / deviation),
            variance.ln(),
        ))
    }
}

struct StateSpace<const N: usize> {
    rows: [Row; N],
    loading: StateVector<N>,
    width: usize,
    known_anchors: bool,
}

impl<const N: usize> StateSpace<N> {
    fn stationary_block(ar: &[f64], ma: &[f64], difference: usize) -> Self {
        let stationary_width = ar.len().max(ma.len() + 1);
        let width = difference + stationary_width;
        let mut rows = [Row::default(); N];
        for index in 0..stationary_width {
            let row = &mut rows[difference + index];
            row.add(difference, ar.get(index).copied().unwrap_or(0.0));
            if index + 1 < stationary_width {
                row.add(difference + index + 1, 1.0);
            }
        }
        let mut loading = [0.0; N];
        loading[difference] = 1.0;
        loading[difference + 1..difference + 1 + ma.len()].copy_from_slice(ma);
        Self {
            rows,
            loading,
            width,
            known_anchors: false,
        }
    }

    fn new(ar: &[f64], ma: &[f64], difference: usize) -> Self {
        let mut system = Self::stationary_block(ar, ma, difference);
        for index in 0..difference {
            system.rows[index] = system.rows[difference];
            for column in index..difference {
                system.rows[index].add(column, 1.0);
            }
            system.loading[index] = 1.0;
        }
        system
    }

    fn with_known_anchors(ar: &[f64], ma: &[f64], difference_tail: &[f64]) -> Self {
        let difference = difference_tail.len();
        let mut system = Self::stationary_block(ar, ma, difference);
        system.rows[0] = system.rows[difference];
        for (lag, &coefficient) in difference_tail.iter().enumerate() {
            system.rows[0].add(lag, -coefficient);
        }
        for index in 1..difference {
            system.rows[index].add(index - 1, 1.0);
        }
        system.loading[0] = 1.0;
        system.known_anchors = true;
        system
    }

    fn predict<const X: usize>(&self, state: &mut State<N, X>) {
        let level = state.level;
        let design = state.design;
        let mut left = [[0.0; N]; N];
        for (index, row) in self.rows[..self.width].iter().enumerate() {
            state.level[index] = row.apply(&level);
            state.design[index] = row.apply(&design);
            for &(column, weight) in &row.terms[..row.len] {
                for j in 0..self.width {
                    left[index][j] += weight * state.covariance[column][j];
                }
            }
        }
        for (i, left_row) in left[..self.width].iter().enumerate() {
            for j in i..self.width {
                let value = self.rows[j].apply(left_row) + self.loading[i] * self.loading[j];
                state.covariance[i][j] = value;
                state.covariance[j][i] = value;
            }
        }
        for regressor in &mut state.regressors {
            let previous = *regressor;
            for (index, row) in self.rows[..self.width].iter().enumerate() {
                regressor[index] = row.apply(&previous);
            }
        }
    }
}

fn product<const N: usize>(left: &Matrix<N>, right: &Matrix<N>, width: usize) -> Matrix<N> {
    let mut result = [[0.0; N]; N];
    for i in 0..width {
        for (k, row) in right[..width].iter().enumerate() {
            for j in 0..width {
                result[i][j] += left[i][k] * row[j];
            }
        }
    }
    result
}

fn stationary_covariance<const N: usize>(
    system: &StateSpace<N>,
    difference: usize,
) -> Result<Matrix<N>, Failure> {
    let width = system.width - difference;
    let mut transition = [[0.0; N]; N];
    let mut covariance = [[0.0; N]; N];
    for i in 0..width {
        let row = &system.rows[difference + i];
        for &(column, weight) in &row.terms[..row.len] {
            transition[i][column - difference] = weight;
        }
        for j in 0..width {
            covariance[i][j] = system.loading[difference + i] * system.loading[difference + j];
        }
    }
    for _ in 0..STATIONARY_COVARIANCE_MAX_ITERATIONS {
        let left = product(&transition, &covariance, width);
        let mut largest_added = 0.0_f64;
        let mut largest_covariance = 0.0_f64;
        for i in 0..width {
            for j in i..width {
                let addition: f64 = left[i][..width]
                    .iter()
                    .zip(&transition[j][..width])
                    .map(|(a, b)| a * b)
                    .sum();
                let value = covariance[i][j] + addition;
                if !value.is_finite() {
                    return Err(Failure::Numeric);
                }
                covariance[i][j] = value;
                covariance[j][i] = value;
                largest_added = largest_added.max(addition.abs());
                largest_covariance = largest_covariance.max(value.abs());
            }
        }
        if largest_added <= f64::EPSILON * largest_covariance {
            return Ok(covariance);
        }
        transition = product(&transition, &transition, width);
    }
    Err(Failure::Numeric)
}

#[derive(Default)]
struct Innovations {
    design_norm: f64,
    projected_level: f64,
    residual_energy: f64,
    log_determinant: f64,
}

impl Innovations {
    fn add(&mut self, level: f64, design: f64, log_variance: f64) {
        let mut residual = level;
        if design != 0.0 {
            let norm = self.design_norm.hypot(design);
            let cosine = self.design_norm / norm;
            let sine = design / norm;
            residual = (-sine).mul_add(self.projected_level, cosine * level);
            self.projected_level = cosine.mul_add(self.projected_level, sine * level);
            self.design_norm = norm;
        }
        self.residual_energy += residual * residual;
        self.log_determinant += log_variance;
    }

    fn profile(&self, n: usize, trend: Trend) -> Result<(f64, f64), Failure> {
        let variance = self.residual_energy / n as f64;
        if !variance.is_finite() || !self.log_determinant.is_finite() {
            return Err(Failure::Numeric);
        }
        if variance.sqrt() <= 32.0 * f64::EPSILON {
            return Err(Failure::Degenerate);
        }
        let coefficient = if trend == Trend::None {
            0.0
        } else {
            self.projected_level / self.design_norm
        };
        if !coefficient.is_finite() {
            return Err(Failure::Degenerate);
        }
        Ok((variance, coefficient))
    }
}

struct Likelihood<const N: usize> {
    state: State<N>,
    variance: f64,
    deterministic: f64,
    log_determinant: f64,
}

struct Sample {
    values: Vec<f64>,
    origin: usize,
    observed: usize,
    difference: usize,
    trend: Trend,
    offset: f64,
    scale: f64,
    check: CancellationCheck,
}

impl Sample {
    fn new(
        values: &[f64],
        dynamics: usize,
        difference: usize,
        trend: Trend,
        check: CancellationCheck,
    ) -> Result<Self, Failure> {
        let mut observed = 0;
        let mut origin = 0;
        let mut observed_parities = 0;
        let mut minimum = f64::INFINITY;
        let mut maximum = f64::NEG_INFINITY;
        for (index, &value) in values.iter().enumerate() {
            if index % CHECK_EVERY == 0 {
                checkpoint(check)?;
            }
            if value.is_nan() {
                continue;
            }
            if !value.is_finite() {
                return Err(Failure::Input(index));
            }
            if observed == 0 {
                origin = index;
            }
            observed += 1;
            observed_parities |= 1 << (index % 2);
            minimum = minimum.min(value);
            maximum = maximum.max(value);
        }
        if observed < difference + 2 * dynamics + usize::from(trend != Trend::None) + 2 {
            return Err(Failure::Insufficient);
        }
        if difference == 0 && dynamics > 0 && observed_parities != 3 {
            return Err(Failure::Degenerate);
        }
        let offset = if difference != 0 || trend == Trend::Mean {
            values[origin]
        } else {
            0.0
        };
        let range = (minimum - offset).abs().max((maximum - offset).abs());
        let scale = if range.is_finite() {
            range
        } else {
            minimum.abs().max(maximum.abs())
        };
        if scale == 0.0 {
            return Err(Failure::Degenerate);
        }
        let mut normalized = Vec::with_capacity(values.len());
        for (index, &value) in values.iter().enumerate() {
            if index % CHECK_EVERY == 0 {
                checkpoint(check)?;
            }
            let centered = value - offset;
            normalized.push(if centered.is_infinite() {
                value / scale - offset / scale
            } else {
                centered / scale
            });
        }
        Ok(Self {
            values: normalized,
            origin,
            observed,
            difference,
            trend,
            offset,
            scale,
            check,
        })
    }

    fn effective(&self) -> usize {
        self.observed - self.difference
    }

    fn filter<const N: usize>(
        &self,
        system: &StateSpace<N>,
        mut visit: impl FnMut(usize, f64, f64, f64),
    ) -> Result<State<N>, Failure> {
        self.filter_regression(
            system,
            |_| [],
            |time, level, design, [], log_variance| {
                visit(time, level, design, log_variance);
            },
        )
    }

    fn filter_regression<const N: usize, const X: usize>(
        &self,
        system: &StateSpace<N>,
        regressors_at: impl Fn(usize) -> [f64; X],
        mut visit: impl FnMut(usize, f64, f64, [f64; X], f64),
    ) -> Result<State<N, X>, Failure> {
        let stationary = stationary_covariance(system, self.difference)?;
        let mut state = State {
            level: [0.0; N],
            design: [0.0; N],
            regressors: [[0.0; N]; X],
            covariance: [[0.0; N]; N],
        };
        let d = self.difference;
        let stationary_width = system.width - d;
        for (i, row) in stationary[..stationary_width].iter().enumerate() {
            state.covariance[d + i][d..system.width].copy_from_slice(&row[..stationary_width]);
        }
        let (start, mut anchors) = if system.known_anchors {
            for index in 0..d {
                let time = d - 1 - index;
                state.level[index] = self.values[time];
                state.design[index] = self.trend.at(time);
                for (channel, value) in state.regressors.iter_mut().zip(regressors_at(time)) {
                    channel[index] = value;
                }
            }
            (d, d)
        } else {
            (self.origin, 0)
        };
        for (position, &value) in self.values[start..].iter().enumerate() {
            let time = start - self.origin + position;
            if position % CHECK_EVERY == 0 {
                checkpoint(self.check)?;
            }
            if time > 0 {
                system.predict(&mut state);
            }
            if value.is_nan() {
                continue;
            }
            let regressors = regressors_at(start + position);
            if anchors < d {
                if anchors == 0 {
                    state.level[0] = value;
                    for (channel, value) in state.regressors.iter_mut().zip(regressors) {
                        channel[0] = value;
                    }
                } else {
                    state.apply_second_diffuse_anchor(value, regressors, time, system.width);
                }
                anchors += 1;
                continue;
            }
            let (level, design, regressors, log_variance) =
                state.observe(system.width, value, self.trend.at(time), regressors)?;
            visit(time, level, design, regressors, log_variance);
        }
        Ok(state)
    }

    fn likelihood<const N: usize>(&self, system: &StateSpace<N>) -> Result<Likelihood<N>, Failure> {
        let mut innovations = Innovations::default();
        let state = self.filter(system, |_, level, design, log_variance| {
            innovations.add(level, design, log_variance);
        })?;
        let (variance, deterministic) = innovations.profile(self.effective(), self.trend)?;
        Ok(Likelihood {
            state,
            variance,
            deterministic,
            log_determinant: innovations.log_determinant,
        })
    }

    fn objective<const N: usize>(&self, system: &StateSpace<N>) -> Result<f64, Failure> {
        let fit = self.likelihood(system)?;
        Ok(0.5 * (fit.variance.ln() + fit.log_determinant / self.effective() as f64))
    }
}

#[derive(Clone, Copy, Default)]
struct LagCorrelation {
    count: usize,
    previous_mean: f64,
    current_mean: f64,
    previous_energy: f64,
    current_energy: f64,
    cross: f64,
}

impl LagCorrelation {
    fn add(&mut self, previous: f64, current: f64) {
        self.count += 1;
        let previous_error = previous - self.previous_mean;
        let current_error = current - self.current_mean;
        self.previous_mean += previous_error / self.count as f64;
        self.current_mean += current_error / self.count as f64;
        self.previous_energy += previous_error * (previous - self.previous_mean);
        self.current_energy += current_error * (current - self.current_mean);
        self.cross += previous_error * (current - self.current_mean);
    }

    fn coefficient(&self) -> f64 {
        if self.count < 3 || self.previous_energy <= 0.0 || self.current_energy <= 0.0 {
            return f64::NAN;
        }
        (self.cross / (self.previous_energy.sqrt() * self.current_energy.sqrt())).clamp(-1.0, 1.0)
    }
}

struct ResidualSummary {
    history: [(usize, f64); RESIDUAL_LAGS],
    pairs: [LagCorrelation; RESIDUAL_LAGS],
    sum: f64,
    squares: f64,
}

impl ResidualSummary {
    fn new() -> Self {
        Self {
            history: [(usize::MAX, 0.0); RESIDUAL_LAGS],
            pairs: [LagCorrelation::default(); RESIDUAL_LAGS],
            sum: 0.0,
            squares: 0.0,
        }
    }

    fn add(&mut self, time: usize, current: f64) {
        self.sum += current;
        self.squares += current * current;
        for (index, pair) in self.pairs[..time.min(RESIDUAL_LAGS)].iter_mut().enumerate() {
            let previous = time - index - 1;
            let (seen, value) = self.history[previous % RESIDUAL_LAGS];
            if seen == previous {
                pair.add(value, current);
            }
        }
        self.history[time % RESIDUAL_LAGS] = (time, current);
    }

    fn finish(self, count: usize) -> Result<[f64; RESIDUAL_LENGTH], Failure> {
        let n = count as f64;
        let mut result = [0.0; RESIDUAL_LENGTH];
        result[0] = self.sum / n;
        result[1] = (self.squares / n).sqrt();
        if !result[0].is_finite() || !result[1].is_finite() {
            return Err(Failure::Numeric);
        }
        for (row, pair) in result[2..].chunks_exact_mut(2).zip(self.pairs) {
            row.copy_from_slice(&[pair.coefficient(), pair.count as f64]);
        }
        Ok(result)
    }
}

fn residual_summary<const N: usize>(
    sample: &Sample,
    system: &StateSpace<N>,
    deterministic: f64,
    deviation: f64,
    mut whiteness: Option<&mut whiteness::Summary>,
) -> Result<[f64; RESIDUAL_LENGTH], Failure> {
    let mut summary = ResidualSummary::new();
    sample.filter(system, |time, level, design, _| {
        let current = (-deterministic).mul_add(design, level) / deviation;
        summary.add(time, current);
        if let Some(diagnostic) = whiteness.as_deref_mut() {
            diagnostic.add(current);
        }
    })?;
    if let Some(diagnostic) = whiteness {
        diagnostic.finish(
            &summary.pairs,
            sample.effective(),
            sample.observed != sample.values.len(),
        );
    }
    summary.finish(sample.effective())
}

struct Fit {
    ar: Coefficients,
    ma: Coefficients,
    observed: usize,
    effective: usize,
    iterations: usize,
    deterministic: f64,
    variance: f64,
    log_likelihood: f64,
    forecast: Vec<[f64; 2]>,
    residuals: [f64; RESIDUAL_LENGTH],
}

fn supported(p: usize, d: usize, q: usize, trend: Trend) -> bool {
    p <= MAX_ORDER
        && d <= MAX_DIFFERENCE
        && q <= MAX_ORDER
        && p + q <= MAX_DYNAMICS
        && matches!(
            (d, trend),
            (_, Trend::None) | (0, Trend::Mean) | (1, Trend::Drift)
        )
}

fn fit_arima(
    values: &[f64],
    p: usize,
    d: usize,
    q: usize,
    trend: Trend,
    horizon: usize,
    check: CancellationCheck,
) -> Result<Fit, Failure> {
    fit_arima_with_whiteness(values, [p, d, q], trend, horizon, check, None)
}

fn fit_arima_with_whiteness(
    values: &[f64],
    [p, d, q]: [usize; 3],
    trend: Trend,
    horizon: usize,
    check: CancellationCheck,
    whiteness: Option<&mut whiteness::Summary>,
) -> Result<Fit, Failure> {
    if !supported(p, d, q, trend) || values.len() > MAX_OBSERVATIONS {
        return Err(Failure::Unsupported);
    }
    if horizon == 0 || horizon > MAX_HORIZON {
        return Err(Failure::Input(usize::MAX));
    }
    let sample = Sample::new(values, p + q, d, trend, check)?;
    let (ar, ma, iterations) = optimizer::fit(&sample, p, q)?;
    let system = StateSpace::<MAX_STATE>::new(&ar[..p], &ma[..q], d);
    finish_fit(&sample, &system, ar, ma, iterations, horizon, whiteness)
}

fn finish_fit<const N: usize>(
    sample: &Sample,
    system: &StateSpace<N>,
    ar: Coefficients,
    ma: Coefficients,
    iterations: usize,
    horizon: usize,
    whiteness: Option<&mut whiteness::Summary>,
) -> Result<Fit, Failure> {
    let Likelihood {
        mut state,
        variance,
        deterministic,
        log_determinant,
    } = sample.likelihood(system)?;
    let residuals = residual_summary(sample, system, deterministic, variance.sqrt(), whiteness)?;
    let deviation = sample.scale * variance.sqrt();
    let variance = deviation * deviation;
    if !variance.is_normal() {
        return Err(Failure::Numeric);
    }
    let effective = sample.effective();
    let log_likelihood = -0.5
        * (effective as f64 * (std::f64::consts::TAU.ln() + 1.0 + variance.ln()) + log_determinant);
    let mut forecast = Vec::with_capacity(horizon);
    for step in 0..horizon {
        system.predict(&mut state);
        let time = sample.values.len() - sample.origin + step;
        let location =
            deterministic.mul_add(sample.trend.at(time) - state.design[0], state.level[0]);
        let mean = sample.scale.mul_add(location, sample.offset);
        let forecast_deviation = deviation * state.covariance[0][0].sqrt();
        let forecast_variance = forecast_deviation * forecast_deviation;
        if !mean.is_finite() || !forecast_variance.is_normal() {
            return Err(Failure::Numeric);
        }
        forecast.push([mean, forecast_variance]);
    }
    let deterministic = match sample.trend {
        Trend::None => 0.0,
        Trend::Mean => sample.scale.mul_add(deterministic, sample.offset),
        Trend::Drift => sample.scale * deterministic,
    };
    if !deterministic.is_finite() || !log_likelihood.is_finite() {
        return Err(Failure::Numeric);
    }
    checkpoint(sample.check)?;
    Ok(Fit {
        ar,
        ma,
        observed: sample.observed,
        effective,
        iterations,
        deterministic,
        variance,
        log_likelihood,
        forecast,
        residuals,
    })
}

fn region<T>(pointer: *const T, len: usize) -> Option<(usize, usize)> {
    let start = pointer as usize;
    let bytes = len.checked_mul(size_of::<T>())?;
    if start == 0 || start % align_of::<T>() != 0 || bytes > isize::MAX as usize {
        return None;
    }
    Some((start, start.checked_add(bytes)?))
}

fn disjoint_regions<const K: usize>(mut regions: [(usize, usize); K]) -> bool {
    regions.sort_unstable();
    regions.windows(2).all(|pair| pair[0].1 <= pair[1].0)
}

struct FitBuffers {
    fit: (*mut f64, usize),
    forecast: (*mut f64, usize),
    residuals: (*mut f64, usize),
    error_index: *mut usize,
}

impl FitBuffers {
    fn valid(
        &self,
        values: *const f64,
        count: usize,
        coefficient_count: usize,
        horizon: usize,
    ) -> bool {
        self.regions(values, count, coefficient_count, horizon)
            .is_some_and(disjoint_regions)
    }

    fn regions(
        &self,
        values: *const f64,
        count: usize,
        coefficient_count: usize,
        horizon: usize,
    ) -> Option<[(usize, usize); 5]> {
        if count == 0
            || !(1..=MAX_HORIZON).contains(&horizon)
            || self.fit.1 != FIT_HEADER + coefficient_count
            || self.forecast.1 != 2 * horizon
            || self.residuals.1 != RESIDUAL_LENGTH
        {
            return None;
        }
        let [Some(input), Some(fit), Some(forecast), Some(residuals), Some(error)] = [
            region(values, count),
            region(self.fit.0, self.fit.1),
            region(self.forecast.0, self.forecast.1),
            region(self.residuals.0, self.residuals.1),
            region(self.error_index, 1),
        ] else {
            return None;
        };
        Some([input, fit, forecast, residuals, error])
    }

    unsafe fn write(&self, estimate: &Fit, p: usize, q: usize, seasonal: &[f64]) -> i32 {
        let header = [
            estimate.variance,
            estimate.log_likelihood,
            estimate.deterministic,
            estimate.observed as f64,
            estimate.effective as f64,
            estimate.iterations as f64,
        ];
        let fit = self.fit.0;
        unsafe {
            ptr::copy_nonoverlapping(header.as_ptr(), fit, FIT_HEADER);
            ptr::copy_nonoverlapping(estimate.ar.as_ptr(), fit.add(FIT_HEADER), p);
            ptr::copy_nonoverlapping(estimate.ma.as_ptr(), fit.add(FIT_HEADER + p), q);
            ptr::copy_nonoverlapping(
                seasonal.as_ptr(),
                fit.add(FIT_HEADER + p + q),
                seasonal.len(),
            );
            ptr::copy_nonoverlapping(
                estimate.forecast.as_ptr().cast(),
                self.forecast.0,
                self.forecast.1,
            );
            ptr::copy_nonoverlapping(
                estimate.residuals.as_ptr(),
                self.residuals.0,
                self.residuals.1,
            );
        }
        0
    }

    unsafe fn failure(&self, failure: Failure) -> i32 {
        match failure {
            Failure::Input(index) => {
                unsafe { self.error_index.write(index) };
                1
            }
            Failure::Numeric => 2,
            Failure::Insufficient => 3,
            Failure::Degenerate => 4,
            Failure::Convergence => 5,
            Failure::Unsupported => 6,
            Failure::Cancelled => 7,
            Failure::MissingAnchor(index) => {
                unsafe { self.error_index.write(index) };
                8
            }
            Failure::InvalidTrainingRegressor(index) => {
                unsafe { self.error_index.write(index) };
                9
            }
            Failure::InvalidFutureRegressor(index) => {
                unsafe { self.error_index.write(index) };
                10
            }
        }
    }
}

/// Fit header: innovation variance, log likelihood, mean or drift, observed count,
/// effective count, optimizer iterations. AR and MA coefficients follow.
/// Forecast rows contain the original-scale mean and variance.
/// Residual summary contains mean and RMS followed by correlation and pair
/// count for each of 12 lags. Nonzero status leaves result buffers untouched.
///
/// # Safety
/// Nonnull pointers must reference valid memory for the supplied lengths, and
/// input values must be initialized. The optional callback must stay valid
/// and must not unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_arima_fit(
    values: *const f64,
    count: usize,
    p: usize,
    d: usize,
    q: usize,
    trend: i32,
    horizon: usize,
    fit: *mut f64,
    fit_len: usize,
    forecasts: *mut f64,
    forecasts_len: usize,
    residuals: *mut f64,
    residuals_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    let Some(trend) = Trend::from_code(trend) else {
        return 6;
    };
    if !supported(p, d, q, trend) || count > MAX_OBSERVATIONS {
        return 6;
    }
    let outputs = FitBuffers {
        fit: (fit, fit_len),
        forecast: (forecasts, forecasts_len),
        residuals: (residuals, residuals_len),
        error_index,
    };
    if !outputs.valid(values, count, p + q, horizon) {
        return 1;
    }
    unsafe { error_index.write(usize::MAX) };
    let values = unsafe { slice::from_raw_parts(values, count) };
    match fit_arima(values, p, d, q, trend, horizon, check) {
        Ok(estimate) => unsafe { outputs.write(&estimate, p, q, &[]) },
        Err(failure) => unsafe { outputs.failure(failure) },
    }
}
