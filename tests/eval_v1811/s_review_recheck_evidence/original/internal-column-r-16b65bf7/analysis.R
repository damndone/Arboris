# Workbench 1.8.11
# project: review
# run: internal-column
# lineage_hash: 2222222222222222222222222222222222222222222222222222222222222222
# Coverage
# model | model.ols | native | 
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

data[["source"]] <- wb_read("data.csv", "0bea4e0503803b2c2abcc213d13f39d8a90afd7d4e346aa1ae854bcbae99482f", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
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
wb_model_frame1[["category"]] <- factor(wb_model_frame1[["category"]], levels=sort(unique(wb_model_frame1[["category"]])))
wb_aliases <- list()
wb_aliases[[paste0("category",levels(wb_model_frame1[["category"]])[match(2.0,as.numeric(levels(wb_model_frame1[["category"]])))])]] <- "C(Q('category'))[T.2]"
wb_aliases[[paste0("category",levels(wb_model_frame1[["category"]])[match(3.0,as.numeric(levels(wb_model_frame1[["category"]])))])]] <- "C(Q('category'))[T.3]"
wb_frame <- wb_model_frame1
wb_fit <- lm(`y` ~ `wb_cat0` + `category`, data=wb_frame)
wb_cov <- vcov(wb_fit)
wb_df <- df.residual(wb_fit)
results[["model"]] <- wb_model(wb_fit,wb_cov,wb_df,"t",wb_aliases)
checks[[1]] <- as.numeric(results[["model"]][["beta"]][["Intercept"]])
checks[[2]] <- as.numeric(results[["model"]][["beta"]][["C(Q('category'))[T.2]"]])
checks[[3]] <- as.numeric(results[["model"]][["beta"]][["C(Q('category'))[T.3]"]])
checks[[4]] <- as.numeric(results[["model"]][["beta"]][["wb_cat0"]])
checks[[5]] <- as.numeric(results[["model"]][["se"]][["Intercept"]])
checks[[6]] <- as.numeric(results[["model"]][["se"]][["C(Q('category'))[T.2]"]])
checks[[7]] <- as.numeric(results[["model"]][["se"]][["C(Q('category'))[T.3]"]])
checks[[8]] <- as.numeric(results[["model"]][["se"]][["wb_cat0"]])
checks[[9]] <- as.numeric(results[["model"]]$nobs)
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[10]] <- as.numeric(results[["model"]][["statistic"]][["Intercept"]])
checks[[11]] <- as.numeric(results[["model"]][["p"]][["Intercept"]])
checks[[12]] <- as.numeric(results[["model"]][["df"]])
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[13]] <- as.numeric(results[["model"]][["statistic"]][["C(Q('category'))[T.2]"]])
checks[[14]] <- as.numeric(results[["model"]][["p"]][["C(Q('category'))[T.2]"]])
checks[[15]] <- as.numeric(results[["model"]][["df"]])
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[16]] <- as.numeric(results[["model"]][["statistic"]][["C(Q('category'))[T.3]"]])
checks[[17]] <- as.numeric(results[["model"]][["p"]][["C(Q('category'))[T.3]"]])
checks[[18]] <- as.numeric(results[["model"]][["df"]])
stopifnot(results[["model"]][["distribution"]] == "t")
checks[[19]] <- as.numeric(results[["model"]][["statistic"]][["wb_cat0"]])
checks[[20]] <- as.numeric(results[["model"]][["p"]][["wb_cat0"]])
checks[[21]] <- as.numeric(results[["model"]][["df"]])
writeLines(sprintf("%.17g",unlist(checks)),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 1.3535431849425417, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[2]], 0.5355131851309874, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[3]], 1.5052757759719748, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[4]], 0.012904407887460556, 1e-08, 1e-06, "model:coefficients")
wb_check(checks[[5]], 0.1148576860774841, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[6]], 0.16341097766868193, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[7]], 0.16317681892709418, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[8]], 0.06663453232839193, 1e-08, 1e-05, "model:std_errors")
wb_check(checks[[9]], 240, 0.0, 0.0, "model:nobs")
wb_check(checks[[10]], 11.78452423314038, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[11]], 1.6316144141067668e-25, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[12]], 236.0, 0.0, 0.0, "model:statistics.df")
wb_check(checks[[13]], 3.277094310131037, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[14]], 0.0012067239241645097, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[15]], 236.0, 0.0, 0.0, "model:statistics.df")
wb_check(checks[[16]], 9.224813829987196, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[17]], 1.6556596795009354e-17, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[18]], 236.0, 0.0, 0.0, "model:statistics.df")
wb_check(checks[[19]], 0.19365946509332954, 1e-08, 1e-05, "model:statistics.value")
wb_check(checks[[20]], 0.8466091101084966, 1e-06, 0.0, "model:statistics.p_value")
wb_check(checks[[21]], 236.0, 0.0, 0.0, "model:statistics.df")


