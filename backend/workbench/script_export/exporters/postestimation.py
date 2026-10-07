"""Covariance-based post-estimation with explicit finite-sample inference."""
from __future__ import annotations
from workbench.contracts.common.envelope import thaw_json
from ..syntax import literal,identifier,refuse,arithmetic
from .models import stata_term

PY_HELPER = '''def wb_single(model, estimate, se):
    statistic = estimate/se
    distribution = model['distribution']
    df = model['df']
    p = 2*(stats.t.sf(abs(statistic),df) if distribution=='t' else stats.norm.sf(abs(statistic)))
    return dict(value=statistic, p_value=p, df=df, df_denominator=None, distribution=distribution)

def wb_wald(model, constraints):
    names=model['names']
    if any(not set(item['terms'])<=set(names) for item in constraints):raise AssertionError('Unknown Wald coefficient')
    R=np.asarray([[item['terms'].get(n,0) for n in names] for item in constraints],dtype=float)
    target=np.asarray([item.get('value',0) for item in constraints],dtype=float)
    if np.linalg.matrix_rank(R)!=len(constraints): raise AssertionError('Dependent Wald restrictions')
    beta=np.asarray([model['beta'][n] for n in names])
    gap=R@beta-target
    W=float(gap@np.linalg.solve(R@model['covariance']@R.T,gap))
    q=len(constraints)
    finite=model['distribution']=='t'
    value=W/q if finite else W
    denominator=model['df'] if finite else None
    if finite and model.get('df_method')=='design' and q>1:
        denominator=model['df']-q+1
        if denominator<=0:raise AssertionError('Too few survey design degrees of freedom')
        value=W*denominator/(model['df']*q)
    p=stats.f.sf(value,q,denominator) if finite else stats.chi2.sf(value,q)
    return dict(beta={},se={},statistics={'test':dict(value=value,p_value=p,df=q,df_denominator=denominator,distribution='F' if finite else 'chi2')})

def wb_lincom(model, terms, constant):
    vector=np.asarray([terms.get(n,0) for n in model['names']],dtype=float)
    if not set(terms)<=set(model['names']):raise AssertionError('Unknown lincom coefficient')
    estimate=float(vector@np.asarray(list(model['beta'].values()))+constant)
    se=float(np.sqrt(vector@model['covariance']@vector))
    return dict(beta={'estimate':estimate},se={'estimate':se},statistics={'test':wb_single(model,estimate,se)})

def wb_nlcom(model, function):
    point=dict(model['beta']);names=model['names'];estimate=float(function(point));gradient=[]
    for name in names:
        h=6e-6*max(1,abs(point[name]))
        gradient.append((function({**point,name:point[name]+h})-function({**point,name:point[name]-h}))/(2*h))
    gradient=np.asarray(gradient)
    se=float(np.sqrt(gradient@model['covariance']@gradient))
    return dict(beta={'estimate':estimate},se={'estimate':se},statistics={'test':wb_single(model,estimate,se)})

def wb_lr(full,restricted):
    if full['loglik'] is None or restricted['loglik'] is None:raise AssertionError('Likelihood is unavailable')
    if full['sample']!=restricted['sample']:raise AssertionError('LR estimation samples differ')
    if not set(restricted['names'])<set(full['names']):raise AssertionError('Models are not nested')
    value=max(0,2*(full['loglik']-restricted['loglik']));df=len(full['names'])-len(restricted['names'])
    return dict(beta={},se={},statistics={'test':dict(value=value,p_value=stats.chi2.sf(value,df),df=df,df_denominator=None,distribution='chi2')})

WB_LINK_DERIVATIVES={
 'identity':lambda eta:(np.ones_like(eta),np.zeros_like(eta)),
 'logit':lambda eta:((1/(1+np.exp(-eta)))*(1-1/(1+np.exp(-eta))), (1/(1+np.exp(-eta)))*(1-1/(1+np.exp(-eta)))*(1-2/(1+np.exp(-eta)))),
 'probit':lambda eta:(stats.norm.pdf(eta),-eta*stats.norm.pdf(eta)),
 'log':lambda eta:(np.exp(eta),np.exp(eta)),
}

def wb_margins(model, variables, at):
    X=model['design']
    if at=='means':X=X.mean(axis=0,keepdims=True)
    beta=np.asarray(list(model['beta'].values()));first,second=WB_LINK_DERIVATIVES[model['link']](X@beta)
    curvature=(second[:,None]*X).mean(axis=0);mean_first=first.mean()
    estimates={};errors={};statistics={}
    for name in variables:
        j=model['names'].index(name);estimate=float(mean_first*beta[j]);gradient=curvature*beta[j];gradient[j]+=mean_first
        se=float(np.sqrt(gradient@model['covariance']@gradient));estimates[name]=estimate;errors[name]=se
        statistics[name]=wb_single(model,estimate,se)
    return dict(beta=estimates,se=errors,statistics=statistics,nobs=model['nobs'])
'''

R_HELPER = '''wb_single <- function(model, estimate, se) {
  value <- estimate/se
  p <- if (model$distribution=="t") 2*pt(-abs(value),model$df) else 2*pnorm(-abs(value))
  list(value=value,p_value=p,df=model$df,df_denominator=NULL,distribution=model$distribution)
}
wb_wald <- function(model, R, target) {
  gap <- R %*% model$beta-target
  if (qr(R)$rank!=nrow(R)) stop("Dependent Wald restrictions")
  W <- as.numeric(t(gap) %*% solve(R %*% model$covariance %*% t(R),gap));q <- nrow(R)
  finite <- model$distribution=="t"; value <- if(finite) W/q else W
  denominator <- if(finite) model$df else NULL
  if(finite && identical(model$df_method,"design") && q>1) {
    denominator <- model$df-q+1
    if(denominator<=0) stop("Too few survey design degrees of freedom")
    value <- W*denominator/(model$df*q)
  }
  p <- if(finite) pf(value,q,denominator,lower.tail=FALSE) else pchisq(value,q,lower.tail=FALSE)
  list(beta=list(),se=list(),statistics=list(test=list(value=value,p_value=p,df=q,df_denominator=denominator,distribution=if(finite) "F" else "chi2")))
}
wb_lincom <- function(model, vector, constant) {
  estimate <- sum(vector*model$beta)+constant
  se <- sqrt(as.numeric(t(vector) %*% model$covariance %*% vector))
  list(beta=list(estimate=estimate),se=list(estimate=se),statistics=list(test=wb_single(model,estimate,se)))
}
wb_nlcom <- function(model, fn) {
  point <- model$beta;estimate <- fn(point)
  gradient <- vapply(seq_along(point),function(i) { h <- 6e-6*max(1,abs(point[i]));hi <- lo <- point;hi[i] <- hi[i]+h;lo[i] <- lo[i]-h;(fn(hi)-fn(lo))/(2*h) }, numeric(1))
  se <- sqrt(as.numeric(t(gradient) %*% model$covariance %*% gradient))
  list(beta=list(estimate=estimate),se=list(estimate=se),statistics=list(test=wb_single(model,estimate,se)))
}
wb_lr <- function(full,restricted) {
  if (is.null(full$loglik)||is.null(restricted$loglik)) stop("Likelihood unavailable")
  if (!identical(full$sample,restricted$sample)) stop("LR estimation samples differ")
  if (!all(restricted$names %in% full$names)||length(full$names)<=length(restricted$names)) stop("Models are not nested")
  value <- max(0,2*(full$loglik-restricted$loglik));df <- length(full$beta)-length(restricted$beta)
  list(beta=list(),se=list(),statistics=list(test=list(value=value,p_value=pchisq(value,df,lower.tail=FALSE),df=df,df_denominator=NULL,distribution="chi2")))
}
wb_links <- list(identity=function(eta) list(rep(1,length(eta)),rep(0,length(eta))),
  logit=function(eta) {p <- plogis(eta);list(p*(1-p),p*(1-p)*(1-2*p))},
  probit=function(eta) list(dnorm(eta),-eta*dnorm(eta)),log=function(eta) list(exp(eta),exp(eta)))
wb_margins <- function(model,variables,at) {
  X <- model$design;if (at=="means") X <- matrix(colMeans(X),nrow=1)
  beta <- model$beta;derivatives <- wb_links[[model$link]](as.numeric(X %*% beta))
  mean_first <- mean(derivatives[[1]]);curvature <- colMeans(derivatives[[2]]*X)
  estimates <- errors <- statistics <- list()
  for (name in variables) {
    j <- match(name,model$names);estimate <- mean_first*beta[j];gradient <- curvature*beta[j];gradient[j] <- gradient[j]+mean_first
    se <- sqrt(as.numeric(t(gradient) %*% model$covariance %*% gradient))
    estimates[[name]] <- estimate;errors[[name]] <- se;statistics[[name]] <- wb_single(model,estimate,se)
  }
  list(beta=estimates,se=errors,statistics=statistics,nobs=model$nobs)
}
'''


def prepare(step,ctx):
    p=thaw_json(step.parameters);models=p.get('models',[])
    if not models:refuse('Post-estimation needs model step references')
    for key in models:
        if key not in ctx.model_steps or ctx.model_steps[key].kind!='model':refuse('Post-estimation input is not a fitted model')
        from workbench.postestimation.registry import require_validated,PostestimationRefusal
        parameters=ctx.model_steps[key].parameters
        family=parameters['model_type']
        if family=='glm':family+=':'+parameters['model_options']['family']
        try:require_validated(family,step.operation.removeprefix('postestimation.'))
        except PostestimationRefusal as exc:refuse(str(exc),exc.code)
    l=ctx.language;lines=[]
    if l in {'python','r'} and not ctx.postestimation_helpers:
        lines.append(PY_HELPER if l=='python' else R_HELPER);ctx.postestimation_helpers=True
    result=f'results[{step.step_id!r}]' if l=='python' else f'results[[{literal(step.step_id,l)}]]'
    refs=[f'results[{key!r}]' if l=='python' else f'results[[{literal(key,l)}]]' for key in models]
    if l=='stata':lines += [f'frame change wb_model_data{ctx.model_indices[models[0]]}',f'estimates restore wb_model{ctx.model_indices[models[0]]}']
    return p,models,result,refs,lines


def checks(step,ctx,result,stata_values=None):
    l=ctx.language;lines=[];expected=step.expected
    model=step.parameters['models'][0]
    if 'nobs' in expected and l != 'stata':
        source=f'results[{model!r}]' if l=='python' else f'results[[{literal(model,l)}]]'
        lines.append(f'{result}["nobs"] = {source}["nobs"]' if l=='python' else f'{result}$nobs <- {source}$nobs')
    distribution=ctx.distributions[model]
    operation=step.operation.removeprefix('postestimation.')
    actual_distribution='chi2' if operation=='lr' else (('F' if distribution=='t' else 'chi2') if operation=='wald' else distribution)
    for stat in expected.get('statistics',{}).values():
        if stat.get('distribution') not in {None,actual_distribution}:refuse('Expected distribution disagrees with post-estimation','REFERENCE_DISTRIBUTION_MISMATCH')
    for kind,field in [('coefficients','beta'),('std_errors','se')]:
        for name,value in expected.get(kind,{}).items():
            expr=stata_values[kind][name] if l=='stata' else (f'{result}[{field!r}][{name!r}]' if l=='python' else f'{result}[[{literal(field,l)}]][[{literal(name,l)}]]')
            lines+=ctx.numeric_check(step,kind,expr,value)
    if 'nobs' in expected:
        expr=stata_values['nobs'] if l=='stata' else (f'{result}["nobs"]' if l=='python' else f'{result}$nobs')
        lines+=ctx.numeric_check(step,'nobs',expr,expected['nobs'])
    for name,stat in expected.get('statistics',{}).items():
        for field in ('value','p_value','df','df_denominator'):
            if stat.get(field) is None:continue
            expr=stata_values['statistics'][name][field] if l=='stata' else (f'{result}["statistics"][{name!r}][{field!r}]' if l=='python' else f'{result}$statistics[[{literal(name,l)}]][[{literal(field,l)}]]')
            lines+=ctx.numeric_check(step,'statistics.'+field,expr,stat[field])
        if l!='stata' and stat.get('distribution'):
            access=f'{result}["statistics"][{name!r}]["distribution"]' if l=='python' else f'{result}$statistics[[{literal(name,l)}]]$distribution'
            test=access+' == '+literal(stat['distribution'],l)
            lines.append('assert '+test if l=='python' else f'stopifnot({test})')
    unknown=set(expected)-{'coefficients','std_errors','nobs','statistics'}
    if unknown:refuse('Unsupported post-estimation expected fields')
    return lines


def term_expression(terms,p):
    pieces=[];lines=[]
    for term,weight in terms.items():
        name,setup=stata_term(term,p);lines+=setup;pieces.append(f'({literal(weight,"stata")}*_b[{name}])')
    return '+'.join(pieces),lines


def wald(step,ctx):
    p,models,result,refs,lines=prepare(step,ctx);l=ctx.language;constraints=p['constraints']
    if l=='python':lines.append(f'{result} = wb_wald({refs[0]}, {constraints!r})')
    elif l=='r':
        lines += [f'wb_m <- {refs[0]}',f'wb_R <- matrix(0,nrow={len(constraints)},ncol=length(wb_m$beta))']
        for i,c in enumerate(constraints,1):
            for term,weight in c['terms'].items():lines.append(f'wb_R[{i}, match({literal(term,l)},wb_m$names)] <- {literal(weight,l)}')
        lines.append(f'{result} <- wb_wald(wb_m, wb_R, {literal([c.get("value",0) for c in constraints],l)})')
    else:
        expressions=[]
        for c in constraints:
            expression,setup=term_expression(c['terms'],ctx.model_parameters[models[0]]);lines+=setup;expressions.append(f'({expression} = {literal(c.get("value",0),l)})')
        model_parameters=ctx.model_parameters[models[0]]
        design=model_parameters.get('model_options',{}).get('survey_design',{})
        suffix=', nosvyadjust' if model_parameters.get('covariance')=='survey_design' and design.get('survey_df')=='design_minus_p' else ''
        lines.append('test '+' '.join(expressions)+suffix)
        distribution=ctx.distributions[models[0]]
        values={'nobs':'e(N)', 'statistics':{'test':{'value':'r(F)' if distribution=='t' else 'r(chi2)','p_value':'r(p)','df':'r(df)','df_denominator':'r(df_r)'}}}
        return lines+checks(step,ctx,result,values)
    return lines+checks(step,ctx,result)


def lincom(step,ctx):
    p,models,result,refs,lines=prepare(step,ctx);l=ctx.language;constant=p.get('constant',0)
    if l=='python':lines.append(f'{result} = wb_lincom({refs[0]}, {p["terms"]!r}, {literal(constant,l)})')
    elif l=='r':
        lines += [f'wb_m <- {refs[0]}','wb_vector <- rep(0,length(wb_m$beta))']
        for term,weight in p['terms'].items():lines.append(f'wb_vector[match({literal(term,l)},wb_m$names)] <- {literal(weight,l)}')
        lines.append(f'{result} <- wb_lincom(wb_m,wb_vector,{literal(constant,l)})')
    else:
        expression,setup=term_expression(p['terms'],ctx.model_parameters[models[0]]);lines+=setup
        # lincom takes coefficient names, rather than _b[] expressions.
        expression=expression.replace('_b[','').replace(']','')
        lines.append(f'lincom {expression}+({literal(constant,l)})')
        distribution=ctx.distributions[models[0]]
        values={'nobs':'e(N)', 'coefficients':{'estimate':'r(estimate)'},'std_errors':{'estimate':'r(se)'},'statistics':{'test':{'value':'r(estimate)/r(se)','p_value':'r(p)','df':'r(df)'}}}
        return lines+checks(step,ctx,result,values)
    return lines+checks(step,ctx,result)


def nlcom(step,ctx):
    p,models,result,refs,lines=prepare(step,ctx);l=ctx.language
    if l!='stata':
        coefficient=lambda name:f'b[{name!r}]' if l=='python' else f'b[[{literal(name,l)}]]'
        expression=arithmetic(p['expression'],l,coefficient)
        fn='lambda b: '+expression if l=='python' else 'function(b) '+expression
        lines.append(f'{result} {"=" if l=="python" else "<-"} wb_nlcom({refs[0]}, {fn})')
        return lines+checks(step,ctx,result)
    setup=[]
    def coefficient(name):
        term,extra=stata_term(name,ctx.model_parameters[models[0]]);setup.extend(extra);return f'_b[{term}]'
    expression=arithmetic(p['expression'],l,coefficient);lines+=setup
    lines += [f'nlcom ({expression})','matrix wb_nb = r(b)','matrix wb_nv = r(V)']
    distribution=ctx.distributions[models[0]]
    statistic='(wb_nb[1,1]/sqrt(wb_nv[1,1]))'
    pvalue=f'2*ttail(e(df_r),abs({statistic}))' if distribution=='t' else f'2*normal(-abs({statistic}))'
    values={'nobs':'e(N)', 'coefficients':{'estimate':'wb_nb[1,1]'},'std_errors':{'estimate':'sqrt(wb_nv[1,1])'},'statistics':{'test':{'value':statistic,'p_value':pvalue,'df':'e(df_r)'}}}
    return lines+checks(step,ctx,result,values)


def lr(step,ctx):
    p,models,result,refs,lines=prepare(step,ctx);l=ctx.language
    if len(models)!=2:refuse('LR needs two fitted models')
    full,restricted=(ctx.model_steps[key] for key in models)
    keys=('model_type','y','entity','time','model_options')
    same_data = full.inputs == restricted.inputs or (full.snapshot is not None and restricted.snapshot is not None
        and (full.snapshot.sha256, full.snapshot.format, full.snapshot.nrows, full.snapshot.columns)
        == (restricted.snapshot.sha256, restricted.snapshot.format, restricted.snapshot.nrows, restricted.snapshot.columns))
    if not same_data or any(full.parameters.get(key)!=restricted.parameters.get(key) for key in keys):
        refuse('LR requires the same response, family, source and likelihood options','INCOMPARABLE_LR_MODELS')
    if not set(restricted.parameters.get('x',[]))<set(full.parameters.get('x',[])):
        refuse('LR requires a strictly nested regressor design','INCOMPARABLE_LR_MODELS')
    for key in models:
        spec=ctx.model_steps[key].parameters
        if spec.get('covariance') not in {None,'unadjusted'} or spec.get('weights',{}):refuse('LR requires unweighted model-based covariance','NOT_MODEL_BASED_VARIANCE')
    if l=='stata':
        first,second=(ctx.model_indices[key] for key in models)
        lines += [f'frlink 1:1 wb_sample_row, frame(wb_model_data{second}) gen(wb_lr_link)',f'frget wb_sample{second}, from(wb_lr_link)',f'assert wb_sample{first} == wb_sample{second}']
        lines.append(f'lrtest wb_model{ctx.model_indices[models[0]]} wb_model{ctx.model_indices[models[1]]}')
        values={'statistics':{'test':{'value':'r(chi2)','p_value':'r(p)','df':'r(df)'}}}
        return lines+checks(step,ctx,result,values)
    lines.append(f'{result} {"=" if l=="python" else "<-"} wb_lr({refs[0]}, {refs[1]})')
    return lines+checks(step,ctx,result)


def margins(step,ctx):
    p,models,result,refs,lines=prepare(step,ctx);l=ctx.language;variables=p['variables'];at=p.get('at','average')
    for c in variables:identifier(c)
    if at not in {'average','means'}:refuse('Unsupported margins evaluation point')
    if l!='stata':
        lines.append(f'{result} {"=" if l=="python" else "<-"} wb_margins({refs[0]}, {literal(variables,l)}, {literal(at,l)})')
        return lines+checks(step,ctx,result)
    lines += ['scalar wb_margin_nobs = e(N)','scalar wb_margin_df = e(df_r)' if ctx.distributions[models[0]]=='t' else 'scalar wb_margin_df = .',f'margins, dydx({" ".join(variables)})'+(' atmeans' if at=='means' else ''),'matrix wb_mb = r(b)','matrix wb_mv = r(V)']
    values={'coefficients':{},'std_errors':{},'statistics':{},'nobs':'wb_margin_nobs'}
    for i,name in enumerate(variables,1):
        estimate=f'wb_mb[1,{i}]';se=f'sqrt(wb_mv[{i},{i}])';statistic=f'({estimate}/{se})'
        distribution=ctx.distributions[models[0]]
        pvalue=f'2*ttail(wb_margin_df,abs({statistic}))' if distribution=='t' else f'2*normal(-abs({statistic}))'
        values['coefficients'][name]=estimate;values['std_errors'][name]=se;values['statistics'][name]={'value':statistic,'p_value':pvalue,'df':'wb_margin_df'}
    return lines+checks(step,ctx,result,values)
