# VERIFICATION LEVEL: HC0, no debiasing; 2SLS with x1 exogenous, xe instrumented by z; z inference.
# Deterministic data, seed 20261003; no downloaded inputs.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
here <- args[1]; phase <- args[2]
stopifnot(here == "tests/fixtures/admission/iv_2sls")
cat("output directory:", here, "phase:", phase, "\n")
dir.create(here, recursive=TRUE, showWarnings=FALSE)
set.seed(20261003)
n <- 450
x1 <- rnorm(n); z <- rnorm(n); u <- rnorm(n)
xe <- .9*z + .3*x1 + .7*u + rnorm(n)
y <- 1 + .5*x1 + .8*xe + u
data <- data.frame(y, x1, xe, z)
write.csv(data, file.path(here, "data.csv"), row.names=FALSE)
if (phase == "data") quit(status=0)
data <- read.csv(file.path(here, "data.csv"))
suppressPackageStartupMessages({library(jsonlite); library(fixest)})
fit <- fixest::feols(y ~ x1 | xe ~ z, data=data)
V <- vcov(fit, vcov="hetero", ssc=fixest::ssc(K.adj=FALSE))
b <- coef(fit)
terms <- names(b)
b <- b[terms]; se <- sqrt(diag(V))[terms]
names(b)[names(b)=="(Intercept)"] <- "Intercept"
names(se)[names(se)=="(Intercept)"] <- "Intercept"
names(b)[names(b)=="fit_xe"] <- "xe"
names(se)[names(se)=="fit_xe"] <- "xe"
oracle <- list(meta=list(generator="tests/fixtures/admission/iv_2sls/generate_oracle.R",
                           r_version=R.version.string, seed=20261003, n=nrow(data),
                           verification_level="HC0, no debiasing; 2SLS with x1 exogenous, xe instrumented by z; z inference"),
               inference=list(covariance_estimator="robust", df_method="asymptotic",
                              reference_distribution="z", df_resid=nrow(data)-length(b)),
               coefficients=as.list(b), std_error=as.list(se))
writeLines(jsonlite::toJSON(oracle, auto_unbox=TRUE, digits=NA, pretty=TRUE), file.path(here,"oracle.json"))
cat("wrote oracle.json\n")
