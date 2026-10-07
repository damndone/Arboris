// Independent Stata IC, variance-prime, persistence and diagnostic checks.
version 18
set more off
args output source
cd "`output'"
foreach case in garch11_constant garch11_zero garch21_constant arch2_constant {
    import delimited using "`source'/data_`case'.csv", asdouble clear case(preserve)
    tsset t
    local ar "ar(1)"
    local variance "arch(1) garch(1)"
    local constant ""
    if "`case'" == "garch21_constant" local ar "ar(1/2)"
    if "`case'" == "arch2_constant" local variance "arch(1/2)"
    if "`case'" == "garch11_zero" local constant "noconstant"
    quietly arch y, `ar' ma(1) `variance' `constant' arch0(xb) arma0(zero) vce(opg) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8)
    matrix b = e(b)
    local k = colsof(b)
    quietly estat ic
    matrix ic = r(S)
    predict double residual, residuals
    predict double variance, variance
    generate double squared = residual^2
    quietly summarize squared, meanonly
    scalar prime = r(mean)
    generate double standardized = residual/sqrt(variance)
    generate double squared_standardized = standardized^2
    file open out using auxiliary_`case'.tsv, write replace
    file write out "aic" _tab %24.17g (ic[1,5]) _n
    file write out "bic" _tab %24.17g (ic[1,6]) _n
    file write out "prime" _tab %24.17g (prime) _n
    if "`case'" != "arch2_constant" {
        scalar persistence = b[1,`k'-2]+b[1,`k'-1]
        file write out "persistence" _tab %24.17g (persistence) _n
        file write out "half_life" _tab %24.17g (ln(.5)/ln(persistence)) _n
    }
    foreach series in standardized squared_standardized {
        foreach lag in 5 10 20 {
            quietly wntestq `series', lags(`lag')
            file write out "`series'_q`lag'" _tab %24.17g (r(stat)) _n
            file write out "`series'_p`lag'" _tab %24.17g (r(p)) _n
        }
    }
    file close out
}
