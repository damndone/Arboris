args <- commandArgs(trailingOnly = TRUE)
values <- as.matrix(read.csv(args[1], header = FALSE))
theta <- as.numeric(args[2])
include_intercept <- as.logical(args[3])
horizon <- as.integer(args[4])
n <- nrow(values) - 1L

design <- values[seq_len(n), , drop = FALSE]
if (include_intercept) design <- cbind(1, design)
response <- values[seq_len(n) + 1L, , drop = FALSE]
whiten <- function(x) vapply(seq_len(ncol(x)), function(j) {
  as.numeric(stats::filter(x[, j], -theta, method = "recursive", init = 0))
}, numeric(n))
fit <- stats::lm.fit(whiten(design), whiten(response), tol = 1e-12, singular.ok = FALSE)
intercept <- if (include_intercept) fit$coefficients[1L, ] else c(0, 0)
ar <- t(tail(fit$coefficients, 2L))
sigma <- crossprod(fit$residuals) / n
last_innovation <- fit$residuals[n, ]
factor <- chol(sigma)
standardized <- forwardsolve(t(factor), t(fit$residuals))
loglik <- -n * (log(2 * pi) + sum(log(diag(factor)))) - sum(standardized^2) / 2

identity <- diag(2L)
zero <- matrix(0, 2L, 2L)
transition <- rbind(cbind(ar, theta * identity), cbind(zero, zero))
selection <- rbind(identity, identity)
process_covariance <- selection %*% sigma %*% t(selection)
state <- c(values[n + 1L, ], last_innovation)
state_covariance <- matrix(0, 4L, 4L)
forecast <- matrix(NA_real_, horizon, 6L)
for (step in seq_len(horizon)) {
  state <- c(intercept, 0, 0) + transition %*% state
  state_covariance <- transition %*% state_covariance %*% t(transition) + process_covariance
  forecast[step, ] <- c(state[1:2], as.vector(t(state_covariance[1:2, 1:2])))
}

emit <- function(key, value) {
  cat(key, paste(formatC(value, digits = 17, format = "g"), collapse = " "), sep = "\t")
  cat("\n")
}
emit("n_fit", n)
emit("intercept", intercept)
emit("ar", as.vector(t(ar)))
emit("innovation_covariance", as.vector(t(sigma)))
emit("last_innovation", last_innovation)
emit("conditional_log_likelihood", loglik)
emit("forecast", as.vector(t(forecast)))
