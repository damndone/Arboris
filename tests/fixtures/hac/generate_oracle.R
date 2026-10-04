# Oracle generator for HAC (Newey-West) OLS standard errors (v1.8.10 step 6).
# Requires: sandwich, jsonlite (tests/fixtures/r-oracle-requirements.txt)
#
# Writes, next to this file:
#   data.csv     an annual series, rows deliberately shuffled
#   oracle.json  Newey-West standard errors and a joint Wald F per lag
#
# Run from the worktree root:
#   Rscript tests/fixtures/hac/generate_oracle.R
#
# VERIFICATION LEVEL:
#   * sandwich::NeweyWest(prewhite = FALSE, adjust = TRUE): Bartlett kernel,
#     no prewhitening, N/(N - K) scaling -- the settings that match Stata's
#     `newey` (R's default prewhite = TRUE does not). Tests also run Stata
#     `newey, lag()` and `test` live when Stata is installed.
#   * The rows are shuffled: the estimator must order them by time itself.
#   * Joint test: F = (Rb)' (R V R')^-1 (Rb) / q on t(N - K), as Stata's `test`.

suppressPackageStartupMessages({
  library(sandwich)
  library(jsonlite)
})

here <- "tests/fixtures/hac"
set.seed(20261003)
n <- 150
year <- 1871:(1871 + n - 1)
e <- as.numeric(arima.sim(list(ar = 0.7), n))
x1 <- as.numeric(arima.sim(list(ar = 0.6), n))
x2 <- as.numeric(arima.sim(list(ar = 0.3), n))
y <- 2 + 0.4 * x1 - 0.25 * x2 + e
data <- data.frame(year = year, y = y, x1 = x1, x2 = x2)
shuffled <- data[sample.int(n), ]
write.csv(shuffled, file.path(here, "data.csv"), row.names = FALSE)

fit <- lm(y ~ x1 + x2, data = data)  # in time order
default_lag <- floor(4 * (n / 100)^(2 / 9))
cases <- list()
for (lag in unique(c(0, 4, 8, default_lag))) {
  V <- NeweyWest(fit, lag = lag, prewhite = FALSE, adjust = TRUE)
  se <- sqrt(diag(V))
  names(se)[names(se) == "(Intercept)"] <- "Intercept"
  b <- coef(fit)
  R <- rbind(c(0, 1, 0), c(0, 0, 1))
  rb <- R %*% b
  f <- as.numeric(t(rb) %*% solve(R %*% V %*% t(R)) %*% rb) / 2
  cases[[paste0("lag_", lag)]] <- list(
    lag = lag,
    std_error = as.list(se),
    wald_x1_x2 = list(F = f, df_num = 2, df_den = fit$df.residual,
                      p_value = pf(f, 2, fit$df.residual, lower.tail = FALSE))
  )
}

oracle <- list(
  meta = list(
    generator = "tests/fixtures/hac/generate_oracle.R",
    r_version = R.version.string,
    sandwich_version = as.character(packageVersion("sandwich")),
    n = n,
    default_lag = default_lag,
    formula = "y ~ x1 + x2, time order: year"
  ),
  tolerances = list(default = 1e-9),
  coefficients = as.list(setNames(coef(fit), c("Intercept", "x1", "x2"))),
  cases = cases
)
writeLines(toJSON(oracle, auto_unbox = TRUE, digits = NA, pretty = TRUE), file.path(here, "oracle.json"))
cat("wrote oracle.json; default lag", default_lag, "\n")
