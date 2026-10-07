# VERIFICATION LEVEL: Poisson log GLM, default nonrobust covariance, dispersion=1, z inference.
# Deterministic data, seed 20261003; no downloaded inputs.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
here <- args[1]; phase <- args[2]
stopifnot(here == "tests/fixtures/admission/glm_poisson")
cat("output directory:", here, "phase:", phase, "\n")
dir.create(here, recursive=TRUE, showWarnings=FALSE)
set.seed(20261003)
n <- 450
x1 <- rnorm(n); x2 <- rnorm(n)
y <- rpois(n, exp(.3 + .4*x1 - .2*x2))
data <- data.frame(y, x1, x2)
write.csv(data, file.path(here, "data.csv"), row.names=FALSE)
if (phase == "data") quit(status=0)
data <- read.csv(file.path(here, "data.csv"))
suppressPackageStartupMessages({library(jsonlite); })
fit <- glm(y ~ x1 + x2, data=data, family=poisson(), control=glm.control(epsilon=1e-14, maxit=100))
V <- vcov(fit); b <- coef(fit); terms <- names(b)
b <- b[terms]; se <- sqrt(diag(V))[terms]
names(b)[names(b)=="(Intercept)"] <- "Intercept"
names(se)[names(se)=="(Intercept)"] <- "Intercept"
oracle <- list(meta=list(generator="tests/fixtures/admission/glm_poisson/generate_oracle.R",
                           r_version=R.version.string, seed=20261003, n=nrow(data),
                           verification_level="Poisson log GLM, default nonrobust covariance, dispersion=1, z inference"),
               inference=list(covariance_estimator="nonrobust", df_method="asymptotic",
                              reference_distribution="z", df_resid=df.residual(fit)),
               coefficients=as.list(b), std_error=as.list(se))
writeLines(jsonlite::toJSON(oracle, auto_unbox=TRUE, digits=NA, pretty=TRUE), file.path(here,"oracle.json"))
cat("wrote oracle.json\n")
