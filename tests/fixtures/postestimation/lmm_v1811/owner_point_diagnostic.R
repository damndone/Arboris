# Diagnostic at the retained owner point, not a native-oracle replacement.
# The analytic derivatives are identical to observed_information.R.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 5L)
if (file.exists(args[5])) stop("Preserve earlier diagnostic evidence")
options(digits = 17)
library(jsonlite)
native <- fromJSON(args[1])
kernel <- fromJSON(args[2])
result <- fromJSON(args[3])$payload
d <- read.csv(args[4], check.names = FALSE)
d$arm <- factor(d$arm, levels = c("a", "b"))
X <- model.matrix(~ arm * time + x, d)[, c("(Intercept)", "armb", "time", "armb:time", "x")]
Z <- model.matrix(~ 0 + factor(d$g))
beta <- as.numeric(kernel$params)
rho <- result$random_effects$intercept_variance / result$random_effects$residual_variance
evaluate_information <- function(X, Z, y, beta, rho) {
  n <- nrow(X); p <- ncol(X); nu <- n - p
  D <- tcrossprod(Z); V1 <- diag(n) + rho * D; W <- solve(V1)
  Wp <- -W %*% D %*% W
  Wpp <- 2 * W %*% D %*% W %*% D %*% W
  u <- as.vector(y - X %*% beta)
  q <- as.numeric(crossprod(u, W %*% u))
  qp <- as.numeric(crossprod(u, Wp %*% u))
  qpp <- as.numeric(crossprod(u, Wpp %*% u))
  T <- crossprod(X, W %*% X)
  Tp <- crossprod(X, Wp %*% X); Tpp <- crossprod(X, Wpp %*% X)
  Ti <- solve(T); trace <- function(a) sum(diag(a))
  v <- as.vector(crossprod(X, W %*% u))
  vp <- as.vector(crossprod(X, Wp %*% u))
  score <- c(nu * v / q,
             -.5 * trace(W %*% D) - .5 * trace(Ti %*% Tp) - .5 * nu * qp / q)
  Hbb <- -nu * T / q + 2 * nu * tcrossprod(v) / q^2
  Hbr <- nu * vp / q - nu * qp * v / q^2
  Hrr <- .5 * trace(W %*% D %*% W %*% D) -
    .5 * (trace(Ti %*% Tpp) - trace(Ti %*% Tp %*% Ti %*% Tp)) -
    .5 * nu * (qpp / q - (qp / q)^2)
  info <- -rbind(cbind(Hbb, Hbr), c(Hbr, Hrr))
  fixed_cov <- solve(info)[seq_len(p), seq_len(p)]
  ell <- -.5 * as.numeric(determinant(V1, logarithm = TRUE)$modulus) -
    .5 * as.numeric(determinant(T, logarithm = TRUE)$modulus) -
    .5 * nu * (log(q / nu) + 1 + log(2 * pi))
  list(score = score, score_divided_by_n = score / n,
       fixed_covariance = fixed_cov, loglik = ell, profiled_sigma2 = q / nu)
}
# One evaluation only. Owner covariance does not enter this calculation.
diag <- evaluate_information(X, Z, d$y, beta, rho)
owner_cov <- as.matrix(kernel$vcov)
native_cov <- as.matrix(native$fixed_covariance)
residual <- owner_cov - diag$fixed_covariance
out <- list(
  purpose = "Owner-point analytic diagnostic; not an independent-native estimator oracle or admission PASS",
  owner_parameters_as_diagnostic_point = TRUE,
  owner_covariance_used_in_information_calculation = FALSE,
  native_reference_changed = FALSE, fits_or_optimizations = 0,
  analytic_evaluation_count = 1,
  beta = beta, rho = rho, native_rho = native$rho,
  score = diag$score, score_divided_by_n = diag$score_divided_by_n,
  loglik = diag$loglik, profiled_sigma2 = diag$profiled_sigma2,
  fixed_covariance = unname(diag$fixed_covariance),
  evaluation_point_covariance_change = unname(diag$fixed_covariance - native_cov),
  owner_minus_native_covariance = unname(owner_cov - native_cov),
  unexplained_covariance_residual = unname(residual),
  unexplained_covariance_max_abs = max(abs(residual)),
  unexplained_covariance_max_relative = max(abs(residual / owner_cov)),
  inference_or_postestimation_certified = FALSE
)
write_json(out, args[5], pretty = TRUE, auto_unbox = TRUE, digits = 17, null = "null")
print(out[c("rho", "native_rho", "score", "score_divided_by_n", "loglik",
            "unexplained_covariance_max_abs", "unexplained_covariance_max_relative")])
sessionInfo()
