# Native R likelihood and natural-coordinate derivative check of published points.
args <- commandArgs(trailingOnly=TRUE)
library(MASS); library(jsonlite)
root <- normalizePath(args[[1]],mustWork=TRUE)
points <- read_json(args[[2]],simplifyVector=TRUE)
rows <- lapply(c("nb2","nb1"),function(name) {
  d <- read.csv(file.path(root,"tests/fixtures/count_models/reference-v3",paste0(name,".csv")))
  X <- model.matrix(~x1+x2,d); y <- d$y; k <- ncol(X)
  ll <- function(p) {
    m <- as.vector(exp(X%*%p[1:k])); theta <- if(name=="nb2") rep(1/p[k+1],length(m)) else m/p[k+1]
    sum(dnbinom(y,mu=m,size=theta,log=TRUE))
  }
  score <- function(p) {
    m <- as.vector(exp(X%*%p[1:k])); a <- p[k+1]
    theta <- if(name=="nb2") rep(1/a,length(m)) else m/a
    st <- digamma(y+theta)-digamma(theta)+log(theta/(theta+m))+(m-y)/(theta+m)
    sb <- (y-m)*theta/(theta+m)
    if(name=="nb1") sb <- sb+theta*st
    c(colSums(X*sb),sum(if(name=="nb2") -st/a^2 else -theta*st/a))
  }
  p <- points[[name]]$params
  H <- optimHess(p,function(p) -ll(p),function(p) -score(p),control=list(ndeps=rep(1e-5,k+1)))
  list(name=name,ll=ll(p),score=score(p),max_score_per_observation=max(abs(score(p)))/nrow(d),
       information=unname(H),covariance=unname(solve(H)))
})
d <- read.csv(file.path(root,"tests/fixtures/count_models/p1-remediation-20261004/fractional-oracle/data.csv"))
f <- glm(y~x1+x2,data=d,family=negative.binomial(theta=2),control=glm.control(epsilon=1e-16,maxit=1000))
write_json(list(version=R.version.string,joint=rows,fractional=list(beta=unname(coef(f)),
  se=unname(sqrt(diag(vcov(f,dispersion=1)))),ll=as.numeric(logLik(f)))),args[[3]],digits=NA,auto_unbox=TRUE,pretty=TRUE)
