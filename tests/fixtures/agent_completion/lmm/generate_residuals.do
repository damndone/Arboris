* Run from a scratch directory, passing the absolute repository root as argument.
* Native Stata mixed predictions; rstandard is not used (different definition).
version 18
args repo
cd "`repo'"
set more off
file open out using tests/fixtures/agent_completion/lmm/residuals_stata.csv, write replace
file write out "setting,source_row_position,conditional_fitted,conditional_residual,marginal_residual" _n
foreach setting in intercept_reml intercept_ml slope_reml slope_ml unbalanced_missing {
    if strpos("`setting'", "intercept") import delimited using tests/fixtures/admission/linear_mixed_effects/data.csv, clear varnames(1) asdouble
    else if "`setting'" == "unbalanced_missing" import delimited using tests/fixtures/agent_completion/lmm/unbalanced_missing.csv, clear varnames(1) asdouble
    else import delimited using tests/fixtures/postestimation/lmm_v1811/random_slope.csv, clear varnames(1) asdouble
    gen long source_row_position = _n - 1
    encode arm, gen(armn)
    local random = cond(strpos("`setting'", "intercept"), "g:,", "g: time, covariance(unstructured)")
    local method = cond(strpos("`setting'", "_ml"), "mle", "reml")
    mixed y i.armn##c.time x || `random' `method' tolerance(1e-10) ltolerance(1e-13)
    assert e(converged) == 1
    predict double conditional_fitted if e(sample), fitted
    predict double conditional_residual if e(sample), residuals
    predict double fixed_only if e(sample), xb
    gen double marginal_residual = y - fixed_only if e(sample)
    forvalues i = 1/`=_N' {
        if !missing(conditional_residual[`i']) {
            file write out "`setting'," %12.0f (source_row_position[`i']) "," %24.17g (conditional_fitted[`i']) "," %24.17g (conditional_residual[`i']) "," %24.17g (marginal_residual[`i']) _n
        }
    }
}
file close out
file open meta using tests/fixtures/agent_completion/lmm/stata_environment.json, write replace
file write meta `"{"stata_version":"`c(stata_version)'","os":"`c(os)'","command":"stata-mp -bq do generate_residuals.do REPO_ROOT","tolerance":{"rtol":0.000002,"atol":0.000002},"definition":"predict fitted; predict residuals; y - predict xb. Not rstandard."}"'
file close meta
