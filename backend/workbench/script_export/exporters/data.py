"""Native pandas, base R and Stata data operations."""
from __future__ import annotations
from workbench.contracts.common.envelope import thaw_json
from ..syntax import identifier, literal, refuse


def setup(step, ctx):
    p = thaw_json(step.parameters)
    target = ctx.ref(step.step_id)
    source = ctx.ref(step.inputs[0])
    if ctx.language == 'stata':
        lines = [f'frame copy {source} {target}', f'frame change {target}']
    else:
        lines = [ctx.assign(step.step_id, source + ('.copy()' if ctx.language == 'python' else ''))]
    return p, target, lines


def column(target, name, language):
    identifier(name)
    return f'{target}[{literal(name,language)}]' if language == 'python' else (f'{target}[[{literal(name,language)}]]' if language == 'r' else name)


def filter_expr(series, op, value, l):
    if op == 'is_missing': return {'python':f'{series}.isna()', 'r':f'is.na({series})', 'stata':f'missing({series})'}[l]
    missing = {'python':f'{series}.notna()', 'r':f'!is.na({series})', 'stata':f'!missing({series})'}[l]
    if op == 'not_missing': return missing
    val = literal(value,l) if op not in {'between','in','not_in'} else None
    symbols = {'eq':'==','ne':'!=','gt':'>','ge':'>=','lt':'<','le':'<='}
    if op in symbols:
        test = f'({series} {symbols[op]} {val})'
    elif op == 'between':
        low,high = (literal(v,l) for v in value)
        test = f'(({series} >= {low}) & ({series} <= {high}))'
    elif op in {'in','not_in'}:
        if not value: refuse('Membership filter needs at least one value')
        if l == 'python': test = f'{series}.isin({literal(value,l)})'
        elif l == 'r': test = f'({series} %in% {literal(value,l)})'
        else: test = '(' + ' | '.join(f'{series} == {literal(v,l)}' for v in value) + ')'
        if op == 'not_in': test = ('~' if l == 'python' else '!') + test
    else: refuse('Unknown filter operator')
    return f'({missing} & {test})'


def subset(step,ctx):
    p,d,lines = setup(step,ctx); l=ctx.language
    if not p.get('columns'): refuse('subset.columns must be a non-empty list')
    columns = [identifier(c) for c in p['columns']]
    filters = list(p.get('filters') or []) + [{'column':k,'op':'eq','value':v} for k,v in p.get('equals',{}).items()]
    for f in filters:
        expression = filter_expr(column(d,f['column'],l),f['op'],f.get('value'),l)
        lines.append(f'{d} = {d}.loc[{expression}].copy()' if l=='python' else (f'{d} <- {d}[which({expression}), , drop=FALSE]' if l=='r' else f'keep if {expression}'))
    if l=='python': lines.append(f'{d} = {d}.loc[:, {columns!r}]')
    elif l=='r': lines.append(f'{d} <- {d}[, {literal(columns,l)}, drop=FALSE]')
    else: lines += ['keep ' + ' '.join(columns), 'order ' + ' '.join(columns)]
    if p.get('row_indices') is not None:
        ids=p['row_indices']
        if any(type(i) is not int or i<0 for i in ids): refuse('Invalid row indices')
        if l=='python': lines.append(f'{d} = {d}.iloc[{ids!r}].copy()')
        elif l=='r': lines.append(f'{d} <- {d}[{literal([i+1 for i in ids],l)},,drop=FALSE]')
        else:
            lines += ['tempvar wb_index', 'generate long `wb_index\' = .']
            lines += [f'replace `wb_index\' = {i} in {value+1}' for i,value in enumerate(ids)]
            lines += ['keep if !missing(`wb_index\')','sort `wb_index\'','drop `wb_index\'']
    span=p.get('row_index_range',p.get('row_range'))
    if span is not None:
        start,stop=(span['start'],span['stop']) if isinstance(span,dict) else span
        if type(start) is not int or type(stop) is not int or start<0 or stop<start: refuse('Invalid row range')
        if l=='python': lines.append(f'{d} = {d}.iloc[{start}:{stop}].copy()')
        elif l=='r': lines.append(f'{d} <- {d}[seq_len(nrow({d}))>{start} & seq_len(nrow({d}))<={stop},,drop=FALSE]')
        else: lines.append(f'keep if _n > {start} & _n <= {stop}')
    if l=='python': lines.append(f'{d} = {d}.reset_index(drop=True)')
    return lines


def recode(step,ctx):
    p,d,lines=setup(step,ctx);l=ctx.language
    s=column(d,p['column'],l);o=column(d,p['output'],l)
    targets = [rule['to'] for rule in p['rules'] if rule['to'] not in {'copy'}] if all(not isinstance(rule['to'],dict) for rule in p['rules']) else []
    string=any(isinstance(v,str) for v in targets)
    if l=='python': lines += [f'{o} = pd.Series(None, index={d}.index, dtype=object)', f'wb_assigned = pd.Series(False, index={d}.index)']
    elif l=='r': lines += [f'{o} <- {"NA_character_" if string else "NA_real_"}', f'wb_assigned <- rep(FALSE, nrow({d}))']
    else: lines += ['tempvar wb_assigned', 'generate byte `wb_assigned\' = 0',f'generate {"strL" if string else "double"} {o} = {"chr(0)" if string else "."}']
    assigned={'python':'wb_assigned','r':'wb_assigned','stata':"`wb_assigned'"}[l]
    for rule in p['rules']:
        origin=rule['from'];to=rule['to']
        if isinstance(origin,dict): expression=filter_expr(s,'between',[origin['low'],origin['high']],l)
        elif origin=='missing': expression=filter_expr(s,'is_missing',None,l)
        elif origin=='else': expression=filter_expr(s,'not_missing',None,l)
        else: expression=filter_expr(s,'eq',origin,l)
        mask=f'({"~" if l=="python" else "!"}{assigned}) & ({expression})'
        value=s if to=='copy' else literal(to,l)
        if l=='python': lines += [f'wb_mask = ({mask}).fillna(False)',f'{d}.loc[wb_mask, {p["output"]!r}] = {s}[wb_mask]' if to=='copy' else f'{d}.loc[wb_mask, {p["output"]!r}] = {value}', 'wb_assigned |= wb_mask']
        elif l=='r': lines += [f'wb_mask <- which({mask})',f'{o}[wb_mask] <- {value + "[wb_mask]" if to=="copy" else value}', 'wb_assigned[wb_mask] <- TRUE']
        else: lines += [f'replace {o} = {value} if {mask}',f'replace {assigned} = 1 if {mask}']
    nonmissing=filter_expr(s,'not_missing',None,l)
    if l=='python': lines += [f'assert (wb_assigned | ~({nonmissing})).all(), "Unmatched recode values"',f'{o} = pd.to_numeric({o}, errors="raise")' if not string else f'{o} = {o}.astype("string")']
    elif l=='r':lines.append(f'stopifnot(all(wb_assigned | !({nonmissing})))')
    else:lines += [f'assert {assigned} | !({nonmissing})','drop `wb_assigned\'']
    return lines


def rename(step,ctx):
    p,d,lines=setup(step,ctx);l=ctx.language
    for a,b in p['mapping'].items(): identifier(a);identifier(b)
    if l=='python':lines.append(f'{d} = {d}.rename(columns={p["mapping"]!r})')
    elif l=='r':lines.append(f'names({d})[match({literal(list(p["mapping"]),l)}, names({d}))] <- {literal(list(p["mapping"].values()),l)}')
    else:lines.append('rename ('+' '.join(p['mapping'])+') ('+' '.join(p['mapping'].values())+')')
    return lines


def fill_missing(step,ctx):
    p,d,lines=setup(step,ctx);l=ctx.language
    for item in p['strategies']:
        s=column(d,item['column'],l);kind=item['strategy']
        if kind=='drop_rows':
            lines.append(f'{d} = {d}.dropna(subset={[item["column"]]!r})' if l=='python' else (f'{d} <- {d}[!is.na({s}),,drop=FALSE]' if l=='r' else f'drop if missing({s})'));continue
        if kind=='constant':value=literal(item['value'],l)
        elif kind in {'mean','median'}:
            if l=='python':value=f'{s}.{kind}()'
            elif l=='r':value=f'{kind}({s}, na.rm=TRUE)'
            else:lines.append(f'quietly summarize {s}, detail');value='r(mean)' if kind=='mean' else 'r(p50)'
        elif kind=='mode':
            if l=='python':value=f'{s}.mode(dropna=True).iloc[0]'
            elif l=='r':value=f'sort(unique({s}[!is.na({s})]))[which.max(tabulate(match({s}, sort(unique({s}[!is.na({s})])))))]'
            else:
                lines += ['tempvar wb_mode', f'egen `wb_mode\' = mode({s}), minmode'];value="`wb_mode'"
        else:refuse('Unsupported missing strategy')
        if l=='python':lines.append(f'{s} = {s}.fillna({value})')
        elif l=='r':lines.append(f'{s}[is.na({s})] <- {value}')
        else:
            lines.append(f'replace {s} = {value} if missing({s})')
            if kind=='mode':lines.append('drop `wb_mode\'')
    if l=='python':lines.append(f'{d} = {d}.reset_index(drop=True)')
    return lines


def dedupe(step,ctx):
    p,d,lines=setup(step,ctx);l=ctx.language;columns=[identifier(c) for c in p['columns']];keep=p['keep']
    if keep not in {'first','last'}:refuse('Invalid dedupe keep policy')
    if l=='python':lines.append(f'{d} = {d}.drop_duplicates(subset={columns!r}, keep={keep!r}, ignore_index=True)')
    elif l=='r':lines.append(f'{d} <- {d}[!duplicated({d}[, {literal(columns,l)},drop=FALSE], fromLast={literal(keep=="last",l)}),,drop=FALSE]')
    else:lines += ['tempvar wb_order', 'generate long `wb_order\' = _n','sort '+' '.join(columns)+' `wb_order\'', 'by '+' '.join(columns)+f': keep if _n == {"1" if keep=="first" else "_N"}', 'sort `wb_order\'','drop `wb_order\'']
    return lines


def append(step,ctx):
    p,d,lines=setup(step,ctx);l=ctx.language;right=ctx.ref(step.inputs[1])
    if l=='python':lines.append(f'{d} = pd.concat([{d}, {right}], ignore_index=True, sort=False)')
    elif l=='r':
        if p.get('schema_policy','exact')=='union':
            lines += [f'wb_right <- {right}',f'wb_names <- union(names({d}), names(wb_right))',f'for (n in setdiff(wb_names, names({d}))) {d}[[n]] <- NA','for (n in setdiff(wb_names, names(wb_right))) wb_right[[n]] <- NA',f'{d} <- rbind({d}[wb_names], wb_right[wb_names])']
        else:lines.append(f'{d} <- rbind({d}, {right})')
    else:lines += ['tempfile wb_secondary',f'frame {right}: save "`wb_secondary\'", replace','append using "`wb_secondary\'"']
    return lines


def merge(step,ctx):
    p,d,lines=setup(step,ctx);l=ctx.language;right=ctx.ref(step.inputs[1]);keys=[identifier(c) for c in p['keys']];how=p.get('how','left');indicator=p.get('indicator')
    if how not in {'left','right','inner','outer'}:refuse('Invalid merge mode')
    if l=='python':lines.append(f'{d} = {d}.merge({right}, on={keys!r}, how={how!r}, suffixes=("_left","_right"), validate="many_to_one", indicator={indicator or False!r})')
    elif l=='r':
        ctx.packages.add('dplyr')
        function={'left':'left_join','right':'right_join','inner':'inner_join','outer':'full_join'}[how]
        lines += [f'wb_left <- {d}',f'wb_right <- {right}','wb_left$.wb_left_order <- seq_len(nrow(wb_left))','wb_right$.wb_right_order <- seq_len(nrow(wb_right))',f'{d} <- dplyr::{function}(wb_left, wb_right, by={literal(keys,l)}, suffix=c("_left","_right"), relationship="many-to-one", na_matches="na")']
        if how=='outer':lines.append(f'{d} <- {d}[do.call(order, {d}[{literal(keys,l)}]),,drop=FALSE]')
        elif how=='right':lines.append(f'{d} <- {d}[order({d}$.wb_right_order,{d}$.wb_left_order),,drop=FALSE]')
        else:lines.append(f'{d} <- {d}[order({d}$.wb_left_order),,drop=FALSE]')
        if indicator:
            name=identifier('_merge' if indicator is True else indicator)
            lines.append(f'{d}[[{literal(name,l)}]] <- ifelse(is.na({d}$.wb_left_order),"right_only",ifelse(is.na({d}$.wb_right_order),"left_only","both"))')
        lines += [f'{d}$.wb_left_order <- NULL',f'{d}$.wb_right_order <- NULL']
    else:
        keep={'left':'master match','right':'using match','inner':'match','outer':'master using match'}[how]
        lines += [f'frame copy {right} wb_right{ctx.index}', f'frame wb_right{ctx.index}: ds', 'local wb_right_columns `r(varlist)\'', 'ds', 'local wb_left_columns `r(varlist)\'', 'local wb_keys '+ ' '.join(keys), 'local wb_common : list wb_left_columns & wb_right_columns', 'local wb_common : list wb_common - wb_keys', 'foreach c of local wb_common {', '    rename `c\' `c\'_left', f'    frame wb_right{ctx.index}: rename `c\' `c\'_right', '}', 'tempvar wb_order wb_right_order', 'generate long `wb_order\' = _n', f'frame wb_right{ctx.index}: generate long `wb_right_order\' = _n', 'tempfile wb_secondary', f'frame wb_right{ctx.index}: save "`wb_secondary\'", replace', f'merge m:1 {" ".join(keys)} using "`wb_secondary\'", keep({keep})']
        lines.append('sort '+ (' '.join(keys) if how=='outer' else ("`wb_right_order' `wb_order'" if how=='right' else "`wb_order'")))
        lines.append('drop `wb_order\' `wb_right_order\'')
        if indicator:
            name=identifier('_merge' if indicator is True else indicator)
            lines += [f'generate str10 {name}_text = cond(_merge == 1,"left_only",cond(_merge==2,"right_only","both"))','drop _merge',f'rename {name}_text {name}']
        else:lines.append('drop _merge')
    return lines


def aggregate(step,ctx):
    p,d,lines=setup(step,ctx);l=ctx.language;groups=[identifier(c) for c in p['group_by']]
    for item in p['aggregations']:identifier(item['column']);identifier(item['output'])
    if l=='python':
        named=', '.join(f'{item["output"]}=pd.NamedAgg(column={item["column"]!r}, aggfunc={item["func"]!r})' for item in p['aggregations'])
        lines.append(f'{d} = {d}.groupby({groups!r}, dropna=False, sort=False).agg({named}).reset_index()')
    elif l=='r':
        ctx.packages.add('dplyr')
        functions={'std':'sd','count':'sum'}
        terms=[]
        for item in p['aggregations']:
            s=identifier(item['column']);fun=item['func'];out=identifier(item['output'])
            expr=f'sum(!is.na({s}))' if fun=='count' else f'{functions.get(fun,fun)}({s}, na.rm=TRUE)'
            if fun in {'min','max'}:expr=f'if (all(is.na({s}))) NA_real_ else {expr}'
            terms.append(out+'='+expr)
        lines += [f'{d}$.wb_order <- seq_len(nrow({d}))', f'{d} <- dplyr::group_by({d}, dplyr::across(dplyr::all_of({literal(groups,l)})), .drop=FALSE)', f'{d} <- as.data.frame(dplyr::summarise({d}, .wb_order=min(.wb_order), {", ".join(terms)}, .groups="drop"))', f'{d} <- {d}[order({d}$.wb_order),,drop=FALSE]', f'{d}$.wb_order <- NULL']
    else:
        lines += ['tempvar wb_order wb_group_order','generate long `wb_order\' = _n','bysort '+' '.join(groups)+': egen long `wb_group_order\' = min(`wb_order\')']
        functions={'std':'sd'}
        pieces=[f'({functions.get(item["func"],item["func"])}) {item["output"]}={item["column"]}' for item in p['aggregations']]
        lines += ['collapse '+' '.join(pieces)+' (min) `wb_group_order\', by('+' '.join(groups)+')','sort `wb_group_order\'','drop `wb_group_order\'', 'order '+' '.join(groups+[a['output'] for a in p['aggregations']])]
    return lines


def reshape(step,ctx):
    p,d,lines=setup(step,ctx);l=ctx.language
    if p['direction']=='wide_to_long':
        ids=[identifier(c) for c in p['id_columns']];values=[identifier(c) for c in p['value_columns']];var=identifier(p.get('var_name','variable'));value=identifier(p.get('value_name','value'))
        if l=='python':lines.append(f'{d} = {d}.melt(id_vars={ids!r}, value_vars={values!r}, var_name={var!r}, value_name={value!r})')
        elif l=='r':
            lines += [f'{d} <- do.call(rbind, lapply({literal(values,l)}, function(n) {{ z <- {d}[, {literal(ids,l)},drop=FALSE]; z[[{literal(var,l)}]] <- n; z[[{literal(value,l)}]] <- {d}[[n]]; z }}))',f'rownames({d}) <- NULL']
        else:
            lines += ['tempvar wb_order wb_value_order', 'generate long `wb_order\' = _n']
            for i,c in enumerate(values):lines.append(f'rename {c} wb_value{i+1}')
            lines += ['keep '+' '.join(ids)+" `wb_order' wb_value*",'reshape long wb_value, i(`wb_order\') j(`wb_value_order\')',f'generate str32 {var} = ""']
            for i,c in enumerate(values):lines.append(f'replace {var} = "{c}" if `wb_value_order\' == {i+1}')
            lines += [f'rename wb_value {value}','sort `wb_value_order\' `wb_order\'','drop `wb_order\' `wb_value_order\'','order '+' '.join(ids+[var,value])]
    elif p['direction']=='long_to_wide':
        ids=[identifier(c) for c in p['index']];var=identifier(p['columns']);value=identifier(p['values'])
        if l=='python':lines.append(f'{d} = {d}.pivot(index={ids!r}, columns={var!r}, values={value!r}).reset_index()')
        elif l=='r':
            ctx.packages.add('tidyr');lines += [f'{d} <- as.data.frame(tidyr::pivot_wider({d}, id_cols=dplyr::all_of({literal(ids,l)}), names_from={var}, values_from={value}, names_sort=TRUE))',f'{d} <- {d}[do.call(order, {d}[{literal(ids,l)}]),,drop=FALSE]']
        else:
            lines += [f'reshape wide {value}, i({" ".join(ids)}) j({var}) string',f'rename {value}* *','sort '+' '.join(ids)]
    else:refuse('Invalid reshape direction')
    return lines


def lag(step,ctx):
    p,d,lines=setup(step,ctx);l=ctx.language;diff=p.get('difference',0)
    if type(diff) is not int or diff<0:refuse('Invalid difference lag')
    for c in p['columns']:
        s=column(d,c,l)
        for lag in p['lags']:
            if type(lag) is not int or lag<1:refuse('Invalid lag period')
            out=column(d,f'{c}_lag{lag}',l)
            if l=='python':lines.append(f'{out} = {s}{f".diff({diff})" if diff else ""}.shift({lag})')
            elif l=='r':lines += [f'wb_base <- {s}' + (f' - c(rep(NA, min({diff},length({s}))), head({s}, -{diff}))' if diff else ''),f'{out} <- c(rep(NA, min({lag},length(wb_base))), head(wb_base, -{lag}))']
            else:lines.append(f'generate double {out} = {s}[_n-{lag}]' + (f' - {s}[_n-{lag+diff}]' if diff else ''))
    return lines


def tsset(step,ctx):
    p,d,lines=setup(step,ctx);l=ctx.language;t=identifier(p['time_column']);entity=p.get('panel_id_column');columns=([identifier(entity)] if entity else [])
    if l=='python':lines += [f'wb_time = pd.to_datetime({d}[{t!r}], format="mixed", errors="raise")',f'wb_sort_keys = pd.DataFrame({{**{{i:{d}[c] for i,c in enumerate({columns!r})}}, {len(columns)}:wb_time}})',f'wb_order = wb_sort_keys.sort_values({list(range(len(columns)+1))!r}, kind="mergesort").index',f'{d} = {d}.loc[wb_order].reset_index(drop=True)']
    elif l=='r':lines += [f'wb_time <- {d}[[{literal(t,l)}]]',f'if (is.character(wb_time)) wb_time <- as.POSIXct(wb_time, tz="UTC")',f'stopifnot(!anyNA(wb_time))',f'{d} <- {d}[order({", ".join([column(d,c,l) for c in columns]+["wb_time"])}),,drop=FALSE]']
    else:
        lines += ['tempvar wb_time',f'capture confirm string variable {t}',f'if !_rc generate double `wb_time\' = cond(missing(clock({t}, "YMDhms")), clock({t}, "YMD"), clock({t}, "YMDhms"))',f'else generate double `wb_time\' = {t}','assert !missing(`wb_time\')','sort '+' '.join(columns)+" `wb_time'",'drop `wb_time\'']
    return lines
