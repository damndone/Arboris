# Closed-form attribution of the retained E6 reference stop point; no refit.
a <- commandArgs(TRUE)
x <- read.csv(a[1])$value
retained <- jsonlite::fromJSON(a[2])
measure <- function(v, x) list(variance=v, ll=sum(dnorm(x,sd=sqrt(v),log=TRUE)),
    score=-length(x)/(2*v)+sum(x*x)/(2*v*v), score_per_observation=(-length(x)/(2*v)+sum(x*x)/(2*v*v))/length(x))
full <- mean(x*x)
prefix <- mean(x[1:140]^2)
result <- list(R_version=R.version.string, definition='zero mean Gaussian: variance MLE = mean(y^2), no optimization',
    n=length(x),closed=measure(full,x),
    workbench=measure(retained$full$variance_stage$parameters$sigma2,x),
    stata=measure(retained$native$variance,x),
    prefix_closed=measure(prefix,x[1:140]),
    prefix_workbench=measure(retained$first$conditional_variance,x[1:140]),
    prefix_stata=measure(retained$native$prefix_variance,x[1:140]))
jsonlite::write_json(result,a[3],digits=17,pretty=TRUE,auto_unbox=TRUE)
