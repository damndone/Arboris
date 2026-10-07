# Exact provenance replay preserving the declared innovation grouping.
library(jsonlite)
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args)==2)
input <- args[1]; output <- args[2]
target <- file.path(output,"reconstructed_exact.csv")
if (file.exists(target)) stop("Preserve earlier exact reconstruction")
options(digits=17)
set.seed(18111004)
n <- 650
draw <- matrix(rnorm(6*n),nrow=n)
x1 <- draw[,1]; z1 <- draw[,2]; z2 <- draw[,3]
e <- draw[,4]; a <- draw[,5]; b <- draw[,6]
v1 <- .7*e+a
v2 <- -.5*e+.3*a+b
xe1 <- .8*z1+.25*z2+.3*x1+v1
xe2 <- -.2*z1+.9*z2-.2*x1+v2
structural_error <- (1+.3*abs(x1))*e
y <- .7+.4*x1+.25*xe1-.18*xe2+structural_error
write.table(data.frame(y,x1,xe1,xe2,z1,z2),target,sep=",",row.names=FALSE,col.names=TRUE,quote=FALSE)
sha <- function(p) strsplit(system2("shasum",c("-a","256",shQuote(p)),stdout=TRUE)," +")[[1]][1]
record <- list(source_sha256=sha(input),reconstructed_sha256=sha(target),byte_identical=identical(readBin(input,"raw",n=file.info(input)$size),readBin(target,"raw",n=file.info(target)$size)))
write_json(record,file.path(output,"reconstructed_exact.json"),auto_unbox=TRUE,digits=17,pretty=TRUE)
print(record)
stopifnot(record$byte_identical)
