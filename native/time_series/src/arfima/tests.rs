use super::*;

fn near(actual: f64, expected: f64, tolerance: f64) {
    assert!(
        (actual - expected).abs() <= tolerance,
        "expected {expected:.15}, got {actual:.15}"
    );
}

fn fixture(d: f64, mut seed: u64, level: f64) -> Vec<f64> {
    let noise: Vec<_> = (0..600)
        .map(|_| {
            seed = (16807 * seed) % 2147483647;
            (seed as f64 - 1073741823.0) / 1073741824.0
        })
        .collect();
    let mut impulse = vec![1.0; 401];
    for lag in 1..impulse.len() {
        impulse[lag] = impulse[lag - 1] * ((lag as f64 - 1.0 + d) / lag as f64);
    }
    (420..600)
        .map(|time| {
            level
                + impulse
                    .iter()
                    .enumerate()
                    .map(|(lag, weight)| weight * noise[time - lag])
                    .sum::<f64>()
        })
        .collect()
}

fn check(reference: &Fit, header: [f64; 5], forecast: [[f64; 2]; 5], tolerance: f64) {
    for (actual, expected) in reference.header.iter().zip(header) {
        near(*actual, expected, tolerance);
    }
    for (actual, expected) in reference.forecast.iter().zip(forecast) {
        near(actual[0], expected[0], tolerance);
        near(actual[1], expected[1], tolerance);
    }
}

#[test]
fn fitted_positive_d_and_level_match_dense_gaussian_ml() {
    let result = fit(
        &fixture(0.29, 173, 4.2),
        5,
        Difference::Estimate,
        true,
        None,
    )
    .unwrap();
    assert_eq!(result.header[5], 180.0);
    assert!(result.header[6] > 17.0);
    check(
        &result,
        [
            0.205306316517174,
            4.21037215000199,
            0.310085308280590,
            0.342822391884265,
            -150.189669439973,
        ],
        [
            [4.23108865169723, 0.310157810719348],
            [4.22474605774571, 0.323260482990068],
            [4.21687024214760, 0.328029577528231],
            [4.21107607670159, 0.330612087416386],
            [4.20697721287890, 0.332273747686637],
        ],
        2e-7,
    );
}

#[test]
fn fitted_negative_d_with_zero_level_matches_dense_gaussian_ml() {
    let result = fit(
        &fixture(-0.31, 913, 0.0),
        5,
        Difference::Estimate,
        false,
        None,
    )
    .unwrap();
    assert_eq!(result.header[1], 0.0);
    check(
        &result,
        [
            -0.203641734597295,
            0.0,
            0.289136018161154,
            0.304813759067573,
            -143.860987261988,
        ],
        [
            [-0.115317783815810, 0.289202379888829],
            [-0.046444019822244, 0.301168283154343],
            [-0.028923660350699, 0.303061027506234],
            [-0.021140963980831, 0.303738053050684],
            [-0.016788430516664, 0.304068134681682],
        ],
        2e-7,
    );
}

const SHORT: [f64; 6] = [2.0, -1.0, 3.0, 2.5, 1.25, -0.5];

#[test]
fn short_fixed_d_likelihood_and_joint_forecast_match_exact_rational_oracle() {
    let result = fit(&SHORT, 5, Difference::Fixed(0.25), true, None).unwrap();
    assert_eq!(result.header[5..], [6.0, 1.0]);
    check(
        &result,
        [
            0.25,
            1.138020833333333,
            2.70249014276706,
            3.189858833948771,
            -11.639575507079636,
        ],
        [
            [0.8483981693363844, 2.729600092161555],
            [0.9951690821256039, 2.909326847201000],
            [1.0485183271409000, 2.980920654082930],
            [1.0751047792459200, 3.021317094341540],
            [1.0906432748538000, 3.047827258261250],
        ],
        1e-12,
    );
}

#[test]
fn fixed_negative_scope_endpoint_matches_dense_covariance() {
    let result = fit(&SHORT, 5, Difference::Fixed(-0.45), false, None).unwrap();
    check(
        &result,
        [
            -0.45,
            0.0,
            5.90392082119164,
            7.23893127622815,
            -14.0907940809915,
        ],
        [
            [-1.137751922002770, 6.07829143360360],
            [-0.467839348607008, 7.14276587591930],
            [-0.281545598046857, 7.21182058523106],
            [-0.192943450842715, 7.22767359733975],
            [-0.142056314859999, 7.23324893785501],
        ],
        1e-12,
    );
}

#[test]
fn zero_d_is_ordinary_gaussian_white_noise_and_forecast_is_flat() {
    let result = fit(&[1.0, 3.0, 2.0, 4.0], 4, Difference::Fixed(0.0), true, None).unwrap();
    near(result.header[1], 2.5, 1e-14);
    near(result.header[2], 1.25, 1e-14);
    assert_eq!(result.header[2], result.header[3]);
    for [mean, variance] in result.forecast {
        near(mean, 2.5, 1e-14);
        near(variance, 1.25, 1e-14);
    }
}

#[test]
fn invalid_gap_zero_energy_short_and_boundary_fit_refuse() {
    let data = [2.0, 3.0, f64::NAN, 1.0];
    assert!(matches!(
        fit(&data, 2, Difference::Fixed(0.2), true, None),
        Err(Failure::Input(2))
    ));
    assert!(matches!(
        fit(&[2.0; 10], 2, Difference::Fixed(0.2), true, None),
        Err(Failure::Degenerate)
    ));
    assert!(matches!(
        fit(&SHORT, 2, Difference::Estimate, true, None),
        Err(Failure::Insufficient)
    ));
    assert!(matches!(
        fit(&SHORT, 2, Difference::Fixed(0.5), true, None),
        Err(Failure::Unsupported)
    ));
    let persistent: Vec<_> = (0..60).map(|t| t as f64).collect();
    assert!(matches!(
        fit(&persistent, 2, Difference::Estimate, true, None),
        Err(Failure::Convergence)
    ));
}

#[test]
fn estimated_d_is_invariant_under_affine_level_and_scale_change() {
    let original = fixture(0.29, 173, 4.2);
    let base = fit(&original, 4, Difference::Estimate, true, None).unwrap();
    for scale in [1e-130_f64, 1e130_f64] {
        let data: Vec<_> = original
            .iter()
            .map(|value| scale * (value + 19.0))
            .collect();
        let model = fit(&data, 4, Difference::Estimate, true, None).unwrap();
        near(model.header[0], base.header[0], 1e-7);
        near(model.header[1] / scale - 19.0, base.header[1], 1e-7);
        near(model.header[2] / scale / scale, base.header[2], 1e-7);
        near(model.header[3] / scale / scale, base.header[3], 1e-7);
        near(
            model.header[4] + base.header[5] * scale.ln(),
            base.header[4],
            1e-7,
        );
        for (row, reference) in model.forecast.iter().zip(&base.forecast) {
            near(row[0] / scale - 19.0, reference[0], 1e-7);
            near(row[1] / scale / scale, reference[1], 1e-7);
        }
    }
}

#[test]
fn cancellation_and_aliases_leave_result_buffers_untouched() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static POLLS: AtomicUsize = AtomicUsize::new(0);
    extern "C" fn cancel() -> i32 {
        i32::from(POLLS.fetch_add(1, Ordering::Relaxed) >= 19)
    }
    let mut data = fixture(0.29, 173, 4.2);
    let mut estimates = [-1.0; 7];
    let mut future = [-2.0; 8];
    let mut error = 99;
    let before = data.clone();
    let status = unsafe {
        arboris_arfima_fit(
            data.as_ptr(),
            data.len(),
            4,
            1,
            0.0,
            1,
            data.as_mut_ptr(),
            7,
            future.as_mut_ptr(),
            future.len(),
            &mut error,
            None,
        )
    };
    assert_eq!(status, 1);
    assert_eq!(error, 99);
    assert_eq!(data, before);
    let status = unsafe {
        arboris_arfima_fit(
            data.as_ptr(),
            data.len(),
            4,
            1,
            0.0,
            1,
            estimates.as_mut_ptr(),
            estimates.len(),
            future.as_mut_ptr(),
            future.len(),
            &mut error,
            Some(cancel),
        )
    };
    assert_eq!(status, 7);
    assert_eq!(POLLS.load(Ordering::Relaxed), 20);
    assert_eq!(estimates, [-1.0; 7]);
    assert_eq!(future, [-2.0; 8]);
}
