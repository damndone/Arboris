# Run at repository root: LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 Rscript tests/fixtures/agent_completion/lmm/generate_residuals.R
# Native predictions/residuals, not a translation of the Arboris formula.
suppressPackageStartupMessages({ library(lme4); library(jsonlite) })
root <- 'tests/fixtures/agent_completion/lmm'
intercept <- 'tests/fixtures/admission/linear_mixed_effects/data.csv'
slope <- 'tests/fixtures/postestimation/lmm_v1811/random_slope.csv'
d <- read.csv(slope)
d <- d[-c(2, 8, 20, 102), ]
d$x[4] <- NA_real_
write.csv(d, file.path(root, 'unbalanced_missing.csv'), row.names=FALSE, na='')
source_sha <- function(path) strsplit(system2('/usr/bin/shasum', c('-a', '256', shQuote(path)), stdout=TRUE), ' +')[[1]][1]
one <- function(path, random_slope, reml) {
  raw <- read.csv(path)
  keep <- complete.cases(raw[, c('y', 'arm', 'time', 'x')])
  d <- raw[keep, ]
  f <- if (random_slope) y ~ arm * time + x + (1 + time | g) else y ~ arm * time + x + (1 | g)
  fit <- lmer(f, data=d, REML=reml,
    control=lmerControl(optimizer='bobyqa', optCtrl=list(rhoend=1e-12, maxfun=1e6)))
  list(source=path, source_sha256=source_sha(path), fit_method=if (reml) 'reml' else 'ml', random_slope=random_slope,
    source_row_positions=as.list(which(keep) - 1L), converged=is.null(fit@optinfo$conv$lme4$messages),
    singular=isSingular(fit), sigma=as.numeric(sigma(fit)),
    conditional_residual=as.list(as.numeric(residuals(fit, type='response'))),
    marginal_residual=as.list(as.numeric(d$y - predict(fit, re.form=NA))),
    conditional_fitted=as.list(as.numeric(predict(fit))),
    scaled_conditional_residual=as.list(as.numeric(residuals(fit, type='pearson', scaled=TRUE))))
}
out <- list(environment=list(R=R.version.string, lme4=as.character(packageVersion('lme4')),
    Matrix=as.character(packageVersion('Matrix')), jsonlite=as.character(packageVersion('jsonlite'))),
  command='LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 Rscript tests/fixtures/agent_completion/lmm/generate_residuals.R',
  tolerance=list(rtol=2e-6, atol=2e-6, comparison='each retained observation, unchanged across settings'),
  residual_method_source=paste(deparse(getS3method('residuals', 'merMod')), collapse='\n'),
  cases=list(intercept_reml=one(intercept, FALSE, TRUE), intercept_ml=one(intercept, FALSE, FALSE),
    slope_reml=one(slope, TRUE, TRUE), slope_ml=one(slope, TRUE, FALSE),
    unbalanced_missing=one(file.path(root, 'unbalanced_missing.csv'), TRUE, TRUE)))
writeLines(toJSON(out, auto_unbox=TRUE, pretty=TRUE, digits=NA), file.path(root, 'residuals_r.json'))
