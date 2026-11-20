use std::slice;

use super::{
    checkpoint, disjoint_regions, optimizer, region, seasonal, supported, CancellationCheck,
    Coefficients, Failure, Fit, FitBuffers, ResidualSummary, Sample, State, StateSpace, Trend,
    CHECK_EVERY, MAX_DYNAMICS, MAX_HORIZON, MAX_STATE,
};

#[cfg(test)]
#[path = "regression_tests.rs"]
mod tests;

const MAX_REGRESSORS: usize = 4;
const MAX_DESIGN: usize = MAX_REGRESSORS + 1;
const MAX_OBSERVATIONS: usize = 10_000;
const MAX_ORDER: usize = 3;
const MAX_ORDER_SUM: usize = 4;
const MAX_DESIGN_CONDITION: f64 = 1e10;
type PredictorRow = [f64; MAX_REGRESSORS];
type LinearRow = [f64; MAX_DESIGN];
type Upper = [LinearRow; MAX_DESIGN];

#[derive(Clone, Copy)]
struct Regressors<'a> {
    train: &'a [f64],
    future: &'a [f64],
    columns: usize,
}

impl<'a> Regressors<'a> {
    fn new(train: &'a [f64], future: &'a [f64], columns: usize) -> Self {
        Self {
            train,
            future,
            columns,
        }
    }

    fn shape(self, rows: usize, horizon: usize) -> bool {
        (1..=MAX_REGRESSORS).contains(&self.columns)
            && rows.checked_mul(self.columns) == Some(self.train.len())
            && horizon.checked_mul(self.columns) == Some(self.future.len())
    }
}

#[derive(Clone, Copy, Default)]
struct Scaling {
    center: f64,
    magnitude: f64,
}

impl Scaling {
    fn normalize(self, value: f64) -> f64 {
        let centered = value - self.center;
        if centered.is_infinite() {
            value / self.magnitude - self.center / self.magnitude
        } else {
            centered / self.magnitude
        }
    }

    fn coefficient(self, normalized: f64, scale: f64) -> Result<f64, Failure> {
        if normalized == 0.0 {
            return Ok(0.0);
        }
        let ratio = scale / self.magnitude;
        let result = if ratio.is_normal() {
            normalized * ratio
        } else {
            let rescaled = normalized * scale;
            if rescaled.is_finite() && rescaled != 0.0 {
                rescaled / self.magnitude
            } else {
                (normalized / self.magnitude) * scale
            }
        };
        if !result.is_finite() || result == 0.0 {
            return Err(Failure::Numeric);
        }
        Ok(result)
    }
}

struct Design<'a> {
    train: Vec<PredictorRow>,
    future: &'a [f64],
    scaling: [Scaling; MAX_REGRESSORS],
    columns: usize,
}

impl<'a> Design<'a> {
    fn new(sample: &Sample, matrices: Regressors<'a>, horizon: usize) -> Result<Self, Failure> {
        if !matrices.shape(sample.values.len(), horizon) {
            return Err(Failure::Input(usize::MAX));
        }
        let columns = matrices.columns;
        let mut minimum = [f64::INFINITY; MAX_REGRESSORS];
        let mut maximum = [f64::NEG_INFINITY; MAX_REGRESSORS];
        for (row, values) in matrices.train.chunks_exact(columns).enumerate() {
            if row % CHECK_EVERY == 0 {
                checkpoint(sample.check)?;
            }
            for (column, &value) in values.iter().enumerate() {
                if !value.is_finite() {
                    return Err(Failure::InvalidTrainingRegressor(row * columns + column));
                }
                minimum[column] = minimum[column].min(value);
                maximum[column] = maximum[column].max(value);
            }
        }
        if let Some(index) = matrices.future.iter().position(|value| !value.is_finite()) {
            return Err(Failure::InvalidFutureRegressor(index));
        }
        let mut scaling = [Scaling::default(); MAX_REGRESSORS];
        for j in 0..columns {
            let center = if sample.difference > 0 || sample.trend == Trend::Mean {
                minimum[j].midpoint(maximum[j])
            } else {
                0.0
            };
            let magnitude = (minimum[j] - center).abs().max((maximum[j] - center).abs());
            if !magnitude.is_finite() {
                return Err(Failure::Numeric);
            }
            if magnitude == 0.0 {
                return Err(Failure::Degenerate);
            }
            scaling[j] = Scaling { center, magnitude };
        }
        let mut train = Vec::with_capacity(sample.values.len());
        for (index, raw) in matrices.train.chunks_exact(columns).enumerate() {
            if index % CHECK_EVERY == 0 {
                checkpoint(sample.check)?;
            }
            let mut row = [0.0; MAX_REGRESSORS];
            for (j, &value) in raw.iter().enumerate() {
                row[j] = scaling[j].normalize(value);
            }
            train.push(row);
        }
        Ok(Self {
            train,
            future: matrices.future,
            scaling,
            columns,
        })
    }

    fn future_row(&self, step: usize) -> Result<PredictorRow, Failure> {
        let mut row = [0.0; MAX_REGRESSORS];
        let start = step * self.columns;
        for (j, &value) in self.future[start..start + self.columns].iter().enumerate() {
            row[j] = self.scaling[j].normalize(value);
            if !row[j].is_finite() {
                return Err(Failure::Numeric);
            }
        }
        Ok(row)
    }
}

#[derive(Default)]
struct Qr {
    upper: Upper,
    transformed_outcome: LinearRow,
    norms: LinearRow,
    residual_energy: f64,
    log_determinant: f64,
}

fn solve_upper(upper: &Upper, mut rhs: LinearRow, columns: usize) -> LinearRow {
    for i in (0..columns).rev() {
        let mut numerator = rhs[i];
        for j in i + 1..columns {
            numerator = (-upper[i][j]).mul_add(rhs[j], numerator);
        }
        rhs[i] = numerator / upper[i][i];
    }
    rhs
}

impl Qr {
    fn add(&mut self, mut outcome: f64, mut row: LinearRow, log_variance: f64, columns: usize) {
        for (norm, &value) in self.norms[..columns].iter_mut().zip(&row) {
            *norm = norm.hypot(value);
        }
        for pivot in 0..columns {
            let incoming = row[pivot];
            if incoming == 0.0 {
                continue;
            }
            let diagonal = self.upper[pivot][pivot];
            let radius = diagonal.hypot(incoming);
            let cosine = diagonal / radius;
            let sine = incoming / radius;
            self.upper[pivot][pivot] = radius;
            for j in pivot + 1..columns {
                let previous = self.upper[pivot][j];
                self.upper[pivot][j] = cosine.mul_add(previous, sine * row[j]);
                row[j] = (-sine).mul_add(previous, cosine * row[j]);
            }
            let previous = self.transformed_outcome[pivot];
            self.transformed_outcome[pivot] = cosine.mul_add(previous, sine * outcome);
            outcome = (-sine).mul_add(previous, cosine * outcome);
        }
        self.residual_energy += outcome * outcome;
        self.log_determinant += log_variance;
    }

    fn check_rank(&self, columns: usize) -> Result<(), Failure> {
        let mut normalized = [[0.0; MAX_DESIGN]; MAX_DESIGN];
        let mut norm: f64 = 0.0;
        for i in 0..columns {
            let mut row_norm = 0.0;
            for j in i..columns {
                let magnitude = self.norms[j];
                if !magnitude.is_finite() || magnitude <= 0.0 {
                    return Err(Failure::Degenerate);
                }
                let value = self.upper[i][j] / magnitude;
                if !value.is_finite() {
                    return Err(Failure::Numeric);
                }
                normalized[i][j] = value;
                row_norm += value.abs();
            }
            if !normalized[i][i].is_finite() || normalized[i][i] < 1.0 / MAX_DESIGN_CONDITION {
                return Err(Failure::Degenerate);
            }
            norm = norm.max(row_norm);
        }
        let mut inverse_row_sums = [0.0; MAX_DESIGN];
        for j in 0..columns {
            let mut unit = [0.0; MAX_DESIGN];
            unit[j] = 1.0;
            let column = solve_upper(&normalized, unit, columns);
            for (sum, value) in inverse_row_sums[..columns].iter_mut().zip(column) {
                if !value.is_finite() {
                    return Err(Failure::Degenerate);
                }
                *sum += value.abs();
            }
        }
        let inverse_norm = inverse_row_sums.into_iter().fold(0.0, f64::max);
        let condition = norm * inverse_norm;
        if !condition.is_finite() || condition > MAX_DESIGN_CONDITION {
            return Err(Failure::Degenerate);
        }
        Ok(())
    }

    fn profile(&self, columns: usize, observations: usize) -> Result<(LinearRow, f64), Failure> {
        self.check_rank(columns)?;
        let variance = self.residual_energy / observations as f64;
        if !variance.is_finite() || !self.log_determinant.is_finite() {
            return Err(Failure::Numeric);
        }
        if variance.sqrt() <= 32.0 * f64::EPSILON {
            return Err(Failure::Degenerate);
        }
        let beta = solve_upper(&self.upper, self.transformed_outcome, columns);
        if !beta[..columns].iter().all(|value| value.is_finite()) {
            return Err(Failure::Numeric);
        }
        Ok((beta, variance))
    }
}

struct Profile<const N: usize> {
    state: State<N, MAX_REGRESSORS>,
    beta: LinearRow,
    variance: f64,
    log_determinant: f64,
}

struct Model<const N: usize> {
    system: StateSpace<N>,
    ar: Coefficients,
    ma: Coefficients,
    seasonal: [f64; 2],
}

struct RegressionFit {
    fit: Fit,
    slopes: PredictorRow,
    seasonal: [f64; 2],
}

struct Regression<'a> {
    sample: Sample,
    design: Design<'a>,
    deterministic: usize,
}

impl<'a> Regression<'a> {
    fn profile<const N: usize>(&self, system: &StateSpace<N>) -> Result<Profile<N>, Failure> {
        let mut qr = Qr::default();
        let start = self.deterministic;
        let columns = start + self.design.columns;
        let state = self.sample.filter_regression(
            system,
            |time| self.design.train[time],
            |_, outcome, deterministic, regressors, log_variance| {
                let mut row = [0.0; MAX_DESIGN];
                row[0] = deterministic;
                row[start..columns].copy_from_slice(&regressors[..self.design.columns]);
                qr.add(outcome, row, log_variance, columns);
            },
        )?;
        let (beta, variance) = qr.profile(columns, self.sample.effective())?;
        Ok(Profile {
            state,
            beta,
            variance,
            log_determinant: qr.log_determinant,
        })
    }

    fn objective<const N: usize>(&self, system: &StateSpace<N>) -> Result<f64, Failure> {
        let fit = self.profile(system)?;
        Ok(0.5 * (fit.variance.ln() + fit.log_determinant / self.sample.effective() as f64))
    }

    fn finish<const N: usize>(
        &self,
        model: Model<N>,
        iterations: usize,
        horizon: usize,
    ) -> Result<RegressionFit, Failure> {
        let Profile {
            mut state,
            beta,
            variance,
            log_determinant,
        } = self.profile(&model.system)?;
        let columns = self.design.columns;
        let trend_beta = if self.deterministic != 0 {
            beta[0]
        } else {
            0.0
        };
        let coefficients = &beta[self.deterministic..self.deterministic + columns];
        let standardized_deviation = variance.sqrt();
        let deviation = self.sample.scale * standardized_deviation;
        let variance = deviation * deviation;
        if !variance.is_normal() {
            return Err(Failure::Numeric);
        }
        let effective = self.sample.effective();
        let log_likelihood = -0.5
            * (effective as f64 * (std::f64::consts::TAU.ln() + 1.0 + variance.ln())
                + log_determinant);
        let mut summary = ResidualSummary::new();
        self.sample.filter_regression(
            &model.system,
            |time| self.design.train[time],
            |time, outcome, design, regressors, _| {
                let mut innovation = (-trend_beta).mul_add(design, outcome);
                for (&coefficient, value) in coefficients.iter().zip(regressors) {
                    innovation = (-coefficient).mul_add(value, innovation);
                }
                summary.add(time, innovation / standardized_deviation);
            },
        )?;
        let residuals = summary.finish(effective)?;
        let mut forecast = Vec::with_capacity(horizon);
        for step in 0..horizon {
            model.system.predict(&mut state);
            let time = self.sample.values.len() - self.sample.origin + step;
            let mut location =
                trend_beta.mul_add(self.sample.trend.at(time) - state.design[0], state.level[0]);
            let future = self.design.future_row(step)?;
            for (i, &coefficient) in coefficients.iter().enumerate() {
                location = coefficient.mul_add(future[i] - state.regressors[i][0], location);
            }
            let mean = self.sample.scale.mul_add(location, self.sample.offset);
            let forecast_deviation = deviation * state.covariance[0][0].sqrt();
            let forecast_variance = forecast_deviation * forecast_deviation;
            if !mean.is_finite() || !forecast_variance.is_normal() {
                return Err(Failure::Numeric);
            }
            forecast.push([mean, forecast_variance]);
        }
        let mut slopes = [0.0; MAX_REGRESSORS];
        let mut intercept = trend_beta;
        for (i, &coefficient) in coefficients.iter().enumerate() {
            let scaling = self.design.scaling[i];
            slopes[i] = scaling.coefficient(coefficient, self.sample.scale)?;
            if self.sample.trend == Trend::Mean {
                intercept = (-coefficient).mul_add(scaling.center / scaling.magnitude, intercept);
            }
        }
        let deterministic = match self.sample.trend {
            Trend::None => 0.0,
            Trend::Mean => self.sample.scale.mul_add(intercept, self.sample.offset),
            Trend::Drift => self.sample.scale * trend_beta,
        };
        if !deterministic.is_finite() || !log_likelihood.is_finite() {
            return Err(Failure::Numeric);
        }
        checkpoint(self.sample.check)?;
        Ok(RegressionFit {
            fit: Fit {
                ar: model.ar,
                ma: model.ma,
                observed: self.sample.observed,
                effective,
                iterations,
                deterministic,
                variance,
                log_likelihood,
                forecast,
                residuals,
            },
            slopes,
            seasonal: model.seasonal,
        })
    }
}

fn fit_regression<const N: usize>(
    sample: Sample,
    regressors: Regressors<'_>,
    horizon: usize,
    dimensions: usize,
    (width, setup_work): (usize, usize),
    starts: &[optimizer::Coordinates],
    model: impl Fn(&optimizer::Coordinates) -> Model<N>,
) -> Result<RegressionFit, Failure> {
    let design = Design::new(&sample, regressors, horizon)?;
    let deterministic = usize::from(sample.trend != Trend::None);
    let columns = deterministic + design.columns;
    if sample.effective() < 2 * dimensions + columns + 2 {
        return Err(Failure::Insufficient);
    }
    let work = sample.values.len()
        * (width * width + width * (MAX_REGRESSORS + 1) + columns * columns)
        + setup_work;
    let regression = Regression {
        sample,
        design,
        deterministic,
    };
    let (point, iterations) = if dimensions == 0 {
        ([0.0; MAX_DYNAMICS], 0)
    } else {
        if !optimizer::enough_budget(work, dimensions) {
            return Err(Failure::Unsupported);
        }
        optimizer::minimize(starts, dimensions, work, |point| {
            regression.objective(&model(point).system)
        })?
    };
    regression.finish(model(&point), iterations, horizon)
}

fn supports_arimax(count: usize, [p, d, q]: [usize; 3], trend: Trend) -> bool {
    count <= MAX_OBSERVATIONS
        && p <= MAX_ORDER
        && q <= MAX_ORDER
        && p + q <= MAX_ORDER_SUM
        && supported(p, d, q, trend)
}

fn fit_arimax(
    values: &[f64],
    regressors: Regressors<'_>,
    order: [usize; 3],
    trend: Trend,
    horizon: usize,
    check: CancellationCheck,
) -> Result<RegressionFit, Failure> {
    if !supports_arimax(values.len(), order, trend) {
        return Err(Failure::Unsupported);
    }
    if !(1..=MAX_HORIZON).contains(&horizon) {
        return Err(Failure::Input(usize::MAX));
    }
    let [p, d, q] = order;
    let sample = Sample::new(values, p + q, d, trend, check)?;
    let width = d + p.max(q + 1);
    let (starts, count) = optimizer::ordinary_starts(p, q);
    fit_regression(
        sample,
        regressors,
        horizon,
        p + q,
        (width, 0),
        &starts[..count],
        |point| {
            let (ar, ma) = optimizer::dynamics(point, p, q);
            Model {
                system: StateSpace::<MAX_STATE>::new(&ar[..p], &ma[..q], d),
                ar,
                ma,
                seasonal: [0.0; 2],
            }
        },
    )
}

fn fit_sarimax(
    values: &[f64],
    regressors: Regressors<'_>,
    order: seasonal::Order,
    trend: Trend,
    horizon: usize,
    check: CancellationCheck,
) -> Result<RegressionFit, Failure> {
    if !order.supported(values.len(), trend) {
        return Err(Failure::Unsupported);
    }
    if !(1..=MAX_HORIZON).contains(&horizon) {
        return Err(Failure::Input(usize::MAX));
    }
    let sample = seasonal::prepare_sample(values, order, trend, check)?;
    let (starts, count) = order.starts();
    fit_regression(
        sample,
        regressors,
        horizon,
        order.dimensions(),
        (order.width(), order.optimizer_setup_work()),
        &starts[..count],
        |point| {
            let factors = seasonal::Factors::new(point, order);
            Model {
                system: factors.system(order),
                ar: factors.ar,
                ma: factors.ma,
                seasonal: [factors.seasonal_ar, factors.seasonal_ma],
            }
        },
    )
}

struct RawRegressors {
    train: (*const f64, usize),
    future: (*const f64, usize),
    columns: usize,
}

unsafe fn run_ffi(
    values: *const f64,
    rows: usize,
    x: RawRegressors,
    horizon: usize,
    [p, q, seasonal_ar, seasonal_ma]: [usize; 4],
    output: FitBuffers,
    fit: impl FnOnce(&[f64], Regressors<'_>) -> Result<RegressionFit, Failure>,
) -> i32 {
    if !(1..=MAX_REGRESSORS).contains(&x.columns)
        || rows.checked_mul(x.columns) != Some(x.train.1)
        || horizon.checked_mul(x.columns) != Some(x.future.1)
    {
        return 1;
    }
    let coefficients = p + q + seasonal_ar + seasonal_ma + x.columns;
    let Some([y, estimates, forecast, residuals, error]) =
        output.regions(values, rows, coefficients, horizon)
    else {
        return 1;
    };
    let [Some(train), Some(future)] =
        [region(x.train.0, x.train.1), region(x.future.0, x.future.1)]
    else {
        return 1;
    };
    if !disjoint_regions([y, train, future, estimates, forecast, residuals, error]) {
        return 1;
    }
    unsafe { output.error_index.write(usize::MAX) };
    let values = unsafe { slice::from_raw_parts(values, rows) };
    let train = unsafe { slice::from_raw_parts(x.train.0, x.train.1) };
    let future = unsafe { slice::from_raw_parts(x.future.0, x.future.1) };
    match fit(values, Regressors::new(train, future, x.columns)) {
        Ok(result) => {
            let seasonal = &result.seasonal[1 - seasonal_ar..1 + seasonal_ma];
            let count = seasonal.len() + x.columns;
            let mut extra = [0.0; 2 + MAX_REGRESSORS];
            extra[..seasonal.len()].copy_from_slice(seasonal);
            extra[seasonal.len()..count].copy_from_slice(&result.slopes[..x.columns]);
            unsafe { output.write(&result.fit, p, q, &extra[..count]) }
        }
        Err(failure) => unsafe { output.failure(failure) },
    }
}

/// Fits ARIMA errors with training and future regressors in row-major order.
/// Source-unit regression coefficients follow the ordinary AR and MA factors.
/// Statuses 9 and 10 identify flattened invalid training/future design cells.
///
/// # Safety
/// All pointers must refer to the declared valid buffers for the entire call.
/// Inputs must be initialized and the callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_arimax_fit(
    values: *const f64,
    rows: usize,
    train_x: *const f64,
    train_len: usize,
    future_x: *const f64,
    future_len: usize,
    columns: usize,
    p: usize,
    d: usize,
    q: usize,
    trend: i32,
    horizon: usize,
    fit: *mut f64,
    fit_len: usize,
    forecasts: *mut f64,
    forecast_len: usize,
    residuals: *mut f64,
    residual_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    let Some(trend) = Trend::from_code(trend) else {
        return 6;
    };
    let order = [p, d, q];
    if !supports_arimax(rows, order, trend) {
        return 6;
    }
    let regressors = RawRegressors {
        train: (train_x, train_len),
        future: (future_x, future_len),
        columns,
    };
    let output = FitBuffers {
        fit: (fit, fit_len),
        forecast: (forecasts, forecast_len),
        residuals: (residuals, residual_len),
        error_index,
    };
    unsafe {
        run_ffi(
            values,
            rows,
            regressors,
            horizon,
            [p, q, 0, 0],
            output,
            |y, x| fit_arimax(y, x, order, trend, horizon, check),
        )
    }
}

/// Fits multiplicative SARIMA errors. Regression coefficients follow the
/// ordinary and seasonal AR and MA factors in the seasonal fit header.
///
/// # Safety
/// All pointers must refer to the declared valid buffers for the entire call.
/// Inputs must be initialized and the callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_sarimax_fit(
    values: *const f64,
    rows: usize,
    train_x: *const f64,
    train_len: usize,
    future_x: *const f64,
    future_len: usize,
    columns: usize,
    p: usize,
    d: usize,
    q: usize,
    seasonal_ar: usize,
    seasonal_difference: usize,
    seasonal_ma: usize,
    period: usize,
    trend: i32,
    horizon: usize,
    fit: *mut f64,
    fit_len: usize,
    forecasts: *mut f64,
    forecast_len: usize,
    residuals: *mut f64,
    residual_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    let Some(trend) = Trend::from_code(trend) else {
        return 6;
    };
    let order = seasonal::Order::new(
        [p, d, q],
        [seasonal_ar, seasonal_difference, seasonal_ma, period],
    );
    if !order.supported(rows, trend) {
        return 6;
    }
    let regressors = RawRegressors {
        train: (train_x, train_len),
        future: (future_x, future_len),
        columns,
    };
    let output = FitBuffers {
        fit: (fit, fit_len),
        forecast: (forecasts, forecast_len),
        residuals: (residuals, residual_len),
        error_index,
    };
    unsafe {
        run_ffi(
            values,
            rows,
            regressors,
            horizon,
            [p, q, seasonal_ar, seasonal_ma],
            output,
            |y, x| fit_sarimax(y, x, order, trend, horizon, check),
        )
    }
}
