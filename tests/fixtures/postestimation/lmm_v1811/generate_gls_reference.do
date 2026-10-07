* Stata mixed references for the four LMM settings of generate_gls_reference.R.
* Writes numbers only; the batch log carries the license header and is not kept.
version 18
set more off
file open out using stata_gls_results.csv, write replace
file write out "setting,quantity,value" _n
foreach setting in random_intercept_reml random_intercept_ml random_slope_reml random_slope_ml {
  if strpos("`setting'", "intercept") import delimited using intercept.csv, clear varnames(1) asdouble
  else import delimited using slope.csv, clear varnames(1) asdouble
  encode arm, gen(armn)
  local re = cond(strpos("`setting'", "slope"), "g: time, covariance(unstructured)", "g:,")
  local method = cond(strpos("`setting'", "reml"), "reml", "mle")
  mixed y i.armn##c.time x || `re' `method' tolerance(1e-10) ltolerance(1e-13)
  file write out "`setting',converged," %21.17g (e(converged)) _n
  file write out "`setting',loglik," %21.17g (e(ll)) _n
  foreach t in _cons 2.armn time 2.armn#c.time x {
    file write out "`setting',b:`t'," %21.17g (_b[`t']) _n
    file write out "`setting',se:`t'," %21.17g (_se[`t']) _n
  }
  test time x
  file write out "`setting',wald_joint," %21.17g (r(chi2)) _n
  test time - x = 1
  file write out "`setting',wald_shifted," %21.17g (r(chi2)) _n
  lincom time + 2*x - 0.5
  file write out "`setting',lincom.estimate," %21.17g (r(estimate)) _n
  file write out "`setting',lincom.se," %21.17g (r(se)) _n
  nlcom _b[time]/_b[x]
  matrix B = r(b)
  matrix V = r(V)
  file write out "`setting',nlcom.estimate," %21.17g (B[1,1]) _n
  file write out "`setting',nlcom.se," %21.17g (sqrt(V[1,1])) _n
}
file close out
