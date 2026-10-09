version 18
set more off
file open out using native_reml_margins_stata.csv, write replace
file write out "setting,quantity,value" _n
foreach setting in random_intercept random_slope {
 if "`setting'" == "random_intercept" import delimited using intercept.csv, clear varnames(1) asdouble
 else import delimited using slope.csv, clear varnames(1) asdouble
 drop if missing(y,arm,time,x,g)
 encode arm, gen(armn)
 local re = cond("`setting'"=="random_slope","g: time, covariance(unstructured)","g:,")
 mixed y i.armn##c.time x || `re' reml tolerance(1e-10) ltolerance(1e-13)
 file write out "`setting',converged," %21.17g (e(converged)) _n
 foreach v in x time {
  margins, dydx(`v') predict(xb)
  matrix T = r(table)
  file write out "`setting',`v'.estimate," %21.17g (T[1,1]) _n
  file write out "`setting',`v'.std_error," %21.17g (T[2,1]) _n
 }
}
file close out
