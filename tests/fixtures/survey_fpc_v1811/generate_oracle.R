# Independent single-stage FPC references. Never overwrite retained evidence.
# Run from the worktree root; an optional argument selects a fresh output file.
suppressPackageStartupMessages({library(survey); library(jsonlite)})
root <- "tests/fixtures/survey_fpc_v1811"
args <- commandArgs(trailingOnly=TRUE)
output <- if (length(args)) args[1] else file.path(root, "oracle_reference.json")
if (file.exists(output)) stop("Select a fresh oracle output; retained evidence is immutable")
options(survey.lonely.psu="fail", survey.adjust.domain.lonely=FALSE)
cases <- list()
record <- function(name, source="design", fpc=NULL, psu=TRUE, strata=TRUE,
                   domain=FALSE, policy="fail") {
  if (name %in% names(cases)) stop("Duplicate oracle case name")
  d <- read.csv(file.path(root, paste0(source, ".csv")))
  if (!psu) d$observation_fpc <- 20
  if (!strata) d$unstratified_fpc <- 32
  options(survey.lonely.psu=policy)
  des <- svydesign(ids=if(psu) ~psu else ~1,
                   strata=if(strata) ~stratum else NULL, weights=~weight,
                   fpc=if(is.null(fpc)) NULL else reformulate(fpc), data=d, nest=TRUE)
  if (domain) des <- subset(des, subpop==1)
  fit <- svyglm(y~x1+x2, design=des)
  b <- coef(fit); V <- vcov(fit); se <- sqrt(diag(V))
  # Keep the full-design Workbench/Stata df convention explicit for domains.
  full_psu <- if(psu) length(unique(paste(d$stratum,d$psu))) else nrow(d)
  full_strata <- if(strata) length(unique(d$stratum)) else 1
  df <- full_psu-full_strata
  t <- b/se; critical <- qt(.975,df)
  idx <- match(c("x1","x2"),names(b))
  W <- as.numeric(t(b[idx]) %*% solve(V[idx,idx]) %*% b[idx])
  q <- length(idx); denominator <- df-q+1
  F <- W*denominator/(df*q)
  L <- c(0,1,-1); estimate <- sum(L*b); linse <- sqrt(as.numeric(t(L)%*%V%*%L))
  cases[[name]] <<- list(source=source,fpc=fpc,psu=psu,strata=strata,domain=domain,
    lonely_psu=policy,nobs=nrow(model.frame(fit)),terms=names(b),
    coefficients=as.list(b), covariance=unname(V),standard_errors=as.list(se),
    design_df=df,t=as.list(t),p=as.list(2*pt(-abs(t),df)),
    ci_lower=as.list(b-critical*se),ci_upper=as.list(b+critical*se),
    wald=list(statistic=F,df=q,ddf=denominator,p=pf(F,q,denominator,lower.tail=FALSE)),
    lincom=list(estimate=estimate,se=linse,t=estimate/linse,
      p=2*pt(-abs(estimate/linse),df),low=estimate-critical*linse,high=estimate+critical*linse))
}
record("without_fpc")
record("population",fpc="population_fpc")
record("fraction",fpc="fraction_fpc")
record("zero_fraction",fpc="zero_fpc")
record("certainty",fpc="certainty_fpc")
record("population_certainty",fpc="population_certainty_fpc")
record("subpopulation",source="subpop",fpc="population_fpc",domain=TRUE)
record("no_psu",fpc="observation_fpc",psu=FALSE)
record("no_strata",fpc="unstratified_fpc",strata=FALSE)
record("lonely_census",source="lonely",fpc="certainty_fpc")
for (policy in c("remove","certainty","adjust","average")) {
  record(paste0("lonely_",policy),source="lonely",fpc="fraction_fpc",policy=policy)
}
out <- list(reference="R survey::svydesign/svyglm; full-design t df; Korn-Graubard adjusted Wald computed in R",
            environment=list(R=R.version.string,survey=as.character(packageVersion("survey")),
                             jsonlite=as.character(packageVersion("jsonlite"))),cases=cases)
write_json(out,output,auto_unbox=TRUE,digits=17,pretty=TRUE,na="null",null="null")
print(sessionInfo())
cat("Wrote",output,"with",length(cases),"independent cases\n")
