# Workbench 1.8.11
# project: review
# run: selected-sheet
# lineage_hash: 6666666666666666666666666666666666666666666666666666666666666666
# Coverage
# result | data.subset | native | 
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

data[["source"]] <- wb_read("data.xlsx", "556c1e00b493dbb8c32c5cee748dba23ee37f3ad860eaef9610c3c04715af8fc", "xlsx", list("sheet"="Chosen"))
data[["result"]] <- data[["source"]]
data[["result"]] <- data[["result"]][, c("x"), drop=FALSE]
checks[[1]] <- as.numeric(nrow(data[["result"]]))
stopifnot(identical(names(data[["result"]]), c("x")))
# Closing self-checks
wb_check(checks[[1]], 3, 0.0, 0.0, "result:nrows")
