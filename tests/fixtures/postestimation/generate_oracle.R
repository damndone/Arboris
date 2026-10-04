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
#   * Marginal effects: marginaleffects::avg_slopes (average) and
#     slopes(newdata = "mean") (at the means), which differentiate numerically
#     and apply the delta method; an independent implementation.
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
PKGS <- c("car", "lmtest", "sandwich", "MASS", "nnet", "marginaleffects", "jsonlite")
require_oracle_packages(PKGS)
suppressMessages({
  library(car)
  library(lmtest)
  library(sandwich)
  library(MASS)
  library(nnet)
  library(marginaleffects)
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
# Drawn after the columns above, so adding them left those columns unchanged.
latent <- 0.8 * x1 - 0.6 * x2 + 0.3 * x3 + rlogis(n)
d$yo <- cut(latent, c(-Inf, -0.4, 0.9, Inf), labels = c("low", "mid", "high"))
util_b <- 0.2 + 0.7 * x1 - 0.3 * x2
util_c <- -0.1 - 0.5 * x1 + 0.6 * x3
u <- cbind(0, util_b, util_c) + matrix(-log(-log(runif(3 * n))), n, 3)
d$ym <- c("a", "b", "c")[max.col(u)]
# Cluster labels for the clustered-OLS case (16 clusters), drawn last.
d$g <- sample(sprintf("c%02d", 1:16), n, replace = TRUE)
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

margins_case <- function(fit, vcov. = NULL) {
  v <- if (is.null(vcov.)) TRUE else vcov.
  pick <- function(x) {
    x <- data.frame(x)
    setNames(lapply(seq_len(nrow(x)), function(i) list(estimate = x$estimate[i], std_error = x$std.error[i])), x$term)
  }
  list(
    average = pick(avg_slopes(fit, variables = c("x1", "x2"), vcov = v)),
    at_means = pick(slopes(fit, variables = c("x1", "x2"), newdata = "mean", vcov = v))
  )
}

# Inference engine v2: robust OLS tests against t(N - K) and F(q, N - K);
# clustered OLS against t(G - 1) and F(q, G - 1), Stata's `regress` rules.
coef_tests <- function(fit, vcov., df) {
  ct <- coeftest(fit, vcov. = vcov., df = df)
  ci <- coefci(fit, vcov. = vcov., df = df)
  setNames(lapply(c("x1", "x2", "x3"), function(term) list(
    estimate = ct[term, 1], std_error = ct[term, 2], statistic = ct[term, 3], p_value = ct[term, 4],
    ci = unname(ci[term, ])
  )), c("x1", "x2", "x3"))
}

cluster_wald <- function(fit, hyp, vcov., df_den) {
  h <- linearHypothesis(fit, hyp, test = "Chisq", vcov. = vcov.)
  q <- h[2, "Df"]
  stat <- h[2, "Chisq"] / q
  list(distribution = "F", statistic = stat, df_num = q, df_den = df_den,
       p_value = pf(stat, q, df_den, lower.tail = FALSE))
}

family_case <- function(full, restricted, test, vcov. = NULL) {
  out <- list(
    params = as.list(coef(full)),
    wald_joint = wald(full, H_JOINT, test, vcov.),
    wald_shifted = wald(full, H_SHIFTED, test, vcov.),
    lincom = delta(full, LINCOM, vcov.),
    nlcom = delta(full, NLCOM, vcov.)
  )
  if (!is.null(restricted)) out$lr_drop_x2_x3 <- lr(full, restricted)
  if (!is.null(restricted)) out$margins <- margins_case(full, vcov.)
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
# glm.nb reports the expected information with theta held fixed; Stata's
# `nbreg` and statsmodels report the observed information of the joint
# likelihood in (beta, alpha). The log link is not canonical for NB2, so the
# two differ (about 5% on the Wald statistic here). The oracle uses the joint
# observed information: the Hessian of the full log-likelihood at the MLE, with
# an analytic gradient so optimHess differentiates only once.
negbin_oim_vcov <- function(fit) {
  X <- model.matrix(fit)
  y <- fit$y
  k <- ncol(X)
  nll <- function(par) {
    mu <- exp(as.vector(X %*% par[1:k]))
    -sum(dnbinom(y, size = par[k + 1], mu = mu, log = TRUE))
  }
  grad <- function(par) {
    theta <- par[k + 1]
    mu <- exp(as.vector(X %*% par[1:k]))
    d_eta <- (y - mu) * theta / (theta + mu)
    d_theta <- digamma(y + theta) - digamma(theta) + log(theta / (theta + mu)) + (mu - y) / (theta + mu)
    -c(colSums(X * d_eta), sum(d_theta))
  }
  par <- c(coef(fit), fit$theta)
  v <- solve(optimHess(par, nll, grad, control = list(ndeps = rep(1e-6, k + 1))))[1:k, 1:k]
  dimnames(v) <- list(names(coef(fit)), names(coef(fit)))
  v
}
# polr and multinom estimate their Hessians numerically (optim), so they agree
# with Workbench's analytic Hessians only to about 1e-4; the tolerance used is
# recorded below with the reason.
ordinal <- polr(factor(yo, levels = c("low", "mid", "high")) ~ x1 + x2 + x3, data = d,
                Hess = TRUE, control = list(reltol = 1e-14, maxit = 1000))
multinomial <- multinom(factor(ym) ~ x1 + x2 + x3, data = d, Hess = TRUE, trace = FALSE,
                        reltol = 1e-14, maxit = 1000)

# Wald and lincom on slopes only: the families' threshold and intercept
# parameterisations differ between R and Workbench, the slopes do not.
slopes_case <- function(fit, prefix = "") {
  b <- coef(fit)
  if (is.matrix(b)) b <- setNames(as.vector(t(b)), paste0(rep(rownames(b), each = ncol(b)), ":", colnames(b)))
  v <- vcov(fit)
  name <- function(term) paste0(prefix, term)
  idx <- c(name("x1"), name("x2"))
  bj <- b[idx]
  vj <- v[idx, idx]
  stat <- as.numeric(t(bj) %*% solve(vj) %*% bj)
  w <- c(1, 2)
  list(
    params = as.list(b),
    wald_joint = list(distribution = "chi2", statistic = stat, df_num = 2,
                      p_value = pchisq(stat, 2, lower.tail = FALSE)),
    lincom = list(estimate = sum(w * bj) - 0.5, std_error = sqrt(as.numeric(t(w) %*% vj %*% w)))
  )
}

oracle <- list(
  generator = "tests/fixtures/postestimation/generate_oracle.R",
  environment = oracle_environment(PKGS),
  hypotheses = list(joint = H_JOINT, shifted = H_SHIFTED, lincom = LINCOM, nlcom = NLCOM),
  restricted_model = "outcome ~ x1",
  families = list(
    ols = family_case(ols, ols_r, "F"),
    # HC1 with t(N - K) and F(q, N - K): Stata's `regress, vce(robust)`.
    ols_robust = c(family_case(ols, NULL, "F", vcovHC(ols, type = "HC1")),
                   list(coef_tests = coef_tests(ols, vcovHC(ols, type = "HC1"), df.residual(ols)))),
    # CR1 (G/(G-1) * (N-1)/(N-K)) with t(G - 1) and F(q, G - 1): Stata's
    # `regress, vce(cluster g)`; sandwich's vcovCL type HC1 is the same matrix.
    ols_cluster = local({
      v <- vcovCL(ols, cluster = ~g, type = "HC1")
      G <- length(unique(d$g))
      list(
        n_clusters = G,
        wald_joint = cluster_wald(ols, H_JOINT, v, G - 1),
        wald_shifted = cluster_wald(ols, H_SHIFTED, v, G - 1),
        coef_tests = coef_tests(ols, v, G - 1)
      )
    }),
    logit = family_case(logit, logit_r, "Chisq"),
    probit = family_case(probit, probit_r, "Chisq", probit_oim_vcov(probit)),
    poisson = family_case(poisson, poisson_r, "Chisq"),
    negative_binomial = family_case(negbin, NULL, "Chisq", negbin_oim_vcov(negbin)),
    ordinal_logit = slopes_case(ordinal),
    multinomial_logit = slopes_case(multinomial, "b:")
  ),
  tolerances = list(
    default = 1e-6,
    negative_binomial = list(rel = 1e-4, reason = paste(
      "the joint observed information is differentiated numerically (optimHess)",
      "from an analytic gradient")),
    ordinal_logit = list(rel = 1e-4, reason = "polr's Hessian is computed numerically by optim"),
    multinomial_logit = list(rel = 1e-4, reason = "multinom's Hessian is computed numerically")
  )
)
oracle$families$negative_binomial$theta <- negbin$theta
write_json(oracle, "tests/fixtures/postestimation/oracle.json", auto_unbox = TRUE, digits = NA, pretty = TRUE)
cat("wrote tests/fixtures/postestimation/oracle.json\n")
