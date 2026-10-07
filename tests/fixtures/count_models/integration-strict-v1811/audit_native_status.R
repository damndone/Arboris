# Distinguish R's algorithm status/warnings from independently small scores.
args <- commandArgs(trailingOnly=TRUE)
if (file.exists(args[2])) stop("Preserve existing native status evidence")
d <- read.csv(args[1]); X <- model.matrix(~ x1+x2+x3,d); y <- d$ynb
results <- list()
for (epsilon in c(1e-14,1e-16)) {
  messages <- character()
  fit <- withCallingHandlers(MASS::glm.nb(ynb~x1+x2+x3,data=d,
            control=glm.control(epsilon=epsilon,maxit=if(epsilon==1e-14)200 else 1000,
                                trace=if(epsilon==1e-14)2 else 0)),
            warning=function(w) messages <<- c(messages,conditionMessage(w)))
  theta <- fit$theta; mu <- exp(drop(X %*% coef(fit)))
  score <- c(drop(crossprod(X,(y-mu)/(1+mu/theta))),
             -theta^2*sum(digamma(y+theta)-digamma(theta)+log(theta/(theta+mu))+(mu-y)/(theta+mu)))
  results[[sprintf("epsilon%.0e",epsilon)]] <- list(converged=fit$converged,final_glm_iterations=fit$iter,
            theta=sprintf("%.17g",theta),beta=sprintf("%.17g",coef(fit)),
            natural_score=sprintf("%.17g",score),natural_mean_score_max=sprintf("%.17g",max(abs(score))/nrow(X)),
            warnings=as.list(messages))
}
jsonlite::write_json(results,args[2],pretty=TRUE,auto_unbox=TRUE)
print(results)
