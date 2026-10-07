# Workbench 1.8.11
# project: categories
# run: branches
# lineage_hash: 3333333333333333333333333333333333333333333333333333333333333333
# Coverage
# weighted | model.ols | native | 
# plain | model.ols | native | 
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

data[["source"]] <- wb_read("data.csv", "050b189f5fcd4768e53803d4dfeed0b822fe264a03c4d5414075e42e6a313024", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
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
wb_model_frame1[["region"]] <- factor(wb_model_frame1[["region"]], levels=sort(unique(wb_model_frame1[["region"]])))
wb_aliases <- list()
wb_aliases[[paste0("region","south")]] <- "C(Q('region'))[T.south]"
wb_aliases[[paste0("region","west")]] <- "C(Q('region'))[T.west]"
wb_frame <- wb_model_frame1
wb_frame <- wb_frame[rep(seq_len(nrow(wb_frame)), wb_frame[["fw"]]),,drop=FALSE]
wb_fit <- lm(`y` ~ `x` + `region`, data=wb_frame)
wb_cov <- vcov(wb_fit)
wb_df <- df.residual(wb_fit)
results[["weighted"]] <- wb_model(wb_fit,wb_cov,wb_df,"t",wb_aliases)
checks[[1]] <- as.numeric(results[["weighted"]][["beta"]][["Intercept"]])
checks[[2]] <- as.numeric(results[["weighted"]][["beta"]][["C(Q('region'))[T.south]"]])
checks[[3]] <- as.numeric(results[["weighted"]][["beta"]][["C(Q('region'))[T.west]"]])
checks[[4]] <- as.numeric(results[["weighted"]][["beta"]][["x"]])
checks[[5]] <- as.numeric(results[["weighted"]][["se"]][["Intercept"]])
checks[[6]] <- as.numeric(results[["weighted"]][["se"]][["C(Q('region'))[T.south]"]])
checks[[7]] <- as.numeric(results[["weighted"]][["se"]][["C(Q('region'))[T.west]"]])
checks[[8]] <- as.numeric(results[["weighted"]][["se"]][["x"]])
checks[[9]] <- as.numeric(results[["weighted"]]$nobs)
wb_model_frame2 <- data[["source"]]
wb_model_frame2[["region"]] <- factor(wb_model_frame2[["region"]], levels=sort(unique(wb_model_frame2[["region"]])))
wb_aliases <- list()
wb_aliases[[paste0("region","south")]] <- "C(Q('region'))[T.south]"
wb_aliases[[paste0("region","west")]] <- "C(Q('region'))[T.west]"
wb_frame <- wb_model_frame2
wb_fit <- lm(`y` ~ `x` + `region`, data=wb_frame)
wb_cov <- vcov(wb_fit)
wb_df <- df.residual(wb_fit)
results[["plain"]] <- wb_model(wb_fit,wb_cov,wb_df,"t",wb_aliases)
checks[[10]] <- as.numeric(results[["plain"]][["beta"]][["Intercept"]])
checks[[11]] <- as.numeric(results[["plain"]][["beta"]][["C(Q('region'))[T.south]"]])
checks[[12]] <- as.numeric(results[["plain"]][["beta"]][["C(Q('region'))[T.west]"]])
checks[[13]] <- as.numeric(results[["plain"]][["beta"]][["x"]])
checks[[14]] <- as.numeric(results[["plain"]][["se"]][["Intercept"]])
checks[[15]] <- as.numeric(results[["plain"]][["se"]][["C(Q('region'))[T.south]"]])
checks[[16]] <- as.numeric(results[["plain"]][["se"]][["C(Q('region'))[T.west]"]])
checks[[17]] <- as.numeric(results[["plain"]][["se"]][["x"]])
checks[[18]] <- as.numeric(results[["plain"]]$nobs)
writeLines(format(unlist(checks),digits=17,trim=TRUE),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 1.1406181831101954, 1e-08, 1e-06, "weighted:coefficients")
wb_check(checks[[2]], -0.08780030675457805, 1e-08, 1e-06, "weighted:coefficients")
wb_check(checks[[3]], -0.10670733571832419, 1e-08, 1e-06, "weighted:coefficients")
wb_check(checks[[4]], 0.5668151259087681, 1e-08, 1e-06, "weighted:coefficients")
wb_check(checks[[5]], 0.06512778819857358, 1e-08, 1e-05, "weighted:std_errors")
wb_check(checks[[6]], 0.0938599257916859, 1e-08, 1e-05, "weighted:std_errors")
wb_check(checks[[7]], 0.0910083263007167, 1e-08, 1e-05, "weighted:std_errors")
wb_check(checks[[8]], 0.036096598808836394, 1e-08, 1e-05, "weighted:std_errors")
wb_check(checks[[9]], 692, 0.0, 0.0, "weighted:nobs")
wb_check(checks[[10]], 1.1525369575209923, 1e-08, 1e-06, "plain:coefficients")
wb_check(checks[[11]], -0.07713734612483514, 1e-08, 1e-06, "plain:coefficients")
wb_check(checks[[12]], -0.12606025144491617, 1e-08, 1e-06, "plain:coefficients")
wb_check(checks[[13]], 0.5722984010583434, 1e-08, 1e-06, "plain:coefficients")
wb_check(checks[[14]], 0.0907095488404284, 1e-08, 1e-05, "plain:std_errors")
wb_check(checks[[15]], 0.12857751264891099, 1e-08, 1e-05, "plain:std_errors")
wb_check(checks[[16]], 0.1283082512402164, 1e-08, 1e-05, "plain:std_errors")
wb_check(checks[[17]], 0.051233154659256375, 1e-08, 1e-05, "plain:std_errors")
wb_check(checks[[18]], 350, 0.0, 0.0, "plain:nobs")
