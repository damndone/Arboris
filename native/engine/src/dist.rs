//! Tail probabilities and quantiles for inference; no external numerical library.

fn ln_gamma(x: f64) -> f64 {
    // Lanczos approximation, g = 7, n = 9.
    const C: [f64; 9] = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313,
        -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
    if x < 0.5 { return (std::f64::consts::PI / (std::f64::consts::PI * x).sin()).ln() - ln_gamma(1.0 - x); }
    let x = x - 1.0;
    let mut sum = C[0];
    for (i, c) in C.iter().enumerate().skip(1) { sum += c / (x + i as f64); }
    let t = x + 7.5;
    0.5 * (2.0 * std::f64::consts::PI).ln() + (x + 0.5) * t.ln() - t + sum.ln()
}

fn beta_fraction(a: f64, b: f64, x: f64) -> f64 {
    const TINY: f64 = 1e-300;
    let (qab, qap, qam) = (a + b, a + 1.0, a - 1.0);
    let mut c = 1.0;
    let mut d = 1.0 - qab * x / qap;
    if d.abs() < TINY { d = TINY; }
    d = 1.0 / d;
    let mut h = d;
    for m in 1..=20000 {
        let m = m as f64;
        let aa = m * (b - m) * x / ((qam + 2.0 * m) * (a + 2.0 * m));
        d = 1.0 + aa * d; if d.abs() < TINY { d = TINY; }
        c = 1.0 + aa / c; if c.abs() < TINY { c = TINY; }
        d = 1.0 / d; h *= d * c;
        let aa = -(a + m) * (qab + m) * x / ((a + 2.0 * m) * (qap + 2.0 * m));
        d = 1.0 + aa * d; if d.abs() < TINY { d = TINY; }
        c = 1.0 + aa / c; if c.abs() < TINY { c = TINY; }
        d = 1.0 / d;
        let delta = d * c;
        h *= delta;
        if (delta - 1.0).abs() < 1e-16 { break; }
    }
    h
}

fn gamma_correction(x: f64) -> f64 {
    let (z, z2) = (1.0 / x, 1.0 / (x * x));
    z * (1.0 / 12.0 - z2 * (1.0 / 360.0 - z2 * (1.0 / 1260.0 - z2 * (1.0 / 1680.0 - z2 / 1188.0))))
}

/// ln B(a, b), without subtracting large log-gammas: at df near a million that alone loses nine digits.
fn ln_beta(a: f64, b: f64) -> f64 {
    let (p, q) = if a < b { (a, b) } else { (b, a) };
    let half_ln_two_pi = 0.5 * (2.0 * std::f64::consts::PI).ln();
    if p >= 10.0 {
        let correction = gamma_correction(p) + gamma_correction(q) - gamma_correction(p + q);
        -0.5 * q.ln() + half_ln_two_pi + correction + (p - 0.5) * (p / (p + q)).ln() + q * (-p / (p + q)).ln_1p()
    } else if q >= 10.0 {
        let correction = gamma_correction(q) - gamma_correction(p + q);
        ln_gamma(p) + correction + p - p * (p + q).ln() + (q - 0.5) * (-p / (p + q)).ln_1p()
    } else {
        ln_gamma(p) + ln_gamma(q) - ln_gamma(p + q)
    }
}

/// I_x(a, b) from x, y = 1 - x and their logarithms, each computed by the caller without cancellation.
fn inc_beta(a: f64, b: f64, x: f64, y: f64, ln_x: f64, ln_y: f64) -> f64 {
    let front = (a * ln_x + b * ln_y - ln_beta(a, b)).exp();
    if x < (a + 1.0) / (a + b + 2.0) { front * beta_fraction(a, b, x) / a } else { 1.0 - front * beta_fraction(b, a, y) / b }
}

pub fn student_two_sided(t: f64, df: f64) -> f64 {
    let u = t * t / df;
    if u == 0.0 { return 1.0; }
    if !u.is_finite() { return 0.0; }
    let ln_x = -u.ln_1p();
    inc_beta(df / 2.0, 0.5, 1.0 / (1.0 + u), u / (1.0 + u), ln_x, u.ln() + ln_x)
}

/// Upper tail of the standard normal doubled, from the complementary error function.
pub fn normal_two_sided(z: f64) -> f64 { erfc(z.abs() / std::f64::consts::SQRT_2) }

fn erfc(x: f64) -> f64 {
    // Continued fraction for large x, series for small; both to working precision.
    if x < 2.0 {
        let mut sum = x;
        let mut term = x;
        let mut n = 0.0;
        while term.abs() > 1e-17 * sum.abs() {
            n += 1.0;
            term *= -x * x / n;
            sum += term / (2.0 * n + 1.0);
        }
        1.0 - 2.0 / std::f64::consts::PI.sqrt() * sum
    } else {
        let mut f = 0.0;
        for k in (1..=120).rev() { f = (k as f64 / 2.0) / (x + f); }
        (-x * x).exp() / std::f64::consts::PI.sqrt() / (x + f)
    }
}

pub fn normal_quantile_975() -> f64 { 1.959963984540054 }

/// Two-sided 95% critical value of Student's t, by bisection on the tail.
pub fn student_critical(df: f64) -> f64 {
    let (mut low, mut high) = (0.0, 2000.0);
    for _ in 0..200 {
        let middle: f64 = 0.5 * (low + high);
        if student_two_sided(middle, df) > 0.05 { low = middle; } else { high = middle; }
    }
    0.5 * (low + high)
}
