"""Native preparation of a declared absorbing treatment panel."""
from collections.abc import Mapping
from functools import lru_cache
import sys
import math
import unicodedata

from .exporters.data import setup,column
from .syntax import identifier,literal,refuse


def configuration(step):
    if 'preparation' not in step.parameters:
        return None
    spec=step.parameters['preparation']
    keys={'kind','version','mode','entity','time','cohort','treat','post','status'}
    if (not isinstance(spec,Mapping) or not keys<=set(spec) or set(spec)-keys-{'boolean_columns','cohort_range'}
            or spec['kind']!='absorbing_treatment_panel' or type(spec['version']) is not int
            or spec['version']!=1 or type(spec['mode']) is not str
            or spec['mode'] not in {'cohort','two_by_two','status'}):
        refuse('Unknown executed estimator input preparation')
    for key in ('entity','time'):
        identifier(spec[key])
    required={'cohort':('cohort',),'two_by_two':('treat','post'),'status':('status',)}[spec['mode']]
    for key in required:identifier(spec[key])
    for key in ('cohort','treat','post','status'):
        if spec[key] is not None:identifier(spec[key])
    boolean=spec.get('boolean_columns',())
    roles={spec[key] for key in ('entity','time','cohort','treat','post','status') if spec[key]}
    if (not isinstance(boolean,(list,tuple)) or any(type(name) is not str for name in boolean)
            or len(set(boolean))!=len(boolean) or not set(boolean)<=roles):
        refuse('Invalid executed Boolean input column declaration')
    span=spec.get('cohort_range')
    if span is not None:
        try:
            valid=(isinstance(span,(list,tuple)) and len(span)==2
                and all(type(value) in {int,float} and math.isfinite(value) and value>0 for value in span)
                and span[0]<=span[1])
        except OverflowError:
            valid=False
        if not valid:refuse('Invalid executed finite cohort range')
    return dict(spec)


@lru_cache(maxsize=1)
def cohort_lexicon():
    """Match float's decimal digits and surrounding whitespace exactly."""
    digits=['' for _ in range(10)]
    whitespace=''
    for point in range(sys.maxunicode+1):
        char=chr(point)
        if unicodedata.category(char)=='Nd':digits[unicodedata.decimal(char)]+=char
        if char.isspace():
            try:float(char+'1'+char)
            except ValueError:continue
            whitespace+=char
    atom='[0-9](?:_?[0-9])*'
    grammar=f'^[+-]?(?:{atom}(?:\\.(?:{atom})?)?|\\.{atom})(?:[eE][+-]?{atom})?$'
    return digits,whitespace,grammar


def capability(step):
    if configuration(step) is None:
        return 'Executed estimator input normalization continues from its verified Workbench dataset snapshot; native preparation is not yet validated.'


def prepare(step,ctx):
    spec=configuration(step)
    if spec is None:refuse('Executed input preparation is not declared')
    _,target,lines=setup(step,ctx)
    language=ctx.language
    span=spec.get('cohort_range')
    if language=='stata' and span and (span[0]<sys.float_info.min or span[1]>sys.float_info.max/2):
        refuse('The executed finite cohort period is outside Stata\'s representable full-precision double range.',
            'UNREPRESENTABLE_COHORT_PERIOD')
    def col(name):return column(target,name,language)
    mode=spec['mode'];entity=col(spec['entity']);time=col(spec['time'])
    cohort=col('_did_cohort');status=col('_did_D');event=col('_did_event_time')
    if language=='python':
        lines += [f'wb_panel_entity = {entity}.copy()',
            f'wb_time = pd.to_numeric({time}, errors="coerce")']
        entity='wb_panel_entity'
        if mode=='cohort':
            lines += ['def wb_cohort_number(value):',
                '    try: return float(value)',
                '    except (TypeError, ValueError): return np.nan',
                f'wb_cohort = {col(spec["cohort"])}.map(wb_cohort_number)',
                f'{cohort} = wb_cohort.where(np.isfinite(wb_cohort) & (wb_cohort > 0) & {entity}.notna()).astype(float)']
        elif mode=='two_by_two':
            lines += [f'wb_first_post = wb_time[pd.to_numeric({col(spec["post"])}, errors="raise") == 1].min()',
                f'wb_treated = (pd.to_numeric({col(spec["treat"])}, errors="raise") == 1).groupby({entity}).transform("any")',
                f'{cohort} = np.where(wb_treated.eq(True) & {entity}.notna(), wb_first_post, np.nan)']
        else:
            lines += [f'wb_on = wb_time.where(pd.to_numeric({col(spec["status"])}, errors="raise") == 1)',
                f'{cohort} = wb_on.groupby({entity}).transform("min")']
        if spec['time']=='_did_cohort':lines.append(f'wb_time = {cohort}.copy()')
        lines += [f'{status} = (wb_time.ge({cohort}) & {cohort}.notna()).astype(int)',
            f'{event} = wb_time - {cohort}']
    elif language=='r':
        lines += ['wb_panel_numeric <- function(z, logical_column=FALSE) {',
            '  if (is.numeric(z) || (is.logical(z) && logical_column)) return(as.numeric(z))',
            '  value <- tolower(as.character(z))',
            '  out <- suppressWarnings(as.numeric(value))',
            '  if (logical_column) {',
            '    out[which(value == "true")] <- 1',
            '    out[which(value == "false")] <- 0', '  }',
            '  out', '}']
        boolean={col(name) for name in spec.get('boolean_columns',())}
        numeric=lambda value:f'wb_panel_numeric({value}, {"TRUE" if value in boolean else "FALSE"})'
        lines += [f'wb_panel_entity <- {entity}',f'wb_time <- {numeric(time)}']
        entity='wb_panel_entity'
        if mode=='cohort':
            from .exact_numeric import r_float_parser
            lines+=r_float_parser(ctx)
            digits,whitespace,grammar=cohort_lexicon()
            value=col(spec['cohort'])
            logical='TRUE' if spec['cohort'] in spec.get('boolean_columns',()) else 'FALSE'
            lines += [f'wb_cohort_input <- {value}',
                f'if (is.numeric(wb_cohort_input) || (is.logical(wb_cohort_input) && {logical})) {{',
                '  wb_cohort <- as.numeric(wb_cohort_input)', '} else {',
                'wb_cohort_text <- as.character(wb_cohort_input)',
                f'wb_cohort_text <- chartr({literal("".join(digits),language)}, {literal("".join(str(i)*len(group) for i,group in enumerate(digits)),language)}, wb_cohort_text)',
                f'wb_cohort_text <- gsub({literal("^["+whitespace+"]+|["+whitespace+"]+$",language)}, "", wb_cohort_text, perl=TRUE)']
            if spec['cohort'] in spec.get('boolean_columns',()):
                lines += ['wb_cohort_text[tolower(wb_cohort_text) == "true" & !is.na(wb_cohort_text)] <- "1"',
                    'wb_cohort_text[tolower(wb_cohort_text) == "false" & !is.na(wb_cohort_text)] <- "0"']
            lines += [f'wb_cohort_valid <- grepl({literal(grammar,language)}, wb_cohort_text, perl=TRUE)',
                'wb_cohort <- rep(NA_real_, length(wb_cohort_text))',
                'if (any(wb_cohort_valid)) wb_cohort[wb_cohort_valid] <- wb_parse_float(wb_cohort_text[wb_cohort_valid])', '}',
                f'{cohort} <- ifelse(is.finite(wb_cohort) & wb_cohort > 0, wb_cohort, NA_real_)']
        elif mode=='two_by_two':
            lines += [f'wb_post <- {numeric(col(spec["post"]))}',
                'wb_first_post <- if (any(wb_post == 1 & !is.na(wb_time), na.rm=TRUE)) min(wb_time[which(wb_post == 1)], na.rm=TRUE) else NA_real_',
                f'wb_treated <- ave({numeric(col(spec["treat"]))}, {entity}, FUN=function(z) as.numeric(any(z == 1)))',
                f'{cohort} <- ifelse(wb_treated == 1, wb_first_post, NA_real_)']
        else:
            lines += [f'wb_on <- ifelse({numeric(col(spec["status"]))} == 1, wb_time, NA_real_)',
                f'{cohort} <- ave(wb_on, {entity}, FUN=function(z) if (all(is.na(z))) NA_real_ else min(z, na.rm=TRUE))']
        lines.append(f'{cohort}[is.na({entity})] <- NA_real_')
        if spec['time']=='_did_cohort':lines.append(f'wb_time <- {cohort}')
        lines += [
            f'{status} <- as.integer(!is.na(wb_time) & !is.na({cohort}) & wb_time >= {cohort})',
            f'{event} <- wb_time - {cohort}']
    else:
        # Each conversion leaves the original column and row order intact.
        temporary=[]
        lines.append('unab wb_original_columns: _all')
        def numeric(name,temp):
            value=identifier(name)
            temporary.append(temp)
            lines.extend([f'tempvar {temp}',f'capture confirm string variable {value}',
                'if !_rc {',f'  generate double `{temp}\' = real({value})'])
            if name in spec.get('boolean_columns',()):
                lines.extend([f'  replace `{temp}\' = 1 if lower({value}) == "true"',
                    f'  replace `{temp}\' = 0 if lower({value}) == "false"'])
            lines.extend(['}',f'else generate double `{temp}\' = {value}'])
            return f'`{temp}\''
        t=numeric(spec['time'],'wb_time')
        temporary.append('wb_entity')
        lines += ['tempvar wb_entity',f'clonevar `wb_entity\' = {identifier(spec["entity"])}']
        if mode=='cohort':
            digits,whitespace,grammar=cohort_lexicon()
            value=identifier(spec['cohort'])
            temporary.extend(['wb_cohort','wb_cohort_text'])
            c="`wb_cohort'"
            lines += ['tempvar wb_cohort wb_cohort_text',f'capture confirm string variable {value}',
                'if !_rc {',f'  generate strL `wb_cohort_text\' = {value}']
            for digit,group in enumerate(digits):
                lines.append(f'  replace `wb_cohort_text\' = ustrregexra(`wb_cohort_text\', {literal("["+group+"]",language)}, "{digit}")')
            # Stata string literals cannot contain control whitespace; use its
            # Unicode regex escape for each whitespace accepted by float().
            trim=''.join('\\u'+format(ord(char),'04x') for char in whitespace)
            lines.append(f'  replace `wb_cohort_text\' = ustrregexra(`wb_cohort_text\', {literal("^["+trim+"]+|["+trim+"]+\\z",language)}, "")')
            if spec['cohort'] in spec.get('boolean_columns',()):
                lines += ['  replace `wb_cohort_text\' = "1" if lower(`wb_cohort_text\') == "true"',
                    '  replace `wb_cohort_text\' = "0" if lower(`wb_cohort_text\') == "false"']
            stata_grammar=grammar.removesuffix('$')+'\\z'
            lines += [f'  generate double `wb_cohort\' = real(subinstr(`wb_cohort_text\', "_", "", .)) if ustrregexm(`wb_cohort_text\', {literal(stata_grammar,language)})',
                '}', 'else {',f'  generate double `wb_cohort\' = {value}',
                '  generate str1 `wb_cohort_text\' = ""', '}']
            if 'cohort_range' not in spec:
                lines += [f'count if ustrregexm(`wb_cohort_text\', {literal(stata_grammar,language)}) & missing(`wb_cohort\')',
                    'if r(N) {',
                    '  display as error "A cohort number is outside Stata\'s representable range; executed finite range was not declared."',
                    '  exit 459', '}']
        elif mode=='two_by_two':
            post=numeric(spec['post'],'wb_post');treat=numeric(spec['treat'],'wb_treat')
        else:on=numeric(spec['status'],'wb_on')
        lines.extend('capture drop '+name for name in ['_did_cohort','_did_D','_did_event_time'])
        if mode=='cohort':
            lines.append(f'generate double _did_cohort = {c} if !missing({c}) & {c} > 0')
        elif mode=='two_by_two':
            lines += [f'quietly summarize {t} if {post} == 1, meanonly',
                'tempname wb_first_post', 'scalar `wb_first_post\' = r(min)',
                'tempvar wb_treated',f'egen byte `wb_treated\' = max({treat} == 1), by(`wb_entity\')',
                'generate double _did_cohort = `wb_first_post\' if `wb_treated\' == 1']
            temporary.append('wb_treated')
        else:
            lines += ['tempvar wb_treated_time',
                f'generate double `wb_treated_time\' = {t} if {on} == 1',
                'egen double _did_cohort = min(`wb_treated_time\'), by(`wb_entity\')']
            temporary.append('wb_treated_time')
        lines.append('replace _did_cohort = . if missing(`wb_entity\')')
        if spec['time']=='_did_cohort':lines.append(f'replace {t} = _did_cohort')
        lines += [
            f'generate byte _did_D = !missing({t}) & !missing(_did_cohort) & {t} >= _did_cohort',
            f'generate double _did_event_time = {t} - _did_cohort']
        lines += ['drop '+' '.join(f'`{name}\'' for name in temporary),
            'order `wb_original_columns\'']
    return lines
