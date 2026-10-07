# Same committed inputs and likelihoods; independent native R precision audit.
# No old oracle is overwritten and no Workbench estimator is invoked here.
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args) == 3)
post_input <- args[1]; glm_input <- args[2]; output <- args[3]
if (dir.exists(output)) stop("Preserve earlier reference directories")
dir.create(output, recursive=TRUE)
packages <- c("MASS", "car", "marginaleffects", "jsonlite")
missing <- packages[!vapply(packages, requireNamespace, logical(1), quietly=TRUE)]
if (length(missing)) stop(paste("Required existing R packages unavailable:", paste(missing, collapse=", ")))
print(list(R=R.version.string, packages=setNames(lapply(packages, function(p) as.character(packageVersion(p))), packages)))

full_precision <- function(value) {
  if (is.list(value)) return(lapply(value, full_precision))
  if (is.numeric(value)) {
    answer <- sprintf("%.17g", value)
    if (!is.null(dim(value))) dim(answer) <- dim(value)
    if (!is.null(names(value))) names(answer) <- names(value)
    return(answer)
  }
  value
}
persist <- function(value, name) {
  value$full_precision <- full_precision(value)
  jsonlite::write_json(value, file.path(output, name), auto_unbox=TRUE, digits=NA, pretty=TRUE)
}

d <- read.csv(post_input)
X <- model.matrix(~ x1 + x2 + x3, d); y <- d$ynb; k <- ncol(X)
nb_ll <- function(p) sum(dnbinom(y, mu=exp(drop(X %*% p[1:k])), size=1/p[k+1], log=TRUE))
nb_derivatives <- function(p) {
  alpha <- p[k+1]; theta <- 1/alpha; mu <- exp(drop(X %*% p[1:k]))
  st <- digamma(y+theta)-digamma(theta)+log(theta/(theta+mu))+(mu-y)/(theta+mu)
  htt <- trigamma(y+theta)-trigamma(theta)+1/theta-1/(theta+mu)-(mu-y)/(theta+mu)^2
  score <- c(drop(crossprod(X, (y-mu)/(1+alpha*mu))), -theta^2*sum(st))
  hessian <- matrix(0, k+1, k+1)
  hessian[1:k, 1:k] <- -crossprod(X, X*(mu*(1+alpha*y)/(1+alpha*mu)^2))
  hessian[1:k, k+1] <- hessian[k+1, 1:k] <- drop(crossprod(X, -mu*(y-mu)/(1+alpha*mu)^2))
  hessian[k+1, k+1] <- theta^4*sum(htt)+2*theta^3*sum(st)
  list(score=score, information=-hessian)
}

snapshot <- function(p) {
  derivatives <- nb_derivatives(p)
  list(params=setNames(as.list(p), c(colnames(X), "alpha")), theta=1/p[k+1],
       ll=nb_ll(p), score=unname(derivatives$score),
       natural_mean_score_max=max(abs(derivatives$score))/nrow(X),
       information=unname(derivatives$information),
       information_eigenvalues=eigen(derivatives$information, symmetric=TRUE, only.values=TRUE)$values)
}

fit14 <- MASS::glm.nb(ynb ~ x1 + x2 + x3, data=d, control=glm.control(epsilon=1e-14, maxit=200), trace=1)
fit16 <- MASS::glm.nb(ynb ~ x1 + x2 + x3, data=d, control=glm.control(epsilon=1e-16, maxit=1000), trace=1)
p14 <- c(coef(fit14), 1/fit14$theta); p <- c(coef(fit16), 1/fit16$theta)
history <- list(snapshot(p))
for (iteration in seq_len(100)) {
  current <- nb_derivatives(p)
  if (max(abs(current$score))/nrow(X) <= 1e-13) break
  step <- solve(current$information, current$score)
  fraction <- 1
  repeat {
    candidate <- p + fraction*step
    if (candidate[k+1] > 0 && is.finite(nb_ll(candidate)) && nb_ll(candidate) >= nb_ll(p)-1e-12) break
    fraction <- fraction/2
    if (fraction < .Machine$double.eps) stop("Native R Newton refinement could not certify a regular interior optimum")
  }
  p <- candidate
  history[[length(history)+1]] <- snapshot(p)
}
stopifnot(max(abs(nb_derivatives(p)$score))/nrow(X) <= 1e-13)
information <- nb_derivatives(p)$information
joint_vcov <- solve(information); chol(information); chol(joint_vcov)
beta_vcov <- joint_vcov[1:k,1:k]
dimnames(beta_vcov) <- list(colnames(X), colnames(X))
fit <- fit16
fit$coefficients <- setNames(p[1:k], colnames(X)); fit$theta <- 1/p[k+1]
fit$linear.predictors <- drop(X %*% p[1:k]); fit$fitted.values <- exp(fit$linear.predictors)
fit$family <- MASS::negative.binomial(theta=fit$theta)

old_numeric_oim <- function(fit) {
  grad_theta <- function(par) {
    theta <- par[k+1]; mu <- exp(drop(X %*% par[1:k]))
    -c(colSums(X*((y-mu)*theta/(theta+mu))),
       sum(digamma(y+theta)-digamma(theta)+log(theta/(theta+mu))+(mu-y)/(theta+mu)))
  }
  par <- c(coef(fit), fit$theta)
  nll <- function(par) -sum(dnbinom(y, mu=exp(drop(X %*% par[1:k])), size=par[k+1], log=TRUE))
  solve(optimHess(par, nll, grad_theta, control=list(ndeps=rep(1e-6,k+1))))[1:k,1:k]
}
wald <- function(hypothesis, covariance) {
  h <- car::linearHypothesis(fit, hypothesis, test="Chisq", vcov.=covariance)[2,]
  list(statistic=h[["Chisq"]], p_value=h[["Pr(>Chisq)"]], df_num=h[["Df"]], distribution="chi2")
}
delta <- function(expression, covariance) {
  result <- car::deltaMethod(fit, expression, vcov.=covariance)
  list(estimate=result[["Estimate"]], std_error=result[["SE"]])
}
pick <- function(result) {
  result <- as.data.frame(result)
  setNames(lapply(seq_len(nrow(result)), function(i) list(estimate=result$estimate[i], std_error=result$std.error[i])), result$term)
}
margins <- list(average=pick(marginaleffects::avg_slopes(fit, variables=c("x1","x2"), vcov=beta_vcov)),
                at_means=pick(marginaleffects::slopes(fit, variables=c("x1","x2"), newdata="mean", vcov=beta_vcov)))
z <- qnorm(.975); alpha <- p[k+1]; se_alpha <- sqrt(joint_vcov[k+1,k+1]); log_se <- se_alpha/alpha
reference <- list(meta=list(input=post_input,n=nrow(X),formula="ynb ~ x1 + x2 + x3", likelihood="NB2 joint beta and natural alpha ML", covariance="full natural OIM inverse projected beta positions 0:3", reference_distribution="z", native_solver_tolerance=1e-13),
                  params=as.list(coef(fit)), theta=fit$theta, alpha=alpha, ll=nb_ll(p),
                  joint_vcov=unname(joint_vcov), beta_vcov=unname(beta_vcov),
                  ancillary=list(alpha=list(estimate=alpha,std_error=se_alpha,conf_low=exp(log(alpha)-z*log_se),conf_high=exp(log(alpha)+z*log_se)),
                                 lnalpha=list(estimate=log(alpha),std_error=log_se,conf_low=log(alpha)-z*log_se,conf_high=log(alpha)+z*log_se)),
                  wald_joint=wald(c("x1=0","x2=0"), beta_vcov), wald_shifted=wald("x1-x2=1", beta_vcov),
                  lincom=delta("x1+2*x2-0.5", beta_vcov), nlcom=delta("x1/x2", beta_vcov), margins=margins,
                  diagnostics=list(epsilon14=snapshot(p14), epsilon16=snapshot(c(coef(fit16),1/fit16$theta)),
                                   old_optimHess_beta_vcov=unname(old_numeric_oim(fit14)), refinement_history=history,
                                   final=snapshot(p)))
persist(reference,"nb2-postestimation-reference.json")
print(reference[c("params","alpha","wald_joint","wald_shifted","lincom","nlcom","margins")])

g <- read.csv(glm_input)
G <- model.matrix(~ x1+x2,g)
glm_reference <- list()
for (epsilon in c(1e-8,1e-14,1e-16)) {
  fitted <- glm(y~x1+x2,data=g,family=MASS::negative.binomial(theta=1),control=glm.control(epsilon=epsilon,maxit=1000))
  mu <- exp(drop(G %*% coef(fitted)))
  covariance <- solve(crossprod(G,G*(mu/(1+mu))))
  glm_reference[[sprintf("epsilon%.0e",epsilon)]] <- list(params=as.list(coef(fitted)),std_error=unname(sqrt(diag(covariance))),
        covariance=unname(covariance),ll=sum(dnbinom(g$y,size=1,mu=mu,log=TRUE)),iterations=fitted$iter,
        max_absolute_score=max(abs(crossprod(G,(g$y-mu)/(1+mu)))),
        meta=list(n=nrow(g),formula="y ~ x1 + x2",alpha_fixed=1,information="expected",scale=1,epsilon=epsilon))
}
persist(glm_reference,"glm-fixed-alpha-reference.json")
print(glm_reference)
cat("Saved new immutable v1811 numeric references\n")
