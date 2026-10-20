version 18
args repo
cd "`repo'"
set more off
file open out using tests/fixtures/agent_completion/survival/cox_reference_stata.csv, write replace
file write out "case,term,estimate,std_error" _n
foreach case in untied_breslow untied_efron tied_breslow tied_efron {
    if strpos("`case'", "untied") import delimited using tests/fixtures/v186_families/families.csv, clear varnames(1) asdouble
    else import delimited using tests/fixtures/agent_completion/survival/tied.csv, clear varnames(1) asdouble
    stset duration, failure(event)
    local ties = cond(strpos("`case'", "efron"), "efron", "breslow")
    stcox x1 x2 grp, `ties' nohr iterate(200) tolerance(1e-10) ltolerance(1e-12)
    assert e(converged) == 1
    foreach term in x1 x2 grp {
        file write out "`case',`term'," %24.17g (_b[`term']) "," %24.17g (_se[`term']) _n
    }
}
file close out
file open meta using tests/fixtures/agent_completion/survival/stata_environment.json, write replace
file write meta `"{"stata_version":"`c(stata_version)'","os":"`c(os)'","definition":"stcox, breslow/efron; coefficients and standard errors only, not a Cox PH score oracle"}"'
file close meta
