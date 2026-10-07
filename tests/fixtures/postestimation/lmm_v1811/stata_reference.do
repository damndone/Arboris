version 18
set more off
import delimited using data.csv, clear varnames(1) asdouble
encode arm, gen(armn)
mixed y i.armn##c.time x || g:, reml
file open out using stata_results.csv, write replace
file write out "quantity,value" _n
foreach t in _cons 2.armn time 2.armn#c.time x {
  file write out "b:`t'," %21.17g (_b[`t']) _n
  file write out "se:`t'," %21.17g (_se[`t']) _n
}
file write out "ll," %21.17g (e(ll)) _n
file write out "converged," %21.17g (e(converged)) _n
test time x
file write out "wald_joint.statistic," %21.17g (r(chi2)) _n
file write out "wald_joint.df," %21.17g (r(df)) _n
file write out "wald_joint.p," %21.17g (r(p)) _n
test time - x = 1
file write out "wald_shifted.statistic," %21.17g (r(chi2)) _n
file write out "wald_shifted.p," %21.17g (r(p)) _n
lincom time + 2*x - 0.5
file write out "lincom.estimate," %21.17g (r(estimate)) _n
file write out "lincom.se," %21.17g (r(se)) _n
nlcom _b[time]/_b[x]
matrix B = r(b)
matrix V = r(V)
file write out "nlcom.estimate," %21.17g (B[1,1]) _n
file write out "nlcom.se," %21.17g (sqrt(V[1,1])) _n
file close out
