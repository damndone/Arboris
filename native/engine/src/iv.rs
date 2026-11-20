//! Two-stage least squares and compatible linearmodels diagnostics with `debiased = false`.
//! Wu-Hausman uses the standard full-instrument Wu T2 projection, correcting linearmodels 7.0.
use crate::linalg::{self, Matrix, Qr};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Covariance { Unadjusted, Robust }

pub struct IvInput<'a> {
    pub y: &'a [f64],
    /// Included exogenous regressors, the constant among them.
    pub exog: Vec<&'a [f64]>,
    pub endog: Vec<&'a [f64]>,
    /// Excluded instruments only.
    pub instruments: Vec<&'a [f64]>,
    pub covariance: Covariance,
    pub threads: usize,
}

pub struct IvFit {
    pub params: Vec<f64>,
    pub cov: Vec<Vec<f64>>,
    pub ssr: f64,
    pub centered_tss: f64,
    /// Wald statistic of the excluded instruments in each first-stage regression.
    pub first_stage_wald: Vec<f64>,
    pub first_stage_df_resid: f64,
    pub wooldridge_regression: f64,
    /// NaN when the model is just identified.
    pub wooldridge_overid: f64,
    /// NaN unless the covariance is unadjusted, the only case the product reads them.
    pub sargan: f64,
    pub wu_hausman: f64,
}

fn owned(columns: &[&[f64]]) -> Matrix {
    let rows = columns.first().map_or(0, |column| column.len());
    Matrix { rows, cols: columns.len(), columns: columns.iter().map(|column| crate::cancel::copy(column)).collect() }
}

fn decompose(columns: &[&[f64]]) -> Result<Qr, String> { linalg::qr(owned(columns)) }

fn project_coordinates(qr: &Qr, work: &mut [f64]) {
    for block in work[qr.vectors.cols..].chunks_mut(4096) { crate::cancel::checkpoint(); block.fill(0.0); }
    qr.q(work);
}

fn projection(qr: &Qr, values: &[f64]) -> Vec<f64> {
    let mut work = crate::cancel::copy(values);
    qr.qt(&mut work);
    project_coordinates(qr, &mut work);
    work
}

fn residuals_with_coordinates(qr: &Qr, values: &[f64], first: usize) -> (Vec<f64>, Vec<f64>) {
    let mut work = crate::cancel::copy(values);
    qr.qt(&mut work);
    let coordinates = work[first..qr.vectors.cols].to_vec();
    project_coordinates(qr, &mut work);
    for (values, fitted) in values.chunks(4096).zip(work.chunks_mut(4096)) {
        crate::cancel::checkpoint();
        for (value, fit) in values.iter().zip(fitted) { *fit = value - *fit; }
    }
    (work, coordinates)
}

fn least_squares_residuals(columns: &[&[f64]], y: &[f64]) -> Result<Vec<f64>, String> {
    let qr = decompose(columns)?;
    let beta = {
        let mut work = crate::cancel::copy(y);
        qr.qt(&mut work);
        qr.solve_r(&work)
    };
    drop(qr);
    let mut residuals = crate::cancel::copy(y);
    for (column, coefficient) in columns.iter().zip(&beta) {
        for (targets, values) in residuals.chunks_mut(4096).zip(column.chunks(4096)) {
            crate::cancel::checkpoint();
            for (target, value) in targets.iter_mut().zip(values) { *target -= coefficient * value; }
        }
    }
    Ok(residuals)
}

fn sum_of_squares(values: &[f64]) -> f64 { linalg::dot(values, values) }

fn squared(values: &[f64]) -> Vec<f64> {
    let mut result = Vec::with_capacity(values.len());
    for block in values.chunks(4096) {
        crate::cancel::checkpoint();
        result.extend(block.iter().map(|value| value * value));
    }
    result
}

fn covariance(qr: &Qr, residuals: &[f64], kind: Covariance, threads: usize) -> Vec<Vec<f64>> {
    let inverse = qr.r_inverse();
    match kind {
        Covariance::Unadjusted => {
            let s2 = sum_of_squares(residuals) / residuals.len() as f64;
            linalg::bread(&inverse).iter().map(|row| row.iter().map(|value| value * s2).collect()).collect()
        }
        Covariance::Robust => {
            // HC0 = R^-1 (Q' diag(e^2) Q) R^-T. Forming (X'X)^-1 on both
            // sides of X' diag(e^2) X squares the conditioning and loses small
            // covariance entries when regressors are nearly collinear.
            let basis = orthogonal_tail(qr, qr.vectors.cols);
            let columns: Vec<&[f64]> = basis.iter().map(Vec::as_slice).collect();
            let squared: Vec<f64> = squared(residuals);
            let meat = linalg::weighted_cross_slices(&columns, &squared, threads);
            let k = inverse.len();
            let first: Vec<Vec<f64>> = inverse.iter().map(|row| (0..k).map(|j| {
                let column: Vec<f64> = meat.iter().map(|values| values[j]).collect();
                linalg::dot(row, &column)
            }).collect()).collect();
            first.iter().map(|row| inverse.iter().map(|other| linalg::dot(row, other)).collect()).collect()
        }
    }
}

/// The tested coefficients can instead be expressed in the trailing orthonormal Q basis.
/// This avoids cancelling large, nearly equal entries of the original-coordinate covariance.
fn orthogonal_tail(qr: &Qr, count: usize) -> Vec<Vec<f64>> {
    (qr.vectors.cols - count..qr.vectors.cols).map(|index| {
        let mut unit = vec![0.0; qr.vectors.rows];
        unit[index] = 1.0;
        qr.q(&mut unit);
        unit
    }).collect()
}

fn orthogonal_wald(coordinates: &[f64], basis: &[Vec<f64>], residuals: &[f64], kind: Covariance, threads: usize) -> Result<f64, String> {
    if kind == Covariance::Unadjusted {
        return Ok(sum_of_squares(coordinates) / (sum_of_squares(residuals) / residuals.len() as f64));
    }
    let columns: Vec<&[f64]> = basis.iter().map(Vec::as_slice).collect();
    let squared: Vec<f64> = squared(residuals);
    let covariance = linalg::weighted_cross_slices(&columns, &squared, threads);
    let solved = linalg::solve_dense(covariance, coordinates.to_vec())?;
    Ok(linalg::dot(coordinates, &solved))
}

pub fn iv_2sls(input: &IvInput) -> Result<IvFit, String> {
    let n = input.y.len();
    let (n_exog, n_endog, n_instruments) = (input.exog.len(), input.endog.len(), input.instruments.len());
    if n_endog == 0 || n_instruments < n_endog { return Err("fewer instruments than endogenous regressors".into()); }
    let mut z_columns: Vec<&[f64]> = input.exog.clone();
    z_columns.extend(input.instruments.iter().copied());
    let z = decompose(&z_columns)?;
    let mut x_columns: Vec<&[f64]> = input.exog.clone();
    x_columns.extend(input.endog.iter().copied());
    // QR owns the projected design. Its fitted residuals are unused in 2SLS;
    // reuse the response buffer for structural residuals on the original X.
    let second_qr = linalg::qr(Matrix {
        rows: n,
        cols: x_columns.len(),
        columns: x_columns.iter().map(|column| projection(&z, column)).collect(),
    })?;
    let mut residuals = crate::cancel::copy(input.y);
    second_qr.qt(&mut residuals);
    let params = second_qr.solve_r(&residuals);
    for (targets, values) in residuals.chunks_mut(4096).zip(input.y.chunks(4096)) {
        crate::cancel::checkpoint();
        targets.copy_from_slice(values);
    }
    for (column, coefficient) in x_columns.iter().zip(&params) {
        for (targets, values) in residuals.chunks_mut(4096).zip(column.chunks(4096)) {
            crate::cancel::checkpoint();
            for (target, value) in targets.iter_mut().zip(values) { *target -= coefficient * value; }
        }
    }
    let cov = covariance(&second_qr, &residuals, input.covariance, input.threads);
    drop(second_qr);
    let ssr = sum_of_squares(&residuals);
    let mean = input.y.chunks(4096).fold(-0.0, |sum, block| { crate::cancel::checkpoint(); block.iter().fold(sum, |sum, value| sum + value) }) / n as f64;
    let mut centered = Vec::with_capacity(n);
    for block in input.y.chunks(4096) {
        crate::cancel::checkpoint();
        centered.extend(block.iter().map(|value| value - mean));
    }
    let centered_tss = sum_of_squares(&centered);
    drop(centered);

    let first_basis = if input.covariance == Covariance::Robust { orthogonal_tail(&z, n_instruments) } else { Vec::new() };
    let mut first_stage_wald = Vec::with_capacity(n_endog);
    let mut first_stage_residuals = Vec::with_capacity(n_endog);
    for endogenous in &input.endog {
        let (residual, coordinates) = residuals_with_coordinates(&z, endogenous, n_exog);
        first_stage_wald.push(orthogonal_wald(&coordinates, &first_basis, &residual, input.covariance, input.threads)?);
        first_stage_residuals.push(residual);
    }
    drop(first_basis);

    let mut augmented: Vec<&[f64]> = x_columns.clone();
    augmented.extend(first_stage_residuals.iter().map(Vec::as_slice));
    let control = decompose(&augmented)?;
    let (control_residuals, control_coordinates) = residuals_with_coordinates(&control, input.y, x_columns.len());
    let control_basis = if input.covariance == Covariance::Robust { orthogonal_tail(&control, n_endog) } else { Vec::new() };
    let wooldridge_regression = orthogonal_wald(&control_coordinates,
        &control_basis, &control_residuals, input.covariance, input.threads)?;
    drop((control, control_coordinates, control_residuals, control_basis));

    let wooldridge_overid = if n_instruments > n_endog {
        let fitted_endog: Vec<Vec<f64>> = input.endog.iter().zip(&first_stage_residuals)
            .map(|(value, residual)| {
                let mut result = Vec::with_capacity(n);
                for (value, residual) in value.chunks(4096).zip(residual.chunks(4096)) {
                    crate::cancel::checkpoint();
                    result.extend(value.iter().zip(residual).map(|(a, b)| a - b));
                }
                result
            }).collect();
        let mut w_columns: Vec<&[f64]> = input.exog.clone();
        w_columns.extend(fitted_endog.iter().map(Vec::as_slice));
        let w = decompose(&w_columns)?;
        let scores: Vec<Vec<f64>> = input.instruments[..n_instruments - n_endog].iter()
            .map(|instrument| {
                let (annihilated, _) = residuals_with_coordinates(&w, instrument, w.vectors.cols);
                let mut result = Vec::with_capacity(n);
                for (values, residuals) in annihilated.chunks(4096).zip(residuals.chunks(4096)) {
                    crate::cancel::checkpoint();
                    result.extend(values.iter().zip(residuals).map(|(a, b)| a * b));
                }
                result
            })
            .collect();
        let score_columns: Vec<&[f64]> = scores.iter().map(Vec::as_slice).collect();
        let ones = vec![1.0; n];
        // n R^2 of ones on the scores is their explained sum of squares; forming it as n - SSR
        // would cancel two numbers of size n.
        sum_of_squares(&projection(&decompose(&score_columns)?, &ones))
    } else {
        f64::NAN
    };

    let (mut sargan, mut wu_hausman) = (f64::NAN, f64::NAN);
    if input.covariance == Covariance::Unadjusted {
        if n_instruments > n_endog {
            // n (1 - e'M_Z e / e'e) = n e'P_Z e / e'e, without cancelling e'e against e'M_Z e.
            sargan = n as f64 * sum_of_squares(&projection(&z, &residuals)) / ssr;
        }
        let ordinary = least_squares_residuals(&x_columns, input.y)?;
        let mut z1_columns = z_columns.clone();
        z1_columns.extend(input.endog.iter().copied());
        let e1 = projection(&decompose(&z1_columns)?, &ordinary);
        let e2 = projection(&z, &residuals);
        let delta = sum_of_squares(&e1) - sum_of_squares(&e2);
        let tested = n_endog as f64;
        let df_denom = n as f64 - n_exog as f64 - n_endog as f64 - tested;
        wu_hausman = (delta / tested) / ((sum_of_squares(&ordinary) - delta) / df_denom);
    }
    Ok(IvFit {
        params, cov, ssr, centered_tss, first_stage_wald,
        first_stage_df_resid: (n - z_columns.len()) as f64,
        wooldridge_regression, wooldridge_overid, sargan, wu_hausman,
    })
}
