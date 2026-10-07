# Native lme4 references for LMM fixed-effect inference on the GLS conditional
# covariance vcov() = sigma^2 (X'V^-1 X)^-1 that lme4 and Stata mixed report.
# Four settings: REML/ML x random intercept (admission fixture) / correlated
# random intercept and slope (new seeded fixture, non-singular by design).
suppressPackageStartupMessages({ library(lme4); library(jsonlite) })
set.seed(20261007)
G <- 60; T <- 6
g <- rep(seq_len(G), each = T); time <- rep(0:(T - 1), G)
arm <- rep(ifelse(seq_len(G) %% 2 == 0, "b", "a"), each = T)
u0 <- rnorm(G, 0, 1.0); u1 <- 0.4 * u0 / 1.0 * 0.35 + rnorm(G, 0, 0.35)
x <- rnorm(G * T)
y <- 1 + 0.3 * (arm == "b") + 0.25 * time + 0.2 * (arm == "b") * time + 0.5 * x +
  u0[g] + u1[g] * time + rnorm(G * T, 0, 0.6)
slope <- data.frame(y = y, x = x, g = g, time = time, arm = arm)
write.csv(slope, "tests/fixtures/postestimation/lmm_v1811/random_slope.csv", row.names = FALSE)
intercept <- read.csv("tests/fixtures/admission/linear_mixed_effects/data.csv")

one <- function(data, random, reml) {
  fit <- lmer(as.formula(paste("y ~ arm * time + x +", random)), data = data, REML = reml,
              control = lmerControl(optimizer = "bobyqa", optCtrl = list(rhoend = 1e-12, maxfun = 1e6)))
  b <- fixef(fit); V <- as.matrix(vcov(fit))
  wald <- function(L, r) { d <- L %*% b - r; s <- as.numeric(t(d) %*% solve(L %*% V %*% t(L), d))
    list(statistic = s, df_num = nrow(L), p_value = pchisq(s, nrow(L), lower.tail = FALSE)) }
  idx <- function(n) match(n, names(b))
  Lj <- matrix(0, 2, length(b)); Lj[1, idx("time")] <- 1; Lj[2, idx("x")] <- 1
  Ls <- matrix(0, 1, length(b)); Ls[1, idx("time")] <- 1; Ls[1, idx("x")] <- -1
  l <- numeric(length(b)); l[idx("time")] <- 1; l[idx("x")] <- 2
  grad <- numeric(length(b)); grad[idx("time")] <- 1 / b[["x"]]; grad[idx("x")] <- -b[["time"]] / b[["x"]]^2
  list(converged = is.null(fit@optinfo$conv$lme4$messages), singular = isSingular(fit),
       loglik = as.numeric(logLik(fit)), params = as.list(b), std_error = as.list(sqrt(diag(V))),
       covariance = unname(V), terms = names(b),
       wald_joint = wald(Lj, c(0, 0)), wald_shifted = wald(Ls, 1),
       lincom = list(estimate = sum(l * b) - 0.5, std_error = sqrt(as.numeric(t(l) %*% V %*% l))),
       nlcom = list(estimate = b[["time"]] / b[["x"]], std_error = sqrt(as.numeric(t(grad) %*% V %*% grad))))
}
out <- list(
  environment = list(R = R.version.string, lme4 = as.character(packageVersion("lme4"))),
  definition = "lme4 vcov(): sigma^2 (X'V^-1 X)^-1 at the (RE)ML estimates",
  random_intercept_reml = one(intercept, "(1 | g)", TRUE),
  random_intercept_ml = one(intercept, "(1 | g)", FALSE),
  random_slope_reml = one(slope, "(1 + time | g)", TRUE),
  random_slope_ml = one(slope, "(1 + time | g)", FALSE))
writeLines(toJSON(out, auto_unbox = TRUE, digits = NA, pretty = TRUE), "tests/fixtures/postestimation/lmm_v1811/gls_reference_r.json")
