# VERIFICATION LEVEL: stable R dnbinom likelihood on the Poisson boundary data.
args <- commandArgs(trailingOnly=TRUE)
input <- normalizePath(args[[1]], mustWork=TRUE)
output <- args[[2]]
stopifnot(!file.exists(output))
cat("Boundary evidence output:", output, "\n")
library(jsonlite)
d <- read.csv(file.path(input,"poisson.csv"))
p <- glm(y~x1+x2, data=d, family=poisson(), control=glm.control(epsilon=1e-14,maxit=1000))
X <- model.matrix(p); y <- p$y; beta <- coef(p); mu <- as.vector(exp(X%*%beta))
grid <- c(1e-8,1e-7,1e-6,1e-5,1e-4,.001,.01,.1,1,10)
rows <- lapply(grid,function(a) {
  fit <- glm(y~x1+x2,data=d,family=MASS::negative.binomial(theta=1/a),control=glm.control(epsilon=1e-14,maxit=1000))
  mf <- as.vector(exp(X%*%coef(fit)))
  list(alpha=a, coefficients=unname(coef(fit)), ll=sum(dnbinom(y,size=1/a,mu=mf,log=TRUE)),
       ll_at_poisson_beta=sum(dnbinom(y,size=1/a,mu=mu,log=TRUE)))
})
ll_tests <- lapply(c("mean","constant"), function(form) lapply(grid,function(a) {
  size <- if(form=="mean") 1/a else mu/a
  effective <- if(form=="mean") rep(a,length(mu)) else a/mu
  t <- if(form=="mean") a*mu else rep(a,length(mu))
  product <- mapply(function(yy,ee) sum(log1p((seq_len(yy)-1)*ee)),y,effective)
  ll <- sum(product+y*log(mu)-lgamma(y+1)-y*log1p(t)-mu*log1p(t)/t)
  list(dispersion=form,alpha=a, ll=ll, ll_dnbinom=sum(dnbinom(y,size=size,mu=mu,log=TRUE)))
}))
res <- list(meta=list(r_version=R.version.string, note="Profile grid is evidence, not a proof of a global boundary optimum"),
  beta=unname(beta), ll_poisson=as.numeric(logLik(p)),
  alpha_score_at_zero=sum((y-mu)^2-y)/2, profile=rows, loglike_checks=unlist(ll_tests,recursive=FALSE))
write_json(res,output,auto_unbox=TRUE,digits=NA,pretty=TRUE)
