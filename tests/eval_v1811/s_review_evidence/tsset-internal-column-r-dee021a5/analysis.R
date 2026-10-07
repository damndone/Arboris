# Workbench 1.8.11
# project: review
# run: tsset-internal-column
# lineage_hash: 4444444444444444444444444444444444444444444444444444444444444444
# Coverage
# result | data.tsset | native | 
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
    dta=haven::read_dta(path), sav=haven::read_sav(path), xlsx=readxl::read_excel(path),
    parquet=as.data.frame(arrow::read_parquet(path)), stop("Unsupported source format"))
}
wb_check <- function(actual, expected, absolute, relative, label) {
  if (length(actual)!=1 || !is.finite(actual) || abs(actual-expected)>absolute+relative*abs(expected))
    stop(paste(label, actual, "!=", expected))
}

data[["source"]] <- wb_read("data.csv", "939eb0dbfb058ae46a294f9560682d2169e55d365d0a4255344bb1aba7a21853", "csv", list())
data[["result"]] <- data[["source"]]
wb_time <- data[["result"]][["time"]]
if (is.character(wb_time)) wb_time <- as.POSIXct(wb_time, tz="UTC")
stopifnot(!anyNA(wb_time))
data[["result"]] <- data[["result"]][order(wb_time),,drop=FALSE]
checks[[1]] <- as.numeric(nrow(data[["result"]]))
stopifnot(identical(names(data[["result"]]), c("time", "__wb_time")))
# Closing self-checks
wb_check(checks[[1]], 2, 0.0, 0.0, "result:nrows")

write.csv(data[["result"]],"actual.csv",row.names=FALSE,na="")
