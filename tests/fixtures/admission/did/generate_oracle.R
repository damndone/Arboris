# VERIFICATION LEVEL: two-period 2x2 TWFE; sum-to-zero unit/time effects preserve intercept; HC1 includes absorbed degrees of freedom; kernel covariance is missing.
# Deterministic data, seed 20261003; no downloaded inputs.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
here <- args[1]; phase <- args[2]
stopifnot(here == "tests/fixtures/admission/did")
cat("output directory:", here, "phase:", phase, "\n")
dir.create(here, recursive=TRUE, showWarnings=FALSE)
set.seed(20261003)
n <- 400
g <- rep(seq_len(200), each=2); time <- rep(0:1, 200)
treat <- as.integer(g > 100); post <- time; D <- treat*post
first_treat <- ifelse(treat==1, 1, 0)
y <- 1 + rnorm(200)[g] + .4*post + .8*D + rnorm(n)
data <- data.frame(y, g, time, treat, post, D, first_treat)
write.csv(data, file.path(here, "data.csv"), row.names=FALSE)
if (phase == "data") quit(status=0)
data <- read.csv(file.path(here, "data.csv"))
suppressPackageStartupMessages({library(jsonlite); library(sandwich)})
fit <- lm(y ~ D + factor(g) + factor(time), data=data,
          contrasts=list("factor(g)"="contr.sum", "factor(time)"="contr.sum"))
V <- sandwich::vcovHC(fit, type="HC1")
b <- coef(fit)
terms <- c("(Intercept)", "D")
b <- b[terms]; se <- sqrt(diag(V))[terms]
names(b)[names(b)=="(Intercept)"] <- "Intercept"
names(se)[names(se)=="(Intercept)"] <- "Intercept"
names(b)[names(b)=="D"] <- "_did_D"
names(se)[names(se)=="D"] <- "_did_D"
oracle <- list(meta=list(generator="tests/fixtures/admission/did/generate_oracle.R",
                           r_version=R.version.string, seed=20261003, n=nrow(data),
                           verification_level="two-period 2x2 TWFE; sum-to-zero unit/time effects preserve intercept; HC1 includes absorbed degrees of freedom; kernel covariance is missing"),
               inference=list(covariance_estimator="runtime robust; kernel null", df_method="asymptotic",
                              reference_distribution="z", df_resid=df.residual(fit)),
               coefficients=as.list(b), std_error=as.list(se))
writeLines(jsonlite::toJSON(oracle, auto_unbox=TRUE, digits=NA, pretty=TRUE), file.path(here,"oracle.json"))
cat("wrote oracle.json\n")

