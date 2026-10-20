suppressPackageStartupMessages(library(jsonlite))
root <- 'tests/fixtures/agent_completion/panel'
d <- read.csv('tests/fixtures/admission/panel_ols/data.csv')
cases <- list()
for (name in c('two_way','one_way','unbalanced')) {
  positions <- seq_len(nrow(d))
  if (name=='unbalanced') positions <- positions[positions %% 19 != 0]
  frame <- d[positions,]
  formula <- if(name=='one_way') y~x1+x2+factor(g) else y~x1+x2+factor(g)+factor(time)
  model <- lm(formula,data=frame)
  cases[[name]] <- list(retained_positions=positions-1L, residuals=as.numeric(residuals(model)),
      parameter_rank=model$rank, residual_df=df.residual(model))
}
writeLines(toJSON(list(environment=list(R=R.version.string),cases=cases,
  definition='Native stats::lm with explicit unit/time indicators; residuals include all fitted fixed effects. No serial-correlation or covariance-validity claim.'),
  auto_unbox=TRUE,pretty=TRUE,digits=NA),file.path(root,'residual_reference_r.json'))
