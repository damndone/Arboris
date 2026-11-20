parameters <- as.numeric(commandArgs(trailingOnly = TRUE))
stopifnot(length(parameters) == 6)
period <- as.integer(parameters[1])
horizon <- as.integer(parameters[2])
alpha <- parameters[3]
beta <- parameters[4]
gamma <- parameters[5]
confidence <- parameters[6]
values <- scan(file("stdin"), quiet = TRUE)
stopifnot(length(values) >= 3 * period, period >= 2)

clock <- seq_len(2 * period)
phase <- factor(rep(seq_len(period), 2))
warm <- values[clock]
initial <- stats::coef(stats::lm(warm ~ 0 + phase + clock))
slope <- initial[[period + 1L]]
phase_intercepts <- initial[seq_len(period)]
level <- mean(phase_intercepts) + max(clock) * slope
season <- phase_intercepts - mean(phase_intercepts)

retained <- stats::ts(values[-seq_len(period)], frequency = period)
fixed_fit <- function(weight) {
    stats::HoltWinters(retained, alpha = weight, beta = beta, gamma = gamma,
                      seasonal = "additive", l.start = level, b.start = slope,
                      s.start = unname(season))
}
grid <- seq_len(20L) / 20
objectives <- numeric(0)
if (is.nan(alpha)) {
    objectives <- vapply(grid, function(weight) fixed_fit(weight)$SSE, numeric(1))
    alpha <- grid[which.min(objectives)]
}
fit <- fixed_fit(alpha)
predictions <- stats::predict(fit, n.ahead = horizon, prediction.interval = TRUE,
                              level = confidence)
fitted <- stats::fitted(fit)
residuals <- as.numeric(stats::residuals(fit))
innovation_variance <- stats::var(residuals)
final_season <- fit$coefficients[-c(1L, 2L)]
scored <- length(residuals)
shifted_season <- fitted[seq_len(scored - period) + period, "season"]
trace <- cbind(fitted[, "xhat"], residuals,
               c(fitted[-1L, "level"], fit$coefficients[[1L]]),
               c(fitted[-1L, "trend"], fit$coefficients[[2L]]),
               c(shifted_season, final_season))

dimension <- period + 2L
transition <- diag(dimension)
transition[1L, 2L] <- 1
transition[3L:dimension, ] <- 0
for (index in seq_len(period - 1L)) {
    transition[2L + index, 3L + index] <- 1
}
transition[dimension, 3L] <- 1
gain <- numeric(dimension)
gain[c(1L, 2L, dimension)] <- c(alpha, alpha * beta, (1 - alpha) * gamma)
observation <- numeric(dimension)
observation[1L:3L] <- 1
covariance <- matrix(0, dimension, dimension)
observation_variance <- numeric(horizon)
for (step in seq_len(horizon)) {
    observation_variance[step] <- innovation_variance +
        drop(crossprod(observation, covariance %*% observation))
    covariance <- transition %*% covariance %*% t(transition) + innovation_variance * tcrossprod(gain)
}

emit <- function(name, values) {
    cat(name, paste(sprintf("%.17g", values), collapse = "\t"), sep = "\t")
    cat("\n")
}
emit("summary", c(level, slope, fit$coefficients[1L:2L], fit$SSE, innovation_variance))
emit("initial_season", season)
emit("final_season", final_season)
emit("trace", as.vector(t(trace)))
emit("forecast_means", predictions[, "fit"])
emit("forecast_variances", observation_variance)
emit("forecast_lower", predictions[, "lwr"])
emit("forecast_upper", predictions[, "upr"])
if (length(objectives)) {
    emit("grid", c(alpha, objectives))
}
