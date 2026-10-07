# Independent audit of committed reference points using native R. No estimator
# source is imported; theta-coordinate optimHess is transformed to natural alpha.
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args) == 1)
root <- args[1]
base <- file.path(root, "tests/fixtures/count_models/integration-strict-v1811")
nb <- jsonlite::read_json(file.path(base, "native-reference/nb2-postestimation-reference.json"))
gl <- jsonlite::read_json(file.path(base, "native-reference/glm-fixed-alpha-reference.json"))
ready <- jsonlite::read_json(file.path(base, "glm-negative-binomial-v1811-oracle.json"))
num <- function(value) as.numeric(unlist(value, use.names=FALSE))
mat <- function(value) do.call(rbind, lapply(value, num))
d <- read.csv(file.path(root, "tests/fixtures/postestimation/data.csv"))
X <- model.matrix(~x1+x2+x3, d); y <- d$ynb; k <- ncol(X)
fp <- nb$full_precision
p <- num(fp$params)
theta <- as.numeric(fp$theta)
q <- c(p, theta)
nll <- function(q) -sum(dnbinom(y, size=q[k+1], mu=exp(drop(X %*% q[1:k])), log=TRUE))
gradient <- function(q) {
  t <- q[k+1]; mu <- exp(drop(X %*% q[1:k]))
  beta <- drop(crossprod(X, (mu-y)*t/(t+mu)))
  size <- -sum(digamma(y+t)-digamma(t)+log(t/(t+mu))+(mu-y)/(t+mu))
  c(beta, size)
}
alpha <- 1/theta
J <- diag(c(rep(1,k), -theta^2))
score <- -drop(J %*% gradient(q))
information <- t(J) %*% optimHess(q, nll, gradient,
                    control=list(ndeps=rep(1e-6,k+1))) %*% J
information[k+1,k+1] <- information[k+1,k+1]+gradient(q)[k+1]*2*theta^3
saved_information <- mat(fp$diagnostics$final$information)
saved_covariance <- mat(fp$joint_vcov)
chol(saved_information); chol(saved_covariance)
information_relative_difference <- max(abs(information-saved_information)/pmax(1,abs(saved_information)))
inverse_error <- max(abs(saved_information %*% saved_covariance-diag(k+1)))
stopifnot(max(abs(score))/nrow(d) <= 1e-13,
          information_relative_difference < 1e-6, inverse_error < 1e-12,
          abs(-nll(q)-as.numeric(fp$ll)) < 1e-10)
original <- MASS::glm.nb(ynb~x1+x2+x3,data=d,control=glm.control(epsilon=1e-14,maxit=200))
qo <- c(coef(original), original$theta)
Jo <- diag(c(rep(1,k), -original$theta^2))
old_mean_score <- max(abs(-drop(Jo %*% gradient(qo))))/nrow(d)
stopifnot(old_mean_score <= 1e-13)

g <- read.csv(file.path(root,"tests/fixtures/admission/glm_negative_binomial/data.csv"))
G <- model.matrix(~x1+x2,g)
fit <- glm(y~x1+x2,data=g,family=MASS::negative.binomial(theta=1),
           control=glm.control(epsilon=1e-16,maxit=1000))
gf <- gl$full_precision[["epsilon1e-16"]]
beta <- num(gf$params); mu <- exp(drop(G %*% beta))
eim <- crossprod(G,G*(mu/(1+mu)))
covariance <- solve(eim)
glm_score <- max(abs(crossprod(G,(g$y-mu)/(1+mu))))
glm_covariance_difference <- max(abs(covariance-mat(gf$covariance)))
glm_native_beta_difference <- max(abs(coef(fit)-beta))
glm_ready_beta_difference <- max(abs(num(ready$coefficients)-beta))
glm_ready_se_difference <- max(abs(num(ready$std_error)-sqrt(diag(covariance))))
stopifnot(glm_native_beta_difference < 1e-12, glm_ready_beta_difference == 0,
          glm_ready_se_difference < 1e-12, glm_covariance_difference < 1e-12,
          glm_score/nrow(g) < 1e-13)
answer <- list(R=R.version.string, nb=list(n=nrow(d), alpha=alpha,
    natural_score=as.list(score), natural_mean_score_max=max(abs(score))/nrow(d),
    original_epsilon14_natural_mean_score_max=old_mean_score,
    numeric_theta_oim_relative_difference=information_relative_difference,
    saved_oim_min_eigenvalue=min(eigen(saved_information,symmetric=TRUE)$values),
    saved_inverse_min_eigenvalue=min(eigen(saved_covariance,symmetric=TRUE)$values),
    saved_oim_inverse_product_error=inverse_error),
  glm=list(n=nrow(g), alpha_fixed=1, max_absolute_score=glm_score,
    native_beta_difference=glm_native_beta_difference, covariance_difference=glm_covariance_difference,
    projected_oracle_beta_difference=glm_ready_beta_difference,
    projected_oracle_se_difference=glm_ready_se_difference))
cat(jsonlite::toJSON(answer, auto_unbox=TRUE, pretty=TRUE, digits=NA), "\n")
