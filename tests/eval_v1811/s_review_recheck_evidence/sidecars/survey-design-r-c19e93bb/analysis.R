# Workbench 1.8.11
# project: survey
# run: native
# lineage_hash: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
# Coverage
# model | model.ols | native_with_equivalence_note | Full no-FPC linearization design; coefficient and joint-test df preserve the executed Workbench convention.
# post | postestimation.wald | native | 
data <- list()
results <- list()
checks <- list()
args <- commandArgs(FALSE)
script <- sub("^--file=", "", args[grepl("^--file=", args)])
base <- dirname(normalizePath(script))
wb_read <- function(name, digest, fmt, options=list()) {
  path <- file.path(base, name)
  hash <- system2("shasum", c("-a", "256", shQuote(path)), stdout=TRUE)
  if (length(hash) != 1L || substr(hash,1,64) != digest) stop(paste("SHA256 mismatch:", name))
  switch(fmt,
    csv=do.call(read.csv, c(list(file=path, check.names=FALSE, stringsAsFactors=FALSE, blank.lines.skip=FALSE, na.strings=c("", "NA")), options)),
    dta=haven::read_dta(path), sav=haven::read_sav(path), xlsx=openxlsx::read.xlsx(path, sheet=if(is.null(options$sheet)) 1 else options$sheet, check.names=FALSE, skipEmptyRows=FALSE, skipEmptyCols=FALSE),
    parquet=as.data.frame(arrow::read_parquet(path)), stop("Unsupported source format"))
}
wb_check <- function(actual, expected, absolute, relative, label) {
  if (length(actual)!=1 || !is.finite(actual) || abs(actual-expected)>absolute+relative*abs(expected))
    stop(paste(label, actual, "!=", expected))
}

data[["source"]] <- wb_read("data.csv", "5f8d0cc66fc9efdfd08e6a06640ea410d58671fe93ac5cac2ad90d6aa68de937", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
wb_model <- function(fit, covariance=vcov(fit), df=NULL, distribution="z", aliases=NULL, likelihood=TRUE) {
  beta <- coef(fit)
  names <- names(beta)
  if (!is.null(aliases)) names <- vapply(names, function(n) if (n %in% names(aliases)) aliases[[n]] else n, character(1))
  names <- gsub("`", "", names, fixed=TRUE)
  names[names=="(Intercept)"] <- "Intercept"
  names(beta) <- names
  se <- sqrt(diag(covariance)); names(se) <- names
  statistic <- beta/se
  p <- if (distribution=="t") 2*pt(-abs(statistic),df) else 2*pnorm(-abs(statistic))
  list(beta=beta,se=se,statistic=statistic,p=p,covariance=covariance,names=names,df=df,
       distribution=distribution,nobs=nobs(fit),fit=fit,loglik=if(likelihood) as.numeric(logLik(fit)) else NULL,link=if(is.null(fit$family$link)) "identity" else fit$family$link, design=model.matrix(fit),sample=rownames(model.frame(fit)))
}

wb_model_frame1 <- data[["source"]]
wb_aliases <- list()
wb_frame <- wb_model_frame1[complete.cases(wb_model_frame1[, c("y", "x1", "x2"),drop=FALSE]),,drop=FALSE]
options(survey.lonely.psu="fail")
wb_design <- survey::svydesign(ids=~psu, strata=~stratum, weights=~weight, data=wb_frame, nest=TRUE)
wb_design_df <- survey::degf(wb_design)
wb_fit <- survey::svyglm(`y` ~ `x1` + `x2`, design=wb_design, family=gaussian())
wb_df <- wb_design_df
results[["model"]] <- wb_model(wb_fit,vcov(wb_fit),wb_df,"t",wb_aliases,likelihood=FALSE)
results[["model"]]$nobs <- nrow(wb_frame)
results[["model"]]$loglik <- NULL
results[["model"]]$df_method <- "design"
checks[[1]] <- as.numeric(results[["model"]][["beta"]][["Intercept"]])
checks[[2]] <- as.numeric(results[["model"]][["beta"]][["x1"]])
checks[[3]] <- as.numeric(results[["model"]][["beta"]][["x2"]])
checks[[4]] <- as.numeric(results[["model"]][["se"]][["Intercept"]])
checks[[5]] <- as.numeric(results[["model"]][["se"]][["x1"]])
checks[[6]] <- as.numeric(results[["model"]][["se"]][["x2"]])
checks[[7]] <- as.numeric(results[["model"]]$nobs)
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[8]] <- as.numeric(results[["model"]][["statistic"]][["Intercept"]])
checks[[9]] <- as.numeric(results[["model"]][["p"]][["Intercept"]])
checks[[10]] <- as.numeric(results[["model"]][["df"]])
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[11]] <- as.numeric(results[["model"]][["statistic"]][["x1"]])
checks[[12]] <- as.numeric(results[["model"]][["p"]][["x1"]])
checks[[13]] <- as.numeric(results[["model"]][["df"]])
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[14]] <- as.numeric(results[["model"]][["statistic"]][["x2"]])
checks[[15]] <- as.numeric(results[["model"]][["p"]][["x2"]])
checks[[16]] <- as.numeric(results[["model"]][["df"]])
wb_single <- function(model, estimate, se) {
  value <- estimate/se
  p <- if (model$distribution=="t") 2*pt(-abs(value),model$df) else 2*pnorm(-abs(value))
  list(value=value,p_value=p,df=model$df,df_denominator=NULL,distribution=model$distribution)
}
wb_wald <- function(model, R, target) {
  gap <- R %*% model$beta-target
  if (qr(R)$rank!=nrow(R)) stop("Dependent Wald restrictions")
  W <- as.numeric(t(gap) %*% solve(R %*% model$covariance %*% t(R),gap));q <- nrow(R)
  finite <- model$distribution=="t"; value <- if(finite) W/q else W
  denominator <- if(finite) model$df else NULL
  if(finite && identical(model$df_method,"design") && q>1) {
    denominator <- model$df-q+1
    if(denominator<=0) stop("Too few survey design degrees of freedom")
    value <- W*denominator/(model$df*q)
  }
  p <- if(finite) pf(value,q,denominator,lower.tail=FALSE) else pchisq(value,q,lower.tail=FALSE)
  list(beta=list(),se=list(),statistics=list(test=list(value=value,p_value=p,df=q,df_denominator=denominator,distribution=if(finite) "F" else "chi2")))
}
wb_lincom <- function(model, vector, constant) {
  estimate <- sum(vector*model$beta)+constant
  se <- sqrt(as.numeric(t(vector) %*% model$covariance %*% vector))
  list(beta=list(estimate=estimate),se=list(estimate=se),statistics=list(test=wb_single(model,estimate,se)))
}
wb_nlcom <- function(model, fn) {
  point <- model$beta;estimate <- fn(point)
  gradient <- vapply(seq_along(point),function(i) { h <- 6e-6*max(1,abs(point[i]));hi <- lo <- point;hi[i] <- hi[i]+h;lo[i] <- lo[i]-h;(fn(hi)-fn(lo))/(2*h) }, numeric(1))
  se <- sqrt(as.numeric(t(gradient) %*% model$covariance %*% gradient))
  list(beta=list(estimate=estimate),se=list(estimate=se),statistics=list(test=wb_single(model,estimate,se)))
}
wb_lr <- function(full,restricted) {
  if (is.null(full$loglik)||is.null(restricted$loglik)) stop("Likelihood unavailable")
  if (!identical(full$sample,restricted$sample)) stop("LR estimation samples differ")
  if (!all(restricted$names %in% full$names)||length(full$names)<=length(restricted$names)) stop("Models are not nested")
  value <- max(0,2*(full$loglik-restricted$loglik));df <- length(full$beta)-length(restricted$beta)
  list(beta=list(),se=list(),statistics=list(test=list(value=value,p_value=pchisq(value,df,lower.tail=FALSE),df=df,df_denominator=NULL,distribution="chi2")))
}
wb_links <- list(identity=function(eta) list(rep(1,length(eta)),rep(0,length(eta))),
  logit=function(eta) {p <- plogis(eta);list(p*(1-p),p*(1-p)*(1-2*p))},
  probit=function(eta) list(dnorm(eta),-eta*dnorm(eta)),log=function(eta) list(exp(eta),exp(eta)))
wb_margins <- function(model,variables,at) {
  X <- model$design;if (at=="means") X <- matrix(colMeans(X),nrow=1)
  beta <- model$beta;derivatives <- wb_links[[model$link]](as.numeric(X %*% beta))
  mean_first <- mean(derivatives[[1]]);curvature <- colMeans(derivatives[[2]]*X)
  estimates <- errors <- statistics <- list()
  for (name in variables) {
    j <- match(name,model$names);estimate <- mean_first*beta[j];gradient <- curvature*beta[j];gradient[j] <- gradient[j]+mean_first
    se <- sqrt(as.numeric(t(gradient) %*% model$covariance %*% gradient))
    estimates[[name]] <- estimate;errors[[name]] <- se;statistics[[name]] <- wb_single(model,estimate,se)
  }
  list(beta=estimates,se=errors,statistics=statistics,nobs=model$nobs)
}

wb_m <- results[["model"]]
wb_R <- matrix(0,nrow=2,ncol=length(wb_m$beta))
wb_R[1, match("x1",wb_m$names)] <- 1
wb_R[2, match("x2",wb_m$names)] <- 1
results[["post"]] <- wb_wald(wb_m, wb_R, c(0.2, 0))
checks[[17]] <- as.numeric(results[["post"]]$statistics[["test"]][["value"]])
checks[[18]] <- as.numeric(results[["post"]]$statistics[["test"]][["p_value"]])
checks[[19]] <- as.numeric(results[["post"]]$statistics[["test"]][["df"]])
checks[[20]] <- as.numeric(results[["post"]]$statistics[["test"]][["df_denominator"]])
stopifnot(results[["post"]]$statistics[["test"]]$distribution == "F")
# Closing self-checks
wb_check(checks[[1]], 4.652711573943123, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[2]], 1.475820771771979, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[3]], -0.40404481777033774, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[4]], 1.5955241455226616, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[5]], 0.17732404110690134, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[6]], 0.08888234469730581, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[7]], 80, 0.0, 0.0, "model:nobs")
wb_check(checks[[8]], 2.9161022645752492, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[9]], 0.019406798019796175, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[10]], 8, 0.0, 0.0, "model:statistics.df")
wb_check(checks[[11]], 8.322733694537604, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[12]], 3.2813378097179405e-05, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[13]], 8, 0.0, 0.0, "model:statistics.df")
wb_check(checks[[14]], -4.545838874371921, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[15]], 0.0018846599328036571, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[16]], 8, 0.0, 0.0, "model:statistics.df")
wb_check(checks[[17]], 88.6728244577567, 1e-08, 1e-05, "post:statistics.value")
wb_check(checks[[18]], 1.0669105752740756e-05, 1e-06, 0.0, "post:statistics.p_value")
wb_check(checks[[19]], 2, 0.0, 0.0, "post:statistics.df")
wb_check(checks[[20]], 7.0, 0.0, 0.0, "post:statistics.df_denominator")
