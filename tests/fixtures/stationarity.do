version 18
args input adf_lag kpss_lag output
set more off
import delimited using "`input'", clear varnames(1) asdouble
quietly tsset time
quietly dfuller y, lags(`adf_lag') regress
scalar adf_stat = r(Zt)
scalar adf_n = r(N)
scalar adf_cv5 = r(cv_5)
scalar adf_p = r(p)
if `adf_lag' == 0 {
    quietly regress D.y L.y
}
else {
    quietly regress D.y L.y L(1/`adf_lag').D.y
}
scalar gamma = _b[L.y]
scalar gamma_se = _se[L.y]
scalar adf_df = e(df_r)

quietly summarize y, meanonly
scalar n = r(N)
scalar mu = r(mean)
quietly generate double residual = y - mu
quietly generate double partial_sum = sum(residual)
quietly generate double square_partial_sum = partial_sum^2
quietly summarize square_partial_sum, meanonly
scalar eta = r(sum) / (n*n)
quietly generate double residual_square = residual^2
quietly summarize residual_square, meanonly
scalar lrv = r(sum) / n
if `kpss_lag' > 0 {
    quietly generate double cross = .
    forvalues lag = 1/`kpss_lag' {
        quietly replace cross = residual * L`lag'.residual
        quietly summarize cross, meanonly
        scalar lrv = lrv + 2 * (1 - `lag'/(`kpss_lag' + 1)) * r(sum) / n
    }
}
scalar kpss_stat = eta / lrv
scalar addon_stat = .
capture which kpss
scalar addon_available = (_rc == 0)
if addon_available == 1 {
    capture quietly kpss y, notrend maxlag(`kpss_lag')
    if _rc == 0 {
        scalar addon_stat = r(kpss`kpss_lag')
    }
}

file open wire using "`output'", write replace
file write wire "adf,gamma,se,adf_n,adf_df,kpss,adf_cv5,adf_p,addon_available,addon_kpss,stata_version" _n
file write wire %24.17g (adf_stat) "," %24.17g (gamma) "," %24.17g (gamma_se) "," %24.17g (adf_n) "," %24.17g (adf_df) "," %24.17g (kpss_stat) "," %24.17g (adf_cv5) "," %24.17g (adf_p) "," %24.17g (addon_available) "," %24.17g (addon_stat) "," %24.17g (c(stata_version)) _n
file close wire
