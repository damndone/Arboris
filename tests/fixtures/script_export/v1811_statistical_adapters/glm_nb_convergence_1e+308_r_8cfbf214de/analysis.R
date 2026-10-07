# Workbench 1.8.11
# project: glm_nb_convergence
# run: 1e+308
# lineage_hash: ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
# Coverage
# model | model.glm:negative_binomial | native | 
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

data[["source"]] <- wb_read("data.csv", "2f2bbd4ad27086b457c361e63b4156be3500493e4cb0114a4477c95135daf355", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
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
wb_alpha <- 1e+308
wb_fit <- glm(`y` ~ `x1` + `x2`,data=wb_model_frame1,family=MASS::negative.binomial(theta=1/wb_alpha,link="log"),control=glm.control(epsilon=1e-16,maxit=1000))
wb_X <- model.matrix(wb_fit); wb_y <- model.response(model.frame(wb_fit))
# Native glm deviance can underflow for large dispersion. Certify the final parameter point instead.
wb_converged <- FALSE
for (wb_iteration in seq_len(1000)) {
  wb_previous <- coef(wb_fit)
  stopifnot(all(is.finite(wb_previous)))
  wb_next <- suppressWarnings(glm.fit(wb_X,wb_y,family=wb_fit$family,start=wb_previous,control=glm.control(epsilon=1e-16,maxit=1)))
  wb_fit[names(wb_next)] <- wb_next
  wb_mu <- exp(drop(wb_X %*% coef(wb_fit))); wb_denominator <- 1+wb_alpha*wb_mu
  if (!all(is.finite(wb_mu)) || any(wb_mu<=0) || !all(is.finite(wb_denominator))) stop("GLM_NB_NUMERIC_FAILURE: non-finite native mean or variance")
  wb_score_residual <- if (wb_alpha>=1) (wb_y/wb_mu-1)/(1+1/(wb_alpha*wb_mu)) else (wb_y-wb_mu)/wb_denominator
  wb_scaled_score <- max(abs(drop(crossprod(wb_X,wb_score_residual)))/nrow(wb_X)/pmax(1,colMeans(abs(wb_X))))
  wb_parameter_change <- max(abs(coef(wb_fit)-wb_previous)/pmax(1,abs(wb_previous)))
  if (is.finite(wb_scaled_score) && wb_parameter_change<=1e-12 && wb_scaled_score<=1e-10) { wb_converged <- TRUE; break }
}
if (!wb_converged) stop("GLM_NB_NOT_CONVERGED: native parameters or scaled score did not converge")
wb_fit$converged <- TRUE; wb_fit$iter <- wb_iteration
wb_cov <- solve(crossprod(wb_X,wb_X*(wb_mu/wb_denominator)))
stopifnot(all(is.finite(wb_cov)))
results[["model"]] <- wb_model(wb_fit,wb_cov,aliases=wb_aliases)
checks[[1]] <- as.numeric(results[["model"]]$nobs)
writeLines(format(unlist(checks),digits=17,trim=TRUE),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 240, 0.0, 0.0, "model:nobs")
