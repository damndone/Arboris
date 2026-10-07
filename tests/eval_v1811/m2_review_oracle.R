# Independent native R checks; no production likelihood implementation is used.
args <- commandArgs(trailingOnly=TRUE)
library(MASS)
library(jsonlite)
root <- normalizePath(args[[1]],mustWork=TRUE)
boundary <- read.csv(file.path(root,"tests/fixtures/count_models/reference-v3/poisson.csv"))
p <- glm(y~x1+x2,data=boundary,family=poisson(),control=glm.control(epsilon=1e-16,maxit=1000))
X <- model.matrix(p); y <- p$y; mu <- fitted(p)
boundary_rows <- lapply(c("mean","constant"),function(form) {
  score0 <- if(form=="mean") sum(((y-mu)^2-y)/2) else sum(((y-mu)^2-y)/(2*mu))
  grid <- lapply(c(1e-5,1e-4,1e-3,.01),function(a) {
    size <- if(form=="mean") 1/a else mu/a
    ll <- sum(dnbinom(y,size=size,mu=mu,log=TRUE))
    h <- a/10
    llp <- sum(dnbinom(y,size=if(form=="mean") 1/(a+h) else mu/(a+h),mu=mu,log=TRUE))
    llm <- sum(dnbinom(y,size=if(form=="mean") 1/(a-h) else mu/(a-h),mu=mu,log=TRUE))
    list(alpha=a,ll=ll,natural_score_fd=(llp-llm)/(2*h))
  })
  list(dispersion=form,score_at_zero=score0,ll_poisson=as.numeric(logLik(p)),beta=unname(coef(p)),grid=grid)
})
d <- read.csv(file.path(root,"tests/fixtures/admission/glm_negative_binomial/data.csv"))
Xg <- model.matrix(~x1+x2,d); yg <- d$y
cases <- lapply(c(1e-14,1e-16),function(eps) {
  f <- glm(y~x1+x2,data=d,family=negative.binomial(theta=1),control=glm.control(epsilon=eps,maxit=1000))
  m <- fitted(f)
  score <- colSums(Xg*((yg-m)/(1+m)))
  list(epsilon=eps,beta=unname(coef(f)),score=unname(score),max_abs_score=max(abs(score)),ll=as.numeric(logLik(f)),iterations=f$iter)
})
# Newton polishing from the epsilon14 iterate uses native GLM score and exact
# fixed-alpha OIM. It verifies the optimum independently of epsilon16's stop.
b <- cases[[1]]$beta
for (i in seq_len(5)) {
  m <- as.vector(exp(Xg%*%b)); s <- colSums(Xg*((yg-m)/(1+m)))
  info <- crossprod(Xg,Xg*as.vector(m*(1+yg)/(1+m)^2))
  b <- b+as.vector(solve(info,s))
}
m <- as.vector(exp(Xg%*%b))
write_json(list(r_version=R.version.string,boundary=boundary_rows,glm=cases,
  polished=list(beta=b,score=unname(colSums(Xg*((yg-m)/(1+m)))),ll=sum(dnbinom(yg,size=1,mu=m,log=TRUE)))),
  args[[2]],auto_unbox=TRUE,digits=NA,pretty=TRUE)
