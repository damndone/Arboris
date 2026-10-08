"""Native model estimators and covariance-preserving inference."""
from __future__ import annotations
import re
import math
from workbench.contracts.common.envelope import thaw_json
from ..syntax import identifier,literal,refuse

PY_MODEL_HELPER = '''import ast
import statsmodels.formula.api as smf
from scipy import stats

def wb_public(name):
    # Q(<string literal>) names a column; the literal may use either quote and escapes.
    if name.startswith("Q(") and name.endswith(")"):
        try:
            column = ast.literal_eval(name[2:-1])
        except (ValueError, SyntaxError):
            return name
        if isinstance(column, str):
            return column
    return name

def wb_model(fit, names=None, df=None, distribution=None, link="identity"):
    names = names or list(fit.model.exog_names)
    beta = np.asarray(fit.params)
    covariance = np.asarray(fit.cov_params())
    names = [wb_public(str(n)) for n in names]
    df = getattr(fit, 'df_resid_inference', fit.df_resid) if df is None else df
    distribution = distribution or ('t' if getattr(fit, 'use_t',False) else 'z')
    se = np.sqrt(np.diag(covariance))
    statistic = beta/se
    p = 2*(stats.t.sf(np.abs(statistic),df) if distribution=='t' else stats.norm.sf(np.abs(statistic)))
    return dict(beta=dict(zip(names,beta)), se=dict(zip(names,se)), statistic=dict(zip(names,statistic)),
                p=dict(zip(names,p)), covariance=covariance, names=names, df=df if distribution=='t' else None,
                distribution=distribution, nobs=float(fit.nobs), fit=fit, loglik=getattr(fit,'llf',None), link=link, design=fit.model.exog, sample=list(fit.model.data.row_labels))
'''

R_MODEL_HELPER = '''wb_model <- function(fit, covariance=vcov(fit), df=NULL, distribution="z", aliases=NULL, likelihood=TRUE) {
  beta <- coef(fit)
  names <- names(beta)
  if (!is.null(aliases)) names <- vapply(names, function(n) if (n %in% names(aliases)) aliases[[n]] else n, character(1))
  names <- gsub("`", "", names, fixed=TRUE)
  names[names=="(Intercept)"] <- "Intercept"
  names(beta) <- names
  se <- sqrt(diag(covariance)); names(se) <- names
  statistic <- beta/se
  p <- if (distribution=="t") 2*pt(-abs(statistic),df) else 2*pnorm(-abs(statistic))
  list(beta=beta,se=se,statistic=statistic,p=p,covariance=covariance,names=names,df=df,
       distribution=distribution,nobs=nobs(fit),fit=fit,loglik=if(likelihood) as.numeric(logLik(fit)) else NULL,link=if(is.null(fit$family$link)) "identity" else fit$family$link, design=model.matrix(fit),sample=rownames(model.frame(fit)))
}
'''


def prepare(step,ctx):
    p=thaw_json(step.parameters);l=ctx.language
    for c in [p['y'],*p.get('x',[])]:identifier(c)
    for c in p.get('categorical_x',[]):identifier(c)
    d=ctx.ref(step.inputs[0]);result=f'results[{step.step_id!r}]' if l=='python' else f'results[[{literal(step.step_id,l)}]]'
    lines=[]
    if l=='python':
        if 'statsmodels' not in ctx.packages:lines.append(PY_MODEL_HELPER)
        ctx.packages.update(('statsmodels','numpy','pandas','scipy'))
    elif l=='r':
        if 'stats' not in ctx.packages:lines.append(R_MODEL_HELPER)
        ctx.packages.add('stats')
        local_frame=f'wb_model_frame{ctx.index}'
        lines.append(f'{local_frame} <- {d}')
        d=local_frame
        for c in p.get('categorical_x',[]):lines.append(f'{d}[[{literal(c,l)}]] <- factor({d}[[{literal(c,l)}]], levels=sort(unique({d}[[{literal(c,l)}]])))')
        lines.append('wb_aliases <- list()')
        for name in step.expected.get('coefficients',{}):
            match=re.fullmatch(r'C\(Q\([\'\"]([A-Za-z_][A-Za-z0-9_]*)[\'\"]\)\)\[T\.(.+)\]',name)
            if match:
                c=match[1];level=match[2]
                levels=f'levels({d}[[{literal(c,l)}]])'
                try:value=float(level)
                except ValueError:value=None
                selector=f'{levels}[match({literal(value,l)},as.numeric({levels}))]' if value is not None else literal(level,l)
                lines.append(f'wb_aliases[[paste0({literal(c,l)},{selector})]] <- {literal(name,l)}')
    else:
        lines += [f'frame copy {d} wb_model_data{ctx.index}', f'frame change wb_model_data{ctx.index}']
        p['stata_categories']={}
        for i,c in enumerate(p.get('categorical_x',[])):
            macro=f'wb_category_{ctx.index}_{i}'
            p['stata_categories'][c]=f"`{macro}'"
            lines += [f'tempvar {macro}',f'egen long `{macro}\' = group({c})']
    ctx.model_parameters[step.step_id]=p
    return p,d,result,lines


def formula(p,l):
    cat=p.get('categorical_x',[])
    if l=='python':return f'Q({p["y"]!r}) ~ '+ (' + '.join(f'C(Q({c!r}))' if c in cat else f'Q({c!r})' for c in p.get('x',[])) or '1')
    if l=='r':return '`'+p['y']+'` ~ '+(' + '.join('`'+c+'`' for c in p.get('x',[])) or '1')
    return p['y']+' '+ ' '.join(f'ib1.{p["stata_categories"][c]}' if c in cat else c for c in p.get('x',[]))


def stata_term(term,p):
    if term in {'Intercept','const','_cons'}:return '_cons',[]
    if term in p.get('x',[]):return identifier(term),[]
    match=re.fullmatch(r'C\(Q\([\'\"]([A-Za-z_][A-Za-z0-9_]*)[\'\"]\)\)\[T\.(.+)\]',term)
    if match and match[1] in p.get('categorical_x',[]):
        c=match[1];level=match[2]
        try:value=float(level)
        except ValueError:value=level
        encoded=p['stata_categories'][c]
        return f'`wb_level\'.{encoded}',[f'quietly summarize {encoded} if {c} == {literal(value,"stata")}',"local wb_level = r(min)"]
    if term in {'_did_D'}:return term,[]
    refuse('Unsupported coefficient name: '+term)


def model_checks(step,ctx,p,result):
    l=ctx.language;lines=[];expected=step.expected
    distribution=ctx.distributions[step.step_id]
    for stat in expected.get('statistics',{}).values():
        if stat.get('distribution') not in {None,distribution}:refuse('Expected distribution disagrees with the estimator','REFERENCE_DISTRIBUTION_MISMATCH')
    if l=='stata':
        lines += [f'estimates store wb_model{ctx.index}','generate long wb_sample_row = _n',f'generate byte wb_sample{ctx.index} = e(sample)']
        ctx.model_steps[step.step_id]=step
    for kind in ('coefficients','std_errors'):
        for term,value in expected.get(kind,{}).items():
            if l=='stata':
                name,setup=stata_term(term,p);lines +=setup;expression=f'_{"b" if kind=="coefficients" else "se"}[{name}]'
            else:expression=f'{result}[{("beta" if kind=="coefficients" else "se")!r}][{term!r}]' if l=='python' else f'{result}[[{literal("beta" if kind=="coefficients" else "se",l)}]][[{literal(term,l)}]]'
            lines+=ctx.numeric_check(step,kind,expression,value)
    if 'nobs' in expected:
        expression='e(N)' if l=='stata' else (f'{result}["nobs"]' if l=='python' else f'{result}$nobs')
        lines+=ctx.numeric_check(step,'nobs',expression,expected['nobs'])
    for name,stat in expected.get('statistics',{}).items():
        if l=='stata':
            term,setup=stata_term(name,p);lines+=setup
            distribution=ctx.distributions[step.step_id]
            value_expr=f'(_b[{term}]/_se[{term}])'
            expressions={'value':value_expr,'p_value':f'2*{ "ttail(e(df_r),abs("+value_expr+"))" if distribution=="t" else "normal(-abs("+value_expr+"))" }','df':'e(df_r)'}
            if distribution=='t':lines+=['capture confirm scalar e(df_r)','if _rc exit 9']
        else:
            access=lambda key:f'{result}[{key!r}]' if l=='python' else f'{result}[[{literal(key,l)}]]'
            expressions={'value':access('statistic')+(f'[{name!r}]' if l=='python' else f'[[{literal(name,l)}]]'),
                         'p_value':access('p')+(f'[{name!r}]' if l=='python' else f'[[{literal(name,l)}]]'),'df':access('df')}
            if stat.get('distribution'):
                test=f'{access("distribution")} == {literal(stat["distribution"],l)}'
                lines.append('assert '+test if l=='python' else f'stopifnot({test})')
        for field in ('value','p_value','df'):
            if stat.get(field) is not None:lines+=ctx.numeric_check(step,'statistics.'+field,expressions[field],stat[field])
    unknown=set(expected)-{'coefficients','std_errors','nobs','statistics'}
    if unknown:refuse('Unsupported model expected fields: '+str(sorted(unknown)))
    return lines


def ols(step,ctx):
    ctx.distributions[step.step_id]='t'
    p,d,result,lines=prepare(step,ctx);l=ctx.language;cov=p.get('covariance','unadjusted');weight=p.get('weights');options=p.get('model_options',{})
    if cov not in {'unadjusted','robust','clustered','hac'}:refuse('Unsupported OLS covariance')
    if weight and weight['kind']=='sampling':refuse('Sampling-weight export needs the full survey design, absent from the normalized plan', 'SURVEY_DESIGN_REQUIRED')
    if l=='python':
        lines += [f'wb_frame = {d}.copy()']
        if weight:
            col=identifier(weight['column']);kind=weight['kind']
            if kind=='frequency':lines.append(f'wb_frame = wb_frame.loc[wb_frame.index.repeat(wb_frame[{col!r}].astype(int))].reset_index(drop=True)')
            elif kind!='analysis':refuse('Unsupported OLS weight kind')
        if cov=='hac':
            t=identifier(options.get('time_order') or p.get('time'));lines.append(f'wb_frame = wb_frame.sort_values({t!r}, kind="mergesort")')
        fit=f'smf.wls({formula(p,l)!r}, data=wb_frame, weights=wb_frame[{weight["column"]!r}]).fit()' if weight and weight['kind']=='analysis' else f'smf.ols({formula(p,l)!r}, data=wb_frame).fit()'
        lines.append('wb_fit = '+fit)
        if cov=='robust':lines.append('wb_fit = wb_fit.get_robustcov_results(cov_type="HC1", use_t=True)')
        elif cov=='clustered':
            cluster=identifier(p['cluster']);lines.append(f'wb_groups = wb_frame.loc[wb_fit.model.data.row_labels, {cluster!r}]')
            lines.append('wb_fit = wb_fit.get_robustcov_results(cov_type="cluster", groups=wb_groups, use_correction=True, df_correction=True, use_t=True)')
        elif cov=='hac':lines.append(f'wb_fit = wb_fit.get_robustcov_results(cov_type="HAC", maxlags={int(p["hac_lags"])}, kernel="bartlett", use_correction=True, use_t=True)')
        lines.append(f'{result} = wb_model(wb_fit)')
    elif l=='r':
        lines += [f'wb_frame <- {d}']
        if weight and weight['kind']=='frequency':lines.append(f'wb_frame <- wb_frame[rep(seq_len(nrow(wb_frame)), wb_frame[[{literal(identifier(weight["column"]),l)}]]),,drop=FALSE]')
        if cov=='hac':lines.append(f'wb_frame <- wb_frame[order(wb_frame[[{literal(identifier(options.get("time_order") or p.get("time")),l)}]]),,drop=FALSE]')
        weight_arg=f', weights=wb_frame[[{literal(identifier(weight["column"]),l)}]]' if weight and weight['kind']=='analysis' else ''
        lines += [f'wb_fit <- lm({formula(p,l)}, data=wb_frame{weight_arg})','wb_cov <- vcov(wb_fit)','wb_df <- df.residual(wb_fit)']
        if cov!='unadjusted':ctx.packages.add('sandwich')
        if cov=='robust':lines.append('wb_cov <- sandwich::vcovHC(wb_fit, type="HC1")')
        elif cov=='clustered':
            col=identifier(p['cluster']);lines += [f'wb_groups <- wb_frame[rownames(model.frame(wb_fit)), {literal(col,l)}]', 'wb_cov <- sandwich::vcovCL(wb_fit, cluster=wb_groups, type="HC1", cadjust=TRUE)','wb_df <- length(unique(wb_groups))-1']
        elif cov=='hac':lines.append(f'wb_cov <- sandwich::NeweyWest(wb_fit, lag={int(p["hac_lags"])}, prewhite=FALSE, adjust=TRUE)')
        lines.append(f'{result} <- wb_model(wb_fit,wb_cov,wb_df,"t",wb_aliases)')
    else:
        weight_arg=''
        if weight:
            kind={'frequency':'fw','analysis':'aw'}.get(weight['kind']);col=identifier(weight['column'])
            if kind is None:refuse('Unsupported OLS weight kind')
            # Frequency expansion aligns listwise deletion and nobs with Workbench.
            if kind=='fw':lines.append(f'expand {col}')
            else:weight_arg=f' [aw={col}]'
        suffix={'unadjusted':'','robust':', vce(robust)','clustered':', vce(cluster '+identifier(p['cluster'])+')' if p.get('cluster') else ', vce(cluster INVALID)','hac':', lag('+str(p.get('hac_lags'))+')'}[cov]
        if cov=='hac':
            time=identifier(options.get('time_order') or p.get('time'))
            lines += ['tempvar wb_hac_time',f'capture confirm string variable {time}','if !_rc {',f'    generate double `wb_hac_time\' = clock({time},"YMDhms")',f'    replace `wb_hac_time\' = clock({time},"YMD") if missing(`wb_hac_time\')','    assert !missing(`wb_hac_time\')','    sort `wb_hac_time\'','    tempvar wb_hac_difference','    generate double `wb_hac_difference\' = `wb_hac_time\' - `wb_hac_time\'[_n-1]','    quietly summarize `wb_hac_difference\', meanonly','    assert r(min) > 0 & r(min) == r(max)','    scalar wb_hac_delta = r(min)',"    scalar wb_hac_start = `wb_hac_time'[1]",'    replace `wb_hac_time\' = (`wb_hac_time\' - scalar(wb_hac_start)) / scalar(wb_hac_delta)','}','else {',f'    generate double `wb_hac_time\' = {time}','}',"tsset `wb_hac_time'",f'newey {formula(p,l)}{weight_arg}{suffix}']
        else:lines.append(f'regress {formula(p,l)}{weight_arg}{suffix}')
    return lines+model_checks(step,ctx,p,result)


def generalized(step,ctx,*,python_call,r_family,stata_command,glm=False,inverse_link="log",nb1=False):
    ctx.distributions[step.step_id]='z'
    p,d,result,lines=prepare(step,ctx);l=ctx.language
    if p.get('weights'):refuse('Weighted generalized model export requires survey design', 'SURVEY_DESIGN_REQUIRED')
    if p.get('covariance') not in {None,'unadjusted'}:refuse('Generalized covariance combination is not validated','UNSUPPORTED_EXPORT_COMBINATION')
    if l=='python':
        ctx.packages.add('statsmodels')
        if glm:lines += ['from statsmodels.genmod import families',f'wb_fit = smf.glm({formula(p,l)!r}, data={d}, family=families.{python_call}()).fit(maxiter=100, tol=1e-12)']
        else:
            fit_options=', method="newton", tol=1e-12, maxiter=500' if python_call=='negativebinomial' else ', maxiter=100'
            model_options=', loglike_method="nb1"' if nb1 else ''
            lines.append(f'wb_fit = smf.{python_call}({formula(p,l)!r}, data={d}{model_options}).fit(disp=False{fit_options})')
        lines.append(f'{result} = wb_model(wb_fit, distribution="z", link={inverse_link!r})')
    elif l=='r':
        if r_family=='negative_binomial':
            ctx.packages.add('MASS');lines.append(f'wb_fit <- MASS::glm.nb({formula(p,l)}, data={d}, control=glm.control(epsilon=1e-12,maxit=100))')
            # MASS reports the expected information; observed information is
            # required for Stata nbreg and Workbench, filled by an OIM helper.
        else:lines.append(f'wb_fit <- glm({formula(p,l)}, data={d}, family={r_family}, control=glm.control(epsilon=1e-12,maxit=100))')
        if r_family=='negative_binomial':
            lines += ['wb_X <- model.matrix(wb_fit)','wb_y <- model.response(model.frame(wb_fit))',
                      'wb_start <- c(coef(wb_fit),log(1/wb_fit$theta))',
                      'wb_nll <- function(parameters) {mu <- exp(wb_X %*% parameters[seq_len(ncol(wb_X))]); alpha <- exp(parameters[length(parameters)]); -sum(dnbinom(wb_y,mu=mu,size=1/alpha,log=TRUE))}',
                      'wb_hessian <- optimHess(wb_start,wb_nll,control=list(ndeps=rep(1e-4,length(wb_start))))',
                      'wb_cov <- solve(wb_hessian)[seq_len(ncol(wb_X)),seq_len(ncol(wb_X)),drop=FALSE]',
                      f'{result} <- wb_model(wb_fit, wb_cov, aliases=wb_aliases)']
        elif r_family=='binomial(link="probit")':
            lines += ['wb_X <- model.matrix(wb_fit)', 'wb_eta <- predict(wb_fit, type="link")',
                      'wb_y <- model.response(model.frame(wb_fit))', 'wb_pdf <- dnorm(wb_eta)',
                      'wb_l1 <- wb_pdf/pnorm(wb_eta)', 'wb_l0 <- wb_pdf/pnorm(-wb_eta)',
                      'wb_w <- wb_y*wb_l1*(wb_l1+wb_eta)+(1-wb_y)*wb_l0*(wb_l0-wb_eta)',
                      'wb_cov <- solve(crossprod(wb_X,wb_w*wb_X))',
                      f'{result} <- wb_model(wb_fit, wb_cov, aliases=wb_aliases)']
        else:
            lines.append(f'{result} <- wb_model(wb_fit, aliases=wb_aliases)')
    else:
        lines.append(f'{stata_command} {formula(p,l)}'+(', dispersion(constant)' if nb1 else '')+(' iterate(100) tolerance(1e-12)' if nb1 else ', iterate(100) tolerance(1e-12)' if stata_command in {'logit','probit','poisson','nbreg'} else ''))
    return lines+model_checks(step,ctx,p,result)


def logit(step,ctx):return generalized(step,ctx,python_call='logit',r_family='binomial(link="logit")',stata_command='logit',inverse_link='logit')
def probit(step,ctx):return generalized(step,ctx,python_call='probit',r_family='binomial(link="probit")',stata_command='probit',inverse_link='probit')
def poisson(step,ctx):return generalized(step,ctx,python_call='poisson',r_family='poisson(link="log")',stata_command='poisson')
def negative_binomial(step,ctx):
    """Estimated-dispersion NB2 (dispersion mean) or NB1 (dispersion constant), observed information."""
    options=step.parameters.get('model_options',{})
    dispersion=options.get('dispersion','mean')
    if dispersion not in {'mean','constant'} or options.get('alpha') is not None:
        refuse('Native NB export is limited to estimated-dispersion NB2 and NB1', 'UNSUPPORTED_EXPORT_COMBINATION')
    if dispersion=='constant' and ctx.language=='r':
        refuse('R has no reference NB1 (constant-dispersion) estimator', 'UNSUPPORTED_EXPORT_COMBINATION')
    return generalized(step,ctx,python_call='negativebinomial',r_family='negative_binomial',stata_command='nbreg',nb1=dispersion=='constant')


def glm_binomial(step,ctx):
    return generalized(step,ctx,python_call='Binomial',r_family='binomial(link="logit")',stata_command='logit',glm=True,inverse_link='logit')

def glm_poisson(step,ctx):
    return generalized(step,ctx,python_call='Poisson',r_family='poisson(link="log")',stata_command='poisson',glm=True)

def glm_nb_alpha(step):
    """The GLM dispersion is explicit and cannot inherit an NB2 default."""
    alpha=step.parameters.get('model_options',{}).get('alpha')
    message='Negative-binomial GLM requires an explicit finite positive numeric alpha'
    if isinstance(alpha,bool) or not isinstance(alpha,(int,float)):
        refuse(message,'GLM_NB_ALPHA_REQUIRED')
    try:alpha=float(alpha)
    except (ValueError,OverflowError):refuse(message,'GLM_NB_ALPHA_REQUIRED')
    if not math.isfinite(alpha) or alpha<=0:refuse(message,'GLM_NB_ALPHA_REQUIRED')
    return alpha


def glm_negative_binomial(step,ctx):
    """Fixed-alpha log GLM, final-point expected information and unit scale."""
    alpha=glm_nb_alpha(step)
    if step.parameters.get('weights') or step.parameters.get('covariance') not in {None,'unadjusted'}:
        refuse('Fixed-alpha GLM export requires unweighted expected-information covariance','UNSUPPORTED_EXPORT_COMBINATION')
    ctx.distributions[step.step_id]='z'
    p,d,result,lines=prepare(step,ctx);l=ctx.language
    if l=='python':
        lines += ['from statsmodels.genmod import families',
                  f'wb_fit = smf.glm({formula(p,l)!r}, data={d}, family=families.NegativeBinomial(alpha={alpha!r})).fit(maxiter=1000,tol=1e-12,tol_criterion="params",scale=1)',
                  'assert wb_fit.converged, "Fixed-alpha GLM did not converge"',
                  'wb_fit._results.normalized_cov_params = np.linalg.inv(-wb_fit.model.hessian(wb_fit.params,observed=False))',
                  'wb_fit._results._cache.clear()',
                  'assert np.isfinite(wb_fit.params).all() and np.isfinite(np.asarray(wb_fit.cov_params())).all()',
                  f'{result} = wb_model(wb_fit,distribution="z",link="log")']
    elif l=='r':
        ctx.packages.add('MASS')
        lines += [f'wb_alpha <- {alpha!r}',
                  f'wb_fit <- glm({formula(p,l)},data={d},family=MASS::negative.binomial(theta=1/wb_alpha,link="log"),control=glm.control(epsilon=1e-16,maxit=1000))',
                  'wb_X <- model.matrix(wb_fit); wb_y <- model.response(model.frame(wb_fit))',
                  '# Native glm deviance can underflow for large dispersion. Certify the final parameter point instead.',
                  'wb_converged <- FALSE',
                  'for (wb_iteration in seq_len(1000)) {',
                  '  wb_previous <- coef(wb_fit)',
                  '  stopifnot(all(is.finite(wb_previous)))',
                  '  wb_next <- suppressWarnings(glm.fit(wb_X,wb_y,family=wb_fit$family,start=wb_previous,control=glm.control(epsilon=1e-16,maxit=1)))',
                  '  wb_fit[names(wb_next)] <- wb_next',
                  '  wb_mu <- exp(drop(wb_X %*% coef(wb_fit))); wb_denominator <- 1+wb_alpha*wb_mu',
                  '  if (!all(is.finite(wb_mu)) || any(wb_mu<=0) || !all(is.finite(wb_denominator))) stop("GLM_NB_NUMERIC_FAILURE: non-finite native mean or variance")',
                  '  wb_score_residual <- if (wb_alpha>=1) (wb_y/wb_mu-1)/(1+1/(wb_alpha*wb_mu)) else (wb_y-wb_mu)/wb_denominator',
                  '  wb_scaled_score <- max(abs(drop(crossprod(wb_X,wb_score_residual)))/nrow(wb_X)/pmax(1,colMeans(abs(wb_X))))',
                  '  wb_parameter_change <- max(abs(coef(wb_fit)-wb_previous)/pmax(1,abs(wb_previous)))',
                  '  if (is.finite(wb_scaled_score) && wb_parameter_change<=1e-12 && wb_scaled_score<=1e-10) { wb_converged <- TRUE; break }',
                  '}',
                  'if (!wb_converged) stop("GLM_NB_NOT_CONVERGED: native parameters or scaled score did not converge")',
                  'wb_fit$converged <- TRUE; wb_fit$iter <- wb_iteration',
                  'wb_cov <- solve(crossprod(wb_X,wb_X*(wb_mu/wb_denominator)))',
                  'stopifnot(all(is.finite(wb_cov)))', f'{result} <- wb_model(wb_fit,wb_cov,aliases=wb_aliases)']
    else:
        lines += [f'glm {formula(p,l)}, family(nbinomial {alpha!r}) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)',
                  'assert e(converged) == 1']
    return lines+model_checks(step,ctx,p,result)


GLM_RENDERERS={'binomial':glm_binomial,'poisson':glm_poisson,'negative_binomial':glm_negative_binomial}

def glm(step,ctx):
    family=step.parameters.get('model_options',{}).get('family')
    renderer=GLM_RENDERERS.get(family)
    if renderer is None:refuse('GLM family export is not validated: '+str(family),'UNSUPPORTED_EXPORT_COMBINATION')
    return renderer(step,ctx)

PY_ARRAY_HELPER = '''def wb_array_model(params,covariance,nobs,df,distribution,design=None,loglik=None,sample=None):
    names=list(params.index);beta=np.asarray(params);covariance=np.asarray(covariance)
    se=np.sqrt(np.diag(covariance));statistic=beta/se
    p=2*(stats.t.sf(np.abs(statistic),df) if distribution=='t' else stats.norm.sf(np.abs(statistic)))
    return dict(beta=dict(zip(names,beta)),se=dict(zip(names,se)),statistic=dict(zip(names,statistic)),
      p=dict(zip(names,p)),covariance=covariance,names=names,df=df if distribution=='t' else None,
      distribution=distribution,nobs=float(nobs),loglik=loglik,link='identity',design=design,sample=sample)
'''


def array_helper(ctx):
    if 'array_helpers' in ctx.helpers:return []
    ctx.helpers.add('array_helpers')
    return [PY_ARRAY_HELPER] if ctx.language=='python' else []


def iv_2sls(step,ctx):
    ctx.distributions[step.step_id]='z'
    p,d,result,lines=prepare(step,ctx);l=ctx.language;options=p.get('model_options',{})
    endog=[identifier(c) for c in options.get('endog',[])];instruments=[identifier(c) for c in options.get('instruments',[])]
    if not endog or not instruments:refuse('IV export requires model_options.endog and instruments')
    covariance=p.get('covariance','robust')
    if covariance not in {'unadjusted','robust'}:refuse('IV covariance export is not validated','UNSUPPORTED_EXPORT_COMBINATION')
    if p.get('weights') or p.get('categorical_x'):refuse('IV weights or categorical export is not validated','UNSUPPORTED_EXPORT_COMBINATION')
    if l=='python':
        ctx.packages.add('linearmodels');lines+=array_helper(ctx)
        f=p['y']+' ~ 1 + '+(' + '.join(p.get('x',[]))+' + ' if p.get('x') else '')+'['+' + '.join(endog)+' ~ '+' + '.join(instruments)+']'
        lines += ['from linearmodels.iv import IV2SLS',f'wb_fit = IV2SLS.from_formula({f!r},data={d}).fit(cov_type={covariance!r},debiased=False)',f'{result} = wb_array_model(wb_fit.params,wb_fit.cov,wb_fit.nobs,None,"z",sample=list(wb_fit.model.dependent.rows))']
    elif l=='r':
        ctx.packages.add('fixest');f=p['y']+' ~ '+(' + '.join(p.get('x',[])) or '1')+' | 0 | '+' + '.join(endog)+' ~ '+' + '.join(instruments)
        required=list(dict.fromkeys([p['y'],*p.get('x',[]),*endog,*instruments]))
        xf='~ '+ ' + '.join('`'+c+'`' for c in [*p.get('x',[]),*endog])
        zf='~ '+ ' + '.join('`'+c+'`' for c in [*p.get('x',[]),*instruments])
        lines += [f'wb_frame <- {d}[complete.cases({d}[{literal(required,l)}]),,drop=FALSE]', f'wb_fit <- fixest::feols({f},data=wb_frame)', 'wb_names <- names(coef(wb_fit))','wb_aliases <- as.list(setNames(sub("^fit_", "", wb_names), wb_names))', f'wb_X <- model.matrix({xf},data=wb_frame)',f'wb_Z <- model.matrix({zf},data=wb_frame)', 'wb_Xhat <- wb_Z %*% solve(crossprod(wb_Z),crossprod(wb_Z,wb_X))', 'wb_bread <- solve(crossprod(wb_X,wb_Xhat))', 'wb_residuals <- residuals(wb_fit)']
        if covariance=='unadjusted':lines.append('wb_cov <- sum(wb_residuals^2)/nrow(wb_frame)*wb_bread')
        else:lines += ['wb_scores <- wb_Xhat*wb_residuals','wb_cov <- wb_bread %*% crossprod(wb_scores) %*% wb_bread']
        lines += ['wb_order <- match(sub("^fit_", "", wb_names),colnames(wb_X))','wb_cov <- wb_cov[wb_order,wb_order,drop=FALSE]', f'{result} <- wb_model(wb_fit,wb_cov,aliases=wb_aliases)']
    else:
        rhs=' '.join(p.get('x',[]));vce=' vce(robust)' if covariance=='robust' else ''
        lines.append(f'ivregress 2sls {p["y"]} {rhs} ({" ".join(endog)} = {" ".join(instruments)})'+(','+vce if vce else ''))
    return lines+model_checks(step,ctx,{**p,'x':[*p.get('x',[]),*endog]},result)

PY_WITHIN_HELPER = '''def wb_within(frame, columns, groups):
    raw=frame[columns].astype(float);current=raw.copy()
    for iteration in range(10000):
        previous=current.copy()
        for group in groups:current=current-current.groupby(frame[group].to_numpy()).transform('mean')
        if np.max(np.abs(current.to_numpy()-previous.to_numpy()))<=1e-13*max(1,np.max(np.abs(previous.to_numpy()))):break
    else:raise AssertionError('Within transformation did not converge')
    return current+raw.mean()

def wb_panel_cov(frame, design, residuals, groups, cluster):
    clustered=frame[cluster]
    if clustered.isna().any():raise AssertionError('Missing panel cluster')
    G=clustered.nunique();N=len(frame);K=design.shape[1]
    if G<2:raise AssertionError('At least two clusters are required')
    for group in groups:
        nested=(frame.groupby(group)[cluster].nunique()<=1).all()
        if not nested:K+=frame[group].nunique()-1
    if N<=K:raise AssertionError('No residual degrees of freedom')
    scores=pd.DataFrame(design*residuals[:,None]).groupby(clustered.to_numpy()).sum().to_numpy()
    bread=np.linalg.pinv(design.T@design)
    return G/(G-1)*(N-1)/(N-K)*bread@scores.T@scores@bread,G-1
'''


def panel(step,ctx,*,did=False):
    ctx.distributions[step.step_id]='t'
    p,d,result,lines=prepare(step,ctx);l=ctx.language
    p={**p,'x':(['_did_D'] if did else [])+list(p.get('x',[]))}
    groups=[identifier(p[key]) for key in ('entity','time') if p.get(key)]
    if not groups:refuse('Panel export requires fixed-effect fields')
    cov=p.get('covariance') or 'clustered';cluster=identifier(p.get('cluster') or p.get('entity')) if cov=='clustered' else None
    if cov!='clustered':refuse('This panel export declaration currently requires CR1 clustering','UNSUPPORTED_EXPORT_COMBINATION')
    if p.get('weights') or p.get('categorical_x'):refuse('Panel weights or categorical terms are not supported','UNSUPPORTED_EXPORT_COMBINATION')
    columns=[p['y'],*p['x']]
    if l=='python':
        ctx.packages.add('linearmodels');lines+=array_helper(ctx)
        if 'within_helpers' not in ctx.helpers:lines.append(PY_WITHIN_HELPER);ctx.helpers.add('within_helpers')
        entity=p.get('entity') or '_wb_entity';time=p.get('time') or '_wb_time'
        lines += ['from linearmodels.panel import PanelOLS', f'wb_frame = {d}.dropna(subset={list(dict.fromkeys(columns+groups+[cluster]))!r}).copy()']
        if not p.get('entity'):lines.append(f'wb_frame[{entity!r}] = 0')
        if not p.get('time'):lines.append(f'wb_frame[{time!r}] = np.arange(len(wb_frame))')
        f=p['y']+' ~ 1 + '+' + '.join(p['x'])+' + '+' + '.join('EntityEffects' if key=='entity' else 'TimeEffects' for key in ('entity','time') if p.get(key))
        lines += [f'wb_fit = PanelOLS.from_formula({f!r}, data=wb_frame.set_index({[entity,time]!r})).fit(cov_type="unadjusted")', f'wb_transformed = wb_within(wb_frame,{columns!r},{groups!r})', f'wb_design = np.column_stack([np.ones(len(wb_frame)),wb_transformed[{p["x"]!r}].to_numpy()])',f'wb_residuals = wb_transformed[{p["y"]!r}].to_numpy()-wb_design@wb_fit.params.to_numpy()', f'wb_cov,wb_df = wb_panel_cov(wb_frame,wb_design,wb_residuals,{groups!r},{cluster!r})', f'{result} = wb_array_model(wb_fit.params,wb_cov,len(wb_frame),wb_df,"t",design=wb_design,loglik=wb_fit.loglik,sample=list(wb_frame.index))']
    elif l=='r':
        ctx.packages.update(('fixest','sandwich'))
        required=list(dict.fromkeys(columns+groups+[cluster]));lines += [f'wb_frame <- {d}[complete.cases({d}[{literal(required,l)}]),,drop=FALSE]',f'wb_raw <- as.matrix(wb_frame[{literal(columns,l)}])',f'wb_within <- fixest::demean(wb_raw, f=wb_frame[{literal(groups,l)}], tol=1e-13,iter=10000)', 'wb_within <- sweep(wb_within,2,colMeans(wb_raw),"+")','wb_within <- as.data.frame(wb_within)', f'wb_fit <- lm({formula(p,l)},data=wb_within)', f'wb_clusters <- wb_frame[[{literal(cluster,l)}]]', 'wb_G <- length(unique(wb_clusters))', 'wb_K <- length(coef(wb_fit))']
        for group in groups:
            lines += [f'wb_nested <- all(vapply(split(wb_clusters,wb_frame[[{literal(group,l)}]]),function(x) length(unique(x))<=1, logical(1)))',f'if (!wb_nested) wb_K <- wb_K + length(unique(wb_frame[[{literal(group,l)}]]))-1']
        lines += ['stopifnot(wb_G>=2,nrow(wb_frame)>wb_K)', 'wb_cov <- sandwich::vcovCL(wb_fit,cluster=wb_clusters,type="HC1",cadjust=TRUE)*(nrow(wb_frame)-length(coef(wb_fit)))/(nrow(wb_frame)-wb_K)',f'{result} <- wb_model(wb_fit,wb_cov,wb_G-1,"t")']
    else:
        lines += ['tempvar wb_order','generate long `wb_order\' = _n','keep if '+ ' & '.join(f'!missing({c})' for c in list(dict.fromkeys(columns+groups+[cluster])))]
        lines += ['tempvar wb_cluster',f'egen long `wb_cluster\' = group({cluster})']
        cluster="`wb_cluster'"
        transformed=[]
        for j,c in enumerate(columns):
            lines += [f'tempvar wb_within{j}',f'generate double `wb_within{j}\' = {c}'];transformed.append(f'`wb_within{j}\'')
        lines += ['scalar wb_converged = 0','forvalues wb_iter = 1/10000 {','    scalar wb_maxdiff = 0']
        for j,c in enumerate(columns):lines += [f'    tempvar wb_previous{j}',f'    generate double `wb_previous{j}\' = {transformed[j]}']
        for group in groups:
            for j,c in enumerate(columns):lines += ['    tempvar wb_group_mean',f'    bysort {group}: egen double `wb_group_mean\' = mean({transformed[j]})',f'    replace {transformed[j]} = {transformed[j]} - `wb_group_mean\'', '    drop `wb_group_mean\'']
        for j,c in enumerate(columns):lines += ['    tempvar wb_difference',f'    generate double `wb_difference\' = abs({transformed[j]} - `wb_previous{j}\')','    quietly summarize `wb_difference\', meanonly','    scalar wb_maxdiff = max(wb_maxdiff,r(max))',f'    drop `wb_difference\' `wb_previous{j}\'']
        lines += ['    if wb_maxdiff < 1e-13 {','        scalar wb_converged = 1','        continue, break','    }','}','assert wb_converged == 1']
        for j,c in enumerate(columns):lines += [f'quietly summarize {c}, meanonly',f'replace {transformed[j]} = {transformed[j]} + r(mean)']
        lines += ['sort `wb_order\'',f'regress {" ".join(transformed)}, vce(cluster {cluster})',f'scalar wb_K = {len(columns)}']
        for group in groups:
            lines += ['tempvar wb_mincluster wb_maxcluster',f'bysort {group}: egen double `wb_mincluster\' = min({cluster})',f'bysort {group}: egen double `wb_maxcluster\' = max({cluster})','count if `wb_mincluster\' != `wb_maxcluster\'','if r(N) {',f'    quietly levelsof {group}, local(wb_levels)','    local wb_nlevels : word count `wb_levels\'','    scalar wb_K = wb_K + `wb_nlevels\' - 1','}','drop `wb_mincluster\' `wb_maxcluster\'']
        names=' '.join([*p['x'],'_cons'])
        lines += [f'matrix wb_cov = e(V)*(e(N)-{len(columns)})/(e(N)-wb_K)','matrix wb_beta = e(b)',f'matrix colnames wb_beta = {names}',f'matrix colnames wb_cov = {names}',f'matrix rownames wb_cov = {names}','wb_repost wb_beta wb_cov']
    return lines+model_checks(step,ctx,p,result)


def panel_ols(step,ctx):return panel(step,ctx)
def did(step,ctx):return panel(step,ctx,did=True)
