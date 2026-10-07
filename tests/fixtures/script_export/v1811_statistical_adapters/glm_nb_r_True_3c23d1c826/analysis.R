# Workbench 1.8.11
# project: glm_nb
# run: 1.0
# lineage_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
# Coverage
# full | model.glm | native | 
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
wb_fit <- glm(`ynb` ~ `x1` + `x2` + `x3`,data=wb_model_frame1,family=MASS::negative.binomial(theta=1/1.0,link="log"),control=glm.control(epsilon=1e-16,maxit=1000))
stopifnot(wb_fit$converged,all(is.finite(coef(wb_fit))))
wb_X <- model.matrix(wb_fit)
wb_mu <- exp(drop(wb_X %*% coef(wb_fit)))
wb_cov <- solve(crossprod(wb_X,wb_X*(wb_mu/(1+1.0*wb_mu))))
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
writeLines(format(unlist(checks),digits=17,trim=TRUE),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 0.524033398275554, 1e-08, 0, "full:coefficients")
wb_check(checks[[2]], 0.37889378683709035, 1e-08, 0, "full:coefficients")
wb_check(checks[[3]], -0.28894515154376593, 1e-08, 0, "full:coefficients")
wb_check(checks[[4]], -0.10121807811349151, 1e-08, 0, "full:coefficients")
wb_check(checks[[5]], 0.16986251046239487, 1e-06, 0, "full:std_errors")
wb_check(checks[[6]], 0.07594663821229021, 1e-06, 0, "full:std_errors")
wb_check(checks[[7]], 0.06578041865981685, 1e-06, 0, "full:std_errors")
wb_check(checks[[8]], 0.14744903698769615, 1e-06, 0, "full:std_errors")
wb_check(checks[[9]], 300, 0.0, 0.0, "full:nobs")
