# Workbench 1.8.11
# project: glm_nb
# run: 0.5
# lineage_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
# Coverage
# full | model.glm:negative_binomial | native | 
# restricted | model.glm:negative_binomial | native | 
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

data[["source"]] <- wb_read("data.csv", "2e1b92f07632a8c88d047074f77cd6e5f9552b4f932f7d6ed2499161a0bf3084", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
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
wb_fit <- glm(`ynb` ~ `x1` + `x2` + `x3`,data=wb_model_frame1,family=MASS::negative.binomial(theta=1/0.5,link="log"),control=glm.control(epsilon=1e-16,maxit=1000))
stopifnot(wb_fit$converged,all(is.finite(coef(wb_fit))))
wb_X <- model.matrix(wb_fit)
wb_mu <- exp(drop(wb_X %*% coef(wb_fit)))
wb_cov <- solve(crossprod(wb_X,wb_X*(wb_mu/(1+0.5*wb_mu))))
stopifnot(all(is.finite(wb_cov)))
results[["full"]] <- wb_model(wb_fit,wb_cov,aliases=wb_aliases)
checks[[1]] <- as.numeric(results[["full"]][["beta"]][["Intercept"]])
checks[[2]] <- as.numeric(results[["full"]][["beta"]][["x1"]])
checks[[3]] <- as.numeric(results[["full"]][["beta"]][["x2"]])
checks[[4]] <- as.numeric(results[["full"]][["beta"]][["x3"]])
checks[[5]] <- as.numeric(results[["full"]][["se"]][["Intercept"]])
checks[[6]] <- as.numeric(results[["full"]][["se"]][["x1"]])
checks[[7]] <- as.numeric(results[["full"]][["se"]][["x2"]])
checks[[8]] <- as.numeric(results[["full"]][["se"]][["x3"]])
checks[[9]] <- as.numeric(results[["full"]]$nobs)
wb_model_frame2 <- data[["source"]]
wb_aliases <- list()
wb_fit <- glm(`ynb` ~ `x1`,data=wb_model_frame2,family=MASS::negative.binomial(theta=1/0.5,link="log"),control=glm.control(epsilon=1e-16,maxit=1000))
stopifnot(wb_fit$converged,all(is.finite(coef(wb_fit))))
wb_X <- model.matrix(wb_fit)
wb_mu <- exp(drop(wb_X %*% coef(wb_fit)))
wb_cov <- solve(crossprod(wb_X,wb_X*(wb_mu/(1+0.5*wb_mu))))
stopifnot(all(is.finite(wb_cov)))
results[["restricted"]] <- wb_model(wb_fit,wb_cov,aliases=wb_aliases)
# Standalone inference primitive probe; public postestimation admission is checked separately.
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

checks[[10]] <- as.numeric(results[["full"]]$covariance[1,1])
checks[[11]] <- as.numeric(results[["full"]]$covariance[1,2])
checks[[12]] <- as.numeric(results[["full"]]$covariance[1,3])
checks[[13]] <- as.numeric(results[["full"]]$covariance[1,4])
checks[[14]] <- as.numeric(results[["full"]]$covariance[2,1])
checks[[15]] <- as.numeric(results[["full"]]$covariance[2,2])
checks[[16]] <- as.numeric(results[["full"]]$covariance[2,3])
checks[[17]] <- as.numeric(results[["full"]]$covariance[2,4])
checks[[18]] <- as.numeric(results[["full"]]$covariance[3,1])
checks[[19]] <- as.numeric(results[["full"]]$covariance[3,2])
checks[[20]] <- as.numeric(results[["full"]]$covariance[3,3])
checks[[21]] <- as.numeric(results[["full"]]$covariance[3,4])
checks[[22]] <- as.numeric(results[["full"]]$covariance[4,1])
checks[[23]] <- as.numeric(results[["full"]]$covariance[4,2])
checks[[24]] <- as.numeric(results[["full"]]$covariance[4,3])
checks[[25]] <- as.numeric(results[["full"]]$covariance[4,4])
wb_probe <- wb_wald(results[["full"]], matrix(c(0, 1, 0, 0, 0, 0, 1, 0),nrow=2,byrow=TRUE),c(0, 0))
checks[[26]] <- as.numeric(wb_probe$statistics[["test"]][["value"]])
checks[[27]] <- as.numeric(wb_probe$statistics[["test"]][["p_value"]])
checks[[28]] <- as.numeric(wb_probe$statistics[["test"]][["df"]])
stopifnot(wb_probe$statistics[["test"]]$distribution == "chi2")
wb_probe <- wb_wald(results[["full"]], matrix(c(0, 1, -1, 0),nrow=1,byrow=TRUE),c(1))
checks[[29]] <- as.numeric(wb_probe$statistics[["test"]][["value"]])
checks[[30]] <- as.numeric(wb_probe$statistics[["test"]][["p_value"]])
checks[[31]] <- as.numeric(wb_probe$statistics[["test"]][["df"]])
stopifnot(wb_probe$statistics[["test"]]$distribution == "chi2")
wb_probe <- wb_lincom(results[["full"]], c(0,1,2,0), -.5)
checks[[32]] <- as.numeric(wb_probe[["beta"]][["estimate"]])
checks[[33]] <- as.numeric(wb_probe[["se"]][["estimate"]])
checks[[34]] <- as.numeric(wb_probe$statistics[["test"]][["value"]])
checks[[35]] <- as.numeric(wb_probe$statistics[["test"]][["p_value"]])
stopifnot(wb_probe$statistics[["test"]]$distribution == "z")
wb_probe <- wb_nlcom(results[["full"]], function(b) b[["x1"]]/b[["x2"]])
checks[[36]] <- as.numeric(wb_probe[["beta"]][["estimate"]])
checks[[37]] <- as.numeric(wb_probe[["se"]][["estimate"]])
checks[[38]] <- as.numeric(wb_probe$statistics[["test"]][["value"]])
checks[[39]] <- as.numeric(wb_probe$statistics[["test"]][["p_value"]])
stopifnot(wb_probe$statistics[["test"]]$distribution == "z")
wb_probe <- wb_lr(results[["full"]],results[["restricted"]])
checks[[40]] <- as.numeric(wb_probe$statistics[["test"]][["value"]])
checks[[41]] <- as.numeric(wb_probe$statistics[["test"]][["p_value"]])
checks[[42]] <- as.numeric(wb_probe$statistics[["test"]][["df"]])
stopifnot(wb_probe$statistics[["test"]]$distribution == "chi2")
wb_probe <- wb_margins(results[["full"]],c("x1","x2"),"average")
checks[[43]] <- as.numeric(wb_probe[["beta"]][["x1"]])
checks[[44]] <- as.numeric(wb_probe[["beta"]][["x2"]])
checks[[45]] <- as.numeric(wb_probe[["se"]][["x1"]])
checks[[46]] <- as.numeric(wb_probe[["se"]][["x2"]])
checks[[47]] <- as.numeric(wb_probe$nobs)
wb_probe <- wb_margins(results[["full"]],c("x1","x2"),"means")
checks[[48]] <- as.numeric(wb_probe[["beta"]][["x1"]])
checks[[49]] <- as.numeric(wb_probe[["beta"]][["x2"]])
checks[[50]] <- as.numeric(wb_probe[["se"]][["x1"]])
checks[[51]] <- as.numeric(wb_probe[["se"]][["x2"]])
checks[[52]] <- as.numeric(wb_probe$nobs)
writeLines(format(unlist(checks),digits=17,trim=TRUE),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 0.5294190766274965, 1e-08, 0, "full:coefficients")
wb_check(checks[[2]], 0.3808453229171612, 1e-08, 0, "full:coefficients")
wb_check(checks[[3]], -0.29806517727677795, 1e-08, 0, "full:coefficients")
wb_check(checks[[4]], -0.10833250363412572, 1e-08, 0, "full:coefficients")
wb_check(checks[[5]], 0.14028025583591924, 1e-06, 0, "full:std_errors")
wb_check(checks[[6]], 0.06283421954867592, 1e-06, 0, "full:std_errors")
wb_check(checks[[7]], 0.05471088883162485, 1e-06, 0, "full:std_errors")
wb_check(checks[[8]], 0.1217725004803211, 1e-06, 0, "full:std_errors")
wb_check(checks[[9]], 300, 0.0, 0.0, "full:nobs")
wb_check(checks[[10]], 0.019678550177390956, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[11]], -0.00033393023438837733, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[12]], 0.00012168684550802438, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[13]], -0.015188215245293268, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[14]], -0.0003339302343883775, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[15]], 0.003948139146291206, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[16]], -4.492202954898318e-05, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[17]], -0.0005450070641983157, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[18]], 0.00012168684550802437, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[19]], -4.492202954898328e-05, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[20]], 0.0029932813567464128, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[21]], 0.00035850408651598664, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[22]], -0.015188215245293268, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[23]], -0.0005450070641983158, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[24]], 0.0003585040865159866, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[25]], 0.014828541873229802, 1e-08, 1e-06, "full:statistics.value")
wb_check(checks[[26]], 65.56604799118558, 0.0, 1e-06, "wald_joint:statistics.value")
wb_check(checks[[27]], 5.787800841522105e-15, 0.0, 1e-05, "wald_joint:statistics.p_value")
wb_check(checks[[28]], 2, 0.0, 0.0, "wald_joint:statistics.df")
wb_check(checks[[29]], 14.662862700531432, 0.0, 1e-06, "wald_shifted:statistics.value")
wb_check(checks[[30]], 0.00012855435494768384, 0.0, 1e-05, "wald_shifted:statistics.p_value")
wb_check(checks[[31]], 1, 0.0, 0.0, "wald_shifted:statistics.df")
wb_check(checks[[32]], -0.7152850316363947, 0.0, 1e-06, "lincom:coefficients")
wb_check(checks[[33]], 0.1254654392854101, 0.0, 1e-06, "lincom:std_errors")
wb_check(checks[[34]], -5.70105230340968, 0.0, 1e-06, "lincom:statistics.value")
wb_check(checks[[35]], 1.1907009230017913e-08, 0.0, 1e-05, "lincom:statistics.p_value")
wb_check(checks[[36]], -1.2777249808135591, 0.0, 1e-06, "nlcom:coefficients")
wb_check(checks[[37]], 0.3132924544398737, 0.0, 1e-06, "nlcom:std_errors")
wb_check(checks[[38]], -4.078377767182315, 0.0, 1e-06, "nlcom:statistics.value")
wb_check(checks[[39]], 4.535103510326398e-05, 0.0, 1e-05, "nlcom:statistics.p_value")
wb_check(checks[[40]], 32.091685454637286, 0.0, 1e-06, "lr_drop_x2_x3:statistics.value")
wb_check(checks[[41]], 1.074927184180779e-07, 0.0, 1e-05, "lr_drop_x2_x3:statistics.p_value")
wb_check(checks[[42]], 2, 0.0, 0.0, "lr_drop_x2_x3:statistics.df")
wb_check(checks[[43]], 0.6563673408291717, 0.0, 1e-06, "margins_average:coefficients")
wb_check(checks[[44]], -0.5137000133439795, 0.0, 1e-06, "margins_average:coefficients")
wb_check(checks[[45]], 0.12335275178705468, 0.0, 1e-05, "margins_average:std_errors")
wb_check(checks[[46]], 0.10472884520065841, 0.0, 1e-05, "margins_average:std_errors")
wb_check(checks[[47]], 300, 0.0, 0.0, "margins_average:nobs")
wb_check(checks[[48]], 0.5746074027696974, 0.0, 1e-06, "margins_means:coefficients")
wb_check(checks[[49]], -0.4497113310012097, 0.0, 1e-06, "margins_means:coefficients")
wb_check(checks[[50]], 0.09460541302509871, 0.0, 1e-05, "margins_means:std_errors")
wb_check(checks[[51]], 0.08236970423645469, 0.0, 1e-05, "margins_means:std_errors")
wb_check(checks[[52]], 300, 0.0, 0.0, "margins_means:nobs")
