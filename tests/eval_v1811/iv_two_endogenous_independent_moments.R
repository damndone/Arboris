# Independent exactly-identified IV moment solve; no fitted owner/reference values.
library(jsonlite)
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args)==2)
input <- args[1]; output <- args[2]
target <- file.path(output,"r_moment_reference.json")
if (file.exists(target)) stop("Preserve retained independent evidence")
options(digits=17)
d <- read.csv(input); n <- nrow(d)
X <- cbind(Intercept=1,as.matrix(d[c("x1","xe1","xe2")]))
Z <- cbind(Intercept=1,as.matrix(d[c("x1","z1","z2")]))
# Equal numbers of instruments and parameters permit direct moment equations.
G <- crossprod(Z,X)/n
beta <- drop(solve(G,crossprod(Z,d$y)/n)); names(beta) <- colnames(X)
u <- drop(d$y-X%*%beta)
A <- solve(G)
S <- crossprod(Z*u)/n
V <- A%*%S%*%t(A)/n
se <- sqrt(diag(V)); names(se) <- names(beta)
index <- match(c("xe1","xe2"),names(beta))
W <- drop(crossprod(beta[index],solve(V[index,index],beta[index])))
ols <- drop(qr.coef(qr(X),d$y))
# Reconstruct the public DGP using a single matrix of sequential native draws.
set.seed(18111004)
draw <- matrix(rnorm(n*6),nrow=n)
x1 <- draw[,1]; z1 <- draw[,2]; z2 <- draw[,3]
e <- draw[,4]; a <- draw[,5]; b <- draw[,6]
xe1 <- .8*z1+.25*z2+.3*x1+.7*e+a
xe2 <- -.2*z1+.9*z2-.2*x1-.5*e+.3*a+b
structural_error <- (1+.3*abs(x1))*e
y <- .7+.4*x1+.25*xe1-.18*xe2+structural_error
reconstructed <- data.frame(y,x1,xe1,xe2,z1,z2)
repro <- file.path(output,"reconstructed_data.csv")
if (file.exists(repro)) stop("Preserve reconstructed sample")
write.table(reconstructed,repro,sep=",",row.names=FALSE,col.names=TRUE,quote=FALSE)
sha <- function(path) strsplit(system2("shasum",c("-a","256",shQuote(path)),stdout=TRUE)," +")[[1]][1]
partial_Z <- qr.resid(qr(cbind(1,d$x1)),as.matrix(d[c("z1","z2")]))
partial_E <- qr.resid(qr(cbind(1,d$x1)),as.matrix(d[c("xe1","xe2")]))
result <- list(method="Exactly identified moment solve beta=(Z'X)^-1 Z'y; HC0 moment sandwich A S A'/N",
 environment=list(R=R.version.string,jsonlite=as.character(packageVersion("jsonlite"))),
 nobs=n,nominal_residual_df=n-ncol(X),terms=names(beta),params=as.list(beta),
 covariance=unname(V),std_error=as.list(se),z=as.list(beta/se),p=as.list(2*pnorm(-abs(beta/se))),
 wald_joint=list(distribution="chi2",statistic=W,df_num=2,df_den=NULL,p_value=pchisq(W,2,lower.tail=FALSE)),
 inference=list(HC0=TRUE,unbiased=FALSE,debiased=FALSE,small_sample_factor=1,reference_distribution="z"),
 diagnostics=list(X_rank=qr(X)$rank,Z_rank=qr(Z)$rank,moment_max_abs=max(abs(crossprod(Z,u)/n)),
 conditional_instrument_rank=qr(crossprod(partial_Z,partial_E))$rank,
 conditional_instrument_singular_values=svd(crossprod(partial_Z,partial_E)/n)$d,
 corr_endogenous_structural_error=c(cor(xe1,structural_error),cor(xe2,structural_error)),
 corr_excluded_structural_error=c(cor(z1,structural_error),cor(z2,structural_error)),
 ols_beta=unname(ols),ols_difference=unname(ols-beta)),
 source_sha256=sha(input),reconstructed_sha256=sha(repro),
 reconstructed_max_abs_difference=max(abs(as.matrix(read.csv(repro))-as.matrix(d))))
write_json(result,target,auto_unbox=TRUE,digits=17,pretty=TRUE,null="null")
print(sessionInfo()); print(result)
