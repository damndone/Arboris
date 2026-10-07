d <- read.csv("data.csv")
f <- glm(y ~ x1+x2, data=d, family=MASS::negative.binomial(theta=.5,link="log"),control=glm.control(epsilon=1e-16,maxit=1000))
stopifnot(f$converged)
X <- model.matrix(f); b <- coef(f)
# Refine the fixed-alpha native likelihood score with its analytic OIM;
# this is independent reference capture, not a modification of the renderer.
for (i in 1:5) {
 mu <- exp(drop(X %*% b)); score <- crossprod(X,(d$y-mu)/(1+2*mu))
 H <- crossprod(X,X*(mu*(1+2*d$y)/(1+2*mu)^2))
 b <- b+drop(solve(H,score))
}
mu <- exp(drop(X %*% b))
V <- solve(crossprod(X,X*(mu/(1+2*mu))))
names(b)[1] <- "Intercept"
values <- c(setNames(b,paste0("b_",names(b))),setNames(sqrt(diag(V)),paste0("se_",names(b))),
 setNames(as.vector(t(V)),paste0("v_",rep(1:3,each=3),"_",rep(1:3,3))),ll=sum(dnbinom(d$y,mu=mu,size=.5,log=TRUE)),
 score=max(abs(crossprod(X,(d$y-mu)/(1+2*mu)))),default_dispersion=summary(f)$dispersion)
write.table(data.frame(key=names(values),value=values),"oracle.tsv",sep="\t",row.names=FALSE,quote=FALSE)
