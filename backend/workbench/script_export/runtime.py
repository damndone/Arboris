"""Language runtimes, local readers and deferred self-checks."""
from __future__ import annotations
from dataclasses import dataclass, field
from workbench.script_export.plan import DEFAULT_TOLERANCES
from .syntax import filename, identifier, literal, refuse

PYTHON_PRELUDE = '''import hashlib
import math
from pathlib import Path
import numpy as np
import pandas as pd

data = {}
results = {}
checks = []
base = Path(__file__).resolve().parent

def wb_read(name, digest, fmt, options=None):
    path = base / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise AssertionError('SHA256 mismatch: ' + name)
    if fmt in {'dta', 'sav'}:
        import pyreadstat
        reader = pyreadstat.read_dta if fmt == 'dta' else pyreadstat.read_sav
        kwargs = {'apply_value_formats': False, **(options or {})}
        if fmt == 'sav': kwargs['user_missing'] = True
        frame, _metadata = reader(str(path), **kwargs)
        for column in frame.columns:
            values = frame[column].dropna()
            if frame[column].dtype == object and len(values) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                frame[column] = pd.to_numeric(frame[column])
        return frame
    readers = {'csv': pd.read_csv,
               'xlsx': pd.read_excel, 'parquet': pd.read_parquet}
    return readers[fmt](path, **(options or {}))

def wb_check(actual, expected, absolute, relative, label):
    if not math.isfinite(float(actual)) or abs(actual-expected) > absolute + relative*abs(expected):
        raise AssertionError(f'{label}: {actual!r} != {expected!r}')
'''

R_PRELUDE = '''data <- list()
results <- list()
checks <- list()
args <- commandArgs(FALSE)
script <- sub("^--file=", "", args[grepl("^--file=", args)])
base <- dirname(normalizePath(script))
wb_read <- function(name, digest, fmt, options=list()) {
  path <- file.path(base, name)
  hash <- system2("shasum", c("-a", "256", shQuote(path)), stdout=TRUE)
  if (length(hash) != 1L || substr(hash,1,64) != digest) stop(paste("SHA256 mismatch:", name))
  switch(fmt,
    csv=do.call(read.csv, c(list(file=path, check.names=FALSE, stringsAsFactors=FALSE, blank.lines.skip=FALSE, na.strings=c("", "NA")), options)),
    dta=as.data.frame(haven::read_dta(path)), sav=as.data.frame(haven::read_sav(path)), xlsx=openxlsx::read.xlsx(path, sheet=if(is.null(options$sheet)) 1 else options$sheet, check.names=FALSE, skipEmptyRows=FALSE, skipEmptyCols=FALSE),
    parquet=as.data.frame(arrow::read_parquet(path)), stop("Unsupported source format"))
}
wb_check <- function(actual, expected, absolute, relative, label) {
  if (length(actual)!=1 || !is.finite(actual) || abs(actual-expected)>absolute+relative*abs(expected))
    stop(paste(label, actual, "!=", expected))
}
'''

STATA_PRELUDE = '''version 18
set more off
set type double
capture program drop wb_repost
program define wb_repost, eclass
    args beta covariance
    ereturn repost b=`beta' V=`covariance', rename
end
capture program drop wb_sha
program define wb_sha
    args filename expected
    tempfile digestfile
    shell shasum -a 256 "`filename'" > "`digestfile'"
    tempname fh
    file open `fh' using "`digestfile'", read text
    file read `fh' line
    file close `fh'
    if substr("`line'",1,64) != "`expected'" {
        display as error "SHA256 mismatch"
        exit 9
    }
end
'''

# Keep existing CSV-only script bytes stable. Statistical-file sources select
# the corrected native readers explicitly when the plan consumes that format.
CSV_PYTHON_PRELUDE = PYTHON_PRELUDE[:PYTHON_PRELUDE.index("    if fmt in {'dta', 'sav'}:")] + '''    readers = {'csv': pd.read_csv, 'dta': pd.read_stata, 'sav': pd.read_spss,
               'xlsx': pd.read_excel, 'parquet': pd.read_parquet}
''' + PYTHON_PRELUDE[PYTHON_PRELUDE.index("    return readers[fmt]"):]
CSV_R_PRELUDE = R_PRELUDE.replace('dta=as.data.frame(haven::read_dta(path)), sav=as.data.frame(haven::read_sav(path)),',
    'dta=haven::read_dta(path), sav=haven::read_sav(path),')


def reader_translation(fmt,options,language):
    """Translate declared reader fields; no unchecked reader kwargs escape."""
    options=dict(options or {})
    transpose=options.pop('transpose',False)
    if type(transpose) is not bool or transpose:
        refuse('Transpose requires an equivalent column/type projection','UNSUPPORTED_READ_OPTIONS')
    sheet=options.pop('sheet_name',None)
    if fmt!='xlsx' and sheet not in {None,''}:
        refuse('sheet_name is only meaningful for Excel','UNSUPPORTED_READ_OPTIONS')
    if fmt=='xlsx':
        if options or (sheet is not None and (not isinstance(sheet,str) or not sheet)):
            refuse('Unsupported Excel reader options','UNSUPPORTED_READ_OPTIONS')
        return ({'sheet_name':sheet or 0} if language=='python' else {'sheet':sheet or 1}),{'sheet':sheet}
    if fmt!='csv':
        if options:refuse('Unsupported statistical-file reader options','UNSUPPORTED_READ_OPTIONS')
        return {},{}
    allowed={'delimiter','sep','encoding','header','names'}
    if set(options)-allowed:refuse('Unknown CSV reader options','UNSUPPORTED_READ_OPTIONS')
    if 'delimiter' in options and 'sep' in options and options['delimiter']!=options['sep']:
        refuse('Conflicting CSV delimiters','UNSUPPORTED_READ_OPTIONS')
    delimiter=options.get('delimiter',options.get('sep',','))
    if delimiter not in {',',';','|','\t'}:refuse('Unsupported CSV delimiter','UNSUPPORTED_READ_OPTIONS')
    encodings={'utf-8':('utf-8','UTF-8'),'utf8':('utf-8','UTF-8'),'utf-8-sig':('utf-8-sig','UTF-8'),'latin1':('latin1','ISO-8859-1'),'iso-8859-1':('latin1','ISO-8859-1'),'cp1252':('cp1252','windows-1252')}
    encoding=options.get('encoding','utf-8')
    if not isinstance(encoding,str) or encoding.lower() not in encodings:
        refuse('Unsupported CSV encoding','UNSUPPORTED_READ_OPTIONS')
    py_encoding,native_encoding=encodings[encoding.lower()]
    header=options.get('header',0);names=options.get('names')
    if header is not None and (type(header) is not int or header!=0):
        refuse('Only first-row and explicitly named headerless CSV are supported','UNSUPPORTED_READ_OPTIONS')
    if names is not None:
        if not isinstance(names,(list,tuple)):refuse('CSV names must be a list','UNSUPPORTED_READ_OPTIONS')
        names=[identifier(c) for c in names]
        if not names or len(names)!=len(set(names)):refuse('CSV names must be nonempty and unique','UNSUPPORTED_READ_OPTIONS')
    if header is None and not names:
        refuse('Headerless CSV requires explicit column identities','UNSUPPORTED_READ_OPTIONS')
    native={'delimiter':delimiter,'encoding':native_encoding,'header':header,'names':names}
    if language=='python':
        kwargs={'sep':delimiter,'encoding':py_encoding,'header':header}
        if names is not None:kwargs['names']=names
    else:
        kwargs={'sep':delimiter,'fileEncoding':native_encoding,'header':header is not None}
        if names is not None:kwargs['col.names']=names
    return kwargs,native

@dataclass
class RenderContext:
    language: str
    datasets: dict = field(default_factory=dict)
    model_steps: dict = field(default_factory=dict)
    model_parameters: dict = field(default_factory=dict)
    model_indices: dict = field(default_factory=dict)
    distributions: dict = field(default_factory=dict)
    postestimation_helpers: bool = False
    helpers: set = field(default_factory=set)
    checks: list = field(default_factory=list)
    packages: set = field(default_factory=set)
    index: int = 0

    def data(self, key):
        if key not in self.datasets:
            refuse(f'Input {key!r} is not a dataset')
        return self.datasets[key]

    def ref(self, key):
        return {'python': f'data[{key!r}]', 'r': f'data[[{literal(key,"r")}]]', 'stata': self.data(key)}[self.language]

    def assign(self, key, expression):
        return f'{self.ref(key)} {"<-" if self.language == "r" else "="} {expression}'

    def read(self, key, name, digest, fmt, options=None):
        filename(name)
        l = self.language
        options,native=reader_translation(fmt,options,l)
        if l=='python':self.packages.update(('numpy','pandas'))
        if l=='python' and fmt in {'dta','sav'}:self.packages.add('pyreadstat')
        if fmt=='xlsx' and l!='stata':self.packages.add('openpyxl' if l=='python' else 'openxlsx')
        if l != 'stata':
            lines=[]
            if l=='r' and fmt=='csv':
                from .exact_numeric import r_float_parser,R_CSV_PRECISION
                lines+=r_float_parser(self)
                if 'exact_csv_double' not in self.helpers:
                    self.helpers.add('exact_csv_double')
                    lines+=R_CSV_PRECISION.splitlines()
            lines.append(self.assign(key, f'wb_read({literal(name,l)}, {literal(digest,l)}, {literal(fmt,l)}, {literal(options or {},l)})'))
            if l=='r' and fmt=='csv':
                lines.append(self.assign(key,f'wb_csv_precision({self.ref(key)}, {literal(name,l)}, {literal(options or {},l)})'))
            return lines
        commands = {'csv': f'import delimited using {literal(name,l)}, varnames(1) asdouble clear case(preserve)',
                    'dta': f'use {literal(name,l)}, clear',
                    'sav': f'import spss using {literal(name,l)}, clear',
                    'xlsx': f'import excel using {literal(name,l)}, firstrow clear'}
        if fmt not in commands:
            refuse('Stata cannot read this source format', 'UNSUPPORTED_SOURCE_FORMAT')
        if fmt=='csv':
            delimiter='\\t' if native['delimiter']=='\t' else native['delimiter']
            header='1' if native['header'] is not None else 'nonames'
            commands[fmt]=f'import delimited using {literal(name,l)}, varnames({header}) delimiters({literal(delimiter,l)}) encoding({literal(native["encoding"],l)}) bindquotes(strict) maxquotedrows(unlimited) asdouble clear case(preserve)'
        if fmt=='xlsx' and native['sheet']:
            commands[fmt]+=f' sheet({literal(native["sheet"],l)})'
        lines=[f'wb_sha {literal(name,l)} {literal(digest,l)}', f'frame create {self.data(key)}', f'frame change {self.data(key)}', commands[fmt]]
        if fmt=='csv' and native['names']:
            lines+=['unab wb_read_columns: _all','local wb_read_count : word count `wb_read_columns\'',f'assert `wb_read_count\' == {len(native["names"])}','rename (`wb_read_columns\') ('+' '.join(native['names'])+')']
        return lines

    def data_checks(self, step, expected=None):
        expected = expected if expected is not None else step.expected
        l = self.language
        lines = []
        if 'nrows' in expected:
            expr = {'python': f'len({self.ref(step.step_id)})', 'r': f'nrow({self.ref(step.step_id)})', 'stata': '_N'}[l]
            lines += self.numeric_check(step, 'nrows', expr, expected['nrows'])
        if 'columns' in expected:
            columns = [str(c) for c in expected['columns']]
            if l == 'stata':
                for c in columns: identifier(c)
                name = f'wb_check_{len(self.checks)}'
                lines += ['unab wb_columns: _all', f'scalar {name} = (`"`wb_columns\'"\' == {literal(" ".join(columns),l)})']
                self.checks.append(f'assert {name} == 1')
            else:
                actual = f'list({self.ref(step.step_id)}.columns)' if l == 'python' else f'names({self.ref(step.step_id)})'
                code = f'assert {actual} == {literal(columns,l)}' if l == 'python' else f'stopifnot(identical({actual}, {literal(columns,l)}))'
                # Capture the column assertion now, while numerical checks remain deferred.
                lines.append(code)
        unknown = set(expected) - {'nrows', 'columns'}
        if unknown: refuse(f'Unsupported data expected fields: {sorted(unknown)}')
        return lines

    def numeric_check(self, step, kind, expression, expected):
        tol = step.tolerances.get(kind, DEFAULT_TOLERANCES.get(kind, {'abs':0.0,'rel':0.0}))
        expected = literal(expected, self.language)
        absolute, relative = literal(tol['abs'],self.language), literal(tol['rel'],self.language)
        label = literal(step.step_id + ':' + kind,self.language)
        if self.language == 'stata':
            name = f'wb_number_{len(self.checks)}'
            self.checks.append(f'assert !missing({name}) & abs({name}-({expected})) <= {absolute}+{relative}*abs({expected})')
            return [f'scalar {name} = {expression}']
        index = len(self.checks)
        if self.language == 'python':
            self.checks.append(f'wb_check(checks[{index}], {expected}, {absolute}, {relative}, {label})')
            return [f'checks.append(float({expression}))']
        self.checks.append(f'wb_check(checks[[{index+1}]], {expected}, {absolute}, {relative}, {label})')
        return [f'checks[[{index+1}]] <- as.numeric({expression})']
