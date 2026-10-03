# Oracle generator for the check library (v1.8.10 step 3).
# Requires: car, jsonlite  (declared in tests/fixtures/r-oracle-requirements.txt)
#
# Writes, next to this file:
#   gvif.csv     a frame with a four-level factor and correlated regressors
#   oracle.json  GVIF per term from car::vif for linear models
#
# Run from the worktree root:
#   Rscript tests/fixtures/checks/generate_oracle.R
#
# VERIFICATION LEVEL: car::vif is an independent implementation of Fox &
# Monette's GVIF. For linear models it is computed from the coefficient
# covariance, which for OLS is proportional to (X'X)^-1, so it equals the
# design-level GVIF Workbench computes. (For GLMs car::vif uses the fitted
# weights; Workbench's check is design-level and is not compared there.)
#
# Separation: detectseparation::detect_separation (Kosmidis, Schumacher &
# Schwendinger), the linear-programming method of Konis (2007); independent.
# Overdispersion: the Cameron-Trivedi auxiliary regression exactly as
# AER::dispersiontest(trafo = 1) writes it, run with R's lm.

source("tests/fixtures/_r_oracle_env.R")
PKGS <- c("car", "detectseparation", "jsonlite")
require_oracle_packages(PKGS)
suppressMessages({
  library(car)
  library(detectseparation)
  library(jsonlite)
})

set.seed(20261003)
n <- 200
z <- rnorm(n)
d <- data.frame(
  x1 = z + rnorm(n, sd = 0.3),
  x2 = z + rnorm(n, sd = 0.3),
  x3 = rnorm(n),
  grp = factor(sample(c("a", "b", "c", "d"), n, replace = TRUE))
)
d$x4 <- as.numeric(d$grp == "b") + rnorm(n, sd = 0.5)
d$y <- 1 + d$x1 - d$x2 + 0.5 * d$x3 + 0.3 * d$x4 + rnorm(n)
write.csv(d, "tests/fixtures/checks/gvif.csv", row.names = FALSE)

gvif <- function(fit) {
  v <- vif(fit)
  if (is.matrix(v)) {
    setNames(lapply(seq_len(nrow(v)), function(i) list(gvif = v[i, 1], df = v[i, 2], gvif_adjusted = v[i, 3])),
             rownames(v))
  } else {
    setNames(lapply(v, function(value) list(gvif = value, df = 1, gvif_adjusted = sqrt(value))), names(v))
  }
}

# Binary outcomes: completely separated, quasi-completely separated, overlapping.
set.seed(7)
m <- 60
b <- data.frame(x1 = rnorm(m), x2 = rnorm(m))
b$complete <- as.integer(b$x1 > 0)
b$quasi <- as.integer(b$x1 > 0)
b$x1[1:3] <- 0
b$quasi[1:3] <- c(0L, 1L, 0L)
b$overlap <- rbinom(m, 1, plogis(0.5 * b$x1))
write.csv(b, "tests/fixtures/checks/separation.csv", row.names = FALSE)
separation_case <- function(outcome, link) {
  fit <- glm(as.formula(paste(outcome, "~ x1 + x2")), family = binomial(link), data = b,
             method = "detect_separation")
  list(separated = fit$outcome, coefficients = as.list(fit$coefficients))
}
separation <- list()
for (outcome in c("complete", "quasi", "overlap")) for (link in c("logit", "probit")) {
  separation[[paste(outcome, link, sep = "_")]] <- separation_case(outcome, link)
}

# Count outcomes: overdispersed (negative binomial draws) and equidispersed.
cnt <- data.frame(x = rnorm(300))
cnt$over <- rnbinom(300, mu = exp(0.5 + 0.4 * cnt$x), size = 1.5)
cnt$equi <- rpois(300, exp(0.5 + 0.4 * cnt$x))
write.csv(cnt, "tests/fixtures/checks/counts.csv", row.names = FALSE)
cameron_trivedi <- function(outcome) {
  fit <- glm(as.formula(paste(outcome, "~ x")), family = poisson, data = cnt)
  y <- fit$y
  mu <- fitted(fit)
  aux <- lm(((y - mu)^2 - y) / mu ~ 0 + mu)
  t <- coef(summary(aux))[1, 3]
  list(alpha = unname(coef(aux)[1]), t = t, p_value = pt(t, df.residual(aux), lower.tail = FALSE))
}

cross <- read.csv("examples/datasets/cross_section.csv")
oracle <- list(
  generator = "tests/fixtures/checks/generate_oracle.R",
  environment = oracle_environment(PKGS),
  cross_section_two = gvif(lm(wage ~ education + experience, cross)),
  cross_section_region = gvif(lm(wage ~ education + experience + region, cross)),
  factor_frame = gvif(lm(y ~ x1 + x2 + x3 + x4 + grp, d)),
  separation = separation,
  overdispersion = list(over = cameron_trivedi("over"), equi = cameron_trivedi("equi"))
)
write_json(oracle, "tests/fixtures/checks/oracle.json", auto_unbox = TRUE, digits = NA, pretty = TRUE)
cat("wrote tests/fixtures/checks/oracle.json\n")
