# Oracle generator for average marginal effects on the GLM families.
# Requires: jsonlite  (declared in tests/fixtures/r-oracle-requirements.txt)
#
# Writes, next to this file:
#   glm.csv      deterministic frame with a binary and a count outcome
#   oracle.json  coefficients and average marginal effects for logit/probit/poisson
#
# Run from the worktree root:
#   Rscript tests/fixtures/marginal_effects/generate_oracle.R
#
# VERIFICATION LEVEL, stated precisely because the two halves differ:
#   * the fit is checked against R's `glm` -- an independent implementation;
#   * the average marginal effect is built from its DEFINITION, the sample mean
#     of the analytic partial derivative, which is what Stata's
#     `margins, dydx(*)` computes.  No third-party AME implementation is
#     involved, because none is installed here.  Calling this "verified against
#     R's margins package" would be false.
#
# Derivatives used:
#   logit    dp/dx_k = b_k * p * (1 - p)
#   probit   dp/dx_k = b_k * dnorm(x'b)
#   poisson  dmu/dx_k = b_k * exp(x'b)

source("tests/fixtures/_r_oracle_env.R")
require_oracle_packages("jsonlite")
suppressMessages(library(jsonlite))

set.seed(20260806)
n <- 200
x1 <- rnorm(n)
x2 <- runif(n, -2, 2)
eta <- 0.4 + 0.9 * x1 - 0.6 * x2
p <- 1 / (1 + exp(-eta))
binary <- rbinom(n, 1, p)
count <- rpois(n, exp(0.3 + 0.5 * x1 - 0.2 * x2))

d <- data.frame(binary = binary, count = count, x1 = x1, x2 = x2)
write.csv(d, "tests/fixtures/marginal_effects/glm.csv", row.names = FALSE)

ame <- function(fit, kind) {
  b <- coef(fit)
  eta_hat <- as.numeric(model.matrix(fit) %*% b)
  scale <- switch(
    kind,
    logit = { ph <- 1 / (1 + exp(-eta_hat)); ph * (1 - ph) },
    probit = dnorm(eta_hat),
    poisson = exp(eta_hat)
  )
  slopes <- b[names(b) != "(Intercept)"]
  as.list(vapply(names(slopes), function(k) mean(scale) * slopes[[k]], numeric(1)))
}

emit <- function(fit, kind) {
  list(
    coefficients = as.list(coef(fit)),
    average_marginal_effects = ame(fit, kind)
  )
}

logit_fit <- glm(binary ~ x1 + x2, data = d, family = binomial(link = "logit"))
probit_fit <- glm(binary ~ x1 + x2, data = d, family = binomial(link = "probit"))
poisson_fit <- glm(count ~ x1 + x2, data = d, family = poisson(link = "log"))

out <- list(
  environment = oracle_environment("jsonlite"),
  verification_level = list(
    fit = "external: R stats::glm",
    average_marginal_effects = paste(
      "definitional: sample mean of the analytic partial derivative,",
      "matching Stata `margins, dydx(*)`. No third-party AME package involved."
    )
  ),
  n_obs = n,
  logit = emit(logit_fit, "logit"),
  probit = emit(probit_fit, "probit"),
  poisson = emit(poisson_fit, "poisson")
)

write_json(out, "tests/fixtures/marginal_effects/oracle.json", digits = 14, auto_unbox = TRUE)
cat("marginal-effects oracle written; n =", n, "\n")
