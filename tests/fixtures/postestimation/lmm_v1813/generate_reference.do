* Run from a temporary staging directory containing intercept.csv and slope.csv.
* Numerical CSV only is retained; the license-bearing batch log is not evidence.
version 18
set more off
file open out using native_stata.csv, write replace
file write out "setting,quantity,value" _n
foreach setting in random_intercept random_slope {
 if "`setting'" == "random_intercept" import delimited using intercept.csv, clear varnames(1) asdouble
 else import delimited using slope.csv, clear varnames(1) asdouble
 drop if missing(y,arm,time,x,g)
 encode arm, gen(armn)
 local re = cond("`setting'"=="random_slope","g: time, covariance(unstructured)","g:,")
 mixed y i.armn##c.time x || `re' mle tolerance(1e-10) ltolerance(1e-13)
 estimates store full
 scalar full_ll = e(ll)
 file write out "`setting',loglik_full," %21.17g (e(ll)) _n
 file write out "`setting',full_converged," %21.17g (e(converged)) _n
 file write out "`setting',nobs," %21.17g (e(N)) _n
 foreach v in x time {
  margins, dydx(`v') predict(xb)
  matrix T = r(table)
  file write out "`setting',`v'.estimate," %21.17g (T[1,1]) _n
  file write out "`setting',`v'.std_error," %21.17g (T[2,1]) _n
 }
 mixed y i.armn##c.time || `re' mle tolerance(1e-10) ltolerance(1e-13)
 file write out "`setting',loglik_restricted," %21.17g (e(ll)) _n
 file write out "`setting',restricted_converged," %21.17g (e(converged)) _n
 lrtest full .
 file write out "`setting',statistic," %21.17g (r(chi2)) _n
 file write out "`setting',df," %21.17g (r(df)) _n
 file write out "`setting',p_value," %21.17g (r(p)) _n
}
file close out
