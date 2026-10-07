# VERIFICATION LEVEL: R 4.6 MASS joint NB2 observed information and fixed-alpha GLM.
args <- commandArgs(trailingOnly=TRUE)
out <- normalizePath(args[[1]], mustWork=TRUE)
cat("R oracle output:", out, "\n")
library(MASS)
library(jsonlite)
d <- read.csv(file.path(out, "nb2.csv"))
tight <- glm.control(epsilon=1e-14, maxit=1000)
f <- glm.nb(y ~ x1 + x2, data=d, control=tight)
X <- model.matrix(f); y <- f$y; k <- ncol(X)
nll <- function(p) -sum(dnbinom(y, size=p[k+1], mu=exp(X %*% p[1:k]), log=TRUE))
grad <- function(p) {
  theta <- p[k+1]; mu <- as.vector(exp(X %*% p[1:k]))
  db <- (y-mu)*theta/(theta+mu)
  dt <- digamma(y+theta)-digamma(theta)+log(theta/(theta+mu))+(mu-y)/(theta+mu)
  -c(colSums(X*db), sum(dt))
}
v <- solve(optimHess(c(coef(f), f$theta), nll, grad, control=list(ndeps=rep(1e-6,k+1))))
fixed <- glm(y ~ x1 + x2, data=d, family=negative.binomial(theta=2), control=tight)
p <- glm(y ~ x1 + x2, data=d, family=poisson(), control=tight)
res <- list(meta=list(r_version=R.version.string, epsilon=1e-14, seed=20261004),
 nb2=list(coefficients=unname(coef(f)), std_error=sqrt(diag(v))[1:k],
          alpha=1/f$theta, se_alpha=sqrt(v[k+1,k+1])/f$theta^2,
          ll=as.numeric(logLik(f)), lr=2*(as.numeric(logLik(f))-as.numeric(logLik(p)))),
 fixed_glm=list(coefficients=unname(coef(fixed)), std_error=unname(sqrt(diag(vcov(fixed, dispersion=1)))), ll=as.numeric(logLik(fixed))))
write_json(res, file.path(out,"r.json"), auto_unbox=TRUE, pretty=TRUE, digits=NA)
