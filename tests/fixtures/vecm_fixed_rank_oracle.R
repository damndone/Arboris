arguments <- as.integer(commandArgs(trailingOnly = TRUE))
lag_differences <- arguments[1L]
horizon <- arguments[2L]
training <- matrix(scan(file("stdin"), quiet = TRUE), byrow = TRUE, ncol = 2L)
colnames(training) <- c("first", "second")

levels_order <- lag_differences + 1L
johansen <- urca::ca.jo(training, type = "trace", ecdet = "const",
                        K = levels_order, spec = "transitory")
fixed <- urca::cajorls(johansen, r = 1L)
beta <- as.numeric(fixed$beta)
fit <- stats::coef(fixed$rlm)
alpha <- fit[1L, ]
innovations <- stats::residuals(fixed$rlm)
sigma <- crossprod(innovations) / nrow(innovations)
gamma <- lapply(seq_len(lag_differences), function(lag) {
    t(fit[1L + 2L * (lag - 1L) + 1L:2L, , drop = FALSE])
})
pi_levels <- tcrossprod(alpha, beta[1L:2L])
drift <- alpha * beta[3L]

levels_coefficients <- list(diag(2L) + pi_levels + gamma[[1L]])
if (lag_differences > 1L) {
    for (lag in 2L:lag_differences) {
        levels_coefficients[[lag]] <- gamma[[lag]] - gamma[[lag - 1L]]
    }
}
levels_coefficients[[levels_order]] <- -gamma[[lag_differences]]
state_size <- 2L * levels_order
companion <- matrix(0, state_size, state_size)
companion[1L:2L, ] <- do.call(cbind, levels_coefficients)
companion[3L:state_size, seq_len(state_size - 2L)] <- diag(state_size - 2L)
state <- as.vector(t(training[nrow(training) - seq_len(levels_order) + 1L, , drop = FALSE]))
state_drift <- c(drift, rep(0, state_size - 2L))
innovation_state <- matrix(0, state_size, state_size)
innovation_state[1L:2L, 1L:2L] <- sigma
state_covariance <- matrix(0, state_size, state_size)
forecast <- numeric()
for (step in seq_len(horizon)) {
    state <- drop(companion %*% state) + state_drift
    state_covariance <- companion %*% state_covariance %*% t(companion) + innovation_state
    forecast <- c(forecast, state[1L:2L], as.vector(t(state_covariance[1L:2L, 1L:2L])))
}

emit <- function(name, values) {
    cat(name, paste(sprintf("%.17g", values), collapse = "\t"), sep = "\t")
    cat("\n")
}
emit("n_fit", nrow(innovations))
emit("lambda", johansen@lambda[1L:2L])
emit("beta", beta)
emit("alpha", alpha)
emit("gamma", unlist(lapply(gamma, function(matrix) as.vector(t(matrix)))))
emit("pi_levels", as.vector(t(pi_levels)))
emit("restricted_drift", drift)
emit("innovation_covariance", as.vector(t(sigma)))
emit("forecast", forecast)
