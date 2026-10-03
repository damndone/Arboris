# Oracle generator for by-group group-difference tests (v1.8.10 step 7).
# Requires: car, sandwich, jsonlite (tests/fixtures/r-oracle-requirements.txt)
#
# Writes, next to this file:
#   data.csv     four regions with different slopes; outcomes for OLS, logit,
#                probit and Poisson
#   oracle.json  Wald tests of group differences from the fully interacted
#                pooled model, per family
#
# Run from the worktree root:
#   Rscript tests/fixtures/by_group/generate_oracle.R
#
# VERIFICATION LEVEL:
#   * The group-difference test is the pooled model with region fully
#     interacted with every regressor, y ~ region * (x1 + x2), and a Wald test
#     on the region terms: all of them (are the groups' coefficients the same?)
#     and, per regressor, region:x (is that regressor's effect the same?).
#     car::linearHypothesis -- an independent implementation.
#   * Covariance as each family runs by default in Workbench: OLS with HC1
#     (sandwich::vcovHC type "HC1") and F(q, N - K); logit, probit and Poisson
#     with the model-based covariance and chi-square(q). probit uses the
#     observed information (as Stata and statsmodels); glm converged to 1e-14.
#   * The reference group is the first in sorted order (east), as in Workbench.

suppressPackageStartupMessages({
  library(car)
  library(sandwich)
  library(jsonlite)
})

here <- "tests/fixtures/by_group"
set.seed(20261003)
n <- 1200
region <- sample(c("east", "north", "south", "west"), n, replace = TRUE)
x1 <- rnorm(n)
x2 <- rnorm(n)
shift <- c(east = 0.2, north = 0.6, south = -0.4, west = 0)[region]
y <- 1 + (0.5 + shift) * x1 - 0.3 * x2 + rnorm(n)
yb <- as.integer(runif(n) < plogis(-0.2 + (0.8 + shift) * x1 - 0.4 * x2))
yc <- rpois(n, exp(0.3 + (0.3 + shift / 2) * x1 - 0.2 * x2))
data <- data.frame(region = region, y = y, yb = yb, yc = yc, x1 = x1, x2 = x2)
write.csv(data, file.path(here, "data.csv"), row.names = FALSE)
data$region <- factor(data$region)

ctrl <- glm.control(epsilon = 1e-14, maxit = 100)
probit_observed_vcov <- function(fit) {
  X <- model.matrix(fit)
  eta <- as.vector(X %*% coef(fit))
  yv <- fit$y
  P <- pnorm(eta); d <- dnorm(eta)
  w <- d * (d * (yv / P^2 + (1 - yv) / (1 - P)^2) + eta * (yv / P - (1 - yv) / (1 - P)))
  solve(t(X * w) %*% X)
}

tests_for <- function(fit, V, f_test) {
  terms <- names(coef(fit))
  group_terms <- grep("^region", terms, value = TRUE)
  out <- list()
  run <- function(name, hyp) {
    h <- linearHypothesis(fit, hyp, vcov. = V, test = if (f_test) "F" else "Chisq")
    if (f_test) {
      out[[name]] <<- list(statistic = h$F[2], df_num = h$Df[2], df_den = h$Res.Df[2], p_value = h$`Pr(>F)`[2])
    } else {
      out[[name]] <<- list(statistic = h$Chisq[2], df_num = h$Df[2], p_value = h$`Pr(>Chisq)`[2])
    }
  }
  run("all", group_terms)
  for (x in c("x1", "x2")) run(x, grep(paste0(":", x, "$"), group_terms, value = TRUE))
  out
}

cases <- list()
ols <- lm(y ~ region * (x1 + x2), data = data)
cases$ols <- tests_for(ols, vcovHC(ols, type = "HC1"), TRUE)
logit <- glm(yb ~ region * (x1 + x2), data = data, family = binomial(), control = ctrl)
cases$logit <- tests_for(logit, vcov(logit), FALSE)
probit <- glm(yb ~ region * (x1 + x2), data = data, family = binomial("probit"), control = ctrl)
cases$probit <- tests_for(probit, probit_observed_vcov(probit), FALSE)
poisson <- glm(yc ~ region * (x1 + x2), data = data, family = poisson(), control = ctrl)
cases$poisson <- tests_for(poisson, vcov(poisson), FALSE)

oracle <- list(
  meta = list(generator = "tests/fixtures/by_group/generate_oracle.R", r_version = R.version.string,
              car_version = as.character(packageVersion("car")), n = n, reference_group = "east"),
  tolerances = list(default = 1e-7),
  cases = cases
)
writeLines(toJSON(oracle, auto_unbox = TRUE, digits = NA, pretty = TRUE), file.path(here, "oracle.json"))
cat("wrote oracle.json\n")
