# Workbench 1.8.11
# project: fixture-project
# run: fixture-run
# lineage_hash: 0000000000000000000000000000000000000000000000000000000000000000
# Coverage
# step:subset | data.subset | native | 
# step:recode | data.recode | native | 
# step:ols | model.ols | native | 
# step:wald | postestimation.wald | native | 
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

data[["source:1"]] <- wb_read("data.csv", "dc82ffc5e7649b9ff9886d1c55818a10888175a1f783648d8638a4a38a677094", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
data[["step:subset"]] <- data[["source:1"]]
data[["step:subset"]] <- data[["step:subset"]][which((!is.na(data[["step:subset"]][["age"]]) & ((data[["step:subset"]][["age"]] >= 25) & (data[["step:subset"]][["age"]] <= 55)))), , drop=FALSE]
data[["step:subset"]] <- data[["step:subset"]][, c("id", "firm", "age", "educ", "region", "wage"), drop=FALSE]
checks[[1]] <- as.numeric(nrow(data[["step:subset"]]))
stopifnot(identical(names(data[["step:subset"]]), c("id", "firm", "age", "educ", "region", "wage")))
data[["step:recode"]] <- data[["step:subset"]]
data[["step:recode"]][["age_group"]] <- NA_real_
wb_assigned <- rep(FALSE, nrow(data[["step:recode"]]))
wb_mask <- which((!wb_assigned) & ((!is.na(data[["step:recode"]][["age"]]) & ((data[["step:recode"]][["age"]] >= 25) & (data[["step:recode"]][["age"]] <= 39)))))
data[["step:recode"]][["age_group"]][wb_mask] <- 1
wb_assigned[wb_mask] <- TRUE
wb_mask <- which((!wb_assigned) & ((!is.na(data[["step:recode"]][["age"]]) & ((data[["step:recode"]][["age"]] >= 40) & (data[["step:recode"]][["age"]] <= 55)))))
data[["step:recode"]][["age_group"]][wb_mask] <- 2
wb_assigned[wb_mask] <- TRUE
stopifnot(all(wb_assigned | !(!is.na(data[["step:recode"]][["age"]]))))
checks[[2]] <- as.numeric(nrow(data[["step:recode"]]))
stopifnot(identical(names(data[["step:recode"]]), c("id", "firm", "age", "educ", "region", "wage", "age_group")))
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

wb_model_frame3 <- data[["step:recode"]]
wb_model_frame3[["region"]] <- factor(wb_model_frame3[["region"]], levels=sort(unique(wb_model_frame3[["region"]])))
wb_aliases <- list()
wb_aliases[[paste0("region","north")]] <- "C(Q('region'))[T.north]"
wb_aliases[[paste0("region","south")]] <- "C(Q('region'))[T.south]"
wb_aliases[[paste0("region","west")]] <- "C(Q('region'))[T.west]"
wb_frame <- wb_model_frame3
wb_fit <- lm(`wage` ~ `educ` + `age` + `age_group` + `region`, data=wb_frame)
wb_cov <- vcov(wb_fit)
wb_df <- df.residual(wb_fit)
wb_groups <- wb_frame[rownames(model.frame(wb_fit)), "firm"]
wb_cov <- sandwich::vcovCL(wb_fit, cluster=wb_groups, type="HC1", cadjust=TRUE)
wb_df <- length(unique(wb_groups))-1
results[["step:ols"]] <- wb_model(wb_fit,wb_cov,wb_df,"t",wb_aliases)
checks[[3]] <- as.numeric(results[["step:ols"]][["beta"]][["Intercept"]])
checks[[4]] <- as.numeric(results[["step:ols"]][["beta"]][["C(Q('region'))[T.north]"]])
checks[[5]] <- as.numeric(results[["step:ols"]][["beta"]][["C(Q('region'))[T.south]"]])
checks[[6]] <- as.numeric(results[["step:ols"]][["beta"]][["C(Q('region'))[T.west]"]])
checks[[7]] <- as.numeric(results[["step:ols"]][["beta"]][["educ"]])
checks[[8]] <- as.numeric(results[["step:ols"]][["beta"]][["age"]])
checks[[9]] <- as.numeric(results[["step:ols"]][["beta"]][["age_group"]])
checks[[10]] <- as.numeric(results[["step:ols"]][["se"]][["Intercept"]])
checks[[11]] <- as.numeric(results[["step:ols"]][["se"]][["C(Q('region'))[T.north]"]])
checks[[12]] <- as.numeric(results[["step:ols"]][["se"]][["C(Q('region'))[T.south]"]])
checks[[13]] <- as.numeric(results[["step:ols"]][["se"]][["C(Q('region'))[T.west]"]])
checks[[14]] <- as.numeric(results[["step:ols"]][["se"]][["educ"]])
checks[[15]] <- as.numeric(results[["step:ols"]][["se"]][["age"]])
checks[[16]] <- as.numeric(results[["step:ols"]][["se"]][["age_group"]])
checks[[17]] <- as.numeric(results[["step:ols"]]$nobs)
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

wb_m <- results[["step:ols"]]
wb_R <- matrix(0,nrow=2,ncol=length(wb_m$beta))
wb_R[1, match("educ",wb_m$names)] <- 1
wb_R[2, match("age",wb_m$names)] <- 1
results[["step:wald"]] <- wb_wald(wb_m, wb_R, c(0, 0))
checks[[18]] <- as.numeric(results[["step:wald"]]$statistics[["test"]][["value"]])
checks[[19]] <- as.numeric(results[["step:wald"]]$statistics[["test"]][["p_value"]])
checks[[20]] <- as.numeric(results[["step:wald"]]$statistics[["test"]][["df"]])
checks[[21]] <- as.numeric(results[["step:wald"]]$statistics[["test"]][["df_denominator"]])
stopifnot(results[["step:wald"]]$statistics[["test"]]$distribution == "F")
# Closing self-checks
wb_check(checks[[1]], 374, 0.0, 0.0, "step:subset:nrows")
wb_check(checks[[2]], 374, 0.0, 0.0, "step:recode:nrows")
wb_check(checks[[3]], 1.476111525279607, 1e-08, 1e-06, "step:ols:coefficients")
wb_check(checks[[4]], -0.12117350337143339, 1e-08, 1e-06, "step:ols:coefficients")
wb_check(checks[[5]], -0.2094250433328843, 1e-08, 1e-06, "step:ols:coefficients")
wb_check(checks[[6]], -0.16099337563024796, 1e-08, 1e-06, "step:ols:coefficients")
wb_check(checks[[7]], 0.08130065224244855, 1e-08, 1e-06, "step:ols:coefficients")
wb_check(checks[[8]], 0.0040281644255432455, 1e-08, 1e-06, "step:ols:coefficients")
wb_check(checks[[9]], 0.021759128365677213, 1e-08, 1e-06, "step:ols:coefficients")
wb_check(checks[[10]], 0.22734577137866313, 1e-08, 1e-05, "step:ols:std_errors")
wb_check(checks[[11]], 0.09529187132344039, 1e-08, 1e-05, "step:ols:std_errors")
wb_check(checks[[12]], 0.08892559053438566, 1e-08, 1e-05, "step:ols:std_errors")
wb_check(checks[[13]], 0.08935301328837976, 1e-08, 1e-05, "step:ols:std_errors")
wb_check(checks[[14]], 0.007800058781949661, 1e-08, 1e-05, "step:ols:std_errors")
wb_check(checks[[15]], 0.006937600305070096, 1e-08, 1e-05, "step:ols:std_errors")
wb_check(checks[[16]], 0.11050990245307929, 1e-08, 1e-05, "step:ols:std_errors")
wb_check(checks[[17]], 368, 0.0, 0.0, "step:ols:nobs")
wb_check(checks[[18]], 54.741006828302886, 1e-08, 1e-05, "step:wald:statistics.value")
wb_check(checks[[19]], 4.765624154540682e-12, 1e-06, 0.0, "step:wald:statistics.p_value")
wb_check(checks[[20]], 2, 0.0, 0.0, "step:wald:statistics.df")
wb_check(checks[[21]], 39.0, 0.0, 0.0, "step:wald:statistics.df_denominator")
