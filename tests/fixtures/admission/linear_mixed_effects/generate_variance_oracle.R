# Supplement the existing sample; never regenerate or rewrite old fixtures.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
sample_path <- normalizePath(args[1], mustWork=TRUE)
output_path <- args[2]
stopifnot(!file.exists(output_path))
suppressPackageStartupMessages({library(lme4); library(jsonlite); library(digest)})
data <- read.csv(sample_path)
fit <- lmer(y ~ arm * time + x + (1 | g), data=data, REML=TRUE,
            control=lmerControl(optimizer="bobyqa", optCtrl=list(maxfun=100000)))
stopifnot(is.null(fit@optinfo$conv$lme4$messages))
b <- fixef(fit); se <- sqrt(diag(as.matrix(vcov(fit))))
names(b)[names(b)=="(Intercept)"] <- "Intercept"
names(se)[names(se)=="(Intercept)"] <- "Intercept"
reference <- list(
  meta=list(generator="tests/fixtures/admission/linear_mixed_effects/generate_variance_oracle.R",
            r_version=R.version.string, lme4_version=as.character(packageVersion("lme4")),
            data_sha256=digest(file=sample_path, algo="sha256"),
            nobs=nobs(fit), n_groups=length(unique(data$g)), reml=TRUE,
            formula="y ~ arm * time + x + (1 | g)", optimizer="bobyqa",
            verification_level="R-only; host Workbench verification pending"),
  coefficients=as.list(b), std_error=as.list(se),
  random_effects=list(intercept_variance=unname(as.matrix(VarCorr(fit)$g)[1,1]),
                      residual_variance=unname(sigma(fit)^2)))
writeLines(toJSON(reference, auto_unbox=TRUE, digits=NA, pretty=TRUE), output_path)
cat("Wrote variance supplement for", nobs(fit), "observations\n")
