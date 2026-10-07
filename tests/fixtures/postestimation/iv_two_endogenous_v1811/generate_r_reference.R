# VERIFICATION LEVEL: independent base-R 2SLS matrix fit and HC0 sandwich.
# No Workbench or linearmodels numerical results enter this reference.
suppressPackageStartupMessages(library(jsonlite))
args <- commandArgs(trailingOnly=TRUE)
if (length(args) != 1) stop("Provide a fresh output directory within the owned fixture directory")
owned <- normalizePath("tests/fixtures/postestimation/iv_two_endogenous_v1811")
output <- normalizePath(args[1])
if (!(output == owned || startsWith(output, paste0(owned, "/")))) stop("Output outside owned directory")
cat("Writing native R evidence to", output, "\n")
targets <- file.path(output, c("data.csv", "provenance.json", "r_reference.json"))
if (any(file.exists(targets))) stop("Retained native assets exist; choose a fresh output directory")
options(digits=17)
set.seed(18111004)
n <- 650L
x1 <- rnorm(n); z1 <- rnorm(n); z2 <- rnorm(n)
e <- rnorm(n); a <- rnorm(n); b <- rnorm(n)
v1 <- .7*e+a
v2 <- -.5*e+.3*a+b
xe1 <- .8*z1+.25*z2+.3*x1+v1
xe2 <- -.2*z1+.9*z2-.2*x1+v2
structural_error <- (1+.3*abs(x1))*e
y <- .7+.4*x1+.25*xe1-.18*xe2+structural_error
data <- data.frame(y=y,x1=x1,xe1=xe1,xe2=xe2,z1=z1,z2=z2)
write.table(data, targets[1], sep=",",row.names=FALSE,col.names=TRUE,quote=FALSE)
# Reimport the retained CSV so both native programs fit identical bytes.
d <- read.csv(targets[1])
X <- cbind(Intercept=1, x1=d$x1, xe1=d$xe1, xe2=d$xe2)
Z <- cbind(Intercept=1, x1=d$x1, z1=d$z1, z2=d$z2)
Xhat <- qr.fitted(qr(Z), X)
bread <- solve(crossprod(Xhat,X))
beta <- as.vector(bread %*% crossprod(Xhat,d$y)); names(beta) <- colnames(X)
residual <- as.vector(d$y-X%*%beta)
covariance <- bread %*% crossprod(Xhat*residual) %*% t(bread)
se <- sqrt(diag(covariance)); names(se) <- names(beta)
z <- beta/se
idx <- match(c("xe1","xe2"),names(beta))
statistic <- as.numeric(t(beta[idx])%*%solve(covariance[idx,idx],beta[idx]))
sha <- strsplit(system2("shasum", c("-a","256",shQuote(targets[1])),stdout=TRUE)," +")[[1]][1]
provenance <- list(source="Deterministic public synthetic DGP generated in base R; no user data",
  seed=18111004,nobs=n,endogenous=c("xe1","xe2"),excluded_instruments=c("z1","z2"),exogenous=I("x1"),
  dgp=list(v1="0.7*e+a",v2="-0.5*e+0.3*a+b",
    xe1="0.8*z1+0.25*z2+0.3*x1+v1",xe2="-0.2*z1+0.9*z2-0.2*x1+v2",
    structural_error="(1+0.3*abs(x1))*e",y="0.7+0.4*x1+0.25*xe1-0.18*xe2+structural_error",
    innovations="x1,z1,z2,e,a,b independent standard normal draws"),
  sample_correlations=list(xe1_structural_error=cor(xe1,structural_error),
    xe2_structural_error=cor(xe2,structural_error),z1_structural_error=cor(z1,structural_error),
    z2_structural_error=cor(z2,structural_error)),
  regressor_rank=qr(X)$rank,instrument_rank=qr(Z)$rank,data_sha256=sha)
reference <- list(reference="Independent base R projected-regressor 2SLS / HC0 sandwich",
  environment=list(R=R.version.string,jsonlite=as.character(packageVersion("jsonlite"))),
  data_sha256=sha,terms=names(beta),nobs=n,params=as.list(beta),std_error=as.list(se),
  covariance=unname(covariance),z=as.list(z),p=as.list(2*pnorm(-abs(z))),
  nominal_residual_df=n-ncol(X),inference=list(covariance_estimator="HC0",unbiased=FALSE,
    debiased=FALSE,reference_distribution="z",df_method="asymptotic",df_den=NULL,
    covariance_formula="(Xhat'X)^(-1) Xhat'diag(u^2)Xhat (Xhat'X)^(-1)'",
    small_sample_factor=1),
  wald_joint=list(distribution="chi2",statistic=statistic,df_num=2L,df_den=NULL,
    p_value=pchisq(statistic,2,lower.tail=FALSE),constraints=c("xe1=0","xe2=0")))
write_json(provenance,targets[2],auto_unbox=TRUE,digits=17,pretty=TRUE,null="null")
write_json(reference,targets[3],auto_unbox=TRUE,digits=17,pretty=TRUE,null="null")
print(sessionInfo())
print(beta); print(se); print(covariance)
cat("Joint Wald chi2(2):",statistic,"p:",reference$wald_joint$p_value,"\n")
cat("Data SHA256:",sha,"\n")
