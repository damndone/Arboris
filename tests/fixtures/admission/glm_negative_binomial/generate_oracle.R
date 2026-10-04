# VERIFICATION LEVEL: negative-binomial log GLM with alpha=1 fixed (theta=1); dispersion=1; glm.nb would estimate a different model.
# Deterministic data, seed 20261003; no downloaded inputs.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
here <- args[1]; phase <- args[2]
stopifnot(here == "tests/fixtures/admission/glm_negative_binomial")
cat("output directory:", here, "phase:", phase, "\n")
dir.create(here, recursive=TRUE, showWarnings=FALSE)
set.seed(20261003)
n <- 450
x1 <- rnorm(n); x2 <- rnorm(n)
y <- rnbinom(n, size=1, mu=exp(.3 + .4*x1 - .2*x2))
data <- data.frame(y, x1, x2)
write.csv(data, file.path(here, "data.csv"), row.names=FALSE)
if (phase == "data") quit(status=0)
data <- read.csv(file.path(here, "data.csv"))
suppressPackageStartupMessages({library(jsonlite); library(MASS)})
epsilon <- if (phase == "oracle_high_precision") 1e-14 else 1e-8
# Same nominal tolerance as Workbench; R uses relative deviance change,
# whereas statsmodels uses absolute deviance change. Do not emulate its solver.
fit <- glm(y ~ x1 + x2, data=data, family=MASS::negative.binomial(theta=1),
           control=glm.control(epsilon=epsilon, maxit=100))
V <- vcov(fit, dispersion=1); b <- coef(fit); terms <- names(b)
b <- b[terms]; se <- sqrt(diag(V))[terms]
names(b)[names(b)=="(Intercept)"] <- "Intercept"
names(se)[names(se)=="(Intercept)"] <- "Intercept"
oracle <- list(meta=list(generator="tests/fixtures/admission/glm_negative_binomial/generate_oracle.R",
                           r_version=R.version.string, seed=20261003, n=nrow(data), epsilon=epsilon,
                           verification_level="negative-binomial log GLM with alpha=1 fixed (theta=1); dispersion=1; glm.nb would estimate a different model"),
               inference=list(covariance_estimator="nonrobust", df_method="asymptotic",
                              reference_distribution="z", df_resid=df.residual(fit)),
               coefficients=as.list(b), std_error=as.list(se))
output <- if (phase == "oracle_high_precision") "oracle_high_precision.json" else "oracle.json"
writeLines(jsonlite::toJSON(oracle, auto_unbox=TRUE, digits=NA, pretty=TRUE), file.path(here,output))
cat("wrote oracle.json\n")
