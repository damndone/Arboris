suppressPackageStartupMessages({library(car); library(sandwich); library(jsonlite)})
root <- 'tests/fixtures/agent_completion/iv_ar'
cases <- list()
for (name in c('q1','q2','q3','q4','distant')) {
  d <- read.csv(file.path(root,paste0(name,'.csv')))
  instruments <- grep('^z',names(d),value=TRUE)
  q <- length(instruments)
  offset <- if (name=='distant') 12000 else 0
  points <- offset+c(-10000,-10,-1,0,1,1.5,2,4,10,10000)
  tests <- lapply(points, function(b) {
    d$transformed <- d$y-b*d$x
    f <- lm(reformulate(c('w',instruments),'transformed'),d)
    robust <- linearHypothesis(f, instruments, vcov.=vcovHC(f,type='HC0'),test='Chisq')
    homo <- linearHypothesis(f,instruments,test='F')
    list(b=b, hc0_chi_square=unname(robust[2,'Chisq']), homoskedastic_f=unname(homo[2,'F']))
  })
  # Native package Wald tests; roots below are local brackets only. They do not
  # certify absence of other components. Global topology is proved separately.
  stat <- function(b) {
    d$transformed <- d$y-b*d$x
    f <- lm(reformulate(c('w',instruments),'transformed'),d)
    linearHypothesis(f,instruments,vcov.=vcovHC(f,type='HC0'),test='Chisq')[2,'Chisq']-qchisq(.95,q)
  }
  centre <- offset+1.5
  bounds <- c(uniroot(stat,c(offset-10,centre),tol=1e-10)$root,
              uniroot(stat,c(centre,offset+10),tol=1e-10)$root)
  cases[[name]] <- list(source=file.path(root,paste0(name,'.csv')), q=q, tests=tests, local_boundaries=bounds)
}
output <- list(environment=list(R=R.version.string,car=as.character(packageVersion('car')),
                  sandwich=as.character(packageVersion('sandwich'))), cases=cases,
  definition='Native car::linearHypothesis(lm(y-b*x ~ w+Z), vcov.=sandwich::vcovHC(type=HC0), test=Chisq); independent point and local boundary oracle, not global topology proof')
writeLines(toJSON(output,auto_unbox=TRUE,pretty=TRUE,digits=NA),file.path(root,'reference_r.json'))
