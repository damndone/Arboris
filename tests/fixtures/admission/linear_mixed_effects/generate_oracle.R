# VERIFICATION LEVEL: R-only provisional reference: REML random intercept, arm*time+x; real Workbench workflow blocked by local containment admission; NOT cross-verified.
# Deterministic data, seed 20261003; no downloaded inputs.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
here <- args[1]; phase <- args[2]
stopifnot(here == "tests/fixtures/admission/linear_mixed_effects")
cat("output directory:", here, "phase:", phase, "\n")
dir.create(here, recursive=TRUE, showWarnings=FALSE)
set.seed(20261003)
n <- 360
g <- rep(seq_len(60), each=6); time <- rep(0:5, 60)
arm <- ifelse(g <= 30, "a", "b"); x <- rnorm(n)
y <- 1 + .3*time + .4*(arm=="b") + .2*time*(arm=="b") + .6*x + rnorm(60, sd=.8)[g] + rnorm(n, sd=.6)
data <- data.frame(y, x, g, time, arm)
write.csv(data, file.path(here, "data.csv"), row.names=FALSE)
if (phase == "data") quit(status=0)
data <- read.csv(file.path(here, "data.csv"))
suppressPackageStartupMessages({library(jsonlite); library(lme4)})
fit <- lme4::lmer(y ~ arm * time + x + (1|g), data=data, REML=TRUE,
                  control=lmerControl(optimizer="bobyqa", optCtrl=list(maxfun=100000)))
V <- as.matrix(vcov(fit)); b <- fixef(fit); terms <- names(b)
b <- b[terms]; se <- sqrt(diag(V))[terms]
names(b)[names(b)=="(Intercept)"] <- "Intercept"
names(se)[names(se)=="(Intercept)"] <- "Intercept"
oracle <- list(meta=list(generator="tests/fixtures/admission/linear_mixed_effects/generate_oracle.R",
                           r_version=R.version.string, seed=20261003, n=nrow(data),
                           verification_level="R-only provisional reference: REML random intercept, arm*time+x; real Workbench workflow blocked by local containment admission; NOT cross-verified"),
               inference=list(covariance_estimator="R REML model covariance; Workbench unavailable", df_method="R asymptotic; Workbench unavailable",
                              reference_distribution="z", df_resid=df.residual(fit)),
               coefficients=as.list(b), std_error=as.list(se))
writeLines(jsonlite::toJSON(oracle, auto_unbox=TRUE, digits=NA, pretty=TRUE), file.path(here,"oracle.json"))
cat("wrote oracle.json\n")
