# Native fixed-alpha log GLM on the unchanged committed postestimation sample.
# The final expected information is evaluated at the reported coefficients.
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args)==3)
input <- args[1]; source_sha256 <- args[2]; output <- args[3]
if (dir.exists(output)) stop("Preserve previous native oracle directories")
dir.create(output,recursive=TRUE)
packages <- c("MASS","car","lmtest","marginaleffects","jsonlite")
missing <- packages[!vapply(packages,requireNamespace,logical(1),quietly=TRUE)]
if (length(missing)) stop(paste("Required installed packages unavailable:",paste(missing,collapse=", ")))
environment <- list(r_version=R.version.string,platform=R.version$platform,
                    packages=setNames(lapply(packages,function(p)as.character(packageVersion(p))),packages))
print(environment)
d <- read.csv(input)
epsilon <- 1e-16
fit_case <- function(formula) {
  warnings <- character()
  fit <- withCallingHandlers(glm(formula,data=d,family=MASS::negative.binomial(theta=1,link="log"),
              control=glm.control(epsilon=epsilon,maxit=1000,trace=TRUE)),
              warning=function(w) warnings <<- c(warnings,conditionMessage(w)))
  X <- model.matrix(fit); mu <- exp(drop(X%*%coef(fit)))
  information <- crossprod(X,X*(mu/(1+mu)))
  covariance <- solve(information); chol(information)
  dimnames(covariance) <- list(names(coef(fit)),names(coef(fit)))
  score <- drop(crossprod(X,(fit$y-mu)/(1+mu)))
  ll <- sum(dnbinom(fit$y,mu=mu,size=1,log=TRUE))
  stopifnot(abs(ll-as.numeric(logLik(fit))) < 1e-10)
  list(fit=fit,covariance=covariance,diagnostic=list(converged=fit$converged,iterations=fit$iter,
       warnings=as.list(warnings),formula=paste(deparse(formula),collapse=""),
       nobs=nobs(fit),df_resid=df.residual(fit),score=unname(score),max_absolute_score=max(abs(score)),
       ll=ll,information=unname(information),params=as.list(coef(fit)),covariance=unname(covariance)))
}
full <- fit_case(ynb~x1+x2+x3); restricted <- fit_case(ynb~x1)
wald <- function(hypothesis) {
  row <- car::linearHypothesis(full$fit,hypothesis,test="Chisq",vcov.=full$covariance)[2,]
  list(distribution="chi2",statistic=row[["Chisq"]],df_num=row[["Df"]],p_value=row[["Pr(>Chisq)"]])
}
delta <- function(expression) {
  result <- car::deltaMethod(full$fit,expression,vcov.=full$covariance)
  list(estimate=result[["Estimate"]],std_error=result[["SE"]])
}
lr_table <- lmtest::lrtest(restricted$fit,full$fit)
lr <- list(statistic=lr_table[2,"Chisq"],df=lr_table[2,"Df"],p_value=lr_table[2,"Pr(>Chisq)"],
           loglik_full=as.numeric(logLik(full$fit)),loglik_restricted=as.numeric(logLik(restricted$fit)))
pick <- function(result) {
  result <- as.data.frame(result)
  setNames(lapply(seq_len(nrow(result)),function(i)list(estimate=result$estimate[i],std_error=result$std.error[i])),result$term)
}
margins <- list(average=pick(marginaleffects::avg_slopes(full$fit,variables=c("x1","x2"),vcov=full$covariance)),
                at_means=pick(marginaleffects::slopes(full$fit,variables=c("x1","x2"),newdata="mean",vcov=full$covariance)))
oracle <- list(params=as.list(coef(full$fit)),wald_joint=wald(c("x1=0","x2=0")),wald_shifted=wald("x1-x2=1"),
               lincom=delta("x1+2*x2-0.5"),nlcom=delta("x1/x2"),lr_drop_x2_x3=lr,margins=margins,
               covariance=unname(full$covariance),std_error=as.list(sqrt(diag(full$covariance))),
               nobs=nobs(full$fit),ll=as.numeric(logLik(full$fit)),
               meta=list(generator="tests/fixtures/postestimation/glm_negative_binomial_v1811/generate_oracle.R",
                         baseline="01fb0752bce129c8d8848c021eca776dadccb515",source=input,source_sha256=source_sha256,
                         full_formula="ynb ~ x1 + x2 + x3",restricted_formula="ynb ~ x1",alpha_fixed=1,
                         epsilon=epsilon,scale=1,information_matrix="expected",reference_distribution="z",
                         covariance_estimator="nonrobust",environment=environment),
               native_diagnostics=list(full=full$diagnostic,restricted=restricted$diagnostic))
full_precision <- function(value) {
  if (is.list(value)) return(lapply(value,full_precision))
  if (is.numeric(value)) {
    result <- sprintf("%.17g",value)
    if (!is.null(names(value))) names(result)<-names(value)
    if (!is.null(dim(value))) dim(result)<-dim(value)
    return(result)
  }
  value
}
oracle$full_precision <- full_precision(oracle)
jsonlite::write_json(oracle,file.path(output,"oracle.json"),digits=NA,pretty=TRUE,auto_unbox=TRUE)
print(oracle[c("params","wald_joint","wald_shifted","lincom","nlcom","lr_drop_x2_x3","margins")])
cat("Native R fixed-alpha five-operation oracle saved\n")
