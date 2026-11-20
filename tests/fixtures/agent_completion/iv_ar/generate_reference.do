version 18
args repo
cd "`repo'"
set more off
file open out using tests/fixtures/agent_completion/iv_ar/reference_stata.csv, write replace
file write out "case,b,hc0_chi_square,homoskedastic_f" _n
foreach case in q1 q2 q3 q4 distant {
    import delimited using tests/fixtures/agent_completion/iv_ar/`case'.csv, clear varnames(1) asdouble
    ds z*
    local instruments `r(varlist)'
    local q : word count `instruments'
    local offset = cond("`case'" == "distant",12000,0)
    foreach value in -10000 -10 -1 0 1 1.5 2 4 10 10000 {
        local b = `offset'+`value'
        generate double transformed = y-`b'*x
        quietly regress transformed w `instruments', vce(robust)
        local n = e(N)
        local df = e(df_r)
        quietly test `instruments'
        scalar hc0 = r(F)*`q'*`n'/`df'
        quietly regress transformed w `instruments'
        quietly test `instruments'
        file write out "`case'," %24.17g (`b') "," %24.17g (hc0) "," %24.17g (r(F)) _n
        drop transformed
    }
}
file close out
file open meta using tests/fixtures/agent_completion/iv_ar/stata_environment.json, write replace
file write meta `"{"stata_version":"`c(stata_version)'","os":"`c(os)'","definition":"Native regress/test; robust HC1 Wald converted to HC0 by N/df_r. Point tests only; not a global topology oracle."}"'
file close meta
