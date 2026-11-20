# Oracle for the opt-in fast IV engine (v1.9.1): R fixest, independent of linearmodels.
# Requires: fixest, jsonlite (tests/fixtures/r-oracle-requirements.txt)
#
# Writes, next to this file:
#   data.csv     400 rows: y, w (exogenous), d1 d2 (endogenous), z1 z2 z3 (instruments)
#   oracle.json  coefficients and standard errors per design and covariance, first-stage
#                Wald, Wu-Hausman and Sargan statistics
#
# Run from the worktree root:
#   Rscript tests/fixtures/fast_engine_iv/generate_oracle.R
#
# VERIFICATION LEVEL:
#   * ssc(adj = FALSE, cluster.adj = FALSE): no small-sample factor, as linearmodels with
#     debiased = false. "hetero" is then HC0 on the second-stage regressors.
#   * fixest's "iid" sigma^2 divides by n - 1 even with adj = FALSE; the product (linearmodels,
#     debiased = false) divides by n. std_error under "unadjusted" is fixest's value times
#     sqrt((n - 1) / n); fixest's own value is kept as std_error_fixest. Its first-stage Wald F
#     uses the same n - 1 variance, so first_stage_wald_f_unadjusted is fixest's times n / (n - 1).
#   * Statistics come from fixest::fitstat: ivwald1 (first-stage Wald F, iid), wh, sargan.
source("tests/fixtures/_r_oracle_env.R")
packages <- require_oracle_packages("fixest", "jsonlite")
suppressPackageStartupMessages({ library(fixest); library(jsonlite) })
options(digits = 17)
here <- "tests/fixtures/fast_engine_iv"
set.seed(20261103)
n <- 400
z1 <- rnorm(n); z2 <- rnorm(n); z3 <- rnorm(n); w <- rnorm(n); u <- rnorm(n)
d1 <- 0.6 * z1 + 0.4 * z2 + 0.5 * u + rnorm(n)
d2 <- -0.3 * z1 + 0.7 * z3 + 0.2 * w - 0.4 * u + rnorm(n)
y <- 1 + 0.3 * w + 0.8 * d1 - 0.5 * d2 + u * (1 + abs(w))
data <- data.frame(y = y, w = w, d1 = d1, d2 = d2, z1 = z1, z2 = z2, z3 = z3)
write.csv(data, file.path(here, "data.csv"), row.names = FALSE)
data <- read.csv(file.path(here, "data.csv"))

designs <- list(
  over = list(formula = y ~ w | d1 ~ z1 + z2, endog = "d1", instruments = c("z1", "z2")),
  just = list(formula = y ~ w | d1 ~ z1, endog = "d1", instruments = "z1"),
  two_endogenous = list(formula = y ~ w | d1 + d2 ~ z1 + z2 + z3, endog = c("d1", "d2"),
                        instruments = c("z1", "z2", "z3"))
)
named <- function(values) {
  names(values) <- sub("^fit_", "", sub("^\\(Intercept\\)$", "Intercept", names(values)))
  as.list(values)
}
cases <- list()
for (name in names(designs)) {
  design <- designs[[name]]
  out <- list(endog = design$endog, instruments = design$instruments)
  for (covariance in c("robust", "unadjusted")) {
    vcov_type <- if (covariance == "robust") "hetero" else "iid"
    fit <- feols(design$formula, data = data, vcov = vcov_type, ssc = ssc(adj = FALSE, cluster.adj = FALSE))
    rescale <- if (covariance == "unadjusted") sqrt((n - 1) / n) else 1
    out[[covariance]] <- list(coefficients = named(coef(fit)), std_error = named(se(fit) * rescale),
                              std_error_fixest = named(se(fit)))
  }
  iid <- feols(design$formula, data = data, vcov = "iid", ssc = ssc(adj = FALSE, cluster.adj = FALSE))
  first <- fitstat(iid, "ivwald1", simplify = FALSE)
  out$first_stage_wald_f_fixest <- lapply(first, function(item) item$stat)
  names(out$first_stage_wald_f_fixest) <- sub("^ivwald1::", "", names(first))
  out$first_stage_wald_f_unadjusted <- lapply(out$first_stage_wald_f_fixest, function(stat) stat * n / (n - 1))
  out$wu_hausman <- fitstat(iid, "wh")$wh$stat
  if (length(design$instruments) > length(design$endog)) out$sargan <- fitstat(iid, "sargan")$sargan$stat
  cases[[name]] <- out
}
oracle <- list(
  meta = list(generator = "tests/fixtures/fast_engine_iv/generate_oracle.R", n = n,
              environment = oracle_environment(names(packages))),
  cases = cases
)
write_json(oracle, file.path(here, "oracle.json"), auto_unbox = TRUE, digits = 17, pretty = TRUE)
