# Native REML random-intercept LMM fixed-effect reference, not an owner refit.
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args)==3)
input <- args[1]; output <- args[2]; source_sha <- args[3]
target <- file.path(output,"r_reference.json")
if (file.exists(target)) stop("Preserve earlier reference evidence")
library(lme4); library(car); library(jsonlite)
options(digits=17)
d <- read.csv(input)
d$arm <- factor(d$arm,levels=c("a","b"))
warnings <- character()
fit <- withCallingHandlers(lmer(y~arm*time+x+(1|g),data=d,REML=TRUE,
    control=lmerControl(optimizer="bobyqa",optCtrl=list(maxfun=100000))),
    warning=function(w) warnings <<- c(warnings,conditionMessage(w)))
b <- fixef(fit); V <- as.matrix(vcov(fit)); X <- model.matrix(fit)
mapping <- c("Intercept"="(Intercept)","C(Q('arm'), Treatment(reference='a'))[T.b]"="armb",
             "time"="time","C(Q('arm'), Treatment(reference='a'))[T.b]:Q('time')"="armb:time","x"="x")
owner_order <- match(unname(mapping),names(b))
wald <- function(hypothesis) {
    row <- car::linearHypothesis(fit,hypothesis,test="Chisq",vcov.=V)[2,]
    list(distribution="chi2",statistic=unname(row[["Chisq"]]),df_num=unname(row[["Df"]]),
         df_den=NULL,p_value=unname(row[["Pr(>Chisq)"]]))
}
single <- function(expression) {
    result <- car::deltaMethod(fit,expression,vcov.=V)
    estimate <- result[["Estimate"]]; se <- result[["SE"]]
    list(estimate=estimate,std_error=se,statistic=estimate/se,distribution="z",df=NULL,
         p_value=2*pnorm(-abs(estimate/se)))
}
prediction <- predict(fit,re.form=NA)
mean_design <- colMeans(X)
mean_estimate <- mean(prediction)
stopifnot(abs(mean_estimate-sum(mean_design*b))<1e-12)
mean_se <- sqrt(drop(t(mean_design)%*%V%*%mean_design))
reference <- list(meta=list(generator="tests/fixtures/postestimation/lmm_v1811/generate_reference.R",
 source=input,data_sha256=source_sha,formula="y ~ arm * time + x + (1|g)",fit_method="reml",
 environment=list(R=R.version.string,lme4=as.character(packageVersion("lme4")),car=as.character(packageVersion("car")),jsonlite=as.character(packageVersion("jsonlite"))),
 native_diagnostics=list(optimizer=fit@optinfo$optimizer,opt_convergence=fit@optinfo$conv$opt,
 convergence_messages=as.list(fit@optinfo$conv$lme4$messages),warnings=as.list(warnings),
 singular=isSingular(fit),REML=isREML(fit),loglik=as.numeric(logLik(fit)),sigma=sigma(fit))),
 nobs=nobs(fit),nominal_fixed_effect_df=nobs(fit)-length(b),owner_terms=names(mapping),coefficient_mapping=as.list(mapping),
 params=as.list(b),std_error=as.list(sqrt(diag(V))),covariance_owner_order=unname(V[owner_order,owner_order]),
 reference_distribution="z",df_method="asymptotic",
 wald_joint=wald(c("time=0","x=0")),wald_shifted=wald("time-x=1"),
 lincom=single("time+2*x-0.5"),nlcom=single("time/x"),
 fixed_effect_average_prediction=list(estimate=mean_estimate,std_error=mean_se,
   mean_design_owner_order=unname(mean_design[owner_order]),nobs=nobs(fit),
   definition="Empirical mean of native predict(fit,re.form=NA) on the unchanged estimation rows",
   random_effects="zero (population fixed-effect prediction)",
   uncertainty="sampling SE of empirical fixed-effect mean; excludes residual/new-subject prediction variance",
   current_operation="lincom with mean fixed-effect design weights; not a margins derivative target"),
 lr=list(available=FALSE,reason="REML_FIXED_EFFECT_LIKELIHOODS_NOT_COMPARABLE",
   explanation="Do not compare restricted likelihoods across different fixed-effect designs; no LR reference generated"))
write_json(reference,target,auto_unbox=TRUE,digits=17,pretty=TRUE,null="null")
print(sessionInfo()); print(reference)
