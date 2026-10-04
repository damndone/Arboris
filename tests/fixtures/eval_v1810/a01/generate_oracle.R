# Oracle generator for multiple-imputation pooling (v1.8.10 step 5).
# Requires: mice, sandwich, jsonlite (tests/fixtures/r-oracle-requirements.txt)
#
# Writes, next to this file:
#   data.csv          frame with missing values (MAR on x1, x2 and y)
#   imputed_<i>.csv   the m = 2 or 20 completed datasets mice produced
#   oracle.json       mice::pool on each model fitted to those datasets
#
# Run from the worktree root:
#   Rscript tests/fixtures/eval_v1810/a01/generate_oracle.R tests/fixtures/eval_v1810/a01/m2 2
#
# VERIFICATION LEVEL:
#   * The completed datasets are R's, so the comparison isolates what Workbench
#     owns: the per-dataset fit, its covariance, and Rubin's rules with the
#     Barnard-Rubin (1999) degrees of freedom. Workbench imputes with
#     statsmodels, whose draws differ from R's; the imputation step itself is
#     checked separately (every requested dataset complete, none partial).
#   * Pooling: mice 3.19 `pool()` -- an independent implementation. For a
#     covariance other than lm's own, the per-dataset estimates and standard
#     errors are passed to `mice:::pool.vector`, which is what `pool()` calls.
#   * Complete-data degrees of freedom (dfcom) follow the reference
#     distribution of each single-dataset fit: N - K for OLS (also with HC1, as
#     the single fit reports t(N - K)), G - 1 for a clustered covariance, and
#     infinite for logit, whose single fit is z-based (Stata's convention for
#     large-sample models; mice would otherwise use N - K from df.residual).
#   * Every glm is converged to 1e-14.

suppressPackageStartupMessages({
  library(mice)
  library(sandwich)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
here <- args[1]
m <- as.integer(args[2])
stopifnot(m %in% c(2L, 20L))
stopifnot(startsWith(here, "tests/fixtures/eval_v1810/a01/"))
cat("output directory:", here, "m:", m, "\n")
dir.create(here, recursive = TRUE, showWarnings = FALSE)
set.seed(20261003)
n <- 300
g <- rep(seq_len(30), each = 10)
x1 <- rnorm(n)
x2 <- 0.5 * x1 + rnorm(n)
x3 <- rnorm(n)
u <- rnorm(30)[g]
y <- 1 + 0.8 * x1 - 0.5 * x2 + 0.3 * x3 + u + rnorm(n)
yb <- as.integer(runif(n) < plogis(-0.3 + 0.9 * x1 - 0.6 * x2 + 0.4 * x3))
# Missing at random: the probability depends on observed columns only.
miss_x1 <- runif(n) < plogis(-2 + 0.8 * x3)
miss_x2 <- runif(n) < plogis(-2.4 + 0.6 * yb)
miss_y <- runif(n) < plogis(-2.6 + 0.5 * x3)
x1[miss_x1] <- NA
x2[miss_x2] <- NA
y[miss_y] <- NA
data <- data.frame(g = g, y = y, yb = yb, x1 = x1, x2 = x2, x3 = x3)
write.csv(data, file.path(here, "data.csv"), row.names = FALSE, na = "")

predictors <- make.predictorMatrix(data)
predictors[, "g"] <- 0
imp <- mice(data, m = m, method = "pmm", predictorMatrix = predictors, seed = 20261003, printFlag = FALSE)
completed <- lapply(seq_len(m), function(i) complete(imp, i))
for (i in seq_len(m)) {
  write.csv(completed[[i]], file.path(here, sprintf("imputed_%d.csv", i)), row.names = FALSE)
}

pooled_table <- function(estimates, ses, dfcom) {
  w <- do.call(rbind, lapply(seq_along(estimates), function(i) {
    data.frame(term = names(estimates[[i]]), estimate = unname(estimates[[i]]), std.error = unname(ses[[i]]))
  }))
  pooled <- mice:::pool.vector(w, dfcom = dfcom, custom.t = NULL, rule = "rubin1987")
  se <- sqrt(pooled$t)
  stat <- pooled$estimate / se
  p <- 2 * pt(-abs(stat), pooled$df)
  crit <- qt(0.975, pooled$df)
  out <- list()
  for (j in seq_len(nrow(pooled))) {
    term <- as.character(pooled$term[j])
    if (term == "(Intercept)") term <- "Intercept"
    out[[term]] <- list(
      estimate = pooled$estimate[j], ubar = pooled$ubar[j], b = pooled$b[j], t = pooled$t[j],
      std_error = se[j], df = pooled$df[j], riv = pooled$riv[j], lambda = pooled$lambda[j],
      fmi = pooled$fmi[j], statistic = stat[j], p_value = p[j],
      ci_lower = pooled$estimate[j] - crit[j] * se[j], ci_upper = pooled$estimate[j] + crit[j] * se[j]
    )
  }
  list(dfcom = dfcom, terms = out)
}

ols_fits <- lapply(completed, function(d) lm(y ~ x1 + x2 + x3, data = d))
k <- 4
cases <- list()

# Unadjusted: the documented mice::pool call itself, cross-checked against the
# table built the same way as the other cases.
direct <- summary(pool(as.mira(ols_fits)), conf.int = TRUE)
ols <- pooled_table(lapply(ols_fits, coef), lapply(ols_fits, function(f) sqrt(diag(vcov(f)))), n - k)
stopifnot(max(abs(direct$std.error - sapply(ols$terms, `[[`, "std_error"))) < 1e-12)
stopifnot(max(abs(direct$df - sapply(ols$terms, `[[`, "df"))) < 1e-9)
cases$ols <- ols

cases$ols_robust <- pooled_table(
  lapply(ols_fits, coef), lapply(ols_fits, function(f) sqrt(diag(vcovHC(f, type = "HC1")))), n - k
)
cases$ols_cluster <- pooled_table(
  lapply(ols_fits, coef),
  lapply(ols_fits, function(f) sqrt(diag(vcovCL(f, cluster = ~g, type = "HC1")))),
  length(unique(g)) - 1
)

# glm reports the variance from the weights of the IRLS iterate *before* the
# last update, about 1e-9 off the variance at the estimate (v1.8.10 A01:
# enough to move a p-value near 5e-5 by 1.4e-7 relative). Refitting from the
# optimum makes the two iterates coincide, so the reference is the variance at
# the estimate, which is what Workbench reports.
logit_fits <- lapply(completed, function(d) {
  first <- glm(yb ~ x1 + x2 + x3, data = d, family = binomial(), control = glm.control(epsilon = 1e-14, maxit = 100))
  glm(yb ~ x1 + x2 + x3, data = d, family = binomial(), start = coef(first),
      control = glm.control(epsilon = 1e-14, maxit = 100))
})
direct_logit <- summary(pool(as.mira(logit_fits), dfcom = Inf))
logit <- pooled_table(lapply(logit_fits, coef), lapply(logit_fits, function(f) sqrt(diag(vcov(f)))), Inf)
stopifnot(max(abs(direct_logit$std.error - sapply(logit$terms, `[[`, "std_error"))) < 1e-12)
cases$logit <- logit

oracle <- list(
  meta = list(
    generator = "tests/fixtures/eval_v1810/a01/generate_oracle.R",
    r_version = R.version.string,
    mice_version = as.character(packageVersion("mice")),
    m = m,
    n = n,
    formula = "y ~ x1 + x2 + x3 (yb for logit)",
    imputation = "mice pmm, seed 20261003, g excluded as a predictor"
  ),
  tolerances = list(default = 1e-7),
  cases = cases
)
writeLines(toJSON(oracle, auto_unbox = TRUE, digits = NA, pretty = TRUE), file.path(here, "oracle.json"))
cat("wrote oracle.json\n")
