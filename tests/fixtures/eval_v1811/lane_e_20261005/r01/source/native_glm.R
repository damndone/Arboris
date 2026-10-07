# Independent final EIM and native public post-estimation references.
args <- commandArgs(TRUE);d <- read.csv(args[1]); result <- list()
make <- function(kind, restricted=FALSE) {
  fam <- switch(kind, binomial=binomial(),poisson=poisson(),negative_binomial=MASS::negative.binomial(theta=1/1.3,link='log'))
  response <- switch(kind,binomial='yb',poisson='yp',negative_binomial='ynb')
  m <- glm(as.formula(paste(response,'~',if(restricted)'x1' else 'x1+x2')),data=d,family=fam,
           control=glm.control(epsilon=1e-16,maxit=1000))
  X <- model.matrix(m);mu <- fitted(m);eta <- drop(X%*%coef(m))
  w <- switch(kind,binomial=mu*(1-mu),poisson=mu,negative_binomial=mu/(1+1.3*mu))
  V <- solve(crossprod(X,X*w));dimnames(V)<-list(names(coef(m)),names(coef(m)))
  stopifnot(m$converged);list(m=m,V=V)
}
for(kind in c('binomial','poisson','negative_binomial')) {
  full<-make(kind);small<-make(kind,TRUE)
  W<-car::linearHypothesis(full$m,c('x1=0','x2=0'),test='Chisq',vcov.=full$V)[2,]
  lc<-car::deltaMethod(full$m,'x1-0.4*x2+0.1',vcov.=full$V)
  nl<-car::deltaMethod(full$m,'exp(x1)',vcov.=full$V)
  LR<-lmtest::lrtest(small$m,full$m)[2,]
  delta <- function(tab) {
    b<-tab[['Estimate']];s<-tab[['SE']]
    list(estimate=b,std_error=s,p_value=2*pnorm(-abs(b/s)),ci=c(b-qnorm(.975)*s,b+qnorm(.975)*s))
  }
  margins<-list()
  for(at in c('average','means')) {
    tab<-if(at=='average')marginaleffects::avg_slopes(full$m,variables='x1',vcov=full$V) else
      marginaleffects::slopes(full$m,variables='x1',newdata='mean',vcov=full$V)
    margins[[at]]<-list(estimate=tab$estimate[[1]],std_error=tab$std.error[[1]])
  }
  result[[kind]]<-list(beta=coef(full$m),covariance=unname(full$V),n=nobs(full$m),
    wald=list(statistic=W[['Chisq']],df_num=W[['Df']],p_value=W[['Pr(>Chisq)']]),
    lincom=delta(lc),nlcom=delta(nl),
    lr=list(statistic=LR[['Chisq']],df=LR[['Df']],p_value=LR[['Pr(>Chisq)']],loglik_full=as.numeric(logLik(full$m)),loglik_restricted=as.numeric(logLik(small$m))),
    margins=margins)
}
jsonlite::write_json(list(R=R.version.string,results=result),args[2],digits=17,auto_unbox=TRUE,pretty=TRUE)
