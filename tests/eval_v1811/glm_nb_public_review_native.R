# Independent native alpha sweep, alternate hypotheses, final EIM scale=1.
args <- commandArgs(TRUE)
stopifnot(length(args)==2, !file.exists(args[2]))
d <- read.csv(args[1])
required <- c('MASS','car','lmtest','marginaleffects','jsonlite')
stopifnot(all(vapply(required,requireNamespace,logical(1),quietly=TRUE)))
make <- function(alpha,formula) {
  m <- glm(formula,data=d,family=MASS::negative.binomial(theta=1/alpha,link='log'),
           control=glm.control(epsilon=1e-16,maxit=1000))
  X <- model.matrix(m); mu <- exp(drop(X%*%coef(m)))
  I <- crossprod(X,X*(mu/(1+alpha*mu))); V <- solve(I); chol(I)
  dimnames(V) <- list(names(coef(m)),names(coef(m)))
  score <- drop(crossprod(X,(m$y-mu)/(1+alpha*mu)))
  stopifnot(m$converged,max(abs(score))/nobs(m)<1e-8)
  list(m=m,V=V,diagnostics=list(converged=m$converged,score_over_n=max(abs(score))/nobs(m),
       beta=as.list(coef(m)),covariance=unname(V),nobs=nobs(m),ll=as.numeric(logLik(m)),
       min_information_eigenvalue=min(eigen(I,symmetric=TRUE,only.values=TRUE)$values)))
}
result <- list()
for(alpha in c(.5,1,2)) {
  full <- make(alpha,ynb~x1+x2+x3); restricted <- make(alpha,ynb~x1)
  W <- car::linearHypothesis(full$m,'x2+x3=0',test='Chisq',vcov.=full$V)[2,]
  lc <- car::deltaMethod(full$m,'x2-0.3*x3+0.2',vcov.=full$V)
  nl <- car::deltaMethod(full$m,'exp(x3)',vcov.=full$V)
  LR <- lmtest::lrtest(restricted$m,full$m)[2,]
  margins <- list()
  for(at in c('average','means')) {
    tab <- if(at=='average') marginaleffects::avg_slopes(full$m,variables='x3',vcov=full$V) else
      marginaleffects::slopes(full$m,variables='x3',newdata='mean',vcov=full$V)
    margins[[at]] <- list(estimate=tab$estimate[[1]],std_error=tab$std.error[[1]])
  }
  result[[as.character(alpha)]] <- list(alpha=alpha,full=full$diagnostics,restricted=restricted$diagnostics,
    wald=list(statistic=W[['Chisq']],df_num=W[['Df']],p_value=W[['Pr(>Chisq)']]),
    lincom=list(estimate=lc[['Estimate']],std_error=lc[['SE']]),
    nlcom=list(estimate=nl[['Estimate']],std_error=nl[['SE']]),
    lr=list(statistic=LR[['Chisq']],df=LR[['Df']],p_value=LR[['Pr(>Chisq)']],
      loglik_full=as.numeric(logLik(full$m)),loglik_restricted=as.numeric(logLik(restricted$m))),
    margins=margins)
}
precision <- function(value) {
  if(is.list(value))return(lapply(value,precision))
  if(is.numeric(value)) {
    text <- sprintf('%.17g',value)
    if(!is.null(names(value)))names(text)<-names(value)
    if(!is.null(dim(value)))dim(text)<-dim(value)
    return(text)
  }
  value
}
jsonlite::write_json(list(environment=list(R=R.version.string,packages=setNames(lapply(required,
  function(p)as.character(packageVersion(p))),required)),full_precision=precision(result)),
  args[2],auto_unbox=TRUE,pretty=TRUE,digits=NA)
cat('Native alpha sweep complete; score/n and EIM positivity checked\n')
