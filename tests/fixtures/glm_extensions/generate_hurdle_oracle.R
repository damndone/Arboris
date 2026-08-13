options(digits = 17)

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1) {
  stop("expected one CSV path")
}
df <- read.csv(args[[1]])
positive <- df$y > 0
y <- df$y[positive]
design <- cbind(1, df$x[positive])

negative_log_likelihood <- function(parameters) {
  eta <- as.vector(design %*% parameters)
  mu <- exp(eta)
  log_pmf <- y * eta - mu - lgamma(y + 1)
  log_positive <- log(-expm1(-mu))
  -sum(log_pmf - log_positive)
}

initial <- coef(glm(y ~ df$x[positive], family = poisson()))
fit <- optim(
  initial,
  negative_log_likelihood,
  method = "BFGS",
  control = list(maxit = 300, reltol = 1e-12)
)
if (fit$convergence != 0) {
  stop("base R hurdle oracle did not converge")
}
hessian <- optimHess(fit$par, negative_log_likelihood)
standard_error <- sqrt(diag(solve(hessian)))
cat(sprintf(
  '{"estimate":[%.17g,%.17g],"standard_error":[%.17g,%.17g]}\n',
  fit$par[[1]], fit$par[[2]], standard_error[[1]], standard_error[[2]]
))
