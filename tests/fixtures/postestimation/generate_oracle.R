# Oracle generator for post-estimation on the inference kernel (v1.8.10 step 2).
# Requires: car, lmtest, sandwich, MASS, jsonlite
#   (declared in tests/fixtures/r-oracle-requirements.txt)
#
# Writes, next to this file:
#   data.csv     deterministic frame with continuous, binary and count outcomes
#   oracle.json  Wald, lincom, nlcom and LR results per model family
#
# Run from the worktree root:
#   Rscript tests/fixtures/postestimation/generate_oracle.R
#
# VERIFICATION LEVEL:
#   * Wald: car::linearHypothesis -- F(q, n-k) for lm, chi2(q) for glm and for a
#     z-based robust covariance; an independent implementation.
#   * lincom and nlcom: car::deltaMethod, which differentiates the expression
#     symbolically; Workbench differentiates numerically, so agreement checks
#     both the gradient and the variance algebra.
#   * LR: lmtest::lrtest; an independent implementation.
#   * probit covariance: R's glm reports the EXPECTED information, while Stata's
#     `probit` (and statsmodels) report the OBSERVED information; for a
#     non-canonical link the two differ (about 1% here). The probit oracle uses
#     the observed information, written out analytically below, so it matches
#     Stata's default. logit and Poisson use canonical links, where the two
#     coincide.
#   * Every glm is converged to 1e-14 rather than R's default 1e-8, so the
#     comparison measures the post-estimation, not the optimiser's tolerance.
#   Stata is not installed here; every figure below is R's.

source("tests/fixtures/_r_oracle_env.R")
PKGS <- c("car", "lmtest", "sandwich", "MASS", "jsonlite")
require_oracle_packages(PKGS)
suppressMessages({
  library(car)
  library(lmtest)
  library(sandwich)
  library(MASS)
  library(jsonlite)
})

set.seed(20261002)
n <- 300
x1 <- rnorm(n)
x2 <- runif(n, -2, 2)
x3 <- rnorm(n, 1, 0.5)
eta <- 0.3 + 0.8 * x1 - 0.5 * x2 + 0.2 * x3
d <- data.frame(
  y = 1 + 0.6 * x1 - 0.4 * x2 + 0.1 * x3 + rnorm(n),
  yb = rbinom(n, 1, 1 / (1 + exp(-eta))),
  yc = rpois(n, exp(0.2 + 0.4 * x1 - 0.2 * x2 + 0.1 * x3)),
  ynb = rnbinom(n, mu = exp(0.5 + 0.4 * x1 - 0.3 * x2), size = 2),
  x1 = x1, x2 = x2, x3 = x3
)
write.csv(d, "tests/fixtures/postestimation/data.csv", row.names = FALSE)

wald <- function(fit, hyp, test, vcov. = NULL) {
  h <- if (is.null(vcov.)) linearHypothesis(fit, hyp, test = test)
       else linearHypothesis(fit, hyp, test = test, vcov. = vcov.)
  row <- h[2, ]
  if (test == "F") {
    list(distribution = "F", statistic = row[["F"]], df_num = row[["Df"]],
         df_den = row[["Res.Df"]], p_value = row[["Pr(>F)"]])
  } else {
    list(distribution = "chi2", statistic = row[["Chisq"]], df_num = row[["Df"]],
         p_value = row[["Pr(>Chisq)"]])
  }
}

delta <- function(fit, expr, vcov. = NULL) {
  dm <- if (is.null(vcov.)) deltaMethod(fit, expr) else deltaMethod(fit, expr, vcov. = vcov.)
  list(estimate = dm[["Estimate"]], std_error = dm[["SE"]])
}

lr <- function(full, restricted) {
  t <- lrtest(restricted, full)
  list(statistic = t[2, "Chisq"], df = t[2, "Df"], p_value = t[2, "Pr(>Chisq)"],
       loglik_full = as.numeric(logLik(full)), loglik_restricted = as.numeric(logLik(restricted)))
}

# The same hypotheses for every family, written once.
H_JOINT <- c("x1 = 0", "x2 = 0")
H_SHIFTED <- c("x1 - x2 = 1")
LINCOM <- "x1 + 2*x2 - 0.5"
NLCOM <- "x1 / x2"

family_case <- function(full, restricted, test, vcov. = NULL) {
  out <- list(
    params = as.list(coef(full)),
    wald_joint = wald(full, H_JOINT, test, vcov.),
    wald_shifted = wald(full, H_SHIFTED, test, vcov.),
    lincom = delta(full, LINCOM, vcov.),
    nlcom = delta(full, NLCOM, vcov.)
  )
  if (!is.null(restricted)) out$lr_drop_x2_x3 <- lr(full, restricted)
  out
}

TIGHT <- glm.control(epsilon = 1e-14, maxit = 200)

# Observed information of a probit fit (Stata's default; see the header).
probit_oim_vcov <- function(fit) {
  X <- model.matrix(fit)
  eta <- as.vector(X %*% coef(fit))
  y <- fit$y
  lambda <- ifelse(y == 1, dnorm(eta) / pnorm(eta), -dnorm(eta) / pnorm(-eta))
  weight <- lambda * (lambda + eta)
  v <- solve(crossprod(X * weight, X))
  dimnames(v) <- list(names(coef(fit)), names(coef(fit)))
  v
}

ols <- lm(y ~ x1 + x2 + x3, data = d)
ols_r <- lm(y ~ x1, data = d)
logit <- glm(yb ~ x1 + x2 + x3, family = binomial("logit"), data = d, control = TIGHT)
logit_r <- glm(yb ~ x1, family = binomial("logit"), data = d, control = TIGHT)
probit <- glm(yb ~ x1 + x2 + x3, family = binomial("probit"), data = d, control = TIGHT)
probit_r <- glm(yb ~ x1, family = binomial("probit"), data = d, control = TIGHT)
poisson <- glm(yc ~ x1 + x2 + x3, family = poisson("log"), data = d, control = TIGHT)
poisson_r <- glm(yc ~ x1, family = poisson("log"), data = d, control = TIGHT)
negbin <- glm.nb(ynb ~ x1 + x2 + x3, data = d, control = TIGHT)

oracle <- list(
  generator = "tests/fixtures/postestimation/generate_oracle.R",
  environment = oracle_environment(PKGS),
  hypotheses = list(joint = H_JOINT, shifted = H_SHIFTED, lincom = LINCOM, nlcom = NLCOM),
  restricted_model = "outcome ~ x1",
  families = list(
    ols = family_case(ols, ols_r, "F"),
    # Workbench reports HC1 robust inference on the normal scale, so the
    # oracle's robust Wald is chi2 with the same HC1 covariance.
    ols_robust = family_case(ols, NULL, "Chisq", vcovHC(ols, type = "HC1")),
    logit = family_case(logit, logit_r, "Chisq"),
    probit = family_case(probit, probit_r, "Chisq", probit_oim_vcov(probit)),
    poisson = family_case(poisson, poisson_r, "Chisq"),
    negative_binomial = family_case(negbin, NULL, "Chisq")
  )
)
oracle$families$negative_binomial$theta <- negbin$theta
write_json(oracle, "tests/fixtures/postestimation/oracle.json", auto_unbox = TRUE, digits = NA, pretty = TRUE)
cat("wrote tests/fixtures/postestimation/oracle.json\n")
