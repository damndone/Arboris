use super::{
    checkpoint, finish_fit, optimizer, slice, CancellationCheck, Coefficients, Failure, Fit,
    FitBuffers, Sample, StateSpace, Trend, CHECK_EVERY, MAX_DIFFERENCE, MAX_DYNAMICS, MAX_HORIZON,
    STATIONARY_COVARIANCE_MAX_ITERATIONS,
};

#[cfg(test)]
#[path = "seasonal_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "period24_tests.rs"]
mod period24_tests;

const MAX_ORDINARY_ORDER: usize = 3;
const LEGACY_MAX_PERIOD: usize = 12;
const DAILY_PERIOD: usize = 24;
const MAX_LAG: usize = MAX_ORDINARY_ORDER + DAILY_PERIOD;
const MAX_INTEGRATION: usize = MAX_DIFFERENCE + DAILY_PERIOD;
pub(super) const MAX_SEASONAL_STATE: usize = 28;
const MAX_SEASONAL_OBSERVATIONS: usize = 2_000;
const MAX_SEASONAL_DYNAMICS: usize = 4;

#[derive(Clone, Copy)]
pub(super) struct Order {
    pub(super) p: usize,
    pub(super) d: usize,
    pub(super) q: usize,
    pub(super) seasonal_ar: usize,
    pub(super) seasonal_difference: usize,
    pub(super) seasonal_ma: usize,
    pub(super) period: usize,
}

impl Order {
    pub(super) const fn new(
        [p, d, q]: [usize; 3],
        [seasonal_ar, seasonal_difference, seasonal_ma, period]: [usize; 4],
    ) -> Self {
        Self {
            p,
            d,
            q,
            seasonal_ar,
            seasonal_difference,
            seasonal_ma,
            period,
        }
    }

    pub(super) fn dimensions(self) -> usize {
        self.p + self.q + self.seasonal_ar + self.seasonal_ma
    }

    fn integration(self) -> usize {
        self.d + self.seasonal_difference * self.period
    }

    fn ar_lags(self) -> usize {
        self.p + self.seasonal_ar * self.period
    }

    fn ma_lags(self) -> usize {
        self.q + self.seasonal_ma * self.period
    }

    fn stationary_width(self) -> usize {
        self.ar_lags().max(self.ma_lags() + 1)
    }

    pub(super) fn width(self) -> usize {
        self.integration() + self.stationary_width()
    }

    pub(super) fn optimizer_setup_work(self) -> usize {
        if self.period == DAILY_PERIOD {
            3 * STATIONARY_COVARIANCE_MAX_ITERATIONS * self.stationary_width().pow(3)
        } else {
            0
        }
    }

    pub(super) fn supported(self, count: usize, trend: Trend) -> bool {
        self.p <= MAX_ORDINARY_ORDER
            && self.q <= MAX_ORDINARY_ORDER
            && self.d <= MAX_DIFFERENCE
            && self.seasonal_ar <= 1
            && self.seasonal_difference <= 1
            && self.seasonal_ma <= 1
            && ((2..=LEGACY_MAX_PERIOD).contains(&self.period) || self.period == DAILY_PERIOD)
            && self.seasonal_ar + self.seasonal_difference + self.seasonal_ma > 0
            && self.dimensions() <= MAX_SEASONAL_DYNAMICS
            && self.width() <= MAX_SEASONAL_STATE
            && count <= MAX_SEASONAL_OBSERVATIONS
            && matches!(
                (self.d + self.seasonal_difference, trend),
                (_, Trend::None) | (0, Trend::Mean) | (1, Trend::Drift)
            )
    }

    fn difference_polynomial(self) -> [f64; MAX_INTEGRATION + 1] {
        let ordinary: &[f64] = match self.d {
            0 => &[1.0],
            1 => &[1.0, -1.0],
            _ => &[1.0, -2.0, 1.0],
        };
        let mut difference = [0.0; MAX_INTEGRATION + 1];
        for (lag, &coefficient) in ordinary.iter().enumerate() {
            difference[lag] += coefficient;
            if self.seasonal_difference > 0 {
                difference[self.period + lag] -= coefficient;
            }
        }
        difference
    }

    pub(super) fn starts(self) -> ([[f64; MAX_DYNAMICS]; 3], usize) {
        let mut starts = [[0.0; MAX_DYNAMICS]; 3];
        if self.q + self.seasonal_ma == 0 {
            return (starts, 1);
        }
        for (index, sign) in [1.0, -1.0].into_iter().enumerate() {
            let point = &mut starts[index + 1];
            if self.p > 0 {
                point[0] = sign * 0.75;
            }
            if self.q > 0 {
                point[self.p] = sign * 0.45;
            }
            if self.seasonal_ar > 0 {
                point[self.p + self.q] = sign * 0.60;
            }
            if self.seasonal_ma > 0 {
                point[self.p + self.q + self.seasonal_ar] = sign * 0.45;
            }
        }
        (starts, 3)
    }
}

fn expand_factor(
    ordinary: &[f64],
    seasonal: f64,
    period: usize,
    cross_sign: f64,
) -> [f64; MAX_LAG] {
    let mut expanded = [0.0; MAX_LAG];
    expanded[..ordinary.len()].copy_from_slice(ordinary);
    if seasonal != 0.0 {
        expanded[period - 1] += seasonal;
        for (lag, &coefficient) in ordinary.iter().enumerate() {
            expanded[period + lag] += cross_sign * seasonal * coefficient;
        }
    }
    expanded
}

pub(super) struct Factors {
    pub(super) ar: Coefficients,
    pub(super) ma: Coefficients,
    pub(super) seasonal_ar: f64,
    pub(super) seasonal_ma: f64,
}

impl Factors {
    pub(super) fn new(point: &optimizer::Coordinates, order: Order) -> Self {
        let (ar, ma) = optimizer::dynamics(point, order.p, order.q);
        let next = order.p + order.q;
        let seasonal_ar = if order.seasonal_ar > 0 {
            point[next].tanh()
        } else {
            0.0
        };
        let seasonal_ma = if order.seasonal_ma > 0 {
            -point[next + order.seasonal_ar].tanh()
        } else {
            0.0
        };
        Self {
            ar,
            ma,
            seasonal_ar,
            seasonal_ma,
        }
    }

    pub(super) fn system(&self, order: Order) -> StateSpace<MAX_SEASONAL_STATE> {
        let expanded_ar = expand_factor(&self.ar[..order.p], self.seasonal_ar, order.period, -1.0);
        let expanded_ma = expand_factor(&self.ma[..order.q], self.seasonal_ma, order.period, 1.0);
        let ar = &expanded_ar[..order.ar_lags()];
        let ma = &expanded_ma[..order.ma_lags()];
        if order.seasonal_difference == 0 {
            StateSpace::new(ar, ma, order.d)
        } else {
            let difference = order.difference_polynomial();
            StateSpace::with_known_anchors(ar, ma, &difference[1..=order.integration()])
        }
    }
}

fn validate_anchors(values: &[f64], count: usize) -> Result<(), Failure> {
    let anchors = values.get(..count).ok_or(Failure::Insufficient)?;
    for (index, &value) in anchors.iter().enumerate() {
        if value.is_nan() {
            return Err(Failure::MissingAnchor(index));
        }
        if !value.is_finite() {
            return Err(Failure::Input(index));
        }
    }
    Ok(())
}

fn validate_phases(sample: &Sample, period: usize) -> Result<(), Failure> {
    let mut anchors = sample.difference;
    let mut counts = [0; DAILY_PERIOD];
    for (time, &value) in sample.values.iter().enumerate() {
        if time % CHECK_EVERY == 0 {
            checkpoint(sample.check)?;
        }
        if value.is_nan() {
            continue;
        }
        if anchors > 0 {
            anchors -= 1;
        } else {
            counts[time % period] += 1;
        }
    }
    if counts[..period].iter().any(|&count| count < 2) {
        return Err(Failure::Insufficient);
    }
    Ok(())
}

struct SeasonalFit {
    fit: Fit,
    seasonal_ar: f64,
    seasonal_ma: f64,
}

pub(super) fn prepare_sample(
    values: &[f64],
    order: Order,
    trend: Trend,
    check: CancellationCheck,
) -> Result<Sample, Failure> {
    checkpoint(check)?;
    let integration = order.integration();
    if order.seasonal_difference > 0 {
        validate_anchors(values, integration)?;
    }
    let dimensions = order.dimensions();
    let sample = Sample::new(values, dimensions, integration, trend, check)?;
    if order.seasonal_ar + order.seasonal_ma > 0 {
        validate_phases(&sample, order.period)?;
    }
    Ok(sample)
}

fn fit_seasonal(
    values: &[f64],
    order: Order,
    trend: Trend,
    horizon: usize,
    check: CancellationCheck,
) -> Result<SeasonalFit, Failure> {
    if !order.supported(values.len(), trend) {
        return Err(Failure::Unsupported);
    }
    if !(1..=MAX_HORIZON).contains(&horizon) {
        return Err(Failure::Input(usize::MAX));
    }
    let dimensions = order.dimensions();
    let sample = prepare_sample(values, order, trend, check)?;
    let (point, iterations) = if dimensions == 0 {
        ([0.0; MAX_DYNAMICS], 0)
    } else {
        let width = order.width();
        let work = values.len() * width * width + order.optimizer_setup_work();
        if !optimizer::enough_budget(work, dimensions) {
            return Err(Failure::Unsupported);
        }
        let (starts, count) = order.starts();
        optimizer::minimize(&starts[..count], dimensions, work, |point| {
            sample.objective(&Factors::new(point, order).system(order))
        })?
    };
    let factors = Factors::new(&point, order);
    let system = factors.system(order);
    let fit = finish_fit(
        &sample, &system, factors.ar, factors.ma, iterations, horizon, None,
    )?;
    Ok(SeasonalFit {
        fit,
        seasonal_ar: factors.seasonal_ar,
        seasonal_ma: factors.seasonal_ma,
    })
}

/// Uses the ARIMA fit header followed by ordinary AR, ordinary MA, seasonal AR
/// and seasonal MA coefficients. Status 8 identifies a missing startup anchor.
///
/// # Safety
/// Nonnull pointers must reference valid memory for the supplied lengths.
/// The input must be initialized. The callback must remain valid and must not
/// unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_sarima_fit(
    values: *const f64,
    count: usize,
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
    forecasts_len: usize,
    residuals: *mut f64,
    residuals_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    let Some(trend) = Trend::from_code(trend) else {
        return 6;
    };
    let order = Order::new(
        [p, d, q],
        [seasonal_ar, seasonal_difference, seasonal_ma, period],
    );
    if !order.supported(count, trend) {
        return 6;
    }
    let outputs = FitBuffers {
        fit: (fit, fit_len),
        forecast: (forecasts, forecasts_len),
        residuals: (residuals, residuals_len),
        error_index,
    };
    if !outputs.valid(values, count, order.dimensions(), horizon) {
        return 1;
    }
    unsafe { error_index.write(usize::MAX) };
    let values = unsafe { slice::from_raw_parts(values, count) };
    match fit_seasonal(values, order, trend, horizon, check) {
        Ok(estimate) => {
            let seasonal = [estimate.seasonal_ar, estimate.seasonal_ma];
            unsafe {
                outputs.write(
                    &estimate.fit,
                    p,
                    q,
                    &seasonal[1 - seasonal_ar..1 + seasonal_ma],
                )
            }
        }
        Err(failure) => unsafe { outputs.failure(failure) },
    }
}
