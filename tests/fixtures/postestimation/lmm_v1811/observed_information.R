# Independent analytic Gaussian REML information at the retained native R point.
# No fitting, optimizer, finite differences, Workbench, or owner covariance input.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 3L)
if (file.exists(args[3])) stop("Preserve earlier observed-information evidence")
options(digits = 17)
library(jsonlite)
warning_messages <- character()
withCallingHandlers({
ref <- fromJSON(args[1], simplifyVector = TRUE)
d <- read.csv(args[2], check.names = FALSE)
d$arm <- factor(d$arm, levels = c("a", "b"))
X <- model.matrix(~ arm * time + x, d)[, c("(Intercept)", "armb", "time", "armb:time", "x")]
beta <- unlist(ref$params)[colnames(X)]
Vgls <- as.matrix(ref$covariance_owner_order)
sigma2 <- ref$meta$native_diagnostics$sigma^2
n <- nrow(X); p <- ncol(X); nu <- n - p
groups <- split(seq_len(n), d$g)
sizes <- lengths(groups)
stopifnot(n == ref$nobs, all(sizes == 6L), p == 5L)
Z <- model.matrix(~ 0 + factor(d$g))
D <- tcrossprod(Z)
# For equal group size m, W=I-lambda*ZZ', lambda=rho/(1+m*rho).
# sigma2*solve(native GLS covariance)=X'WX.  The intercept precision
# therefore uniquely recovers lambda using n-sigma2*precision[1,1].
lambda <- (n - sigma2 * solve(Vgls)[1, 1]) / sum(sizes^2)
rho <- lambda / (1 - sizes[1] * lambda)
stopifnot(is.finite(rho), rho > 0)
V1 <- diag(n) + rho * D
W <- solve(V1)
Wp <- -W %*% D %*% W
Wpp <- 2 * W %*% D %*% W %*% D %*% W
u <- as.vector(d$y - X %*% beta)
q <- as.numeric(crossprod(u, W %*% u))
qp <- as.numeric(crossprod(u, Wp %*% u))
qpp <- as.numeric(crossprod(u, Wpp %*% u))
T <- crossprod(X, W %*% X)
Tp <- crossprod(X, Wp %*% X)
Tpp <- crossprod(X, Wpp %*% X)
Ti <- solve(T)
trace <- function(a) sum(diag(a))
v <- as.vector(crossprod(X, W %*% u))
vp <- as.vector(crossprod(X, Wp %*% u))
score_beta <- nu * v / q
score_rho <- -.5 * trace(W %*% D) - .5 * trace(Ti %*% Tp) - .5 * nu * qp / q
# Exact derivatives of the scale-profile REML extension in (beta,rho).
Hbb <- -nu * T / q + 2 * nu * tcrossprod(v) / q^2
Hbr <- nu * vp / q - nu * qp * v / q^2
Hrr <- .5 * trace(W %*% D %*% W %*% D) -
  .5 * (trace(Ti %*% Tpp) - trace(Ti %*% Tp %*% Ti %*% Tp)) -
  .5 * nu * (qpp / q - (qp / q)^2)
H <- rbind(cbind(Hbb, Hbr), c(Hbr, Hrr))
info <- -H
full_cov <- solve(info)
fixed_cov <- full_cov[seq_len(p), seq_len(p)]
gls_reconstructed <- sigma2 * Ti
ell <- -.5 * as.numeric(determinant(V1, logarithm = TRUE)$modulus) -
  .5 * as.numeric(determinant(T, logarithm = TRUE)$modulus) -
  .5 * nu * (log(q / nu) + 1 + log(2 * pi))
out <- list(
  definition = "Gaussian marginal scale-profile REML extension at native GLS beta; beta and direct relative random-intercept variance retained jointly for observed information",
  parameter_order = c(colnames(X), "rho=tau2/sigma2"),
  evaluation_point_source = "Previously generated native lme4 beta/sigma/GLS covariance; rho algebraically recovered from balanced-group GLS precision",
  owner_beta_or_covariance_as_reference_input = FALSE, fitting_or_optimization = FALSE,
  finite_difference_steps = NULL,
  nobs = n, fixed_parameter_count = p, residual_scale_profile_df = nu,
  beta = as.list(beta), rho = rho, tau2 = rho * sigma2,
  retained_native_sigma2 = sigma2, profiled_sigma2 = q / nu,
  loglik = ell, retained_native_loglik = ref$meta$native_diagnostics$loglik,
  gls_reconstruction_max_abs = max(abs(gls_reconstructed - Vgls)),
  score = c(score_beta, score_rho), score_divided_by_n = c(score_beta, score_rho) / n,
  beta_stationarity_hessian_correction_max_abs = max(abs(2 * nu * tcrossprod(v) / q^2)),
  cross_stationarity_hessian_correction_max_abs = max(abs(nu * qp * v / q^2)),
  information_eigenvalues = eigen(info, symmetric = TRUE, only.values = TRUE)$values,
  joint_information = unname(info), joint_covariance = unname(full_cov),
  fixed_covariance = unname(fixed_cov),
  schur_adjustment_from_profile_gls = unname(fixed_cov - (q / nu) * Ti),
  warnings = warning_messages,
  certification = "Analytic evaluation only; raw score retained, no new stationarity tolerance or admission claim"
)
write_json(out, args[3], pretty = TRUE, auto_unbox = TRUE, digits = 17, null = "null")
print(list(rho = rho, sigma2 = sigma2, profile_sigma2 = q / nu,
           score = c(score_beta, score_rho), loglik = ell,
           gls_reconstruction_max_abs = max(abs(gls_reconstructed - Vgls))))
sessionInfo()
}, warning = function(w) warning_messages <<- c(warning_messages, conditionMessage(w)))
