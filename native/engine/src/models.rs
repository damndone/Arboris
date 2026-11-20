//! OLS, two-stage least squares and two-way fixed effects on complete cases.
use crate::dist;
use crate::linalg::{self, Matrix, Qr};
use std::collections::HashMap;

pub struct Fit {
    pub terms: Vec<String>,
    pub estimate: Vec<f64>,
    pub std_error: Vec<f64>,
    pub statistic: Vec<f64>,
    pub p_value: Vec<f64>,
    pub ci_lower: Vec<f64>,
    pub ci_upper: Vec<f64>,
    pub nobs: usize,
    pub df_resid: f64,
    pub df_model: f64,
    pub r_squared: f64,
    pub r_squared_adj: f64,
    pub covariance: &'static str,
    pub distribution: &'static str,
}

fn with_constant(columns: &[&[f64]], rows: usize) -> Matrix {
    let mut out = vec![vec![1.0; rows]];
    out.extend(columns.iter().map(|column| column.to_vec()));
    Matrix { rows, cols: out.len(), columns: out }
}

fn solve(qr: &Qr, y: &[f64]) -> Vec<f64> {
    let mut work = y.to_vec();
    qr.qt(&mut work);
    qr.solve_r(&work)
}

fn residuals(x: &Matrix, beta: &[f64], y: &[f64]) -> Vec<f64> {
    let mut out = y.to_vec();
    for (column, coefficient) in x.columns.iter().zip(beta) {
        for (target, value) in out.iter_mut().zip(column) { *target -= coefficient * value; }
    }
    out
}

fn centered_ss(y: &[f64]) -> f64 {
    let mean = y.iter().sum::<f64>() / y.len() as f64;
    y.iter().map(|value| (value - mean) * (value - mean)).sum()
}

fn inference(terms: Vec<String>, estimate: Vec<f64>, cov: &[Vec<f64>], normal: bool, df: f64) -> Fit {
    let critical = if normal { dist::normal_quantile_975() } else { dist::student_critical(df) };
    let std_error: Vec<f64> = (0..estimate.len()).map(|i| cov[i][i].sqrt()).collect();
    let statistic: Vec<f64> = estimate.iter().zip(&std_error).map(|(b, s)| b / s).collect();
    let p_value = statistic.iter().map(|t| if normal { dist::normal_two_sided(*t) } else { dist::student_two_sided(*t, df) }).collect();
    let ci_lower = estimate.iter().zip(&std_error).map(|(b, s)| b - critical * s).collect();
    let ci_upper = estimate.iter().zip(&std_error).map(|(b, s)| b + critical * s).collect();
    Fit { terms, estimate, std_error, statistic, p_value, ci_lower, ci_upper, nobs: 0, df_resid: df, df_model: 0.0,
          r_squared: 0.0, r_squared_adj: 0.0, covariance: "", distribution: if normal { "normal" } else { "student_t" } }
}

/// `hc` is 0, 1, or none for the classical covariance.
pub fn ols(y: &[f64], x: &[&[f64]], names: &[String], hc: Option<u8>, threads: usize) -> Result<Fit, String> {
    let n = y.len();
    let design = with_constant(x, n);
    let k = design.cols;
    let copy = Matrix { rows: n, cols: k, columns: design.columns.clone() };
    let qr = linalg::qr(copy)?;
    let beta = solve(&qr, y);
    let e = residuals(&design, &beta, y);
    let ssr: f64 = e.iter().map(|v| v * v).sum();
    let df = (n - k) as f64;
    let inverse = qr.r_inverse();
    let bread = linalg::bread(&inverse);
    let cov: Vec<Vec<f64>> = match hc {
        None => { let s2 = ssr / df; bread.iter().map(|row| row.iter().map(|v| v * s2).collect()).collect() }
        Some(kind) => {
            let weights: Vec<f64> = e.iter().map(|v| v * v).collect();
            let mut meat = linalg::weighted_cross(&design, &weights, threads);
            if kind == 1 { for row in &mut meat { for value in row { *value *= n as f64 / df; } } }
            linalg::sandwich(&bread, &meat)
        }
    };
    let mut terms = vec!["Intercept".to_string()];
    terms.extend(names.iter().cloned());
    let mut fit = inference(terms, beta, &cov, false, df);
    fit.nobs = n;
    fit.df_model = (k - 1) as f64;
    fit.r_squared = 1.0 - ssr / centered_ss(y);
    fit.r_squared_adj = 1.0 - (1.0 - fit.r_squared) * (n as f64 - 1.0) / df;
    fit.covariance = match hc { None => "classical", Some(0) => "hc0", _ => "hc1" };
    Ok(fit)
}

/// Heteroskedasticity-robust 2SLS with large-sample inference, as the product's default.
pub fn iv_2sls(y: &[f64], exog: &[&[f64]], endog: &[&[f64]], instruments: &[&[f64]], names: &[String], threads: usize) -> Result<Fit, String> {
    let n = y.len();
    let mut z_columns: Vec<&[f64]> = exog.to_vec();
    z_columns.extend_from_slice(instruments);
    let z = with_constant(&z_columns, n);
    if z.cols < exog.len() + endog.len() + 1 { return Err("fewer instruments than endogenous regressors".into()); }
    let z_qr = linalg::qr(z)?;
    let mut x_columns: Vec<&[f64]> = exog.to_vec();
    x_columns.extend_from_slice(endog);
    let x = with_constant(&x_columns, n);
    // X-hat: the projection of each regressor on the instruments.
    let mut projected = Vec::with_capacity(x.cols);
    for column in &x.columns {
        let mut work = column.clone();
        z_qr.qt(&mut work);
        for value in &mut work[z_qr.vectors.cols..] { *value = 0.0; }
        z_qr.q(&mut work);
        projected.push(work);
    }
    let x_hat = Matrix { rows: n, cols: x.cols, columns: projected };
    let copy = Matrix { rows: n, cols: x.cols, columns: x_hat.columns.clone() };
    let qr = linalg::qr(copy)?;
    let beta = solve(&qr, y);
    let e = residuals(&x, &beta, y);
    let ssr: f64 = e.iter().map(|v| v * v).sum();
    let bread = linalg::bread(&qr.r_inverse());
    let weights: Vec<f64> = e.iter().map(|v| v * v).collect();
    let cov = linalg::sandwich(&bread, &linalg::weighted_cross(&x_hat, &weights, threads));
    let mut terms = vec!["Intercept".to_string()];
    terms.extend(names.iter().cloned());
    let df = (n - x.cols) as f64;
    let mut fit = inference(terms, beta, &cov, true, df);
    fit.nobs = n;
    fit.df_model = (x.cols - 1) as f64;
    fit.r_squared = 1.0 - ssr / centered_ss(y);
    fit.r_squared_adj = 1.0 - (1.0 - fit.r_squared) * (n as f64 - 1.0) / df;
    fit.covariance = "robust";
    Ok(fit)
}

fn codes(values: &[f64]) -> (Vec<u32>, usize) {
    let mut seen: HashMap<u64, u32> = HashMap::with_capacity(values.len() / 8 + 8);
    let mut out = Vec::with_capacity(values.len());
    for value in values {
        let next = seen.len() as u32;
        out.push(*seen.entry(value.to_bits()).or_insert(next));
    }
    (out, seen.len())
}

fn sweep(column: &mut [f64], group: &[u32], count: &[f64], means: &mut [f64]) {
    means.iter_mut().for_each(|value| *value = 0.0);
    for (value, g) in column.iter().zip(group) { means[*g as usize] += value; }
    for (mean, n) in means.iter_mut().zip(count) { *mean /= n; }
    for (value, g) in column.iter_mut().zip(group) { *value -= means[*g as usize]; }
}

/// Entity and time effects by alternating projections; standard errors clustered on entity.
pub fn two_way_fe(y: &[f64], x: &[&[f64]], entity: &[f64], time: &[f64], names: &[String]) -> Result<Fit, String> {
    let n = y.len();
    let (entity_codes, entities) = codes(entity);
    let (time_codes, times) = codes(time);
    let tally = |group: &[u32], size: usize| {
        let mut out = vec![0.0; size];
        for g in group { out[*g as usize] += 1.0; }
        out
    };
    let (entity_count, time_count) = (tally(&entity_codes, entities), tally(&time_codes, times));
    let balanced = entity_count.iter().all(|c| *c == entity_count[0]) && time_count.iter().all(|c| *c == time_count[0]);
    let demean = |source: &[f64]| -> Vec<f64> {
        let mut column = source.to_vec();
        let (mut entity_means, mut time_means) = (vec![0.0; entities], vec![0.0; times]);
        let limit = if balanced { 2 } else { 2000 };
        for _ in 0..limit {
            let before = column.clone();
            sweep(&mut column, &entity_codes, &entity_count, &mut entity_means);
            sweep(&mut column, &time_codes, &time_count, &mut time_means);
            let change = column.iter().zip(&before).map(|(a, b)| (a - b).abs()).fold(0.0, f64::max);
            if change < 1e-13 { break; }
        }
        column
    };
    let mean = |column: &[f64]| column.iter().sum::<f64>() / n as f64;
    let restore = |source: &[f64]| -> Vec<f64> {
        let (mut within, center) = (demean(source), mean(source));
        within.iter_mut().for_each(|value| *value += center);
        within
    };
    // Grand means go back in, so the constant keeps its usual meaning.
    let y_within = restore(y);
    let mut columns = vec![vec![1.0; n]];
    columns.extend(x.iter().map(|column| restore(column)));
    let k = columns.len();
    let design = Matrix { rows: n, cols: k, columns: columns.clone() };
    let qr = linalg::qr(Matrix { rows: n, cols: k, columns })?;
    let beta = solve(&qr, &y_within);
    let e = residuals(&design, &beta, &y_within);
    let ssr: f64 = e.iter().map(|v| v * v).sum();
    let bread = linalg::bread(&qr.r_inverse());
    let mut scores = vec![0.0; entities * k];
    for (a, column) in design.columns.iter().enumerate() {
        for ((value, residual), g) in column.iter().zip(&e).zip(&entity_codes) {
            scores[*g as usize * k + a] += value * residual;
        }
    }
    let mut meat = vec![vec![0.0; k]; k];
    for group in scores.chunks_exact(k) {
        for a in 0..k { for b in 0..k { meat[a][b] += group[a] * group[b]; } }
    }
    // Entity effects are nested in the clusters, so only the time effects count against the sample.
    let (rows, clusters) = (n as f64, entities as f64);
    let counted = (k + times - 1) as f64;
    let factor = clusters / (clusters - 1.0) * (rows - 1.0) / (rows - counted);
    let mut cov = linalg::sandwich(&bread, &meat);
    for row in &mut cov { for value in row { *value *= factor; } }
    let df = clusters - 1.0;
    let mut terms = vec!["Intercept".to_string()];
    terms.extend(names.iter().cloned());
    let mut fit = inference(terms, beta, &cov, false, df);
    fit.nobs = n;
    fit.df_model = (k - 1 + entities + times - 1) as f64;
    fit.df_resid = (n - k - entities - times + 2) as f64;
    fit.r_squared = 1.0 - ssr / centered_ss(&y_within);
    fit.r_squared_adj = f64::NAN;
    fit.covariance = "clustered";
    Ok(fit)
}
