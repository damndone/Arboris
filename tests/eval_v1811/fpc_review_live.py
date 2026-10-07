"""Independent native FPC total-variance probes and oracle reproduction."""
from pathlib import Path
import json
import subprocess
import sys
import uuid

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stata_oracle import STATA,emit,run
from workbench.survey import SurveyDesign

ROOT=Path(__file__).resolve().parents[1]/"fixtures/survey_fpc_v1811"
OUT=Path(__file__).resolve().parent/("fpc_review_evidence_"+uuid.uuid4().hex[:8])
OUT.mkdir()
print(f"evidence_directory={OUT}",flush=True)
subprocess.run(["Rscript",str(ROOT/"generate_oracle.R"),str(OUT/"r_reproduced.json")],check=True)
original=json.loads((ROOT/"oracle_reference.json").read_text())
reproduced=json.loads((OUT/"r_reproduced.json").read_text())
assert original==reproduced
print("14 retained R reference cases reproduced exactly",flush=True)

configs=[]
for source in ("design","lonely","subpop"):
    for policy in ("fail","remove","certainty","adjust","average"):
        for mode in ("heterogeneous_count","certainty_plus_lonely"):
            if source!="lonely" and policy!="fail":continue
            frame=pd.read_csv(ROOT/f"{source}.csv")
            groups=frame.groupby("stratum")["psu"].nunique()
            n=frame.stratum.map(groups).to_numpy()
            h=frame.stratum.map({key:i for i,key in enumerate(groups.index)}).to_numpy()
            frame["review_fpc"]=n*(2+(h%3))
            if mode=="certainty_plus_lonely":
                # Leave the genuinely lonely stratum noncertainty while making
                # a healthy stratum census: exercise policy/FPC interactions.
                certainty=groups[groups>=2].index[0]
                frame.loc[frame.stratum==certainty,"review_fpc"]=n[frame.stratum==certainty]
            domain=source=="subpop"
            if domain:
                # Exclude a whole stratum, not merely individual observations.
                frame["review_domain"]=(frame.subpop==1)&(frame.stratum!=groups.index[0])
            else:frame["review_domain"]=True
            frame["review_domain"]=frame["review_domain"].astype(int)
            name=f"{source}_{mode}_{policy}"
            frame.to_csv(OUT/f"{name}.csv",index=False,float_format="%.17g")
            configs.append(dict(name=name,source=source,policy=policy,domain=domain))

r_code='''suppressPackageStartupMessages({library(survey);library(jsonlite)})
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
'''
(OUT/"configs.json").write_text(json.dumps(configs,indent=2))
(OUT/"totals.R").write_text(r_code)
subprocess.run(["Rscript",str(OUT/"totals.R"),str(OUT)],check=True)
oracles=json.loads((OUT/"r_totals.json").read_text())
comparisons=[];failures=[]
for config in configs:
    name=config["name"];frame=pd.read_csv(OUT/f"{name}.csv")
    design=SurveyDesign(frame,weight="weight",strata="stratum",psu="psu",fpc="review_fpc",lonely_psu=config["policy"])
    mask=frame.review_domain.to_numpy(dtype=bool)
    contributions=frame.loc[mask,["x1","x2"]].to_numpy()*frame.loc[mask,"weight"].to_numpy()[:,None]
    expected=oracles[name]
    try:actual=design._design_variance(contributions,mask=mask)
    except Exception as error:
        comparison={"name":name,"workbench_error":str(error),"r":expected}
        if "error" not in expected:failures.append(comparison)
    else:
        comparison={"name":name,"workbench":actual.tolist(),"r":expected}
        if "error" in expected:failures.append(comparison)
        else:
            comparison["maximum_absolute_difference"]=float(np.max(np.abs(actual-np.asarray(expected["covariance"]))))
            try:np.testing.assert_allclose(actual,expected["covariance"],rtol=1e-9,atol=1e-9)
            except AssertionError as error:failures.append({**comparison,"assertion":str(error)})
    comparisons.append(comparison)
    print(json.dumps(comparison),flush=True)

# Fresh Stata check of coefficient/SE/DF/Wald/lincom on two retained CSV cases.
assert STATA.exists(),"Real Stata required; no skip"
body=[]
for case,source in [("population","design"),("subpopulation","subpop")]:
    body.append(f'import delimited "{ROOT/(source+".csv")}", clear asdouble case(preserve)')
    body.append('svyset psu [pweight=weight], strata(stratum) fpc(population_fpc) singleunit(missing)')
    body.append('svy, subpop(subpop): regress y x1 x2' if case=="subpopulation" else 'svy: regress y x1 x2')
    body.append(emit(case+"_df","e(df_r)"))
    for canonical,term in [("Intercept","_cons"),("x1","x1"),("x2","x2")]:
        body.extend([emit(case+"_b_"+canonical,f"_b[{term}]"),emit(case+"_se_"+canonical,f"_se[{term}]")])
    body.extend(["test x1 x2",emit(case+"_wald","r(F)"),emit(case+"_wald_p","r(p)"),"lincom x1-x2",emit(case+"_lincom","r(estimate)"),emit(case+"_lincom_se","r(se)"),emit(case+"_lincom_p","r(p)")])
native=run(OUT/"stata",'\n'.join(body),name="fpc_review_oracle")
retained=json.loads((ROOT/"stata_reference.json").read_text())["values"]
for key,value in native.items():assert np.isclose(value,retained[key],rtol=1e-9,atol=1e-11),(key,value,retained[key])
(OUT/"stata_reproduced.json").write_text(json.dumps(native,indent=2))
print("2 retained Stata reference cases reproduced within unchanged contract tolerance; maximum absolute difference="+str(max(abs(value-retained[key]) for key,value in native.items())),flush=True)
(OUT/"comparisons.json").write_text(json.dumps(comparisons,indent=2))
(OUT/"failures.json").write_text(json.dumps(failures,indent=2))
assert not failures,json.dumps(failures,indent=2)
print(f"{len(configs)} independent R FPC interaction cases passed",flush=True)
