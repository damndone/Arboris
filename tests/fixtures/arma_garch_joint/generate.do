// VERIFICATION LEVEL: independent Stata 18 normal ARCH likelihood oracle.
// Usage: stata-mp -b do generate.do <fresh output directory>
version 18
set more off
args output
cd "`output'"
set seed 181104
foreach case in garch11_constant garch11_zero garch21_constant arch2_constant {
    clear
    local N = cond("`case'" == "garch11_constant",2540,1800)
    set obs `N'
    generate long t = _n
    generate double h = 1
    generate double e = 0
    generate double u = 0
    local mu = cond("`case'" == "garch11_zero",0,2)
    forvalues i = 3/`N' {
        if "`case'" == "arch2_constant" {
            quietly replace h = .5 + .3*e[`i'-1]^2 + .15*e[`i'-2]^2 in `i'
        }
        else {
            quietly replace h = .15 + .18*e[`i'-1]^2 + .67*h[`i'-1] in `i'
        }
        quietly replace e = sqrt(h)*rnormal() in `i'
        quietly replace u = .55*u[`i'-1] + .35*e[`i'-1] + e in `i'
        if "`case'" == "garch21_constant" {
            quietly replace u = u - .2*u[`i'-2] in `i'
        }
    }
    generate double y = `mu' + u
    tsset t
    format y %24.17g
    export delimited t y using data_`case'.csv, replace
    local ar "ar(1)"
    local variance "arch(1) garch(1)"
    local constant ""
    if "`case'" == "garch21_constant" local ar "ar(1/2)"
    if "`case'" == "arch2_constant" local variance "arch(1/2)"
    if "`case'" == "garch11_zero" local constant "noconstant"
    foreach vce in opg oim robust {
        quietly arch y, `ar' ma(1) `variance' `constant' arch0(xb) arma0(zero) vce(`vce') tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8) iterate(500)
        matrix b = e(b)
        matrix V = e(V)
        local k = colsof(b)
        file open out using stata_`case'_`vce'.tsv, write replace
        file write out "ll" _tab %24.17g (e(ll)) _n
        file write out "nobs" _tab %24.17g (e(N)) _n
        file write out "converged" _tab %24.17g (e(converged)) _n
        forvalues i=1/`k' {
            file write out "b`i'" _tab %24.17g (b[1,`i']) _n
            file write out "se`i'" _tab %24.17g (sqrt(V[`i',`i'])) _n
            forvalues j=1/`k' {
                file write out "v`i'_`j'" _tab %24.17g (V[`i',`j']) _n
            }
        }
        file close out
        predict double residual_`vce', residuals
        predict double variance_`vce', variance
    }
    export delimited t residual_* variance_* using series_`case'.csv, replace
}
