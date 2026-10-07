# Workbench 1.8.11
# project: model-oracle
# run: negative_binomial
# lineage_hash: 1111111111111111111111111111111111111111111111111111111111111111
# Coverage
# model | model.negative_binomial | native | 
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

data[["source"]] <- wb_read("data.csv", "0f643fba418a92bc7a08befa218425056e866314340e1148775107241af4e143", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
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
wb_fit <- MASS::glm.nb(`nb` ~ `x` + `z`, data=wb_model_frame1, control=glm.control(epsilon=1e-12,maxit=100))
wb_X <- model.matrix(wb_fit)
wb_y <- model.response(model.frame(wb_fit))
wb_start <- c(coef(wb_fit),log(1/wb_fit$theta))
wb_nll <- function(parameters) {mu <- exp(wb_X %*% parameters[seq_len(ncol(wb_X))]); alpha <- exp(parameters[length(parameters)]); -sum(dnbinom(wb_y,mu=mu,size=1/alpha,log=TRUE))}
wb_hessian <- optimHess(wb_start,wb_nll,control=list(ndeps=rep(1e-4,length(wb_start))))
wb_cov <- solve(wb_hessian)[seq_len(ncol(wb_X)),seq_len(ncol(wb_X)),drop=FALSE]
results[["model"]] <- wb_model(wb_fit, wb_cov, aliases=wb_aliases)
checks[[1]] <- as.numeric(results[["model"]][["beta"]][["Intercept"]])
checks[[2]] <- as.numeric(results[["model"]][["beta"]][["x"]])
checks[[3]] <- as.numeric(results[["model"]][["beta"]][["z"]])
checks[[4]] <- as.numeric(results[["model"]][["se"]][["Intercept"]])
checks[[5]] <- as.numeric(results[["model"]][["se"]][["x"]])
checks[[6]] <- as.numeric(results[["model"]][["se"]][["z"]])
checks[[7]] <- as.numeric(results[["model"]]$nobs)
stopifnot(results[["model"]][["distribution"]] == "z")
checks[[8]] <- as.numeric(results[["model"]][["statistic"]][["Intercept"]])
checks[[9]] <- as.numeric(results[["model"]][["p"]][["Intercept"]])
stopifnot(results[["model"]][["distribution"]] == "z")
checks[[10]] <- as.numeric(results[["model"]][["statistic"]][["x"]])
checks[[11]] <- as.numeric(results[["model"]][["p"]][["x"]])
stopifnot(results[["model"]][["distribution"]] == "z")
checks[[12]] <- as.numeric(results[["model"]][["statistic"]][["z"]])
checks[[13]] <- as.numeric(results[["model"]][["p"]][["z"]])
writeLines(format(unlist(checks),digits=17,trim=TRUE),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 0.10851292261202276, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[2]], 0.32492468922364875, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[3]], -0.15375475867698613, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[4]], 0.06669042046072572, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[5]], 0.0653253220041807, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[6]], 0.0705561035827149, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[7]], 350, 0.0, 0.0, "model:nobs")
wb_check(checks[[8]], 1.6271140871862773, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[9]], 0.10371286966217054, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[10]], 4.973946997197414, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[11]], 6.560325292163608e-07, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[12]], -2.179184377673791, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[13]], 0.02931797400075623, 1e-06, 0.0, "model:statistics.p_value")
