version 18
args repo
cd "`repo'"
set more off
file open out using tests/fixtures/agent_completion/panel/residual_reference_stata.csv, write replace
file write out "case,source_position,residual" _n
foreach case in two_way one_way unbalanced {
    import delimited using tests/fixtures/admission/panel_ols/data.csv, clear varnames(1) asdouble
    generate long source_position = _n-1
    if "`case'" == "unbalanced" drop if mod(source_position+1,19)==0
    xtset g time
    local timefe = cond("`case'"=="one_way","","i.time")
    quietly xtreg y x1 x2 `timefe', fe vce(cluster g)
    predict double residual, e
    forvalues row = 1/`=_N' {
        file write out "`case'," %12.0g (source_position[`row']) "," %24.17g (residual[`row']) _n
    }
}
file close out
