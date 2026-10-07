# Independent review: fixed-alpha likelihood, convergence, and native operations.
args <- commandArgs(TRUE)
stopifnot(length(args) == 2)
d <- read.csv(args[1])
fit <- function(rhs, epsilon) glm(rhs, data=d,
  family=MASS::negative.binomial(theta=1, link="log"),
  control=glm.control(epsilon=epsilon, maxit=1000))
diagnostic <- function(m) {
  X <- model.matrix(m); mu <- exp(drop(X %*% coef(m)))
  V <- solve(crossprod(X, X * (mu/(1+mu))))
  list(beta=unname(coef(m)), covariance=unname(V), covariance_scale=1,
       native_summary_dispersion=summary(m)$dispersion,
       score_max=max(abs(drop(crossprod(X, (d$ynb-mu)/(1+mu))))),
       ll=sum(dnbinom(d$ynb, mu=mu, size=1, log=TRUE)),
       converged=m$converged, iterations=m$iter)
}
sequence <- lapply(c(1e-8,1e-12,1e-14,1e-16), function(e) {
  m <- fit(ynb~x1+x2+x3,e); c(list(epsilon=e),diagnostic(m))
})
full <- fit(ynb~x1+x2+x3,1e-16); restricted <- fit(ynb~x1,1e-16)
z <- diagnostic(full); V <- z$covariance
dimnames(V) <- list(names(coef(full)), names(coef(full)))
values <- list(nobs=nobs(full), df_resid=df.residual(full), converged=as.numeric(full$converged),
               ll_full=as.numeric(logLik(full)),ll_restricted=as.numeric(logLik(restricted)))
for (i in seq_along(coef(full))) {
  term <- c("_cons","x1","x2","x3")[i]
  values[[paste0("b_",term)]] <- coef(full)[i]
  values[[paste0("se_",term)]] <- sqrt(V[i,i])
}
for (kind in c("wj","ws")) {
  h <- if(kind=="wj") c("x1=0","x2=0") else "x1-x2=1"
  tab <- car::linearHypothesis(full,h,test="Chisq",vcov.=V)
  values[[paste0(kind,"_stat")]] <- tab[2,"Chisq"]
  values[[paste0(kind,"_df")]] <- tab[2,"Df"]
  values[[paste0(kind,"_p")]] <- tab[2,"Pr(>Chisq)"]
}
for (kind in c("lc","nl")) {
  expression <- if(kind=="lc") "x1+2*x2-0.5" else "x1/x2"
  tab <- car::deltaMethod(full,expression,vcov.=V)
  values[[paste0(kind,"_est")]] <- tab[["Estimate"]]
  values[[paste0(kind,"_se")]] <- tab[["SE"]]
}
tab <- lmtest::lrtest(restricted,full)
values$lr_stat <- tab[2,"Chisq"]; values$lr_df <- tab[2,"Df"]; values$lr_p <- tab[2,"Pr(>Chisq)"]
analytic <- list()
X <- model.matrix(full); beta <- coef(full)
for (at in c("ma","mm")) {
  tab <- if(at=="ma") marginaleffects::avg_slopes(full,variables=c("x1","x2"),vcov=V) else
    marginaleffects::slopes(full,variables=c("x1","x2"),newdata="mean",vcov=V)
  for(i in seq_len(nrow(tab))) {
    term <- tab$term[i]; j <- match(term,names(beta))
    values[[paste0(at,"_",term,"_est")]] <- tab$estimate[i]
    values[[paste0(at,"_",term,"_se")]] <- tab$std.error[i]
    A <- if(at=="ma") X else matrix(colMeans(X),nrow=1)
    mu <- exp(drop(A %*% beta)); g <- beta[j]*colMeans(A*mu); g[j] <- g[j]+mean(mu)
    analytic[[paste0(at,"_",term,"_est")]] <- beta[j]*mean(mu)
    analytic[[paste0(at,"_",term,"_se")]] <- sqrt(drop(t(g)%*%V%*%g))
  }
}
# BFGS starts away from IRLS and optimizes the fixed-alpha likelihood directly.
X <- model.matrix(full)
objective <- function(b) -sum(dnbinom(d$ynb,mu=exp(drop(X%*%b)),size=1,log=TRUE))
gradient <- function(b) {mu <- exp(drop(X%*%b)); -drop(crossprod(X,(d$ynb-mu)/(1+mu)))}
independent <- optim(rep(0,ncol(X)),objective,gradient,method="BFGS",
                     control=list(reltol=1e-14,maxit=1000))
polished <- independent$par
for (iteration in seq_len(8)) {
  mu <- exp(drop(X%*%polished))
  observed <- crossprod(X,X*(mu*(1+d$ynb)/(1+mu)^2))
  polished <- polished-solve(observed,gradient(polished))
  if(max(abs(gradient(polished))) < 1e-12) break
}
result <- list(values=values, full=z, restricted=diagnostic(restricted), epsilon_sequence=sequence,
  analytic_margins=analytic, bfgs=list(params=independent$par, ll=-independent$value,
  convergence=independent$convergence,score_max=max(abs(gradient(independent$par)))),
  polished_likelihood=list(params=polished,ll=-objective(polished),score_max=max(abs(gradient(polished)))),
  environment=list(R=R.version.string,packages=setNames(lapply(c("MASS","car","lmtest","marginaleffects","jsonlite"),
    function(p) as.character(packageVersion(p))),c("MASS","car","lmtest","marginaleffects","jsonlite"))))
jsonlite::write_json(result,args[2],digits=NA,auto_unbox=TRUE,pretty=TRUE)
