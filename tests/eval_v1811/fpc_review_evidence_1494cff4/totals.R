suppressPackageStartupMessages({library(survey);library(jsonlite)})
args<-commandArgs(trailingOnly=TRUE)
configs<-fromJSON(file.path(args[1],"configs.json"))
results<-list()
for(i in seq_len(nrow(configs))){
 c<-configs[i,];d<-read.csv(file.path(args[1],paste0(c$name,".csv")))
 options(survey.lonely.psu=c$policy,survey.adjust.domain.lonely=FALSE)
 results[[c$name]]<-tryCatch({
  des<-svydesign(ids=~psu,strata=~stratum,weights=~weight,fpc=~review_fpc,data=d,nest=TRUE)
  if(c$domain)des<-subset(des,review_domain==1)
  total<-svytotal(~x1+x2,des)
  list(estimate=as.list(coef(total)),covariance=unname(vcov(total)))
 },error=function(e)list(error=conditionMessage(e)))
}
write_json(results,file.path(args[1],"r_totals.json"),auto_unbox=TRUE,digits=17,pretty=TRUE)
