// Verify Stata defaults and the parameter-dependent variance prime.
version 18
set more off
args output data
cd "`output'"
import delimited using "`data'", asdouble clear case(preserve)
tsset t
quietly arch y, ar(1) ma(1) arch(1) garch(1) vce(opg) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8)
scalar default_ll = e(ll)
scalar default_n = e(N)
matrix default_b = e(b)
quietly arch y, ar(1) ma(1) arch(1) garch(1) arch0(xb) arma0(zero) vce(opg) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8)
matrix explicit_b = e(b)
predict double residual, residuals
predict double variance, variance
generate double square = residual^2
quietly summarize square, meanonly
scalar prime = r(mean)
scalar first_expected = explicit_b[1,6]+(explicit_b[1,4]+explicit_b[1,5])*prime
file open out using probe.tsv, write replace
file write out "default_ll" _tab %24.17g (default_ll) _n
file write out "explicit_ll" _tab %24.17g (e(ll)) _n
file write out "default_n" _tab %24.17g (default_n) _n
file write out "explicit_n" _tab %24.17g (e(N)) _n
file write out "prime" _tab %24.17g (prime) _n
file write out "first_variance" _tab %24.17g (variance[1]) _n
file write out "first_expected" _tab %24.17g (first_expected) _n
forvalues i=1/6 {
    file write out "parameter_difference`i'" _tab %24.17g (default_b[1,`i']-explicit_b[1,`i']) _n
}
file close out
