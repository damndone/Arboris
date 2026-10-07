"""Declared linearization exports for the Workbench sampling OLS estimator."""
from __future__ import annotations
import ast
from workbench.contracts.common.envelope import thaw_json
from workbench.survey.fields import DESIGN_FIELDS
from ..syntax import identifier,literal,refuse


def configuration(step):
    p=thaw_json(step.parameters);design=p.get('model_options',{}).get('survey_design')
    if not isinstance(design,dict) or not design:
        refuse('Sampling weights require an explicit survey design','SURVEY_DESIGN_REQUIRED')
    allowed=set(DESIGN_FIELDS)|{'sampling_weight','survey_method','survey_seed'}
    if set(design)-allowed:refuse('Unknown survey design fields','UNSUPPORTED_SURVEY_DESIGN')
    weight=design.get('sampling_weight')
    if weight!=p['weights']['column']:refuse('Sampling weight and design weight disagree','UNSUPPORTED_SURVEY_DESIGN')
    for key in ('sampling_weight','survey_strata_col','survey_psu_col','survey_fpc_col'):
        if design.get(key):identifier(design[key])
    if not (design.get('survey_strata_col') or design.get('survey_psu_col')):
        refuse('Sampling design needs strata and/or PSU','SURVEY_DESIGN_REQUIRED')
    fpc=design.get('survey_fpc_col')
    if fpc is not None and fpc!='':identifier(fpc)
    if design.get('survey_method','linearization')!='linearization' or design.get('survey_replicate_type') or design.get('survey_replicate_weights'):
        return design,'Replicate sampling variance requires a validated replicate construction and matching target refits; this exporter validates linearization only.'
    if p.get('covariance')!='survey_design':refuse('Sampling OLS requires the executed survey_design covariance','UNSUPPORTED_SURVEY_DESIGN')
    if p.get('categorical_x'):return design,'Workbench survey adapter does not support categorical contrast terms.'
    if design.get('survey_df','design') not in {'design','design_minus_p'}:refuse('Unknown survey degrees of freedom','UNSUPPORTED_SURVEY_DESIGN')
    if design.get('survey_lonely_psu','fail') not in {'fail','remove','certainty','adjust','average'}:refuse('Unknown lonely PSU policy','UNSUPPORTED_SURVEY_DESIGN')
    if design.get('survey_weight_frame') not in {None,'','cross_sectional'}:return design,'Longitudinal weight-frame export is not validated for cross-sectional sampling OLS.'
    if design.get('survey_subpop'):domain(design['survey_subpop'],'python','wb_frame')
    return design,None


def fpc_validation(design, language):
    """Validate approved one-stage units before restricting a domain."""
    fpc=design.get('survey_fpc_col')
    if not fpc:return []
    strata=design.get('survey_strata_col');psu=design.get('survey_psu_col')
    if language=='r':
        groups=f'as.character(wb_frame[[{literal(strata,"r")}]])' if strata else 'rep("all",nrow(wb_frame))'
        units=f'wb_frame[[{literal(psu,"r")}]]' if psu else 'seq_len(nrow(wb_frame))'
        return [f'wb_fpc <- wb_frame[[{literal(fpc,"r")}]]',
                'stopifnot(is.numeric(wb_fpc),!is.logical(wb_fpc),length(wb_fpc)>0,all(is.finite(wb_fpc)),all(wb_fpc>=0))',
                'wb_fpc_fraction <- all(wb_fpc<=1)',
                'if (!wb_fpc_fraction) stopifnot(all(wb_fpc>1),all(wb_fpc==floor(wb_fpc)))',
                f'wb_fpc_groups <- split(seq_len(nrow(wb_frame)),{groups})',f'wb_fpc_units <- {units}',
                'for (wb_rows in wb_fpc_groups) {',
                '  stopifnot(length(unique(wb_fpc[wb_rows]))==1)',
                '  if (!wb_fpc_fraction) stopifnot(wb_fpc[wb_rows[1]]>=length(unique(wb_fpc_units[wb_rows])))','}']
    return [f'assert !missing({fpc}) & {fpc} >= 0',f'quietly summarize {fpc}, meanonly',
            'scalar wb_fpc_fraction = (r(max)<=1)',
            f'if !wb_fpc_fraction assert {fpc}>1 & {fpc}==floor({fpc})',
            'tempvar wb_fpc_order wb_fpc_stratum wb_fpc_psu wb_fpc_tag wb_fpc_n',
            'generate long `wb_fpc_order\' = _n',
            f'egen long `wb_fpc_stratum\' = group({strata})' if strata else 'generate long `wb_fpc_stratum\' = 1',
            f'egen long `wb_fpc_psu\' = group(`wb_fpc_stratum\' {psu})' if psu else 'generate long `wb_fpc_psu\' = _n',
            'egen byte `wb_fpc_tag\' = tag(`wb_fpc_stratum\' `wb_fpc_psu\')',
            'bysort `wb_fpc_stratum\': egen long `wb_fpc_n\' = total(`wb_fpc_tag\')',
            f'bysort `wb_fpc_stratum\': assert {fpc}=={fpc}[1]',
            f'if !wb_fpc_fraction assert {fpc}>=`wb_fpc_n\'', 'sort `wb_fpc_order\'']


def domain(text,language,frame):
    """Compile a closed boolean domain expression; never execute input code."""
    if not isinstance(text,str) or len(text)>500:refuse('Invalid survey domain','UNSUPPORTED_SURVEY_DESIGN')
    try:tree=ast.parse(text.strip(),mode='eval')
    except SyntaxError:refuse('Invalid survey domain','UNSUPPORTED_SURVEY_DESIGN')
    symbols={ast.Eq:'==',ast.NotEq:'!=',ast.Lt:'<',ast.LtE:'<=',ast.Gt:'>',ast.GtE:'>='}
    def walk(node):
        if isinstance(node,ast.BoolOp) and isinstance(node.op,(ast.And,ast.Or)):
            operator=' & ' if isinstance(node.op,ast.And) else ' | '
            return '('+operator.join(walk(v) for v in node.values)+')'
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.Not):
            return ('~' if language=='python' else '!')+'('+walk(node.operand)+')'
        if isinstance(node,ast.Compare) and len(node.ops)==1 and type(node.ops[0]) in symbols and isinstance(node.left,ast.Name) and isinstance(node.comparators[0],ast.Constant):
            name=identifier(node.left.id);value=node.comparators[0].value
            if value is None or not isinstance(value,(str,int,float,bool)):refuse('Invalid domain literal','UNSUPPORTED_SURVEY_DESIGN')
            series=f'{frame}[{name!r}]' if language=='python' else (f'{frame}[[{literal(name,language)}]]' if language=='r' else name)
            comparison=f'({series} {symbols[type(node.ops[0])]} {literal(value,language)})'
            if language=='python':return comparison
            missing=f'is.na({series})' if language=='r' else f'missing({series})'
            return f'({missing} | {comparison})' if isinstance(node.ops[0],ast.NotEq) else f'(!{missing} & {comparison})'
        refuse('Survey domains allow only column/literal comparisons and boolean operators','UNSUPPORTED_SURVEY_DESIGN')
    return walk(tree.body)


def ols(step,ctx):
    from .models import prepare,formula,model_checks,array_helper
    design,reason=configuration(step)
    if reason:refuse(reason,'UNSUPPORTED_SURVEY_DESIGN')
    p,d,result,lines=prepare(step,ctx);l=ctx.language
    ctx.distributions[step.step_id]='t'
    convention=design.get('survey_df') or 'design'
    lonely=design.get('survey_lonely_psu') or 'fail'
    columns=[p['y'],*p['x']];subpop=design.get('survey_subpop')
    if l=='python':
        ctx.packages.add('workbench');lines+=array_helper(ctx)
        artifacts={'_'+k:v for k,v in design.items()}
        lines += ['from workbench.survey.adapters import build_design_from_artifacts, glm_estimator_spec','from workbench.survey.engine import estimate_with_design',
                  f'wb_frame = {d}.dropna(subset={columns!r}).copy()',
                  f'wb_design = build_design_from_artifacts(wb_frame, {artifacts!r})',
                  f'wb_estimator = glm_estimator_spec(family="ols", glm_family="gaussian", y={p["y"]!r}, x={p["x"]!r})',
                  f'wb_survey = estimate_with_design(wb_design,wb_estimator,method="linearization",df_convention={convention!r})',
                  'wb_params = pd.Series(wb_survey.estimates).rename(index={"(Intercept)":"Intercept"})',
                  'wb_mask = wb_design.subpop_mask()',
                  f'wb_X = np.column_stack([np.ones(int(wb_mask.sum())),*([wb_frame.loc[wb_mask,c].to_numpy() for c in {p["x"]!r}])])',
                  f'{result} = wb_array_model(wb_params,wb_survey.covariance,len(wb_frame),wb_survey.inference_degf,"t",design=wb_X,sample=list(wb_frame.index[wb_mask]))',
                  f'{result}["df_method"] = {convention!r}']
    elif l=='r':
        ctx.packages.add('survey')
        lines += [f'wb_frame <- {d}[complete.cases({d}[, {literal(columns,l)},drop=FALSE]),,drop=FALSE]',f'options(survey.lonely.psu={literal(lonely,l)})']
        ids='~'+identifier(design['survey_psu_col']) if design.get('survey_psu_col') else '~1'
        strata=', strata=~'+identifier(design['survey_strata_col']) if design.get('survey_strata_col') else ''
        lines += fpc_validation(design,l)
        fpc=', fpc=~'+design['survey_fpc_col'] if design.get('survey_fpc_col') else ''
        lines += [f'wb_design <- survey::svydesign(ids={ids}{strata}, weights=~{design["sampling_weight"]}{fpc}, data=wb_frame, nest=TRUE)',
                  'wb_design_df <- survey::degf(wb_design)']
        if subpop:lines.append(f'wb_design <- wb_design[{domain(subpop,l,"wb_frame")},]')
        lines += [f'wb_fit <- survey::svyglm({formula(p,l)}, design=wb_design, family=gaussian())',
                  'wb_df <- wb_design_df'+(' - length(coef(wb_fit)) + 1' if convention=='design_minus_p' else ''),
                  f'{result} <- wb_model(wb_fit,vcov(wb_fit),wb_df,"t",wb_aliases,likelihood=FALSE)',
                  f'{result}$nobs <- nrow(wb_frame)',f'{result}$loglik <- NULL',f'{result}$df_method <- {literal(convention,l)}']
    else:
        lines += ['drop if '+' | '.join(f'missing({c})' for c in columns)]
        strata=', strata('+design['survey_strata_col']+')' if design.get('survey_strata_col') else ','
        single={'fail':'missing','remove':'certainty','certainty':'certainty','adjust':'centered','average':'scaled'}[lonely]
        psu=design.get('survey_psu_col') or '_n'
        lines += fpc_validation(design,l)
        fpc=' fpc('+design['survey_fpc_col']+')' if design.get('survey_fpc_col') else ''
        lines += [f'svyset {psu} [pw={design["sampling_weight"]}]{strata}{fpc} singleunit({single})']
        prefix='svy'
        if subpop:
            lines += ['tempvar wb_survey_domain',f'generate byte `wb_survey_domain\' = {domain(subpop,l,"")}']
            prefix+=" , subpop(`wb_survey_domain')"
        lines.append(f'{prefix}: regress {formula(p,l)}')
        # Explicitly chosen coefficient t degrees of freedom, not Stata's default.
        if convention=='design_minus_p':
            lines += ['capture program drop wb_survey_df','program define wb_survey_df, eclass','    ereturn scalar df_r = e(N_psu) - e(N_strata) - e(rank) + 1','end','wb_survey_df']
        lines += ['assert e(df_r) > 0','matrix wb_survey_v = e(V)','mata: assert(!hasmissing(st_matrix("wb_survey_v")))']
    return lines+model_checks(step,ctx,p,result)
