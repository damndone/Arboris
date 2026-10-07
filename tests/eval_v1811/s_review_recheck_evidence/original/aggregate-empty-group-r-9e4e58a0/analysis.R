# Workbench 1.8.11
# project: review
# run: aggregate-empty-group
# lineage_hash: 4444444444444444444444444444444444444444444444444444444444444444
# Coverage
# result | data.aggregate | native | 
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

data[["source"]] <- wb_read("data.csv", "1609211b4fec4d01adf93da8d4bfbdaae21706bb8256859bb6c6da400fcc5c14", "csv", list("sep"=",", "fileEncoding"="UTF-8", "header"=TRUE))
data[["result"]] <- data[["source"]]
data[["result"]]$.wb_order <- seq_len(nrow(data[["result"]]))
data[["result"]] <- dplyr::group_by(data[["result"]], dplyr::across(dplyr::all_of(c("group"))), .drop=FALSE)
data[["result"]] <- as.data.frame(dplyr::summarise(data[["result"]], .wb_order=min(.wb_order), minimum=if (all(is.na(x))) NA_real_ else min(x, na.rm=TRUE), maximum=if (all(is.na(x))) NA_real_ else max(x, na.rm=TRUE), .groups="drop"))
data[["result"]] <- data[["result"]][order(data[["result"]]$.wb_order),,drop=FALSE]
data[["result"]]$.wb_order <- NULL
checks[[1]] <- as.numeric(nrow(data[["result"]]))
stopifnot(identical(names(data[["result"]]), c("group", "minimum", "maximum")))
writeLines(sprintf("%.17g",unlist(checks)),"numeric_actual.tsv")
# Closing self-checks
wb_check(checks[[1]], 2, 0.0, 0.0, "result:nrows")

write.csv(data[["result"]],"actual.csv",row.names=FALSE,na="")
