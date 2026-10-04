# VERIFICATION LEVEL: two-way FE with sum-to-zero effects; explicit dummy OLS HC1 includes all absorbed degrees of freedom; kernel covariance is missing.
# Deterministic data, seed 20261003; no downloaded inputs.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
here <- args[1]; phase <- args[2]
stopifnot(here == "tests/fixtures/admission/panel_ols")
cat("output directory:", here, "phase:", phase, "\n")
dir.create(here, recursive=TRUE, showWarnings=FALSE)
set.seed(20261003)
n <- 400
g <- rep(seq_len(50), each=8); time <- rep(seq_len(8), 50)
x1 <- rnorm(n); x2 <- rnorm(n)
y <- 1 + .7*x1 - .4*x2 + rnorm(50)[g] + .2*time + rnorm(n)
data <- data.frame(y, x1, x2, g, time)
write.csv(data, file.path(here, "data.csv"), row.names=FALSE)
if (phase == "data") quit(status=0)
data <- read.csv(file.path(here, "data.csv"))
suppressPackageStartupMessages({library(jsonlite); library(sandwich)})
fit <- lm(y ~ x1 + x2 + factor(g) + factor(time), data=data,
          contrasts=list("factor(g)"="contr.sum", "factor(time)"="contr.sum"))
V <- sandwich::vcovHC(fit, type="HC1")
b <- coef(fit)
terms <- c("(Intercept)", "x1", "x2")
b <- b[terms]; se <- sqrt(diag(V))[terms]
names(b)[names(b)=="(Intercept)"] <- "Intercept"
names(se)[names(se)=="(Intercept)"] <- "Intercept"
oracle <- list(meta=list(generator="tests/fixtures/admission/panel_ols/generate_oracle.R",
                           r_version=R.version.string, seed=20261003, n=nrow(data),
                           verification_level="two-way FE with sum-to-zero effects; explicit dummy OLS HC1 includes all absorbed degrees of freedom; kernel covariance is missing"),
               inference=list(covariance_estimator="runtime robust; kernel null", df_method="asymptotic",
                              reference_distribution="z", df_resid=df.residual(fit)),
               coefficients=as.list(b), std_error=as.list(se))
writeLines(jsonlite::toJSON(oracle, auto_unbox=TRUE, digits=NA, pretty=TRUE), file.path(here,"oracle.json"))
cat("wrote oracle.json\n")
